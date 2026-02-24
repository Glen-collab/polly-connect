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
    2. check_transcription() — does the text start with the wake word?
    """

    def __init__(self, rms_threshold: int = 500, wake_phrases: list = None):
        self.rms_threshold = rms_threshold
        self.wake_phrases = wake_phrases or [
            "hey polly",
            "polly",
            "hey poly",
            "poly",
        ]
        self._ready = True
        logger.info(f"VAD wake word detector initialized (RMS threshold: {rms_threshold})")

    @property
    def ready(self) -> bool:
        return self._ready

    def detect(self, audio_chunk: np.ndarray) -> float:
        """Return RMS energy normalized to 0.0-1.0 range (for API compat)."""
        rms = float(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))
        # Normalize: 0 at silence, 1.0 at ~5000 RMS
        return min(rms / 5000.0, 1.0)

    def detected(self, audio_chunk: np.ndarray) -> bool:
        """Returns True if audio RMS exceeds speech threshold."""
        rms = int(np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2)))
        return rms > self.rms_threshold

    def check_transcription(self, text: str) -> tuple:
        """
        Check if transcription starts with a wake phrase.
        Returns (is_wake, cleaned_text) where cleaned_text has the wake phrase stripped.
        """
        text_lower = text.lower().strip()
        for phrase in self.wake_phrases:
            if text_lower.startswith(phrase):
                # Strip the wake phrase and clean up
                remainder = text_lower[len(phrase):].strip()
                # Remove leading punctuation/comma
                remainder = re.sub(r'^[,.\s]+', '', remainder)
                return True, remainder if remainder else text
        return False, text

    def reset(self):
        """No-op for API compatibility with OpenWakeWord detector."""
        pass
