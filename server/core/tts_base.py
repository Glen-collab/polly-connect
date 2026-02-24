"""
Abstract base class for Text-to-Speech backends.
Swap between pyttsx3 (local) and Amazon Polly (cloud) via config.
"""

from abc import ABC, abstractmethod
from typing import Optional


class TTSBackend(ABC):
    @abstractmethod
    def synthesize(self, text: str) -> Optional[bytes]:
        """Convert text to WAV audio bytes. Returns None on failure."""
        ...

    @property
    def available(self) -> bool:
        return True
