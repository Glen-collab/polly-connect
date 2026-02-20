"""
Wake word detection using OpenWakeWord with custom hey_polly.onnx model.

Processes 1280-sample (80ms) chunks of 16kHz int16 audio.
"""

import logging
import os
import numpy as np

logger = logging.getLogger(__name__)

try:
    from openwakeword.model import Model
    WAKEWORD_AVAILABLE = True
except ImportError:
    WAKEWORD_AVAILABLE = False
    logger.warning("openwakeword not installed — wake word detection disabled")


class WakeWordDetector:
    def __init__(self, model_path: str = None, threshold: float = 0.5):
        self.model = None
        self.threshold = threshold
        self.model_path = model_path
        self.model_name = None  # key returned by predict()

        if not WAKEWORD_AVAILABLE:
            logger.error("Cannot init wake word detector: openwakeword not installed")
            return

        if not model_path or not os.path.exists(model_path):
            logger.error(f"Wake word model not found: {model_path}")
            return

        try:
            self.model = Model(wakeword_models=[model_path])
            # Discover the model key used by predict()
            # OpenWakeWord uses the model filename (without extension) as key
            self.model_name = os.path.splitext(os.path.basename(model_path))[0]
            logger.info(f"Wake word detector loaded: {model_path} (key: {self.model_name})")
        except Exception as e:
            logger.error(f"Failed to load wake word model: {e}")

    @property
    def ready(self) -> bool:
        return self.model is not None

    def detect(self, audio_chunk: np.ndarray) -> float:
        """Feed a 1280-sample int16 chunk. Returns detection score (0.0-1.0)."""
        if not self.model:
            return 0.0

        try:
            prediction = self.model.predict(audio_chunk)
            score = prediction.get(self.model_name, 0.0)
            return float(score)
        except Exception as e:
            logger.error(f"Wake word predict error: {e}")
            return 0.0

    def detected(self, audio_chunk: np.ndarray) -> bool:
        """Convenience: returns True if score exceeds threshold."""
        return self.detect(audio_chunk) > self.threshold

    def reset(self):
        """Reset internal model state between detections."""
        if self.model:
            self.model.reset()
