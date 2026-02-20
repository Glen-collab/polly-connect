"""
Audio streaming endpoint for Polly Connect.

Supports two WebSocket modes:
1. Event-based (existing): ESP32 detects wake word locally, sends audio after detection
2. Continuous stream (new): ESP32 streams all mic audio, server runs OpenWakeWord
"""

import asyncio
import base64
import json
import logging
import io
import time
import wave
from typing import Optional
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.intent_parser import IntentParser
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

intent_parser = IntentParser(use_spacy=False)

# OpenWakeWord processes 1280-sample chunks (80ms at 16kHz)
OWW_CHUNK_SAMPLES = 1280
OWW_CHUNK_BYTES = OWW_CHUNK_SAMPLES * 2  # int16 = 2 bytes


class AudioSession:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.audio_buffer = bytearray()
        self.listening_for_command = False
        self.command_audio = bytearray()

    def add_audio(self, audio_bytes: bytes):
        self.audio_buffer.extend(audio_bytes)

    def clear(self):
        self.audio_buffer = bytearray()

    def clear_command(self):
        self.command_audio = bytearray()

    def get_wav_bytes(self, audio_data: bytearray = None) -> bytes:
        data = audio_data if audio_data else self.audio_buffer
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(settings.CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(settings.SAMPLE_RATE)
            wav_file.writeframes(data)
        return wav_buffer.getvalue()


# ─── Continuous Stream Handler ───────────────────────────────────────────────

@router.websocket("/continuous")
async def continuous_stream(websocket: WebSocket):
    """
    Continuous audio streaming with server-side wake word detection.

    Protocol (binary frames):
    - ESP32 sends raw 16-bit PCM chunks continuously over WebSocket (binary)
    - Server feeds chunks to OpenWakeWord
    - On detection: sends {"event": "wake_word_detected"} (text frame)
    - Keeps buffering audio until silence → runs Whisper/intent/TTS
    - Sends {"event": "response", ...} + audio_chunk frames back
    """
    await websocket.accept()

    app = websocket.app
    db = app.state.db
    transcriber = app.state.transcriber
    tts = app.state.tts
    detector = app.state.wake_word_detector

    if not detector.ready:
        logger.error("Wake word detector not ready — rejecting continuous stream")
        await websocket.send_json({"event": "error", "message": "Wake word detector not available"})
        await websocket.close()
        return

    device_id = "unknown"
    pcm_buffer = bytearray()  # accumulates raw PCM until we have OWW_CHUNK_BYTES

    # State: "listening" (for wake word) or "recording" (post-wake, capturing command)
    state = "listening"
    command_audio = bytearray()
    last_voice_time = 0.0
    command_start_time = 0.0

    logger.info("Continuous stream connected")

    try:
        while True:
            message = await websocket.receive()

            # Handle text frames (JSON control messages)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                event = data.get("event")

                if event == "connect":
                    device_id = data.get("device_id", "unknown")
                    logger.info(f"Continuous stream device: {device_id}")
                    await websocket.send_json({"event": "connected", "message": "Streaming mode ready"})
                    continue

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    continue

                continue

            # Handle binary frames (raw PCM audio)
            if "bytes" not in message:
                continue

            pcm_data = message["bytes"]
            pcm_buffer.extend(pcm_data)

            # Process in OWW_CHUNK_BYTES-sized pieces
            while len(pcm_buffer) >= OWW_CHUNK_BYTES:
                chunk_bytes = bytes(pcm_buffer[:OWW_CHUNK_BYTES])
                del pcm_buffer[:OWW_CHUNK_BYTES]
                chunk_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)

                if state == "listening":
                    # Feed to wake word detector
                    if detector.detected(chunk_int16):
                        logger.info(f"*** WAKE WORD DETECTED (device: {device_id}) ***")
                        detector.reset()

                        state = "recording"
                        command_audio = bytearray()
                        last_voice_time = time.monotonic()
                        command_start_time = time.monotonic()

                        await websocket.send_json({"event": "wake_word_detected"})

                elif state == "recording":
                    # Accumulate command audio
                    command_audio.extend(chunk_bytes)

                    # Check audio level for silence detection
                    rms = int(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
                    if rms > settings.SILENCE_THRESHOLD_RMS:
                        last_voice_time = time.monotonic()

                    now = time.monotonic()
                    silence_duration = now - last_voice_time
                    total_duration = now - command_start_time

                    # End recording on silence or max duration
                    if silence_duration > settings.SILENCE_TIMEOUT_S or total_duration > settings.MAX_COMMAND_S:
                        reason = "silence" if silence_duration > settings.SILENCE_TIMEOUT_S else "max_duration"
                        logger.info(f"Command recording ended ({reason}), {len(command_audio)} bytes")

                        # Process the command
                        await _process_command(
                            websocket, command_audio, transcriber, tts, db
                        )

                        # Reset to listening
                        state = "listening"
                        command_audio = bytearray()
                        detector.reset()

    except WebSocketDisconnect:
        logger.info(f"Continuous stream disconnected: {device_id}")
    except Exception as e:
        logger.error(f"Continuous stream error: {e}")


async def _process_command(
    websocket: WebSocket,
    command_audio: bytearray,
    transcriber,
    tts,
    db,
):
    """Run Whisper STT → intent parse → response → TTS on buffered command audio."""
    if len(command_audio) == 0:
        await websocket.send_json({"event": "response", "text": "I didn't hear anything.", "audio": None})
        return

    # Wrap raw PCM in WAV header for Whisper
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(settings.CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(settings.SAMPLE_RATE)
        wf.writeframes(command_audio)
    wav_bytes = wav_buffer.getvalue()

    # Transcribe
    transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
    logger.info(f"Transcription: {transcription}")

    if not transcription:
        await websocket.send_json({"event": "response", "text": "I didn't catch that.", "audio": None})
        return

    # Intent parse
    intent_result = intent_parser.parse(transcription)
    logger.info(f"Intent: {intent_result}")

    # Process intent
    response_text = await process_intent(intent_result, db, transcription)
    logger.info(f"Response: {response_text}")

    # Send text response
    await websocket.send_json({
        "event": "response",
        "text": response_text,
        "intent": intent_result.get("intent"),
        "transcription": transcription,
    })

    # Generate and send TTS audio
    try:
        tts_audio = await asyncio.to_thread(tts.speak, response_text)
        if tts_audio:
            chunk_size = 8000
            for i in range(0, len(tts_audio), chunk_size):
                chunk = tts_audio[i:i + chunk_size]
                chunk_b64 = base64.b64encode(chunk).decode()
                await websocket.send_json({
                    "event": "audio_chunk",
                    "audio": chunk_b64,
                    "final": (i + chunk_size >= len(tts_audio)),
                })
                await asyncio.sleep(0.05)
    except Exception as e:
        logger.error(f"TTS error: {e}")


# ─── Original Event-Based Stream Handler ─────────────────────────────────────

@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    await websocket.accept()

    session: Optional[AudioSession] = None
    device_id: str = "unknown"

    app = websocket.app
    db = app.state.db
    transcriber = app.state.transcriber
    tts = app.state.tts

    try:
        while True:
            raw_message = await websocket.receive_text()

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event = message.get("event")

            if event == "connect":
                device_id = message.get("device_id", "unknown")
                session = AudioSession(device_id)
                logger.info(f"Device connected: {device_id}")
                await websocket.send_json({"event": "connected", "message": "Ready"})

            elif event == "wake_word_detected":
                # ESP32 detected wake word locally
                if not session:
                    session = AudioSession("unknown")

                session.listening_for_command = True
                session.clear_command()

                logger.info(f"Wake word detected by device: {device_id}")

                # Optional acknowledgment
                await websocket.send_json({
                    "event": "wake_ack",
                    "message": "Ready for command"
                })

            elif event == "audio_stream":
                # Now only receives audio AFTER wake word detected on ESP32
                if not session:
                    session = AudioSession("unknown")

                audio_b64 = message.get("data", "")
                if audio_b64 and session.listening_for_command:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.command_audio.extend(audio_bytes)

            elif event == "command_end":
                # End of command after wake word
                if session and session.listening_for_command:
                    session.listening_for_command = False

                    if len(session.command_audio) > 0:
                        wav_bytes = session.get_wav_bytes(session.command_audio)
                        transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
                        logger.info(f"Transcription: {transcription}")

                        if transcription:
                            intent_result = intent_parser.parse(transcription)
                            logger.info(f"Intent: {intent_result}")

                            response_text = await process_intent(intent_result, db, transcription)
                            logger.info(f"Response: {response_text}")

                            await websocket.send_json({
                                "event": "response",
                                "text": response_text,
                                "audio": None,
                                "intent": intent_result.get("intent"),
                                "transcription": transcription
                            })

                            # Generate and send audio
                            try:
                                tts_audio = await asyncio.to_thread(tts.speak, response_text)
                                if tts_audio:
                                    chunk_size = 8000
                                    for i in range(0, len(tts_audio), chunk_size):
                                        chunk = tts_audio[i:i+chunk_size]
                                        chunk_b64 = base64.b64encode(chunk).decode()
                                        await websocket.send_json({
                                            "event": "audio_chunk",
                                            "audio": chunk_b64,
                                            "final": (i + chunk_size >= len(tts_audio))
                                        })
                                        await asyncio.sleep(0.05)
                            except Exception as e:
                                logger.error(f"TTS error: {e}")
                        else:
                            await websocket.send_json({
                                "event": "response",
                                "text": "I didn't catch that.",
                                "audio": None
                            })

                    session.clear_command()

            elif event == "audio":
                # Button-triggered mode (existing)
                if not session:
                    session = AudioSession("unknown")
                audio_b64 = message.get("data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.add_audio(audio_bytes)

            elif event == "end_stream":
                # Button-triggered mode (existing)
                if not session or len(session.audio_buffer) == 0:
                    await websocket.send_json({"event": "error", "message": "No audio"})
                    continue

                logger.info(f"Processing {len(session.audio_buffer)} bytes")

                wav_bytes = session.get_wav_bytes()
                transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
                logger.info(f"Transcription: {transcription}")

                if not transcription:
                    await websocket.send_json({
                        "event": "response",
                        "text": "I didn't catch that.",
                        "audio": None
                    })
                    session.clear()
                    continue

                intent_result = intent_parser.parse(transcription)
                logger.info(f"Intent: {intent_result}")

                response_text = await process_intent(intent_result, db, transcription)
                logger.info(f"Response: {response_text}")

                await websocket.send_json({
                    "event": "response",
                    "text": response_text,
                    "audio": None,
                    "intent": intent_result.get("intent"),
                    "transcription": transcription
                })

                try:
                    tts_audio = await asyncio.to_thread(tts.speak, response_text)
                    if tts_audio:
                        chunk_size = 8000
                        for i in range(0, len(tts_audio), chunk_size):
                            chunk = tts_audio[i:i+chunk_size]
                            chunk_b64 = base64.b64encode(chunk).decode()
                            await websocket.send_json({
                                "event": "audio_chunk",
                                "audio": chunk_b64,
                                "final": (i + chunk_size >= len(tts_audio))
                            })
                            await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"TTS error: {e}")

                session.clear()

            elif event == "ping":
                await websocket.send_json({"event": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Device disconnected: {device_id}")


async def process_intent(intent_result: dict, db, raw_text: str) -> str:
    intent = intent_result.get("intent", "unknown")

    if intent == "store":
        item = intent_result.get("item")
        location = intent_result.get("location")
        context = intent_result.get("context")

        if item and location:
            db.store_item(item, location, context, raw_text)
            return f"Got it. {item} is in the {location}."
        return "I didn't understand what to store."

    elif intent == "retrieve_item":
        item = intent_result.get("item")
        if item:
            results = db.find_item(item)
            if results:
                r = results[0]
                if r.get("context"):
                    return f"The {r['item']} is in the {r['location']}, {r['context']}."
                return f"The {r['item']} is in the {r['location']}."
            return f"I don't know where the {item} is."
        return "What item are you looking for?"

    elif intent == "retrieve_location":
        location = intent_result.get("location")
        if location:
            results = db.find_by_location(location)
            if results:
                items = [r["item"] for r in results]
                return f"In the {location}, you have: {', '.join(items)}."
            return f"Nothing stored in {location}."
        return "Which location?"

    elif intent == "delete":
        item = intent_result.get("item")
        if item:
            if db.delete_item(item):
                return f"Forgot about the {item}."
            return f"I don't have {item} stored."
        return "What should I forget?"

    elif intent == "list_all":
        items = db.list_all()
        return f"You have {len(items)} items stored."

    elif intent == "help":
        return "Tell me where things are, then ask me to find them later."

    return "I didn't understand that."
