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
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default intervals (can be overridden per-device via settings)
IDLE_SQUAWK_MIN = 5 * 60    # 5 minutes
IDLE_SQUAWK_MAX = 15 * 60   # 15 minutes

# Default chatter interval (minutes) — configurable in web settings
DEFAULT_CHATTER_MINUTES = 45

# Chance of squawk after a TTS response
POST_RESPONSE_SQUAWK_CHANCE = 0.50  # 50%

# Volume reduction (0.0 = silent, 1.0 = full)
SQUAWK_VOLUME = 0.30  # 30% volume so mic doesn't pick it up


def _convert_to_16k_mono(wav_bytes: bytes, volume: float = SQUAWK_VOLUME) -> bytes:
    """Convert any WAV to 16kHz mono 16-bit WAV with volume adjustment."""
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

    # Apply volume reduction
    samples = samples * volume

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
        self._send_locks: Dict[str, asyncio.Lock] = {}  # prevent concurrent WS writes
        self._squawk_interval: Dict[str, int] = {}   # per-device squawk interval (minutes)
        self._chatter_interval: Dict[str, int] = {}  # per-device chatter interval (minutes)
        self._snoozed_until: Dict[str, Optional[float]] = {}  # epoch time when snooze ends
        self._quiet_hours: Dict[str, tuple] = {}  # per-device (start_hour, end_hour)

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

    def register_device(self, device_id: str, websocket,
                        squawk_interval: int = None, chatter_interval: int = None,
                        quiet_hours_start: int = 21, quiet_hours_end: int = 7):
        """Start idle squawk timer for a connected device."""
        self._active_devices[device_id] = websocket
        self._playing[device_id] = False
        self._send_locks[device_id] = asyncio.Lock()
        self._squawk_interval[device_id] = squawk_interval or 10
        self._chatter_interval[device_id] = chatter_interval or DEFAULT_CHATTER_MINUTES
        self._quiet_hours[device_id] = (quiet_hours_start, quiet_hours_end)
        self._start_idle_timer(device_id)
        if self.chatter:
            self._start_chatter_timer(device_id)

    def unregister_device(self, device_id: str):
        """Stop timers when device disconnects."""
        self._active_devices.pop(device_id, None)
        self._playing.pop(device_id, None)
        self._send_locks.pop(device_id, None)
        self._squawk_interval.pop(device_id, None)
        self._chatter_interval.pop(device_id, None)
        self._snoozed_until.pop(device_id, None)
        self._quiet_hours.pop(device_id, None)
        task = self._idle_tasks.pop(device_id, None)
        if task:
            task.cancel()
        task = self._chatter_tasks.pop(device_id, None)
        if task:
            task.cancel()

    def snooze(self, device_id: str, minutes: int):
        """Snooze all squawks/chatter for N minutes."""
        import time
        self._snoozed_until[device_id] = time.time() + minutes * 60
        # Cancel current timers, they'll skip when they fire if snoozed
        task = self._idle_tasks.pop(device_id, None)
        if task:
            task.cancel()
        task = self._chatter_tasks.pop(device_id, None)
        if task:
            task.cancel()
        # Schedule timers to resume after snooze ends
        asyncio.ensure_future(self._resume_after_snooze(device_id, minutes * 60))
        logger.info(f"Squawks snoozed for {minutes}min → {device_id}")

    def unsnooze(self, device_id: str):
        """Cancel snooze and resume squawks immediately."""
        self._snoozed_until.pop(device_id, None)
        if device_id in self._active_devices:
            self._start_idle_timer(device_id)
            if self.chatter:
                self._start_chatter_timer(device_id)
        logger.info(f"Squawks unsnoozed → {device_id}")

    def is_snoozed(self, device_id: str) -> bool:
        import time
        until = self._snoozed_until.get(device_id)
        if until and time.time() < until:
            return True
        return self._in_quiet_hours(device_id)

    def _in_quiet_hours(self, device_id: str) -> bool:
        """Check if current time is within quiet hours (no squawks at night)."""
        from config import settings as app_settings
        try:
            import pytz
            tz = pytz.timezone(app_settings.TIMEZONE)
        except Exception:
            from datetime import timezone
            tz = timezone.utc
        now_hour = datetime.now(tz).hour
        start, end = self._quiet_hours.get(device_id, (21, 7))
        if start > end:
            # Wraps midnight: e.g. 21-7 means 9PM to 7AM
            return now_hour >= start or now_hour < end
        elif start < end:
            # Same day: e.g. 14-16 means 2PM to 4PM
            return start <= now_hour < end
        return False

    async def _resume_after_snooze(self, device_id: str, delay: float):
        """Resume squawk timers after snooze expires."""
        try:
            await asyncio.sleep(delay)
            if device_id in self._active_devices and self.is_snoozed(device_id):
                self._snoozed_until.pop(device_id, None)
            if device_id in self._active_devices:
                self._start_idle_timer(device_id)
                if self.chatter:
                    self._start_chatter_timer(device_id)
                logger.info(f"Squawks resumed after snooze → {device_id}")
        except asyncio.CancelledError:
            pass

    def update_intervals(self, device_id: str, squawk_interval: int = None,
                         chatter_interval: int = None,
                         quiet_hours_start: int = None, quiet_hours_end: int = None):
        """Update intervals for a device (from web settings)."""
        if squawk_interval is not None:
            self._squawk_interval[device_id] = squawk_interval
        if chatter_interval is not None:
            self._chatter_interval[device_id] = chatter_interval
        if quiet_hours_start is not None and quiet_hours_end is not None:
            self._quiet_hours[device_id] = (quiet_hours_start, quiet_hours_end)
        # Restart timers with new intervals
        if device_id in self._active_devices:
            task = self._idle_tasks.pop(device_id, None)
            if task:
                task.cancel()
            task = self._chatter_tasks.pop(device_id, None)
            if task:
                task.cancel()
            self._start_idle_timer(device_id)
            if self.chatter:
                self._start_chatter_timer(device_id)

    def get_send_lock(self, device_id: str) -> Optional[asyncio.Lock]:
        """Get the websocket send lock for a device (used by _send_tts too)."""
        return self._send_locks.get(device_id)

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
        interval = self._squawk_interval.get(device_id, 10) * 60
        delay = random.randint(int(interval * 0.5), int(interval * 1.5))
        task = asyncio.ensure_future(self._idle_squawk_loop(device_id, delay))
        self._idle_tasks[device_id] = task

    def _start_chatter_timer(self, device_id: str):
        """Schedule next chatter session."""
        if not self.chatter:
            return
        interval = self._chatter_interval.get(device_id, DEFAULT_CHATTER_MINUTES) * 60
        delay = random.randint(int(interval * 0.75), int(interval * 1.25))
        task = asyncio.ensure_future(self._chatter_loop(device_id, delay))
        self._chatter_tasks[device_id] = task

    async def _idle_squawk_loop(self, device_id: str, delay: int):
        """Wait, then play a random squawk, then reschedule."""
        try:
            await asyncio.sleep(delay)
            ws = self._active_devices.get(device_id)
            if ws and self.squawks and not self.is_snoozed(device_id):
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
            if ws and self.chatter and not self.is_snoozed(device_id):
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
        if not self.squawks or self.is_snoozed(device_id):
            return
        if random.random() < POST_RESPONSE_SQUAWK_CHANCE:
            # Wait past the 3s response cooldown so mic feedback doesn't retrigger
            await asyncio.sleep(random.uniform(3.5, 5.0))
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
        lock = self._send_locks.get(device_id)
        if not lock:
            return

        async with lock:
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
