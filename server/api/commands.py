"""
REST API endpoints for Polly Connect
Compatible with original Parrot API for web UI support
"""

from typing import Optional, List
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.intent_parser import IntentParser
from models.schemas import (
    CommandRequest, CommandResponse,
    ItemCreate, ItemResponse, 
    StatsResponse, ExportResponse
)

router = APIRouter()

# Intent parser instance
intent_parser = IntentParser(use_spacy=False)


# --- Request/Response Models ---

class CommandRequest(BaseModel):
    text: str


class ItemCreate(BaseModel):
    item: str
    location: str
    context: Optional[str] = None


# --- Endpoints ---

@router.post("/command", response_model=dict)
async def process_command(request: Request, command: CommandRequest):
    """Process a natural language command (for web UI / text input)."""
    db = request.app.state.db
    
    result = intent_parser.parse(command.text)
    intent = result.get("intent", "unknown")
    
    response = {
        "intent": intent,
        "confidence": result.get("confidence", 0),
        "input": command.text
    }
    
    if intent == "store":
        item = result.get("item")
        location = result.get("location")
        context = result.get("context")
        
        if item and location:
            row_id = db.store_item(item, location, context, command.text)
            response["message"] = f"Stored: {item} → {location}"
            response["item_id"] = row_id
        else:
            response["message"] = "Couldn't understand what to store"
            response["error"] = True
            
    elif intent == "retrieve_item":
        item = result.get("item")
        results = db.find_item(item) if item else []
        response["results"] = results
        if results:
            r = results[0]
            response["message"] = f"{r['item']} is in {r['location']}"
        else:
            response["message"] = f"No record of '{item}'"
            
    elif intent == "retrieve_location":
        location = result.get("location")
        results = db.find_by_location(location) if location else []
        response["results"] = results
        response["message"] = f"Found {len(results)} items in {location}"
        
    elif intent == "delete":
        item = result.get("item")
        if item and db.delete_item(item):
            response["message"] = f"Deleted: {item}"
        else:
            response["message"] = f"No record of '{item}'"
            response["error"] = True
            
    elif intent == "list_all":
        results = db.list_all()
        response["results"] = results
        response["message"] = f"Found {len(results)} items"
        
    elif intent == "help":
        response["message"] = "Commands: store items, find items, list all, forget items"
        response["examples"] = [
            "the wrench is in the drawer",
            "where is the wrench?",
            "what's in the toolbox?",
            "forget the wrench",
            "list everything"
        ]
    else:
        response["message"] = "I didn't understand that"
        response["error"] = True
        
    return response


@router.get("/items")
async def list_items(
    request: Request,
    search: Optional[str] = None,
    location: Optional[str] = None
):
    """List all items, optionally filtered."""
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
    """Add item directly (without natural language)."""
    db = request.app.state.db
    
    row_id = db.store_item(item.item, item.location, item.context)
    return {
        "id": row_id,
        "item": item.item,
        "location": item.location,
        "context": item.context,
        "message": "Item stored"
    }


@router.delete("/items/{item_id}")
async def delete_item_by_id(request: Request, item_id: int):
    """Delete item by ID."""
    db = request.app.state.db
    
    if db.delete_by_id(item_id):
        return {"message": "Item deleted", "id": item_id}
    raise HTTPException(status_code=404, detail="Item not found")


@router.get("/locations")
async def list_locations(request: Request):
    """List all unique locations."""
    db = request.app.state.db
    
    items = db.list_all()
    locations = list(set(item["location"] for item in items))
    return {"locations": sorted(locations), "count": len(locations)}


@router.get("/locations/{location_name}")
async def get_location(request: Request, location_name: str):
    """Get items in a specific location."""
    db = request.app.state.db
    
    results = db.find_by_location(location_name)
    return {"location": location_name, "items": results, "count": len(results)}


@router.get("/stats")
async def get_stats(request: Request):
    """Get database statistics."""
    db = request.app.state.db
    return db.get_stats()


@router.get("/export")
async def export_data(request: Request):
    """Export all data as JSON."""
    db = request.app.state.db
    
    items = db.list_all()
    return {
        "version": "1.0",
        "items": items,
        "count": len(items)
    }


@router.post("/import")
async def import_data(request: Request, data: dict):
    """Import data from JSON backup."""
    db = request.app.state.db
    
    items = data.get("items", [])
    imported = 0
    
    for item in items:
        if "item" in item and "location" in item:
            db.store_item(
                item["item"],
                item["location"],
                item.get("context"),
                item.get("raw_input")
            )
            imported += 1
            
    return {"message": f"Imported {imported} items", "count": imported}
