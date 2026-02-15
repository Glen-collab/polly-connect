"""Configuration for Polly Connect server"""

import os


class Settings:
    HOST: str = os.getenv("POLLY_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("POLLY_PORT", "8000"))
    DEBUG: bool = os.getenv("POLLY_DEBUG", "true").lower() == "true"
    DATABASE_PATH: str = os.getenv("POLLY_DB_PATH", "polly.db")
    WHISPER_MODEL: str = os.getenv("POLLY_WHISPER_MODEL", "base")
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1


settings = Settings()
