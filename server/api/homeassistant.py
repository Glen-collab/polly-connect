"""
Home Assistant integration endpoint for Polly Connect
Receives transcriptions from Home Assistant and processes them
"""

import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from core.intent_parser import IntentParser
from core.database import Database

router = APIRouter()
logger = logging.getLogger(__name__)

intent_parser = IntentParser(use_spacy=False)


class CommandRequest(BaseModel):
    transcription: str
    device_id: str = "unknown"
    source: str = "home_assistant"


@router.post("/process")
async def process_command(request: Request, command: CommandRequest):
    """
    Process voice command from Home Assistant
    """
    logger.info(f"Received command from {command.source}: {command.transcription}")

    # Get database instance from app state
    db = request.app.state.db

    # Parse intent
    intent_result = intent_parser.parse(command.transcription)
    logger.info(f"Intent: {intent_result}")

    # Process intent and generate response
    response_text = await process_intent(intent_result, db, command.transcription)
    logger.info(f"Response: {response_text}")

    return {
        "success": True,
        "transcription": command.transcription,
        "intent": intent_result.get("intent"),
        "response": response_text,
        "device_id": command.device_id
    }


async def process_intent(intent_result: dict, db: Database, transcription: str) -> str:
    """Process intent and return response text"""
    intent = intent_result.get("intent")

    if intent == "store":
        item = intent_result.get("item")
        location = intent_result.get("location")
        if item and location:
            db.store_item(item, location, transcription)
            return f"Got it. I'll remember that {item} is in the {location}."
        return "I didn't catch what you want to store. Please try again."

    elif intent == "retrieve_item":
        item = intent_result.get("item")
        if item:
            location = db.get_item_location(item)
            if location:
                return f"The {item} is in the {location}."
            return f"I don't know where the {item} is."
        return "What item are you looking for?"

    elif intent == "retrieve_location":
        location = intent_result.get("location")
        if location:
            items = db.get_items_in_location(location)
            if items:
                items_str = ", ".join(items)
                return f"In the {location}, I have: {items_str}."
            return f"I don't have anything recorded in the {location}."
        return "Which location do you want to know about?"

    elif intent == "delete":
        item = intent_result.get("item")
        if item:
            deleted = db.delete_item(item)
            if deleted:
                return f"Okay, I've forgotten about the {item}."
            return f"I don't have any record of {item}."
        return "What do you want me to forget?"

    elif intent == "list_all":
        all_items = db.get_all_items()
        if all_items:
            items_list = [f"{item} in the {location}" for item, location in all_items]
            return f"Here's what I know: {', '.join(items_list)}."
        return "I don't have any items stored yet."

    elif intent == "help":
        return """I can help you remember where things are.
                  You can say things like: 'my keys are in the kitchen',
                  'where are my keys', or 'what's in the kitchen'."""

    else:
        return "I'm not sure what you want me to do. Try asking me to remember where something is."
