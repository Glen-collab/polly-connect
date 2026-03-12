"""
Pre-cached acknowledgment audio for instant playback.

At server startup, generates short Polly TTS clips and caches them in memory.
When the user finishes speaking, one is fired immediately over WebSocket
BEFORE STT starts — eliminates dead air perception.

Clips are ~0.3-0.5s so they finish well before STT returns (1-3s).
No collision with response TTS is possible.
"""

import asyncio
import base64
import logging
import random
from typing import Optional, List

logger = logging.getLogger(__name__)


# Short acknowledgment phrases — Polly speaks these in ~0.3-0.5 seconds
ACK_PHRASES = [
    '<speak><prosody rate="105%">Mm-hmm.</prosody></speak>',
    '<speak><prosody rate="105%">Okay.</prosody></speak>',
    '<speak><prosody rate="110%">Got it.</prosody></speak>',
    '<speak><prosody rate="105%">Hmm.</prosody></speak>',
    '<speak><prosody rate="110%">Let me see.</prosody></speak>',
    '<speak><prosody rate="110%">One moment.</prosody></speak>',
]


class AckCache:
    """Pre-generated acknowledgment audio clips cached in memory."""

    def __init__(self):
        self._clips: List[bytes] = []  # raw WAV bytes
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and len(self._clips) > 0

    def warm_up(self, tts_backend):
        """Generate and cache all acknowledgment clips. Call at startup."""
        for phrase in ACK_PHRASES:
            try:
                audio = tts_backend.synthesize(phrase)
                if audio and len(audio) > 100:
                    self._clips.append(audio)
                    logger.debug(f"Cached ack: {phrase[:30]}... ({len(audio)} bytes)")
            except Exception as e:
                logger.warning(f"Failed to cache ack phrase: {e}")

        self._ready = len(self._clips) > 0
        logger.info(f"Ack cache ready: {len(self._clips)} clips cached")

    def get_random_clip(self) -> Optional[bytes]:
        """Return a random cached audio clip (WAV bytes)."""
        if not self._clips:
            return None
        return random.choice(self._clips)

    async def send_ack(self, websocket, squawk_mgr=None, device_id: str = None) -> float:
        """Send a random acknowledgment chirp over WebSocket.
        Returns estimated playback duration in seconds."""
        clip = self.get_random_clip()
        if not clip:
            return 0.0

        try:
            # Estimate duration: 16kHz, 16-bit mono = 32000 bytes/sec
            audio_duration = len(clip) / 32000.0

            lock = squawk_mgr.get_send_lock(device_id) if squawk_mgr and device_id else None

            async def _do_send():
                chunk_size = 8000
                for i in range(0, len(clip), chunk_size):
                    chunk = clip[i:i + chunk_size]
                    chunk_b64 = base64.b64encode(chunk).decode()
                    await websocket.send_json({
                        "event": "audio_chunk",
                        "audio": chunk_b64,
                        "final": (i + chunk_size >= len(clip)),
                    })
                    await asyncio.sleep(0.02)

            if lock:
                async with lock:
                    await _do_send()
            else:
                await _do_send()

            return audio_duration
        except Exception as e:
            logger.error(f"Ack send error: {e}")
            return 0.0
