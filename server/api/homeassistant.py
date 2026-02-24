"""
Home Assistant integration endpoint for Polly Connect
Receives transcriptions from Home Assistant and processes them
"""

import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.intent_parser import IntentParser

router = APIRouter()
logger = logging.getLogger(__name__)

intent_parser = IntentParser(use_spacy=False)


class CommandRequest(BaseModel):
    transcription: str
    device_id: str = "unknown"
    source: str = "home_assistant"


@router.post("/process")
async def process_command(request: Request, command: CommandRequest):
    """Process voice command from Home Assistant."""
    logger.info(f"Received command from {command.source}: {command.transcription}")

    cmd = request.app.state.cmd

    intent_result = intent_parser.parse(command.transcription)
    logger.info(f"Intent: {intent_result}")

    response_text = await cmd.process(intent_result, command.transcription, command.device_id)
    logger.info(f"Response: {response_text}")

    return {
        "success": True,
        "transcription": command.transcription,
        "intent": intent_result.get("intent"),
        "response": response_text,
        "device_id": command.device_id
    }
