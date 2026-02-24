"""
REST API endpoints for Polly Connect
"""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.intent_parser import IntentParser

router = APIRouter()
intent_parser = IntentParser(use_spacy=False)


class CommandRequest(BaseModel):
    text: str
    device_id: str = "rest_client"


class ItemCreate(BaseModel):
    item: str
    location: str
    context: Optional[str] = None


@router.post("/command")
async def process_command(request: Request, command: CommandRequest):
    cmd = request.app.state.cmd
    result = intent_parser.parse(command.text)

    response_text = await cmd.process(result, command.text, command.device_id)

    return {
        "intent": result.get("intent", "unknown"),
        "input": command.text,
        "message": response_text,
    }


@router.get("/items")
async def list_items(request: Request, search: Optional[str] = None, location: Optional[str] = None):
    db = request.app.state.db
    if search:
        results = db.search(search)
    elif location:
        results = db.find_by_location(location)
    else:
        results = db.list_all()
    return {"items": results, "count": len(results)}


@router.post("/items")
async def create_item(request: Request, item: ItemCreate):
    db = request.app.state.db
    row_id = db.store_item(item.item, item.location, item.context)
    return {"id": row_id, "message": "Stored"}


@router.delete("/items/{item_id}")
async def delete_item_by_id(request: Request, item_id: int):
    db = request.app.state.db
    if db.delete_by_id(item_id):
        return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/stats")
async def get_stats(request: Request):
    return request.app.state.db.get_stats()
