"""
Whisper transcription module for Polly Connect
Handles speech-to-text conversion
"""

import io
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Try to import faster-whisper first, fall back to openai-whisper
try:
    from faster_whisper import WhisperModel
    WHISPER_BACKEND = "faster-whisper"
    logger.info("Using faster-whisper backend")
except ImportError:
    try:
        import whisper
        WHISPER_BACKEND = "openai-whisper"
        logger.info("Using openai-whisper backend")
    except ImportError:
        WHISPER_BACKEND = None
        logger.warning("No Whisper backend available!")


class WhisperTranscriber:
    """
    Whisper-based speech transcription.
    
    Supports both faster-whisper (recommended) and openai-whisper backends.
    """
    
    def __init__(self, model_size: str = "base", device: str = "auto"):
        """
        Initialize the Whisper model.
        
        Args:
            model_size: Model size (tiny, base, small, medium, large)
            device: Device to use (auto, cpu, cuda)
        """
        self.model_size = model_size
        self.model = None
        self.backend = WHISPER_BACKEND
        
        if self.backend == "faster-whisper":
            # Determine compute type and device
            if device == "auto":
                device = "cpu"  # Default to CPU for Pi compatibility
                compute_type = "int8"
            elif device == "cuda":
                compute_type = "float16"
            else:
                compute_type = "int8"
                
            logger.info(f"Loading faster-whisper model: {model_size} on {device}")
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type
            )
            
        elif self.backend == "openai-whisper":
            logger.info(f"Loading openai-whisper model: {model_size}")
            self.model = whisper.load_model(model_size)
            
        else:
            logger.error("No Whisper backend available. Install faster-whisper or openai-whisper.")
            
    def transcribe(self, audio: Union[bytes, str], language: str = "en") -> str:
        """
        Transcribe audio to text.
        
        Args:
            audio: WAV audio bytes or path to audio file
            language: Language code (default: en)
            
        Returns:
            Transcribed text
        """
        if not self.model:
            logger.error("No model loaded")
            return ""
            
        try:
            if self.backend == "faster-whisper":
                return self._transcribe_faster(audio, language)
            else:
                return self._transcribe_openai(audio, language)
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            return ""
            
    def _transcribe_faster(self, audio: Union[bytes, str], language: str) -> str:
        """Transcribe using faster-whisper."""
        import tempfile
        import os
        
        # If bytes, write to temp file
        if isinstance(audio, bytes):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                temp_path = f.name
            try:
                segments, info = self.model.transcribe(
                    temp_path,
                    language=language,
                    beam_size=5,
                    vad_filter=True
                )
                text = " ".join([seg.text for seg in segments])
                return text.strip()
            finally:
                os.unlink(temp_path)
        else:
            # Audio is a file path
            segments, info = self.model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=True
            )
            text = " ".join([seg.text for seg in segments])
            return text.strip()
            
    def _transcribe_openai(self, audio: Union[bytes, str], language: str) -> str:
        """Transcribe using openai-whisper."""
        import tempfile
        import os
        
        # If bytes, write to temp file
        if isinstance(audio, bytes):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio)
                temp_path = f.name
            try:
                result = self.model.transcribe(
                    temp_path,
                    language=language,
                    fp16=False  # CPU compatibility
                )
                return result["text"].strip()
            finally:
                os.unlink(temp_path)
        else:
            result = self.model.transcribe(
                audio,
                language=language,
                fp16=False
            )
            return result["text"].strip()


# Test
if __name__ == "__main__":
    print(f"Whisper backend: {WHISPER_BACKEND}")
    
    if WHISPER_BACKEND:
        transcriber = WhisperTranscriber(model_size="tiny")
        print("Transcriber initialized successfully")
    else:
        print("No Whisper backend available")
