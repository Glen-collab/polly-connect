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


class ItemCreate(BaseModel):
    item: str
    location: str
    context: Optional[str] = None


@router.post("/command")
async def process_command(request: Request, command: CommandRequest):
    db = request.app.state.db
    result = intent_parser.parse(command.text)
    intent = result.get("intent", "unknown")
    
    response = {"intent": intent, "input": command.text}
    
    if intent == "store":
        item = result.get("item")
        location = result.get("location")
        if item and location:
            row_id = db.store_item(item, location, result.get("context"), command.text)
            response["message"] = f"Stored: {item} → {location}"
            response["item_id"] = row_id
        else:
            response["message"] = "Couldn't understand"
            
    elif intent == "retrieve_item":
        item = result.get("item")
        results = db.find_item(item) if item else []
        response["results"] = results
        response["message"] = f"Found {len(results)} results"
        
    elif intent == "retrieve_location":
        location = result.get("location")
        results = db.find_by_location(location) if location else []
        response["results"] = results
        
    elif intent == "delete":
        item = result.get("item")
        if item and db.delete_item(item):
            response["message"] = f"Deleted: {item}"
        else:
            response["message"] = "Not found"
            
    elif intent == "list_all":
        response["results"] = db.list_all()
        
    elif intent == "help":
        response["message"] = "Store items, find items, list all"
        
    return response


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
