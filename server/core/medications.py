"""
Medication reminder system for Polly Connect.
Background scheduler checks medication times every minute,
pushes squawk + TTS voice reminders through WebSocket connections.
"""

import asyncio
import base64
import glob
import io
import json
import logging
import os
import random
import struct
import wave
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings

logger = logging.getLogger(__name__)

# Path to squawk WAV files
SOUNDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "sounds")


def format_time_12hr(time_str: str) -> str:
    """Convert '14:00' to '2:00 PM'."""
    try:
        h, m = time_str.split(":")
        h = int(h)
        m = int(m)
        period = "AM" if h < 12 else "PM"
        display_h = h % 12 or 12
        if m == 0:
            return f"{display_h} {period}"
        return f"{display_h}:{m:02d} {period}"
    except (ValueError, AttributeError):
        return time_str


def _get_local_now():
    """Get current datetime in the configured timezone."""
    tz = ZoneInfo(settings.TIMEZONE)
    return datetime.now(tz)


def _load_squawk_16k_mono() -> Optional[bytes]:
    """Pick a random squawk WAV, convert to 16kHz mono PCM bytes."""
    pattern = os.path.join(SOUNDS_DIR, "squawk*.wav")
    files = glob.glob(pattern)
    if not files:
        logger.warning(f"No squawk WAV files found in {SOUNDS_DIR}")
        return None

    chosen = random.choice(files)
    try:
        with wave.open(chosen, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        # Convert to 16-bit samples
        if sampwidth == 1:
            # 8-bit unsigned → 16-bit signed
            samples = [((b - 128) << 8) for b in raw]
        elif sampwidth == 2:
            samples = list(struct.unpack(f"<{len(raw)//2}h", raw))
        elif sampwidth == 3:
            # 24-bit → 16-bit (take top 2 bytes)
            samples = []
            for i in range(0, len(raw), 3):
                val = int.from_bytes(raw[i:i+3], "little", signed=True)
                samples.append(val >> 8)
        else:
            logger.error(f"Unsupported sample width: {sampwidth}")
            return None

        # Stereo → mono (average channels)
        if n_channels == 2:
            mono = []
            for i in range(0, len(samples), 2):
                if i + 1 < len(samples):
                    mono.append((samples[i] + samples[i + 1]) // 2)
                else:
                    mono.append(samples[i])
            samples = mono
        elif n_channels > 2:
            # Take first channel
            mono = []
            for i in range(0, len(samples), n_channels):
                mono.append(samples[i])
            samples = mono

        # Resample to 16kHz if needed (simple linear interpolation)
        if framerate != 16000:
            ratio = framerate / 16000
            new_len = int(len(samples) / ratio)
            resampled = []
            for i in range(new_len):
                src_idx = i * ratio
                idx = int(src_idx)
                frac = src_idx - idx
                if idx + 1 < len(samples):
                    val = int(samples[idx] * (1 - frac) + samples[idx + 1] * frac)
                else:
                    val = samples[idx] if idx < len(samples) else 0
                # Clamp to int16 range
                val = max(-32768, min(32767, val))
                resampled.append(val)
            samples = resampled

        # Pack as 16-bit PCM
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        return pcm

    except Exception as e:
        logger.error(f"Error loading squawk WAV {chosen}: {e}")
        return None


def _make_wav(pcm_data: bytes) -> bytes:
    """Wrap raw 16kHz mono PCM in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _extract_pcm(wav_bytes: bytes) -> bytes:
    """Extract raw PCM from a WAV file."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        return wf.readframes(wf.getnframes())


class MedicationScheduler:
    def __init__(self, db, tts=None):
        self.db = db
        self.tts = tts
        self._running = False
        self._websockets = {}  # device_id -> {"ws": websocket, "tenant_id": int}
        self._task = None
        self._last_reminded = {}  # med_id:time_str -> "YYYY-MM-DD HH:MM"

    def register_websocket(self, device_id: str, websocket, tenant_id: int = 1):
        """Track active WebSocket connections for push reminders."""
        self._websockets[device_id] = {"ws": websocket, "tenant_id": tenant_id}
        logger.info(f"Medication scheduler: registered device {device_id} (tenant={tenant_id})")

    def unregister_websocket(self, device_id: str):
        removed = self._websockets.pop(device_id, None)
        if removed:
            logger.info(f"Medication scheduler: unregistered device {device_id}")

    async def start(self):
        """Start the background medication check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info(f"Medication scheduler started (timezone: {settings.TIMEZONE})")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _check_loop(self):
        """Check medication schedules every 60 seconds."""
        while self._running:
            try:
                await self._check_medications()
            except Exception as e:
                logger.error(f"Medication check error: {e}")
            await asyncio.sleep(60)

    async def _check_medications(self):
        """Check if any medications are due now (using configured timezone)."""
        now = _get_local_now()
        current_time = now.strftime("%H:%M")
        current_day = now.strftime("%a").lower()
        today_key = now.strftime("%Y-%m-%d")

        meds = self.db.get_medications()
        for med in meds:
            times = json.loads(med["times"]) if isinstance(med["times"], str) else med["times"]
            active_days = json.loads(med["active_days"]) if isinstance(med["active_days"], str) else med["active_days"]

            if current_day not in active_days:
                continue

            tenant_id = med.get("tenant_id")

            for med_time in times:
                if med_time == current_time:
                    # Prevent duplicate sends within the same minute
                    dedup_key = f"{med['id']}:{med_time}:{today_key}"
                    if dedup_key in self._last_reminded:
                        continue
                    self._last_reminded[dedup_key] = True

                    await self._send_reminder(med, med_time, tenant_id)

        # Clean old dedup keys (keep only today's)
        old_keys = [k for k in self._last_reminded if not k.endswith(today_key)]
        for k in old_keys:
            del self._last_reminded[k]

    async def _send_reminder(self, med: dict, med_time: str, tenant_id: int = None):
        """Push squawk + TTS medication reminder to connected devices for this tenant."""
        name = med["name"]
        dosage = med.get("dosage", "")
        time_display = format_time_12hr(med_time)

        # Build announcement text
        msg = f"It's {time_display}, time to take"
        if dosage:
            msg += f" {dosage} of {name}"
        else:
            msg += f" your {name}"

        logger.info(f"Medication reminder: {msg}")

        # Generate combined squawk + TTS audio
        combined_wav = await self._build_reminder_audio(msg)

        sent_count = 0
        for device_id, info in list(self._websockets.items()):
            # Only send to devices belonging to this medication's tenant
            if tenant_id is not None and info["tenant_id"] != tenant_id:
                continue

            ws = info["ws"]
            try:
                # Send text event
                await ws.send_json({
                    "event": "medication_reminder",
                    "text": msg,
                    "medication_id": med["id"],
                    "medication_name": name,
                })

                # Send audio chunks
                if combined_wav:
                    chunk_size = 8000
                    for i in range(0, len(combined_wav), chunk_size):
                        chunk = combined_wav[i:i + chunk_size]
                        chunk_b64 = base64.b64encode(chunk).decode()
                        await ws.send_json({
                            "event": "audio_chunk",
                            "audio": chunk_b64,
                            "final": (i + chunk_size >= len(combined_wav)),
                        })
                        await asyncio.sleep(0.05)

                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send reminder to {device_id}: {e}")
                self.unregister_websocket(device_id)

        if sent_count > 0:
            logger.info(f"Reminder sent to {sent_count} device(s)")
        else:
            logger.info("No connected devices for this tenant — reminder logged only")

        # Log the reminder
        self.db.log_medication(med["id"], "reminded", scheduled_time=med_time, reminder_count=1)

    async def _build_reminder_audio(self, text: str) -> Optional[bytes]:
        """Build combined squawk + TTS WAV audio."""
        pcm_parts = []

        # 1. Load a random squawk
        squawk_pcm = _load_squawk_16k_mono()
        if squawk_pcm:
            pcm_parts.append(squawk_pcm)
            # Add 0.3s silence gap between squawk and voice
            silence = b"\x00" * (16000 * 2 * 3 // 10)  # 0.3s at 16kHz 16-bit
            pcm_parts.append(silence)

        # 2. Generate TTS for the message
        if self.tts:
            try:
                tts_wav = await asyncio.to_thread(self.tts.synthesize, text)
                if tts_wav:
                    tts_pcm = _extract_pcm(tts_wav)
                    pcm_parts.append(tts_pcm)
            except Exception as e:
                logger.error(f"TTS synthesis for reminder failed: {e}")

        if not pcm_parts:
            return None

        # Combine all PCM and wrap in WAV
        combined_pcm = b"".join(pcm_parts)
        return _make_wav(combined_pcm)

    def parse_medication_command(self, text: str) -> Optional[dict]:
        """Parse medication-related voice commands."""
        text_lower = text.lower()

        # "remind me to take aspirin at 8am and 8pm"
        import re
        add_match = re.search(
            r"remind me to take (.+?) at (.+)", text_lower
        )
        if add_match:
            name = add_match.group(1).strip()
            time_str = add_match.group(2).strip()
            # Parse times like "8am and 8pm" or "8:00, 20:00"
            times = self._parse_times(time_str)
            return {"action": "add", "name": name, "times": times}

        # "what medications do I take"
        if "what medication" in text_lower or "my pills" in text_lower:
            return {"action": "list"}

        # "did I take my pills" / "yes I took it"
        if "took" in text_lower or "yes" in text_lower or "taken" in text_lower:
            return {"action": "confirm_taken"}

        return None

    def _parse_times(self, time_str: str) -> list:
        """Parse time strings like '8am and 8pm' into ['08:00', '20:00']."""
        import re
        times = []
        # Find patterns like 8am, 8:00am, 20:00
        matches = re.findall(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str.lower())
        for hour, minute, period in matches:
            h = int(hour)
            m = int(minute) if minute else 0
            if period == "pm" and h < 12:
                h += 12
            elif period == "am" and h == 12:
                h = 0
            times.append(f"{h:02d}:{m:02d}")
        return times if times else ["08:00"]
