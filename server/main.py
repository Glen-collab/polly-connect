"""
Polly Connect - Cloud Brain Server
FastAPI server that handles audio streaming, transcription, intent parsing, and TTS
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.audio import router as audio_router
from api.commands import router as commands_router
from api.devices import router as devices_router
from core.database import PollyDB
from core.transcription import WhisperTranscriber
from core.tts import TTSEngine
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    # Startup
    logger.info("Starting Polly Connect server...")
    
    # Initialize database
    app.state.db = PollyDB(settings.DATABASE_PATH)
    logger.info(f"Database initialized: {settings.DATABASE_PATH}")
    
    # Initialize Whisper
    logger.info(f"Loading Whisper model: {settings.WHISPER_MODEL}")
    app.state.transcriber = WhisperTranscriber(model_size=settings.WHISPER_MODEL)
    logger.info("Whisper model loaded")
    
    # Initialize TTS
    app.state.tts = TTSEngine()
    logger.info("TTS engine initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Polly Connect server...")


# Create FastAPI app
app = FastAPI(
    title="Polly Connect",
    description="Cloud brain for Polly voice assistant",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware (allow ESP32 and web clients)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(audio_router, prefix="/api/audio", tags=["audio"])
app.include_router(commands_router, prefix="/api", tags=["commands"])
app.include_router(devices_router, prefix="/api/devices", tags=["devices"])


@app.get("/")
async def root():
    return {
        "name": "Polly Connect",
        "version": "0.1.0",
        "status": "online"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
