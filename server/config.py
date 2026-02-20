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

    # Wake word detection
    WAKE_WORD_MODEL_PATH: str = os.getenv(
        "POLLY_WAKE_WORD_MODEL",
        os.path.join(os.path.expanduser("~"), "Desktop", "polly-connect", "wake-word", "hey_polly.onnx")
    )
    WAKE_WORD_THRESHOLD: float = float(os.getenv("POLLY_WAKE_WORD_THRESHOLD", "0.5"))

    # Silence detection for end-of-command
    SILENCE_THRESHOLD_RMS: int = int(os.getenv("POLLY_SILENCE_THRESHOLD", "500"))
    SILENCE_TIMEOUT_S: float = float(os.getenv("POLLY_SILENCE_TIMEOUT", "1.5"))
    MAX_COMMAND_S: float = float(os.getenv("POLLY_MAX_COMMAND_S", "10.0"))


settings = Settings()
