"""
Polly Connect - Cloud Brain Server
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Polly Connect server...")
    app.state.db = PollyDB(settings.DATABASE_PATH)
    logger.info(f"Loading Whisper model: {settings.WHISPER_MODEL}")
    app.state.transcriber = WhisperTranscriber(model_size=settings.WHISPER_MODEL)
    app.state.tts = TTSEngine()
    logger.info("Server ready")
    yield
    logger.info("Shutting down...")


app = FastAPI(title="Polly Connect", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router, prefix="/api/audio", tags=["audio"])
app.include_router(commands_router, prefix="/api", tags=["commands"])
app.include_router(devices_router, prefix="/api/devices", tags=["devices"])


@app.get("/")
async def root():
    return {"name": "Polly Connect", "status": "online"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
