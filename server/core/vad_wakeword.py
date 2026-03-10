"""
Simple VAD-based wake word detection for cloud deployment.
Replaces heavy OpenWakeWord — uses RMS energy to detect speech onset,
then checks transcription text for "hey polly" / "polly" prefix.

This is lighter weight than loading an ONNX model and works on t2.micro.
"""

import logging
import re
import numpy as np

logger = logging.getLogger(__name__)


class VADWakeWordDetector:
    """
    Two-phase wake word detection:
    1. detect() / detected() — RMS energy threshold (is someone speaking?)
       Requires multiple consecutive loud frames to avoid false triggers.
    2. check_transcription() — does the text start with the wake word?
    """

    def __init__(self, rms_threshold: int = 500, wake_phrases: list = None,
                 consecutive_frames: int = 4):
        self.rms_threshold = rms_threshold
        self.consecutive_frames = consecutive_frames  # need N consecutive loud frames
        self._loud_count = 0
        self._log_counter = 0
        self.wake_phrases = wake_phrases or [
            "hey polly",
            "polly",
            "hey poly",
            "poly",
            "hey holly",
            "holly",
            "hey paulie",
            "paulie",
            "hey pauly",
            "pauly",
            "hey paul",
            "play",
            "hey play",
        ]
        self._ready = True
        logger.info(f"VAD wake word detector initialized (RMS threshold: {rms_threshold}, "
                     f"consecutive frames: {consecutive_frames})")

    @property
    def ready(self) -> bool:
        return self._ready

    def detect(self, audio_chunk: np.ndarray) -> float:
        """Return RMS energy normalized to 0.0-1.0 range (for API compat)."""
        rms = float(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))
        # Normalize: 0 at silence, 1.0 at ~5000 RMS
        return min(rms / 5000.0, 1.0)

    def detected(self, audio_chunk: np.ndarray) -> bool:
        """Returns True if audio RMS exceeds speech threshold for N consecutive frames."""
        rms = int(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))

        # Log RMS periodically so we can tune the threshold
        self._log_counter += 1
        if self._log_counter % 25 == 0:  # every ~2 seconds
            logger.info(f"VAD RMS sample: {rms} (threshold: {self.rms_threshold}, "
                        f"loud_streak: {self._loud_count}/{self.consecutive_frames})")

        if rms > self.rms_threshold:
            self._loud_count += 1
            if self._loud_count >= self.consecutive_frames:
                logger.info(f"VAD triggered: {self.consecutive_frames} consecutive frames "
                            f"above {self.rms_threshold} (last RMS: {rms})")
                self._loud_count = 0
                return True
        else:
            self._loud_count = 0

        return False

    def check_transcription(self, text: str) -> tuple:
        """
        Check if transcription contains a wake phrase.
        Returns (is_wake, cleaned_text) where cleaned_text has everything
        up to and including the wake phrase stripped.
        """
        text_lower = text.lower().strip()
        # Try startswith first (most common case)
        for phrase in self.wake_phrases:
            if text_lower.startswith(phrase):
                remainder = text_lower[len(phrase):].strip()
                remainder = re.sub(r'^[,.\s]+', '', remainder)
                return True, remainder if remainder else text
        # Also check if wake phrase appears anywhere (e.g. "good job buddy hey polly what time")
        for phrase in self.wake_phrases:
            idx = text_lower.find(phrase)
            if idx > 0:
                remainder = text_lower[idx + len(phrase):].strip()
                remainder = re.sub(r'^[,.\s]+', '', remainder)
                return True, remainder if remainder else text
        return False, text

    def reset(self):
        """No-op for API compatibility with OpenWakeWord detector."""
        pass
