"""
Audio streaming endpoint for Polly Connect
"""

import asyncio
import base64
import json
import logging
import io
import wave
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.intent_parser import IntentParser
from core.wakeword import WakeWordDetector
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

intent_parser = IntentParser(use_spacy=False)
# Disable server-side wake word detection (now handled on ESP32 device)
wake_detector = WakeWordDetector(threshold=0.5, enabled=False)


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