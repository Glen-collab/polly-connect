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
from core.conversation_state import ConversationMode
from core.vad_wakeword import VADWakeWordDetector
from core.auth import verify_device_api_key, verify_websocket_key
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
    """
    await websocket.accept()

    app = websocket.app
    db = app.state.db
    transcriber = app.state.transcriber
    tts = app.state.tts
    detector = app.state.wake_word_detector
    cmd = app.state.cmd

    if not detector.ready:
        logger.error("Wake word detector not ready — rejecting continuous stream")
        await websocket.send_json({"event": "error", "message": "Wake word detector not available"})
        await websocket.close()
        return

    device_id = "unknown"
    pcm_buffer = bytearray()

    state = "listening"
    command_audio = bytearray()
    last_voice_time = 0.0
    command_start_time = 0.0
    last_response_time = 0.0  # cooldown after response to avoid speaker feedback
    RESPONSE_COOLDOWN = 3.0   # ignore triggers for 3s after a response
    still_there_prompted = False  # tracks if we've asked "still there?"
    accumulated_parts = []        # partial audio from before the prompt

    # Pre-roll: keep last ~1.5 seconds of audio so we capture the wake phrase
    # 16kHz * 2 bytes * 1.5s = 48000 bytes
    PRE_ROLL_SIZE = 48000
    pre_roll = bytearray()

    # Use the VAD threshold for silence detection during recording too
    from core.vad_wakeword import VADWakeWordDetector
    vad_threshold = detector.rms_threshold if isinstance(detector, VADWakeWordDetector) else settings.SILENCE_THRESHOLD_RMS
    # Lower threshold for recording silence — catches softer speech during conversation
    recording_silence_threshold = max(vad_threshold // 2, 50)

    logger.info("Continuous stream connected")

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                try:
                    msg_data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                event = msg_data.get("event")

                if event == "connect":
                    device_id = msg_data.get("device_id", "unknown")
                    # Authenticate device
                    device_info = verify_device_api_key(msg_data.get("api_key", ""), db)
                    if device_info:
                        conv_state = cmd._get_state(device_id)
                        conv_state.tenant_id = device_info["tenant_id"]
                        conv_state.user_id = device_info["user_id"]
                        logger.info(f"Continuous stream device: {device_id} (tenant={device_info['tenant_id']})")
                    elif not verify_websocket_key(msg_data):
                        logger.warning(f"Continuous stream auth failed: {device_id}")
                        await websocket.send_json({"event": "error", "message": "Authentication failed"})
                        await websocket.close()
                        return
                    else:
                        # Global key fallback → tenant 1
                        conv_state = cmd._get_state(device_id)
                        conv_state.tenant_id = 1
                        logger.info(f"Continuous stream device: {device_id} (global key, tenant=1)")
                    await websocket.send_json({"event": "connected", "message": "Streaming mode ready"})
                    continue

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    continue

                continue

            if "bytes" not in message:
                continue

            pcm_data = message["bytes"]
            pcm_buffer.extend(pcm_data)

            while len(pcm_buffer) >= OWW_CHUNK_BYTES:
                chunk_bytes = bytes(pcm_buffer[:OWW_CHUNK_BYTES])
                del pcm_buffer[:OWW_CHUNK_BYTES]
                chunk_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)

                if state == "listening":
                    # Maintain pre-roll buffer
                    pre_roll.extend(chunk_bytes)
                    if len(pre_roll) > PRE_ROLL_SIZE:
                        pre_roll = pre_roll[-PRE_ROLL_SIZE:]

                    # Get live conversation state for dynamic timeouts
                    conv_state = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None

                    # In conversational mode, skip wake word — go straight to recording
                    if conv_state and conv_state.is_conversational:
                        rms = int(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
                        if rms > vad_threshold:
                            logger.info(f"Voice detected in conversational mode (device: {device_id})")
                            state = "recording"
                            skip_wake_check = True  # don't require wake phrase
                            command_audio = bytearray(pre_roll)  # include pre-roll
                            last_voice_time = time.monotonic()
                            command_start_time = time.monotonic()
                            await websocket.send_json({"event": "conversation_listening"})
                    elif detector.detected(chunk_int16):
                        # Ignore triggers during cooldown after response (speaker feedback)
                        if time.monotonic() - last_response_time < RESPONSE_COOLDOWN:
                            continue
                        logger.info(f"*** WAKE WORD DETECTED (device: {device_id}) ***")
                        detector.reset()

                        state = "recording"
                        skip_wake_check = False  # require wake phrase
                        # Include pre-roll so we capture "Hey Polly" before trigger
                        command_audio = bytearray(pre_roll)
                        last_voice_time = time.monotonic()
                        command_start_time = time.monotonic()

                        await websocket.send_json({"event": "wake_word_detected"})

                elif state == "recording":
                    command_audio.extend(chunk_bytes)

                    rms = int(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
                    if rms > recording_silence_threshold:
                        last_voice_time = time.monotonic()

                    now = time.monotonic()
                    silence_duration = now - last_voice_time
                    total_duration = now - command_start_time

                    # Use dynamic timeouts from conversation state
                    conv_state = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
                    silence_limit = conv_state.silence_timeout if conv_state else settings.SILENCE_TIMEOUT_S
                    max_duration = conv_state.max_recording if conv_state else settings.MAX_COMMAND_S

                    if silence_duration > silence_limit or total_duration > max_duration:
                        reason = "silence" if silence_duration > silence_limit else "max_duration"

                        # Combine any accumulated audio with current
                        if accumulated_parts:
                            full_audio = bytearray()
                            for part in accumulated_parts:
                                full_audio.extend(part)
                            full_audio.extend(command_audio)
                            command_audio = full_audio
                            accumulated_parts = []

                        logger.info(f"Command recording ended ({reason}), {len(command_audio)} bytes")

                        pre_transcription = None

                        # In conversational mode on silence, transcribe first to decide
                        if (conv_state and conv_state.is_conversational
                                and reason == "silence"
                                and not still_there_prompted):
                            # Quick transcribe to check if user actually spoke
                            check_wav = io.BytesIO()
                            with wave.open(check_wav, 'wb') as wf:
                                wf.setnchannels(settings.CHANNELS)
                                wf.setsampwidth(2)
                                wf.setframerate(settings.SAMPLE_RATE)
                                wf.writeframes(command_audio)
                            check_text = await asyncio.to_thread(
                                transcriber.transcribe, check_wav.getvalue()
                            )

                            if not check_text or not check_text.strip():
                                # No speech detected — prompt "still there?"
                                still_there_prompted = True
                                logger.info("No speech in conversational mode — prompting user")
                                prompt = "Are you still there? Take your time, and say 'I'm done' when you're finished."
                                await websocket.send_json({
                                    "event": "response",
                                    "text": prompt,
                                    "intent": "still_there_prompt",
                                })
                                await _send_tts(websocket, tts, prompt)
                                accumulated_parts.append(bytes(command_audio))
                                state = "listening"
                                command_audio = bytearray()
                                pre_roll = bytearray()
                                last_response_time = time.monotonic()
                                continue

                            # User said something — process it (skip re-transcription)
                            pre_transcription = check_text
                            logger.info(f"Conversational speech detected: {check_text[:100]}")

                        await _process_command(
                            websocket, command_audio, transcriber, tts, cmd, device_id,
                            detector=detector,
                            skip_wake_check=skip_wake_check,
                            pre_transcription=pre_transcription,
                        )

                        # After processing, reset state
                        still_there_prompted = False
                        last_response_time = time.monotonic()
                        pre_roll = bytearray()
                        if conv_state and conv_state.is_conversational:
                            state = "listening"
                            command_audio = bytearray()
                        else:
                            state = "listening"
                            command_audio = bytearray()
                            detector.reset()

    except WebSocketDisconnect:
        logger.info(f"Continuous stream disconnected: {device_id}")
    except Exception as e:
        import traceback
        logger.error(f"Continuous stream error: {e}")
        traceback.print_exc()


async def _process_command(
    websocket: WebSocket,
    command_audio: bytearray,
    transcriber,
    tts,
    cmd,
    device_id: str = "unknown",
    detector=None,
    skip_wake_check: bool = False,
    pre_transcription: str = None,
):
    """Run STT → intent parse → CommandProcessor → TTS on buffered command audio."""
    if len(command_audio) == 0 and not pre_transcription:
        await websocket.send_json({"event": "response", "text": "I didn't hear anything.", "audio": None})
        return

    if pre_transcription:
        transcription = pre_transcription
    else:
        # Wrap raw PCM in WAV header for STT
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

    # If using VAD detector, check transcription for wake phrase (skip in conversational mode)
    if detector and isinstance(detector, VADWakeWordDetector) and not skip_wake_check:
        is_wake, cleaned = detector.check_transcription(transcription)
        if not is_wake:
            logger.info(f"VAD: no wake phrase in transcription, ignoring: {transcription}")
            # Tell ESP32 to resume streaming (no command to process)
            await websocket.send_json({"event": "no_wake_word", "text": transcription})
            return
        logger.info(f"VAD: wake phrase found, command: {cleaned}")
        transcription = cleaned

    # Intent parse
    intent_result = intent_parser.parse(transcription)
    logger.info(f"Intent: {intent_result}")

    # Use conversation-aware processing if available
    if hasattr(cmd, 'process_in_context'):
        response_text, new_mode = await cmd.process_in_context(intent_result, transcription, device_id)
        logger.info(f"Response: {response_text} (mode: {new_mode.value})")
    else:
        response_text = await cmd.process(intent_result, transcription, device_id)
        new_mode = ConversationMode.COMMAND
        logger.info(f"Response: {response_text}")

    # Send text response
    await websocket.send_json({
        "event": "response",
        "text": response_text,
        "intent": intent_result.get("intent"),
        "transcription": transcription,
        "mode": new_mode.value,
    })

    # Generate and send TTS audio
    await _send_tts(websocket, tts, response_text)


async def _send_tts(websocket: WebSocket, tts, text: str):
    """Generate TTS audio and send as chunked base64."""
    try:
        tts_audio = tts.synthesize(text)
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
        import traceback
        logger.error(f"TTS error: {e}")
        traceback.print_exc()


# ─── Original Event-Based Stream Handler ─────────────────────────────────────

@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    await websocket.accept()

    session: Optional[AudioSession] = None
    device_id: str = "unknown"

    app = websocket.app
    transcriber = app.state.transcriber
    tts = app.state.tts
    cmd = app.state.cmd

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
                # Authenticate device
                device_info = verify_device_api_key(message.get("api_key", ""), app.state.db)
                if device_info:
                    conv_state_obj = cmd._get_state(device_id)
                    conv_state_obj.tenant_id = device_info["tenant_id"]
                    conv_state_obj.user_id = device_info["user_id"]
                    logger.info(f"Device connected: {device_id} (tenant={device_info['tenant_id']})")
                elif not verify_websocket_key(message):
                    logger.warning(f"Device auth failed: {device_id}")
                    await websocket.send_json({"event": "error", "message": "Authentication failed"})
                    await websocket.close()
                    return
                else:
                    conv_state_obj = cmd._get_state(device_id)
                    conv_state_obj.tenant_id = 1
                    logger.info(f"Device connected: {device_id} (global key, tenant=1)")
                await websocket.send_json({"event": "connected", "message": "Ready"})

            elif event == "wake_word_detected":
                if not session:
                    session = AudioSession("unknown")
                session.listening_for_command = True
                session.clear_command()
                logger.info(f"Wake word detected by device: {device_id}")
                await websocket.send_json({"event": "wake_ack", "message": "Ready for command"})

            elif event == "audio_stream":
                if not session:
                    session = AudioSession("unknown")
                audio_b64 = message.get("data", "")
                if audio_b64 and session.listening_for_command:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.command_audio.extend(audio_bytes)

            elif event == "command_end":
                if session and session.listening_for_command:
                    session.listening_for_command = False

                    if len(session.command_audio) > 0:
                        wav_bytes = session.get_wav_bytes(session.command_audio)
                        transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
                        logger.info(f"Transcription: {transcription}")

                        if transcription:
                            intent_result = intent_parser.parse(transcription)
                            logger.info(f"Intent: {intent_result}")

                            if hasattr(cmd, 'process_in_context'):
                                response_text, new_mode = await cmd.process_in_context(
                                    intent_result, transcription, device_id)
                            else:
                                response_text = await cmd.process(intent_result, transcription, device_id)
                                new_mode = ConversationMode.COMMAND
                            logger.info(f"Response: {response_text}")

                            await websocket.send_json({
                                "event": "response",
                                "text": response_text,
                                "audio": None,
                                "intent": intent_result.get("intent"),
                                "transcription": transcription,
                                "mode": new_mode.value,
                            })

                            await _send_tts(websocket, tts, response_text)
                        else:
                            await websocket.send_json({
                                "event": "response",
                                "text": "I didn't catch that.",
                                "audio": None
                            })

                    session.clear_command()

            elif event == "audio":
                if not session:
                    session = AudioSession("unknown")
                audio_b64 = message.get("data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.add_audio(audio_bytes)

            elif event == "end_stream":
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

                if hasattr(cmd, 'process_in_context'):
                    response_text, new_mode = await cmd.process_in_context(
                        intent_result, transcription, device_id)
                else:
                    response_text = await cmd.process(intent_result, transcription, device_id)
                    new_mode = ConversationMode.COMMAND
                logger.info(f"Response: {response_text}")

                await websocket.send_json({
                    "event": "response",
                    "text": response_text,
                    "audio": None,
                    "intent": intent_result.get("intent"),
                    "transcription": transcription,
                    "mode": new_mode.value,
                })

                await _send_tts(websocket, tts, response_text)
                session.clear()

            elif event == "ping":
                await websocket.send_json({"event": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Device disconnected: {device_id}")
