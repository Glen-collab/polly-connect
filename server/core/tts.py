"""
pyttsx3 Text-to-Speech module — local TTS backend.
"""

import io
import logging
import os
import struct
import tempfile
import wave
from typing import Optional

from core.tts_base import TTSBackend

logger = logging.getLogger(__name__)

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


class Pyttsx3TTS(TTSBackend):
    def __init__(self, rate: int = 175):
        self.rate = rate
        self._available = PYTTSX3_AVAILABLE
        if self._available:
            logger.info("pyttsx3 TTS engine initialized")
        else:
            logger.warning("pyttsx3 not available")

    @property
    def available(self) -> bool:
        return self._available

    def _get_engine(self):
        """Create fresh engine each time to avoid run loop issues."""
        if not self._available:
            return None
        engine = pyttsx3.init()
        engine.setProperty('rate', self.rate)
        return engine

    def speak_local(self, text: str):
        """Speak directly through PC speakers."""
        if not text or not self._available:
            return
        engine = self._get_engine()
        if engine:
            engine.say(text)
            engine.runAndWait()
            engine.stop()

    def synthesize(self, text: str) -> Optional[bytes]:
        """Convert text to 16kHz mono WAV bytes."""
        if not text or not self._available:
            return None

        try:
            engine = self._get_engine()
            if not engine:
                return None

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            engine.save_to_file(text, temp_path)
            engine.runAndWait()
            engine.stop()

            # Read original WAV
            with wave.open(temp_path, 'rb') as wav_in:
                params = wav_in.getparams()
                frames = wav_in.readframes(params.nframes)

            os.unlink(temp_path)

            # Convert to samples
            sample_width = params.sampwidth
            if sample_width == 2:
                samples = list(struct.unpack(f'<{len(frames)//2}h', frames))
            else:
                return None

            # If stereo, take left channel
            if params.nchannels == 2:
                samples = samples[::2]

            # Downsample to 16kHz
            if params.framerate > 16000:
                ratio = max(1, params.framerate // 16000)
                samples = samples[::ratio]

            # Create 16kHz mono WAV
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(22050)
                wav_out.writeframes(struct.pack(f'<{len(samples)}h', *samples))

            return output.getvalue()

        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None

    # Keep old method name as alias for compatibility
    def speak(self, text: str) -> Optional[bytes]:
        return self.synthesize(text)


# Backwards-compatible alias
TTSEngine = Pyttsx3TTS
