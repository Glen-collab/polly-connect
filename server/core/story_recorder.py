"""
Story Recorder for Polly Connect.

Manages WAV recording sessions triggered by the story button.
Accumulates raw PCM audio to disk, transcribes in segments,
and saves the final WAV + transcript as a story.
"""

import io
import logging
import os
import time
import wave
from typing import Optional

logger = logging.getLogger(__name__)

# Max recording: 30 minutes of 16kHz mono 16-bit = ~57.6 MB
MAX_DURATION_S = 1800
SAMPLE_RATE = 16000
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")


class StoryRecordingSession:
    """Manages a single button-triggered WAV recording session."""

    def __init__(self, device_id: str, tenant_id: int = None):
        self.device_id = device_id
        self.tenant_id = tenant_id
        self.start_time = time.monotonic()
        self.total_bytes = 0
        self.finished = False

        # Accumulate PCM in memory (PSRAM on device, RAM on server)
        # For 30min at 16kHz mono 16-bit = ~57MB — manageable on EC2
        self._pcm_chunks = []

        # Segment transcription: accumulate audio between silences,
        # transcribe each segment, build full transcript
        self._segment_audio = bytearray()
        self._segment_start = time.monotonic()
        self._last_voice_time = time.monotonic()
        self._transcript_parts = []

        logger.info(f"Story recording started for device {device_id}")

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def is_over_limit(self) -> bool:
        return self.duration_seconds > MAX_DURATION_S

    def add_audio(self, pcm_bytes: bytes, rms: int = 0):
        """Add a chunk of raw PCM audio to the recording."""
        if self.finished:
            return

        self._pcm_chunks.append(pcm_bytes)
        self._segment_audio.extend(pcm_bytes)
        self.total_bytes += len(pcm_bytes)

        # Track voice activity for segment splitting
        if rms > 100:
            self._last_voice_time = time.monotonic()

    def should_transcribe_segment(self) -> bool:
        """Check if we've hit a silence gap worth transcribing."""
        if self.finished:
            return False
        silence = time.monotonic() - self._last_voice_time
        segment_duration = time.monotonic() - self._segment_start
        # Transcribe after 3s silence or 60s continuous
        return (silence > 3.0 and len(self._segment_audio) > 32000) or segment_duration > 60.0

    def get_segment_wav(self) -> Optional[bytes]:
        """Get current segment as WAV bytes for transcription, then reset segment."""
        if len(self._segment_audio) < 3200:  # less than 0.1s
            return None

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(self._segment_audio)

        # Reset segment
        self._segment_audio = bytearray()
        self._segment_start = time.monotonic()

        return wav_buffer.getvalue()

    def add_transcript_segment(self, text: str):
        """Add a transcribed segment to the running transcript."""
        if text and text.strip():
            self._transcript_parts.append(text.strip())

    def get_full_transcript(self) -> str:
        """Get the complete transcript from all segments."""
        return " ".join(self._transcript_parts)

    def finish(self) -> dict:
        """
        Finalize the recording. Returns dict with:
          wav_path, transcript, duration_seconds, total_bytes
        """
        if self.finished:
            return {}
        self.finished = True

        duration = self.duration_seconds
        logger.info(f"Story recording finished: {self.total_bytes} bytes, {duration:.1f}s")

        # Combine all PCM chunks into a WAV file
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        timestamp = int(time.time())
        filename = f"story_{self.device_id}_{timestamp}.wav"
        wav_path = os.path.join(RECORDINGS_DIR, filename)

        try:
            all_pcm = b"".join(self._pcm_chunks)
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(all_pcm)
            logger.info(f"WAV saved: {wav_path} ({len(all_pcm)} bytes PCM)")
        except Exception as e:
            logger.error(f"Failed to save WAV: {e}")
            wav_path = None

        # Free memory
        self._pcm_chunks = []
        self._segment_audio = bytearray()

        return {
            "wav_path": wav_path,
            "wav_filename": filename if wav_path else None,
            "transcript": self.get_full_transcript(),
            "duration_seconds": duration,
            "total_bytes": self.total_bytes,
        }
