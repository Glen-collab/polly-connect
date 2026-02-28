"""Configuration for Polly Connect server"""

import os

# Load .env file from project root (one level up from server/)
_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())


class Settings:
    HOST: str = os.getenv("POLLY_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("POLLY_PORT", "8000"))
    DEBUG: bool = os.getenv("POLLY_DEBUG", "true").lower() == "true"
    DATABASE_PATH: str = os.getenv("POLLY_DB_PATH", "polly.db")
    WHISPER_MODEL: str = os.getenv("POLLY_WHISPER_MODEL", "base")
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1

    # Backend selection: "whisper" or "aws_transcribe"
    STT_BACKEND: str = os.getenv("POLLY_STT_BACKEND", "whisper")
    # Backend selection: "pyttsx3" or "aws_polly"
    TTS_BACKEND: str = os.getenv("POLLY_TTS_BACKEND", "pyttsx3")

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

    # Owner name (used for relationship questions; overridden by DB once setup is complete)
    OWNER_NAME: str = os.getenv("POLLY_OWNER_NAME", "Glen")

    # OpenAI API key (for Vision photo scan + follow-up questions)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Web session duration (hours)
    SESSION_DURATION_HOURS: int = int(os.getenv("POLLY_SESSION_HOURS", "72"))

    # Data directory
    DATA_DIR: str = os.getenv("POLLY_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))


settings = Settings()
