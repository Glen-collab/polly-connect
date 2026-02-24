"""
Story mode recording for Polly Connect.
Extended recording sessions (up to 30 min), streams PCM to temp file.
On completion: converts to WAV, uploads to S3, triggers transcription.
"""

import io
import logging
import os
import tempfile
import time
import wave
from typing import Optional

logger = logging.getLogger(__name__)


class StoryModeSession:
    """Manages a single long-form recording session."""

    def __init__(self, device_id: str, user_id: int = None,
                 max_duration_s: float = 1800, silence_timeout_s: float = 5.0,
                 sample_rate: int = 16000):
        self.device_id = device_id
        self.user_id = user_id
        self.max_duration_s = max_duration_s
        self.silence_timeout_s = silence_timeout_s
        self.sample_rate = sample_rate

        self.source = "voice"  # or "wav_button"
        self.speaker_name = None

        # Recording state
        self._temp_file = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        self._temp_path = self._temp_file.name
        self._start_time = time.monotonic()
        self._last_voice_time = time.monotonic()
        self._total_bytes = 0
        self._finished = False

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def is_finished(self) -> bool:
        return self._finished

    def add_audio(self, pcm_bytes: bytes, rms: int = 0, silence_threshold: int = 300):
        """Add a chunk of raw PCM audio to the recording."""
        if self._finished:
            return

        self._temp_file.write(pcm_bytes)
        self._total_bytes += len(pcm_bytes)

        # Track voice activity
        if rms > silence_threshold:
            self._last_voice_time = time.monotonic()

        # Check end conditions
        now = time.monotonic()
        silence = now - self._last_voice_time
        total = now - self._start_time

        if silence > self.silence_timeout_s or total > self.max_duration_s:
            self.finish()

    def finish(self):
        """Mark recording as done, close temp file."""
        if self._finished:
            return
        self._finished = True
        self._temp_file.close()
        logger.info(f"Story recording finished: {self._total_bytes} bytes, "
                    f"{self.duration_seconds:.1f}s")

    def get_wav_bytes(self) -> Optional[bytes]:
        """Convert raw PCM to WAV bytes."""
        if not self._finished:
            self.finish()

        if self._total_bytes == 0:
            return None

        try:
            with open(self._temp_path, "rb") as f:
                raw_pcm = f.read()

            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)
                wav.writeframes(raw_pcm)

            return output.getvalue()
        except Exception as e:
            logger.error(f"Error creating WAV from story: {e}")
            return None

    def cleanup(self):
        """Remove temp file."""
        try:
            if os.path.exists(self._temp_path):
                os.unlink(self._temp_path)
        except Exception:
            pass

    def __del__(self):
        self.cleanup()
