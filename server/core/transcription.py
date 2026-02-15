"""
Whisper transcription module
"""

import logging
from typing import Union

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("faster-whisper not available")


class WhisperTranscriber:
    def __init__(self, model_size: str = "base"):
        self.model = None
        
        if WHISPER_AVAILABLE:
            logger.info(f"Loading Whisper model: {model_size}")
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info("Whisper model loaded")
        else:
            logger.error("No Whisper backend available")
            
    def transcribe(self, audio: Union[bytes, str], language: str = "en") -> str:
        if not self.model:
            return ""
            
        try:
            import tempfile
            import os
            
            if isinstance(audio, bytes):
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio)
                    temp_path = f.name
                try:
                    segments, info = self.model.transcribe(temp_path, language=language)
                    text = " ".join([seg.text for seg in segments])
                    return text.strip()
                finally:
                    os.unlink(temp_path)
            else:
                segments, info = self.model.transcribe(audio, language=language)
                text = " ".join([seg.text for seg in segments])
                return text.strip()
                
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
