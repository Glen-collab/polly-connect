"""
Configuration for Polly Connect server
Uses environment variables with sensible defaults
"""

import os
from pathlib import Path


class Settings:
    """Server configuration."""
    
    # Server
    HOST: str = os.getenv("POLLY_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("POLLY_PORT", "8000"))
    DEBUG: bool = os.getenv("POLLY_DEBUG", "true").lower() == "true"
    
    # Database
    DATABASE_PATH: str = os.getenv("POLLY_DB_PATH", "polly.db")
    
    # Whisper
    WHISPER_MODEL: str = os.getenv("POLLY_WHISPER_MODEL", "base")
    
    # Audio settings
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1
    CHUNK_SIZE: int = 1024
    
    # Silence detection
    SILENCE_THRESHOLD: float = float(os.getenv("POLLY_SILENCE_THRESHOLD", "0.01"))
    SILENCE_DURATION: float = float(os.getenv("POLLY_SILENCE_DURATION", "1.0"))
    
    # TTS
    TTS_ENGINE: str = os.getenv("POLLY_TTS_ENGINE", "pyttsx3")  # pyttsx3, espeak, or api
    TTS_VOICE: str = os.getenv("POLLY_TTS_VOICE", "")
    TTS_RATE: int = int(os.getenv("POLLY_TTS_RATE", "150"))


settings = Settings()
