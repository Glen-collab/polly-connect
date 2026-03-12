"""
Pre-cached acknowledgment squawk audio for instant playback.

At server startup, loads short parrot squawk WAV files and converts them
to 16kHz mono PCM (matching ESP32 format). When the user finishes speaking,
a random chirp is fired immediately over WebSocket BEFORE STT starts —
eliminates dead air perception.

Clips are ~0.5-1.0s so they finish well before STT returns (1-3s).
No collision with response TTS is possible.
"""

import asyncio
import base64
import io
import logging
import os
import random
import struct
import wave
from typing import Optional, List

logger = logging.getLogger(__name__)

# Short squawk files to use as acknowledgment chirps (under 1 second)
ACK_SQUAWK_FILES = ["squawk1.wav", "squawk6.wav", "squawk2.wav"]


class AckCache:
    """Pre-loaded squawk audio clips cached in memory for instant ack."""

    def __init__(self):
        self._clips: List[bytes] = []  # 16kHz mono WAV bytes
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready and len(self._clips) > 0

    def warm_up(self, sounds_dir: str):
        """Load and convert squawk files to 16kHz mono WAV. Call at startup."""
        for filename in ACK_SQUAWK_FILES:
            path = os.path.join(sounds_dir, filename)
            if not os.path.exists(path):
                logger.warning(f"Ack squawk not found: {path}")
                continue
            try:
                clip = self._load_and_convert(path)
                if clip and len(clip) > 100:
                    dur = len(clip) / 32000.0
                    self._clips.append(clip)
                    logger.debug(f"Cached ack squawk: {filename} ({dur:.2f}s)")
            except Exception as e:
                logger.warning(f"Failed to cache ack squawk {filename}: {e}")

        self._ready = len(self._clips) > 0
        logger.info(f"Ack cache ready: {len(self._clips)} squawk clips cached")

    def _load_and_convert(self, path: str) -> Optional[bytes]:
        """Load a WAV file and convert to 16kHz mono WAV bytes."""
        with wave.open(path, 'rb') as wav_in:
            n_channels = wav_in.getnchannels()
            sample_width = wav_in.getsampwidth()
            framerate = wav_in.getframerate()
            frames = wav_in.readframes(wav_in.getnframes())

        if sample_width != 2:
            logger.warning(f"Unsupported sample width {sample_width} in {path}")
            return None

        # Decode to int16 samples
        n_samples = len(frames) // 2
        samples = list(struct.unpack(f'<{n_samples}h', frames))

        # Stereo → mono (take left channel)
        if n_channels == 2:
            samples = samples[::2]

        # Downsample to 16kHz if needed
        if framerate > 16000:
            ratio = max(1, round(framerate / 16000))
            samples = samples[::ratio]

        # Wrap in 16kHz mono WAV
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(16000)
            wav_out.writeframes(struct.pack(f'<{len(samples)}h', *samples))

        return output.getvalue()

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
