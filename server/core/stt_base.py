"""
Abstract base class for Speech-to-Text backends.
Swap between Whisper (local) and Amazon Transcribe (cloud) via config.
"""

from abc import ABC, abstractmethod


class STTBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        """Transcribe WAV audio bytes to text."""
        ...

    @property
    def available(self) -> bool:
        return True
