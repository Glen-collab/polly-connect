"""
Google Speech Recognition STT backend.
Uses the free Google Web Speech API via the speech_recognition library.
No API key required. Good for short voice commands.
"""

import io
import logging

from core.stt_base import STTBackend

logger = logging.getLogger(__name__)

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    logger.warning("speech_recognition not installed — Google STT disabled")


class GoogleSTT(STTBackend):
    def __init__(self):
        self._available = SR_AVAILABLE
        if self._available:
            self._recognizer = sr.Recognizer()
            logger.info("Google Speech Recognition STT initialized (free, no API key)")
        else:
            self._recognizer = None

    @property
    def available(self) -> bool:
        return self._available

    def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        if not self._available:
            return ""

        try:
            # audio_bytes is a WAV file
            audio_file = io.BytesIO(audio_bytes)
            with sr.AudioFile(audio_file) as source:
                audio_data = self._recognizer.record(source)

            text = self._recognizer.recognize_google(audio_data, language=f"{language}-US")
            return text.strip()

        except sr.UnknownValueError:
            logger.info("Google STT: could not understand audio")
            return ""
        except sr.RequestError as e:
            logger.error(f"Google STT request error: {e}")
            return ""
        except Exception as e:
            logger.error(f"Google STT error: {e}")
            return ""
