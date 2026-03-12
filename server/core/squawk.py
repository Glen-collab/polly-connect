"""
Parrot squawk / ambient sound system for Polly Connect.

Clock-based scheduling: squawks and chatter fire on wall-clock intervals,
surviving WebSocket reconnects without resetting timers.

Short squawks: play at regular intervals (default every 10 min) with jitter.
Long chatter: play at longer intervals (default every 45 min) with jitter.
Post-response squawks: 50% chance after TTS, with delay to avoid mic feedback.
"""

import asyncio
import base64
import io
import logging
import os
import random
import time
import wave
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default intervals (can be overridden per-device via settings)
DEFAULT_SQUAWK_MINUTES = 10
DEFAULT_CHATTER_MINUTES = 45

# Chance of squawk after a TTS response (disabled — causes ESP32 crash)
POST_RESPONSE_SQUAWK_CHANCE = 0.0  # disabled

# Volume reduction (0.0 = silent, 1.0 = full)
SQUAWK_VOLUME = 0.30  # 30% volume so mic doesn't pick it up

# Jitter range (seconds) added to scheduled times so sounds feel natural
JITTER_SECONDS = 120  # ±2 minutes

# Delay before first squawk after reconnect (seconds)
RECONNECT_GRACE = 60


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


def _convert_to_16k_mono_from_pcm(wav_bytes: bytes, volume: float) -> bytes:
    """Apply volume to an already-converted 16kHz mono WAV."""
    with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    samples = samples * volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.tobytes())
    return out.getvalue()


class SquawkManager:
    def __init__(self, sounds_dir: str):
        self.squawks: List[bytes] = []       # short squawk WAVs (16kHz mono, default volume)
        self.chatter: List[bytes] = []       # long chatter WAVs (16kHz mono, default volume)
        self._raw_squawks: List[bytes] = []  # raw WAVs at full volume (for per-device volume)
        self._raw_chatter: List[bytes] = []  # raw WAVs at full volume (for per-device volume)
        self._active_devices: Dict[str, asyncio.WebSocketServerProtocol] = {}
        self._playing: Dict[str, bool] = {}  # True if currently sending squawk/chatter
        self._busy: Dict[str, bool] = {}     # True if device is recording/processing/playing TTS
        self._send_locks: Dict[str, asyncio.Lock] = {}  # prevent concurrent WS writes
        self._snoozed_until: Dict[str, Optional[float]] = {}  # epoch time when snooze ends
        self._quiet_hours: Dict[str, tuple] = {}  # per-device (start_hour, end_hour)
        self.last_squawk_end: Dict[str, float] = {}  # monotonic time when last squawk/chatter finished
        self._volume: Dict[str, float] = {}  # per-device volume (0.0-1.0)

        # Clock-based scheduling: wall-clock epoch timestamps
        self._next_squawk_time: Dict[str, float] = {}  # next squawk epoch
        self._next_chatter_time: Dict[str, float] = {}  # next chatter epoch
        self._squawk_interval: Dict[str, int] = {}   # per-device squawk interval (minutes)
        self._chatter_interval: Dict[str, int] = {}  # per-device chatter interval (minutes)

        # Nostalgia callbacks: device_id -> async callable
        self._nostalgia_callbacks: Dict[str, callable] = {}

        # Single scheduler task per device (polling loop)
        self._scheduler_tasks: Dict[str, asyncio.Task] = {}

        self._load_sounds(sounds_dir)

    def _load_sounds(self, sounds_dir: str):
        """Load and convert all squawk/chatter WAV files."""
        if not os.path.isdir(sounds_dir):
            logger.warning(f"Sounds directory not found: {sounds_dir}")
            return

        for fname in sorted(os.listdir(sounds_dir)):
            if not fname.endswith('.wav'):
                continue
            path = os.path.join(sounds_dir, fname)
            try:
                with open(path, 'rb') as f:
                    raw_bytes = f.read()
                converted = _convert_to_16k_mono(raw_bytes)
                raw_full = _convert_to_16k_mono(raw_bytes, volume=1.0)
                if fname.startswith('chatter'):
                    self.chatter.append(converted)
                    self._raw_chatter.append(raw_full)
                    logger.info(f"Loaded chatter sound: {fname}")
                elif fname.startswith('squawk'):
                    self.squawks.append(converted)
                    self._raw_squawks.append(raw_full)
                    logger.info(f"Loaded squawk sound: {fname}")
            except Exception as e:
                logger.error(f"Failed to load sound {fname}: {e}")

        logger.info(f"SquawkManager ready: {len(self.squawks)} squawks, {len(self.chatter)} chatter files")

    def _schedule_next_squawk(self, device_id: str, min_delay: float = 0):
        """Set the next squawk time based on interval + jitter. 0 = disabled."""
        interval_min = self._squawk_interval.get(device_id, DEFAULT_SQUAWK_MINUTES)
        if interval_min == 0:
            self._next_squawk_time[device_id] = float('inf')  # never fires
            return
        interval = interval_min * 60
        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
        delay = max(min_delay, interval + jitter)
        self._next_squawk_time[device_id] = time.time() + delay
        logger.debug(f"Next squawk for {device_id} in {delay:.0f}s")

    def _schedule_next_chatter(self, device_id: str, min_delay: float = 0):
        """Set the next chatter time based on interval + jitter. 0 = disabled."""
        interval_min = self._chatter_interval.get(device_id, DEFAULT_CHATTER_MINUTES)
        if interval_min == 0:
            self._next_chatter_time[device_id] = float('inf')  # never fires
            return
        interval = interval_min * 60
        jitter = random.uniform(-JITTER_SECONDS, JITTER_SECONDS)
        delay = max(min_delay, interval + jitter)
        self._next_chatter_time[device_id] = time.time() + delay
        logger.debug(f"Next chatter for {device_id} in {delay:.0f}s")

    def register_device(self, device_id: str, websocket,
                        squawk_interval: int = None, chatter_interval: int = None,
                        quiet_hours_start: int = 21, quiet_hours_end: int = 7,
                        squawk_volume: int = 30):
        """Register or re-register a connected device. Preserves existing schedules."""
        # Always update the websocket reference
        self._active_devices[device_id] = websocket
        self._playing[device_id] = False
        self._send_locks[device_id] = asyncio.Lock()
        self._quiet_hours[device_id] = (quiet_hours_start, quiet_hours_end)
        self._volume[device_id] = max(0, min(100, squawk_volume)) / 100.0

        # Update intervals
        self._squawk_interval[device_id] = squawk_interval or DEFAULT_SQUAWK_MINUTES
        self._chatter_interval[device_id] = chatter_interval or DEFAULT_CHATTER_MINUTES

        # Only schedule if no existing schedule (don't reset on reconnect!)
        now = time.time()
        if device_id not in self._next_squawk_time or self._next_squawk_time[device_id] < now:
            # Either first time or schedule already passed — schedule with grace period
            self._schedule_next_squawk(device_id, min_delay=RECONNECT_GRACE)

        if device_id not in self._next_chatter_time or self._next_chatter_time[device_id] < now:
            self._schedule_next_chatter(device_id, min_delay=RECONNECT_GRACE * 3)

        # Start scheduler loop if not already running
        existing_task = self._scheduler_tasks.get(device_id)
        if not existing_task or existing_task.done():
            task = asyncio.ensure_future(self._scheduler_loop(device_id))
            self._scheduler_tasks[device_id] = task

        logger.info(
            f"Squawk registered {device_id}: "
            f"squawk every {self._squawk_interval[device_id]}min, "
            f"chatter every {self._chatter_interval[device_id]}min, "
            f"next squawk in {self._next_squawk_time[device_id] - now:.0f}s, "
            f"next chatter in {self._next_chatter_time[device_id] - now:.0f}s"
        )

    def register_nostalgia_callback(self, device_id: str, callback):
        """Register an async callback for nostalgia TTS during chatter slots."""
        self._nostalgia_callbacks[device_id] = callback

    def unregister_nostalgia_callback(self, device_id: str):
        self._nostalgia_callbacks.pop(device_id, None)

    def unregister_device(self, device_id: str):
        """Mark device as disconnected. Does NOT cancel schedules."""
        self._active_devices.pop(device_id, None)
        self._playing.pop(device_id, None)
        self._nostalgia_callbacks.pop(device_id, None)
        # Keep send lock, schedules, intervals, quiet hours — they survive reconnects
        # The scheduler loop will idle while device is not in _active_devices

    def snooze(self, device_id: str, minutes: int):
        """Snooze all squawks/chatter for N minutes."""
        self._snoozed_until[device_id] = time.time() + minutes * 60
        logger.info(f"Squawks snoozed for {minutes}min → {device_id}")

    def unsnooze(self, device_id: str):
        """Cancel snooze and resume squawks immediately."""
        self._snoozed_until.pop(device_id, None)
        logger.info(f"Squawks unsnoozed → {device_id}")

    def is_snoozed(self, device_id: str) -> bool:
        until = self._snoozed_until.get(device_id)
        if until and time.time() < until:
            return True
        return self._in_quiet_hours(device_id)

    def _in_quiet_hours(self, device_id: str) -> bool:
        """Check if current time is within quiet hours (no squawks at night)."""
        from config import settings as app_settings
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(app_settings.TIMEZONE)
        except Exception:
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

    def update_intervals(self, device_id: str, squawk_interval: int = None,
                         chatter_interval: int = None,
                         quiet_hours_start: int = None, quiet_hours_end: int = None,
                         squawk_volume: int = None):
        """Update intervals for a device (from web settings)."""
        if squawk_interval is not None:
            self._squawk_interval[device_id] = squawk_interval
        if chatter_interval is not None:
            self._chatter_interval[device_id] = chatter_interval
        if quiet_hours_start is not None and quiet_hours_end is not None:
            self._quiet_hours[device_id] = (quiet_hours_start, quiet_hours_end)
        if squawk_volume is not None:
            self._volume[device_id] = max(0, min(100, squawk_volume)) / 100.0
        # Reschedule with new intervals
        self._schedule_next_squawk(device_id, min_delay=30)
        self._schedule_next_chatter(device_id, min_delay=60)

    def get_send_lock(self, device_id: str) -> Optional[asyncio.Lock]:
        """Get the websocket send lock for a device (used by _send_tts too)."""
        return self._send_locks.get(device_id)

    def stop_playback(self, device_id: str):
        """Interrupt any currently playing squawk/chatter."""
        self._playing[device_id] = False

    def is_playing(self, device_id: str) -> bool:
        return self._playing.get(device_id, False)

    def set_busy(self, device_id: str, busy: bool):
        """Mark device as busy (recording, processing, or playing TTS). Suppresses squawks."""
        self._busy[device_id] = busy

    def is_busy(self, device_id: str) -> bool:
        return self._busy.get(device_id, False)

    def reset_idle_timer(self, device_id: str):
        """Push back the next squawk after user activity (so it doesn't squawk mid-conversation)."""
        grace = self._squawk_interval.get(device_id, DEFAULT_SQUAWK_MINUTES) * 60
        next_time = time.time() + grace
        # Only push forward, never pull back
        if next_time > self._next_squawk_time.get(device_id, 0):
            self._next_squawk_time[device_id] = next_time

    # ── Scheduler loop ──────────────────────────────────────────────

    async def _scheduler_loop(self, device_id: str):
        """Single polling loop per device. Checks wall-clock schedules every 15s."""
        logger.info(f"Scheduler loop started → {device_id}")
        try:
            while True:
                await asyncio.sleep(15)  # Check every 15 seconds

                # If device not connected, just idle
                ws = self._active_devices.get(device_id)
                if not ws:
                    continue

                # Skip during quiet hours or snooze
                if self.is_snoozed(device_id):
                    continue

                # Skip if device is busy (recording, processing, or playing TTS)
                if self.is_busy(device_id):
                    continue

                now = time.time()

                # Check squawk schedule
                next_sq = self._next_squawk_time.get(device_id, 0)
                if now >= next_sq and self.squawks:
                    await self.send_squawk(device_id)
                    self._schedule_next_squawk(device_id)

                # Check chatter schedule (20% chance to play nostalgia snippet instead)
                next_ch = self._next_chatter_time.get(device_id, 0)
                if now >= next_ch and self.chatter:
                    nostalgia_cb = self._nostalgia_callbacks.get(device_id)
                    if nostalgia_cb and random.random() < 0.20:
                        try:
                            await nostalgia_cb()
                        except Exception as e:
                            logger.error(f"Nostalgia callback error: {e}")
                            await self.send_chatter(device_id)
                    else:
                        await self.send_chatter(device_id)
                    self._schedule_next_chatter(device_id)

        except asyncio.CancelledError:
            logger.info(f"Scheduler loop cancelled → {device_id}")
        except Exception as e:
            logger.error(f"Scheduler loop error for {device_id}: {e}")

    # ── Sound sending ───────────────────────────────────────────────

    def _pick_sound(self, device_id: str, raw_list: List[bytes], default_list: List[bytes]) -> bytes:
        """Pick a random sound with per-device volume applied."""
        vol = self._volume.get(device_id, SQUAWK_VOLUME)
        idx = random.randrange(len(raw_list))
        # If volume matches default, use pre-converted version
        if abs(vol - SQUAWK_VOLUME) < 0.01:
            return default_list[idx]
        return _convert_to_16k_mono_from_pcm(raw_list[idx], vol)

    async def send_squawk(self, device_id: str):
        """Send a random short squawk to a device."""
        if not self.squawks:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        squawk = self._pick_sound(device_id, self._raw_squawks, self.squawks)
        logger.info(f"Squawk! → {device_id} (vol {self._volume.get(device_id, SQUAWK_VOLUME):.0%})")
        await self._send_wav(ws, device_id, squawk)

    async def send_chatter(self, device_id: str):
        """Send a random long chatter clip (interruptible)."""
        if not self.chatter:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        chatter = self._pick_sound(device_id, self._raw_chatter, self.chatter)
        logger.info(f"Chatter starting → {device_id} (vol {self._volume.get(device_id, SQUAWK_VOLUME):.0%})")
        await self._send_wav(ws, device_id, chatter, interruptible=True)

    async def maybe_post_response_squawk(self, device_id: str, tts_duration: float = 0.0):
        """50% chance of a short squawk after a TTS response."""
        if not self.squawks or self.is_snoozed(device_id):
            return
        if self._squawk_interval.get(device_id, DEFAULT_SQUAWK_MINUTES) == 0:
            return  # squawks disabled
        if random.random() < POST_RESPONSE_SQUAWK_CHANCE:
            # Wait for TTS to finish playing on ESP32, plus buffer for speaker→mic fade
            wait = max(3.5, tts_duration + 2.0) + random.uniform(0.5, 2.0)
            await asyncio.sleep(wait)
            # Re-check busy/snoozed after waiting (user may have started talking)
            if self.is_busy(device_id) or self.is_snoozed(device_id):
                return
            await self.send_squawk(device_id)

    async def send_wake_squawk(self, device_id: str):
        """Short squawk on wake word detection."""
        if not self.squawks:
            return
        ws = self._active_devices.get(device_id)
        if not ws:
            return
        squawk = self._pick_sound(device_id, self._raw_squawks, self.squawks)
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
                self.last_squawk_end[device_id] = time.monotonic()
