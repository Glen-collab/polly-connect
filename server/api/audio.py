"""
Audio streaming endpoint for Polly Connect
Handles WebSocket connections from ESP32 devices
"""

import asyncio
import base64
import json
import logging
import io
import wave
import struct
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
import numpy as np

from core.intent_parser import IntentParser
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Intent parser instance
intent_parser = IntentParser(use_spacy=False)  # Start without spaCy for speed


class AudioSession:
    """Manages an audio streaming session from a device."""
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.audio_buffer = bytearray()
        self.is_recording = False
        self.silence_start: Optional[float] = None
        
    def add_audio(self, audio_bytes: bytes):
        """Add audio chunk to buffer."""
        self.audio_buffer.extend(audio_bytes)
        
    def clear(self):
        """Clear the audio buffer."""
        self.audio_buffer = bytearray()
        
    def get_audio(self) -> bytes:
        """Get all buffered audio."""
        return bytes(self.audio_buffer)
    
    def get_wav_bytes(self) -> bytes:
        """Convert raw audio buffer to WAV format."""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(settings.CHANNELS)
            wav_file.setsampwidth(2)  # 16-bit audio
            wav_file.setframerate(settings.SAMPLE_RATE)
            wav_file.writeframes(self.audio_buffer)
        return wav_buffer.getvalue()


@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    """
    WebSocket endpoint for audio streaming.
    
    Protocol:
    - Device connects and sends: {"event": "connect", "device_id": "polly001"}
    - Device streams: {"event": "audio", "data": "<base64 audio chunk>"}
    - Device signals end: {"event": "end_stream"}
    - Server responds: {"event": "response", "audio": "<base64 TTS>", "text": "..."}
    """
    await websocket.accept()
    
    session: Optional[AudioSession] = None
    device_id: str = "unknown"
    
    # Get app state
    app = websocket.app
    db = app.state.db
    transcriber = app.state.transcriber
    tts = app.state.tts
    
    try:
        while True:
            # Receive message
            raw_message = await websocket.receive_text()
            
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {raw_message[:100]}")
                continue
                
            event = message.get("event")
            
            if event == "connect":
                # Device connecting
                device_id = message.get("device_id", "unknown")
                session = AudioSession(device_id)
                logger.info(f"Device connected: {device_id}")
                
                await websocket.send_json({
                    "event": "connected",
                    "message": "Ready to receive audio"
                })
                
            elif event == "audio":
                # Audio chunk received
                if not session:
                    session = AudioSession("unknown")
                    
                audio_b64 = message.get("data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.add_audio(audio_bytes)
                    
            elif event == "end_stream":
                # End of audio stream - process it
                if not session or len(session.audio_buffer) == 0:
                    await websocket.send_json({
                        "event": "error",
                        "message": "No audio received"
                    })
                    continue
                    
                logger.info(f"Processing audio from {device_id}: {len(session.audio_buffer)} bytes")
                
                # 1. Transcribe audio
                wav_bytes = session.get_wav_bytes()
                transcription = await asyncio.to_thread(
                    transcriber.transcribe, wav_bytes
                )
                logger.info(f"Transcription: {transcription}")
                
                if not transcription or transcription.strip() == "":
                    await websocket.send_json({
                        "event": "response",
                        "text": "I didn't catch that. Could you repeat?",
                        "audio": None
                    })
                    session.clear()
                    continue
                
                # 2. Parse intent
                intent_result = intent_parser.parse(transcription)
                logger.info(f"Intent: {intent_result}")
                
                # 3. Execute intent and generate response
                response_text = await process_intent(intent_result, db, transcription)
                logger.info(f"Response: {response_text}")
                
                # 4. Generate TTS audio
                tts_audio = await asyncio.to_thread(tts.speak, response_text)
                tts_b64 = base64.b64encode(tts_audio).decode() if tts_audio else None
                
                # 5. Send response
                await websocket.send_json({
                    "event": "response",
                    "text": response_text,
                    "audio": tts_b64,
                    "intent": intent_result.get("intent"),
                    "transcription": transcription
                })
                
                # Clear buffer for next interaction
                session.clear()
                
            elif event == "ping":
                # Keep-alive
                await websocket.send_json({"event": "pong"})
                
    except WebSocketDisconnect:
        logger.info(f"Device disconnected: {device_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.close()
        except:
            pass


async def process_intent(intent_result: dict, db, raw_text: str) -> str:
    """Process parsed intent and return response text."""
    
    intent = intent_result.get("intent", "unknown")
    
    if intent == "store":
        item = intent_result.get("item")
        location = intent_result.get("location")
        context = intent_result.get("context")
        
        if item and location:
            db.store_item(item, location, context, raw_text)
            if context:
                return f"Got it. {item} is in the {location}, {context}."
            return f"Got it. {item} is in the {location}."
        return "I didn't understand what to store. Try: 'the wrench is in the drawer'."
        
    elif intent == "retrieve_item":
        item = intent_result.get("item")
        if item:
            results = db.find_item(item)
            if results:
                r = results[0]
                if r.get("context"):
                    return f"The {r['item']} is in the {r['location']}, {r['context']}."
                return f"The {r['item']} is in the {r['location']}."
            return f"I don't know where the {item} is. You haven't told me yet."
        return "What item are you looking for?"
        
    elif intent == "retrieve_location":
        location = intent_result.get("location")
        if location:
            results = db.find_by_location(location)
            if results:
                items = [r["item"] for r in results]
                if len(items) == 1:
                    return f"In the {location}, you have: {items[0]}."
                return f"In the {location}, you have: {', '.join(items[:-1])}, and {items[-1]}."
            return f"I don't have anything stored for {location}."
        return "Which location do you want to check?"
        
    elif intent == "delete":
        item = intent_result.get("item")
        if item:
            if db.delete_item(item):
                return f"Okay, I've forgotten about the {item}."
            return f"I don't have any record of {item}."
        return "What should I forget?"
        
    elif intent == "list_all":
        items = db.list_all()
        if items:
            count = len(items)
            if count <= 5:
                summary = ". ".join([f"{i['item']} in {i['location']}" for i in items])
                return f"You have {count} items stored. {summary}."
            return f"You have {count} items stored. Ask me about specific items or locations."
        return "You haven't stored anything yet."
        
    elif intent == "help":
        return "You can tell me where things are, like 'the wrench is in the drawer'. Then ask 'where is the wrench' to find it later."
        
    else:
        return "I didn't understand that. Try telling me where something is, or ask me to find something."
