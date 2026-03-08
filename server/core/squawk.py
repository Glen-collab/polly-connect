"""
Parrot squawk / ambient sound system for Polly Connect.

Short squawks: play randomly every 5-15 minutes idle, after TTS (~20%), on wake.
Long chatter: play every ~2 hours, interruptible with wake word / "be quiet" / "stop".
"""

import asyncio
import base64
import io
import logging
import os
import random
import struct
import wave
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# How often short squawks fire (seconds)
IDLE_SQUAWK_MIN = 5 * 60    # 5 minutes
IDLE_SQUAWK_MAX = 15 * 60   # 15 minutes

# How often long chatter fires (seconds)
CHATTER_INTERVAL = 2 * 60 * 60  # 2 hours

# Chance of squawk after a TTS response
POST_RESPONSE_SQUAWK_CHANCE = 0.20  # 20%


def _convert_to_16k_mono(wav_bytes: bytes) -> bytes:
    """Convert any WAV to 16kHz mono 16-bit WAV."""
    with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        raw = w.readframes(w.getnframes())

    # Convert to numpy
    if sampwidth == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) * 256
    elif sampwidth == 4:
        samples = (np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 65536)
    else:
        logger.warning(f"Unsupported sample width: {sampwidth}")
        return wav_bytes

    # Stereo to mono
    if channels == 2:
        samples = (samples[0::2] + samples[1::2]) / 2

    # Resample if not 16kHz
    if framerate != 16000:
        num_out = int(len(samples) * 16000 / framerate)
        indices = np.linspace(0, len(samples) - 1, num_out)
        samples = np.interp(indices, np.arange(len(samples)), samples)

    # Back to int16
    samples = np.clip(samples, -32768, 32767).astype(np.int16)

    # Wrap in WAV
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())
    return out.getvalue()


class SquawkManager:
    def __init__(self, sounds_dir: str):
        self.squawks: List[bytes] = []       # short squawk WAVs (16kHz mono)
        self.chatter: List[bytes] = []       # long chatter WAVs (16kHz mono)
        self._active_devices: Dict[str, asyncio.WebSocketServerProtocol] = {}
        self._idle_tasks: Dict[str, asyncio.Task] = {}
        self._chatter_tasks: Dict[str, asyncio.Task] = {}
        self._playing: Dict[str, bool] = {}  # True if currently sending squawk/chatter

        self._load_sounds(sounds_dir)

    def _load_sounds(self, sounds_dir: str):
        """Load and convert all squawk/chatter WAV files."""
        squawk_dir = sounds_dir
        if not os.path.isdir(squawk_dir):
            logger.warning(f"Sounds directory not found: {squawk_dir}")
            return

        for fname in sorted(os.listdir(squawk_dir)):
            if not fname.endswith('.wav'):
                continue
            path = os.path.join(squawk_dir, fname)
            try:
                with open(path, 'rb') as f:
                    raw = f.read()
                converted = _convert_to_16k_mono(raw)
                if fname.startswith('chatter'):
                    self.chatter.append(converted)
                    logger.info(f"Loaded chatter sound: {fname}")
                elif fname.startswith('squawk'):
                    self.squawks.append(converted)
                    logger.info(f"Loaded squawk sound: {fname}")
            except Exception as e:
                logger.error(f"Failed to load sound {fname}: {e}")

        logger.info(f"SquawkManager ready: {len(self.squawks)} squawks, {len(self.chatter)} chatter files")

    def register_device(self, device_id: str, websocket):
        """Start idle squawk timer for a connected device."""
        self._active_devices[device_id] = websocket
        self._playing[device_id] = False
        self._start_idle_timer(device_id)
        if self.chatter:
            self._start_chatter_timer(device_id)

    def unregister_device(self, device_id: str):
        """Stop timers when device disconnects."""
        self._active_devices.pop(device_id, None)
        self._playing.pop(device_id, None)
        task = self._idle_tasks.pop(device_id, None)
        if task:
            task.cancel()
        task = self._chatter_tasks.pop(device_id, None)
        if task:
            task.cancel()

    def stop_playback(self, device_id: str):
        """Interrupt any currently playing squawk/chatter."""
        self._playing[device_id] = False

    def is_playing(self, device_id: str) -> bool:
        return self._playing.get(device_id, False)

    def reset_idle_timer(self, device_id: str):
        """Reset the idle squawk timer (call after any activity)."""
        task = self._idle_tasks.pop(device_id, None)
        if task:
            task.cancel()
        if device_id in self._active_devices:
            self._start_idle_timer(device_id)

    def _start_idle_timer(self, device_id: str):
        """Schedule next idle squawk."""
        if not self.squawks:
            return
        delay = random.randint(IDLE_SQUAWK_MIN, IDLE_SQUAWK_MAX)
        task = asyncio.ensure_future(self._idle_squawk_loop(device_id, delay))
        self._idle_tasks[device_id] = task

    def _start_chatter_timer(self, device_id: str):
        """Schedule next chatter session."""
        if not self.chatter:
            return
        # First chatter after 1.5-2.5 hours, then every ~2 hours
        delay = random.randint(int(CHATTER_INTERVAL * 0.75), int(CHATTER_INTERVAL * 1.25))
        task = asyncio.ensure_future(self._chatter_loop(device_id, delay))
        self._chatter_tasks[device_id] = task

    async def _idle_squawk_loop(self, device_id: str, delay: int):
        """Wait, then play a random squawk, then reschedule."""
        try:
            await asyncio.sleep(delay)
            ws = self._active_devices.get(device_id)
            if ws and self.squawks:
                await self.send_squawk(device_id)
            # Reschedule
            if device_id in self._active_devices:
                self._start_idle_timer(device_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Idle squawk error for {device_id}: {e}")

    async def _chatter_loop(self, device_id: str, delay: int):
        """Wait, then play a random chatter clip, then reschedule."""
        try:
            await asyncio.sleep(delay)
            ws = self._active_devices.get(device_id)
            if ws and self.chatter:
                await self.send_chatter(device_id)
            # Reschedule
            if device_id in self._active_devices:
                self._start_chatter_timer(device_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Chatter error for {device_id}: {e}")

    async def send_squawk(self, device_id: str):
        """Send a random short squawk to a device."""
        if not self.squawks:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        squawk = random.choice(self.squawks)
        logger.info(f"Squawk! → {device_id}")
        await self._send_wav(ws, device_id, squawk)

    async def send_chatter(self, device_id: str):
        """Send a random long chatter clip (interruptible)."""
        if not self.chatter:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        chatter = random.choice(self.chatter)
        logger.info(f"Chatter starting → {device_id}")
        await self._send_wav(ws, device_id, chatter, interruptible=True)

    async def maybe_post_response_squawk(self, device_id: str):
        """20% chance of a short squawk after a TTS response."""
        if not self.squawks:
            return
        if random.random() < POST_RESPONSE_SQUAWK_CHANCE:
            # Small delay so it feels natural — like a parrot reacting
            await asyncio.sleep(random.uniform(0.3, 1.0))
            await self.send_squawk(device_id)

    async def send_wake_squawk(self, device_id: str):
        """Short squawk on wake word detection."""
        if not self.squawks:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        # Pick a random short squawk
        squawk = random.choice(self.squawks)
        logger.info(f"Wake squawk → {device_id}")
        await self._send_wav(ws, device_id, squawk)

    async def _send_wav(self, ws, device_id: str, wav_data: bytes, interruptible: bool = False):
        """Send WAV data as chunked base64 audio_chunk events."""
        self._playing[device_id] = True
        try:
            # Notify ESP32 that ambient sound is starting
            await ws.send_json({"event": "squawk_start"})

            chunk_size = 8000
            for i in range(0, len(wav_data), chunk_size):
                if not self._playing.get(device_id, False):
                    logger.info(f"Squawk/chatter interrupted → {device_id}")
                    break
                chunk = wav_data[i:i + chunk_size]
                chunk_b64 = base64.b64encode(chunk).decode()
                await ws.send_json({
                    "event": "audio_chunk",
                    "audio": chunk_b64,
                    "final": (i + chunk_size >= len(wav_data)),
                    "squawk": True,
                })
                await asyncio.sleep(0.05)

            await ws.send_json({"event": "squawk_end"})
        except Exception as e:
            logger.error(f"Squawk send error: {e}")
        finally:
            self._playing[device_id] = False
