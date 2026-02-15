"""
Wake word detection using OpenWakeWord
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    from openwakeword.model import Model
    WAKEWORD_AVAILABLE = True
except ImportError:
    WAKEWORD_AVAILABLE = False
    logger.warning("openwakeword not available")


class WakeWordDetector:
    def __init__(self, threshold: float = 0.5, enabled: bool = True):
        self.model = None
        self.threshold = threshold
        self.enabled = enabled

        if not enabled:
            logger.info("Wake word detector disabled (edge detection enabled)")
            return

        if WAKEWORD_AVAILABLE:
            try:
                self.model = Model(inference_framework="onnx")
                logger.info("Wake word detector initialized (hey jarvis)")
            except Exception as e:
                logger.error(f"Failed to init wake word: {e}")
        
    def detect(self, audio_bytes: bytes) -> bool:
        if not self.enabled or not self.model:
            return False
            
        try:
            audio = np.frombuffer(audio_bytes, dtype=np.int16)
            prediction = self.model.predict(audio)
            
            for key, score in prediction.items():
                if score > self.threshold:
                    logger.info(f"Wake word detected: {key} ({score:.2f})")
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"Wake word error: {e}")
            return False
    
    def reset(self):
        if self.model:
            self.model.reset()
