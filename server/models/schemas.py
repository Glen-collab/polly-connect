"""
Pydantic models for API request/response validation
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# --- Request Models ---

class CommandRequest(BaseModel):
    """Natural language command input."""
    text: str


class ItemCreate(BaseModel):
    """Direct item creation (bypassing NLP)."""
    item: str
    location: str
    context: Optional[str] = None


class ItemImport(BaseModel):
    """Item for bulk import."""
    item: str
    location: str
    context: Optional[str] = None
    raw_input: Optional[str] = None


class ImportRequest(BaseModel):
    """Bulk import request."""
    version: Optional[str] = "1.0"
    items: List[ItemImport]


# --- Response Models ---

class ItemResponse(BaseModel):
    """Single item response."""
    id: int
    item: str
    location: str
    context: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ItemListResponse(BaseModel):
    """List of items response."""
    items: List[ItemResponse]
    count: int


class CommandResponse(BaseModel):
    """Response to a natural language command."""
    intent: str
    confidence: float
    input: str
    message: str
    results: Optional[List[ItemResponse]] = None
    item_id: Optional[int] = None
    error: Optional[bool] = None
    examples: Optional[List[str]] = None


class StatsResponse(BaseModel):
    """Database statistics."""
    total_items: int
    unique_locations: int
    recent: List[dict]


class ExportResponse(BaseModel):
    """Export data response."""
    version: str
    items: List[ItemResponse]
    count: int


class LocationListResponse(BaseModel):
    """List of locations."""
    locations: List[str]
    count: int


class LocationItemsResponse(BaseModel):
    """Items in a specific location."""
    location: str
    items: List[ItemResponse]
    count: int


# --- WebSocket Models ---

class AudioStreamMessage(BaseModel):
    """Message in audio WebSocket stream."""
    event: str  # connect, audio, end_stream, ping
    device_id: Optional[str] = None
    data: Optional[str] = None  # base64 audio


class AudioResponse(BaseModel):
    """Response sent back to device."""
    event: str  # connected, response, error, pong
    text: Optional[str] = None
    audio: Optional[str] = None  # base64 audio
    intent: Optional[str] = None
    transcription: Optional[str] = None
    message: Optional[str] = None


# --- Device Models ---

class DeviceInfo(BaseModel):
    """Device registration info."""
    device_id: str
    firmware_version: Optional[str] = None
    hardware_version: Optional[str] = None
    registered_at: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    status: Optional[str] = "unknown"


class DeviceConfig(BaseModel):
    """Configuration sent to device."""
    wake_word_sensitivity: float = 0.5
    silence_timeout_ms: int = 1000
    sample_rate: int = 16000
    server_url: Optional[str] = None
