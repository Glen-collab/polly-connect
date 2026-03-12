"""
Polly Connect - Cloud Brain Server
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.audio import router as audio_router
from api.commands import router as commands_router
from api.devices import router as devices_router
from api.homeassistant import router as ha_router
from api.web import router as web_router
from api.firmware import router as firmware_router
from core.database import PollyDB
from core.wakeword import WakeWordDetector
from core.vad_wakeword import VADWakeWordDetector
from core.data_loader import DataLoader
from core.command_processor import CommandProcessor
from core.bible import BibleVerseService
from core.prayer import PrayerService
from core.weather import AlmanacWeather
from core.medications import MedicationScheduler
from core.family_identity import FamilyIdentityService
from core.followup_generator import FollowupGenerator
from core.echo_bridge_invite import EchoEngine
from core.narrative_arc import NarrativeArc
from core.memory_extractor import MemoryExtractor
from core.engagement import EngagementTracker
from core.verification import VerificationService
from core.book_builder import BookBuilder
from core.vision import VisionService
from core.auth import APIKeyMiddleware
from core.squawk import SquawkManager
from core.ack_cache import AckCache
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_stt_backend():
    """Factory: select STT backend based on config."""
    if settings.STT_BACKEND == "aws_transcribe":
        from core.aws_transcribe import AWSTranscribeSTT
        return AWSTranscribeSTT()
    elif settings.STT_BACKEND == "google":
        from core.google_stt import GoogleSTT
        return GoogleSTT()
    else:
        from core.transcription import WhisperSTT
        return WhisperSTT(model_size=settings.WHISPER_MODEL)


def create_tts_backend():
    """Factory: select TTS backend based on config."""
    if settings.TTS_BACKEND == "aws_polly":
        from core.aws_polly import AWSPollyTTS
        return AWSPollyTTS()
    else:
        from core.tts import Pyttsx3TTS
        return Pyttsx3TTS()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Polly Connect server...")
    app.state.db = PollyDB(settings.DATABASE_PATH)

    logger.info(f"STT backend: {settings.STT_BACKEND}")
    app.state.transcriber = create_stt_backend()

    logger.info(f"TTS backend: {settings.TTS_BACKEND}")
    app.state.tts = create_tts_backend()

    # Pre-cache acknowledgment chirps for instant playback
    app.state.ack_cache = AckCache()
    app.state.ack_cache.warm_up(app.state.tts)

    logger.info(f"Loading wake word model: {settings.WAKE_WORD_MODEL_PATH}")
    detector = WakeWordDetector(
        model_path=settings.WAKE_WORD_MODEL_PATH,
        threshold=settings.WAKE_WORD_THRESHOLD,
    )
    if detector.ready:
        app.state.wake_word_detector = detector
        logger.info("Wake word detector ready (OpenWakeWord)")
    else:
        logger.info("OpenWakeWord not available — falling back to VAD wake word detector")
        app.state.wake_word_detector = VADWakeWordDetector(
            rms_threshold=200,
            consecutive_frames=3,
        )

    # Load data files (jokes, questions, config)
    app.state.data = DataLoader(settings.DATA_DIR)
    logger.info(f"Data loaded: {app.state.data.stats()}")

    # Initialize feature services
    app.state.bible = BibleVerseService(app.state.db, settings.DATA_DIR)
    app.state.prayer = PrayerService(settings.DATA_DIR)  # db/followup_gen set below
    app.state.weather = AlmanacWeather(settings.DATA_DIR)
    app.state.med_scheduler = MedicationScheduler(app.state.db, tts=app.state.tts)

    # Family identity and narrative services
    app.state.family_identity = FamilyIdentityService(app.state.db)
    app.state.followup_gen = FollowupGenerator()
    # Wire up prayer service with db + OpenAI now that they're ready
    app.state.prayer.db = app.state.db
    app.state.prayer.followup_gen = app.state.followup_gen
    app.state.narrative_arc = NarrativeArc(app.state.db)
    app.state.memory_extractor = MemoryExtractor()
    app.state.echo_engine = EchoEngine(
        followup_generator=app.state.followup_gen,
        narrative_arc=app.state.narrative_arc,
    )
    app.state.engagement = EngagementTracker(
        app.state.db, narrative_arc=app.state.narrative_arc,
    )
    app.state.verification = VerificationService(app.state.db)
    app.state.vision = VisionService()
    logger.info(f"Vision service ready: {app.state.vision.available}")
    app.state.book_builder = BookBuilder(
        app.state.db, followup_generator=app.state.followup_gen,
    )
    logger.info(f"Legacy story system ready (AI: {app.state.followup_gen.available})")

    # Central command processor
    app.state.cmd = CommandProcessor(
        db=app.state.db,
        data=app.state.data,
        bible_service=app.state.bible,
        prayer_service=app.state.prayer,
        weather_service=app.state.weather,
        med_scheduler=app.state.med_scheduler,
        family_identity=app.state.family_identity,
        echo_engine=app.state.echo_engine,
        memory_extractor=app.state.memory_extractor,
        narrative_arc=app.state.narrative_arc,
        engagement=app.state.engagement,
        followup_gen=app.state.followup_gen,
    )

    # Squawk / ambient parrot sounds
    sounds_dir = os.path.join(os.path.dirname(__file__), "static", "sounds")
    app.state.squawk = SquawkManager(sounds_dir)

    # Start medication reminder background task
    await app.state.med_scheduler.start()

    # Clean up expired web sessions
    app.state.db.cleanup_expired_sessions()
    logger.info("Expired web sessions cleaned up")

    logger.info("Server ready")
    yield

    # Cleanup
    await app.state.med_scheduler.stop()
    logger.info("Shutting down...")


app = FastAPI(title="Polly Connect", version="0.1.0", lifespan=lifespan)

app.add_middleware(APIKeyMiddleware)
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
app.include_router(ha_router, prefix="/api/commands", tags=["homeassistant"])
app.include_router(web_router, prefix="/web", tags=["web"])
app.include_router(firmware_router, prefix="/api/firmware", tags=["firmware"])

# Static files for photo uploads and story recordings
static_dir = os.path.join(os.path.dirname(__file__), "static")
uploads_dir = os.path.join(static_dir, "uploads")
recordings_dir = os.path.join(static_dir, "recordings")
firmware_dir = os.path.join(static_dir, "firmware")
os.makedirs(uploads_dir, exist_ok=True)
os.makedirs(recordings_dir, exist_ok=True)
os.makedirs(firmware_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/web/dashboard")


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG,
                ws="wsproto", ws_ping_interval=None, ws_ping_timeout=None)
