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


def _tenant(request: Request) -> int:
    """The caller's tenant, set by APIKeyMiddleware from its key. Every route here
    is scoped to it, so a device only ever sees its own family's items."""
    auth = getattr(request.state, "api_auth", None)
    if not auth or not auth.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return auth["tenant_id"]


@router.post("/command")
async def process_command(request: Request, command: CommandRequest):
    cmd = request.app.state.cmd
    tid = _tenant(request)
    result = intent_parser.parse(command.text)

    # Conversation state is keyed by device id; namespace it by tenant so a caller
    # can't borrow another family's state by naming their device.
    device_id = f"rest:{tid}:{command.device_id}"
    cmd._get_state(device_id).tenant_id = tid
    response_text = await cmd.process(result, command.text, device_id)

    return {
        "intent": result.get("intent", "unknown"),
        "input": command.text,
        "message": response_text,
    }


@router.get("/items")
async def list_items(request: Request, search: Optional[str] = None, location: Optional[str] = None):
    db = request.app.state.db
    tid = _tenant(request)
    if search:
        results = db.search(search, tenant_id=tid)
    elif location:
        results = db.find_by_location(location, tenant_id=tid)
    else:
        results = db.list_all(tenant_id=tid)
    return {"items": results, "count": len(results)}


@router.post("/items")
async def create_item(request: Request, item: ItemCreate):
    db = request.app.state.db
    row_id = db.store_item(item.item, item.location, item.context, tenant_id=_tenant(request))
    return {"id": row_id, "message": "Stored"}


@router.delete("/items/{item_id}")
async def delete_item_by_id(request: Request, item_id: int):
    db = request.app.state.db
    if db.delete_by_id(item_id, tenant_id=_tenant(request)):
        return {"message": "Deleted"}
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/stats")
async def get_stats(request: Request):
    return request.app.state.db.get_stats(tenant_id=_tenant(request))
