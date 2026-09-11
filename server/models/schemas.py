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


# ================================
# Legacy Book Models
# ================================

# --- Profile Models ---

class ProfileCreate(BaseModel):
    """Create a new profile."""
    name: str
    nickname: Optional[str] = None
    birthdate: Optional[str] = None
    relationship: Optional[str] = None


class ProfileUpdate(BaseModel):
    """Update an existing profile."""
    name: Optional[str] = None
    nickname: Optional[str] = None
    birthdate: Optional[str] = None
    relationship: Optional[str] = None


class ProfileResponse(BaseModel):
    """Profile response."""
    id: int
    name: str
    nickname: Optional[str] = None
    birthdate: Optional[str] = None
    relationship: Optional[str] = None
    photo_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileListResponse(BaseModel):
    """List of profiles."""
    profiles: List[ProfileResponse]
    count: int


# --- Story Models ---

class StoryCreate(BaseModel):
    """Create a new story."""
    question_id: str
    question_text: str
    answer: str
    week: Optional[int] = None
    theme: Optional[str] = None
    question_type: Optional[str] = None
    emotion_tags: Optional[List[str]] = None
    notes: Optional[str] = None


class StoryUpdate(BaseModel):
    """Update an existing story."""
    answer: Optional[str] = None
    emotion_tags: Optional[List[str]] = None
    is_favorite: Optional[bool] = None
    chapter_override: Optional[str] = None
    notes: Optional[str] = None


class StoryPhotoResponse(BaseModel):
    """Story photo response."""
    id: int
    story_id: int
    photo_path: str
    caption: Optional[str] = None
    sort_order: int = 0
    uploaded_at: Optional[datetime] = None


class StoryResponse(BaseModel):
    """Story response."""
    id: int
    profile_id: int
    question_id: str
    question_text: str
    answer: str
    week: Optional[int] = None
    theme: Optional[str] = None
    question_type: Optional[str] = None
    emotion_tags: Optional[List[str]] = None
    recorded_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    audio_path: Optional[str] = None
    is_favorite: bool = False
    chapter_override: Optional[str] = None
    notes: Optional[str] = None
    photos: Optional[List[StoryPhotoResponse]] = None


class StoryListResponse(BaseModel):
    """List of stories."""
    stories: List[StoryResponse]
    count: int


# --- Progress Models ---

class ProgressResponse(BaseModel):
    """Profile story collection progress."""
    profile_id: int
    total_stories: int
    total_questions: int = 312  # 52 weeks * 6 questions
    completion_percentage: float
    themes: dict
    weeks_completed: List[int]
    favorites: int


class NextQuestionResponse(BaseModel):
    """Next question to ask."""
    question_id: str
    question_text: str
    week: int
    theme: str
    question_type: str


# --- Book Models ---

class BookCreate(BaseModel):
    """Create a new book."""
    title: str
    subtitle: Optional[str] = None
    format: str = "pdf"


class ChapterResponse(BaseModel):
    """Book chapter response."""
    id: int
    book_id: int
    chapter_number: int
    title: str
    theme: Optional[str] = None
    content: Optional[str] = None
    story_ids: Optional[List[int]] = None


class BookResponse(BaseModel):
    """Book response."""
    id: int
    profile_id: int
    title: str
    subtitle: Optional[str] = None
    status: str = "draft"
    format: str = "pdf"
    file_path: Optional[str] = None
    cover_image_path: Optional[str] = None
    generated_at: Optional[datetime] = None
    story_count: Optional[int] = None
    chapters: Optional[List[ChapterResponse]] = None


class BookListResponse(BaseModel):
    """List of books."""
    books: List[BookResponse]
    count: int


class BookPreviewResponse(BaseModel):
    """Book content preview."""
    profile: ProfileResponse
    chapters: List[dict]
    total_stories: int
    has_photos: bool


class GenerateBookRequest(BaseModel):
    """Request to generate a book."""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    format: str = "pdf"
    include_photos: bool = True
    ai_narrative: bool = True


class BookStatusResponse(BaseModel):
    """Book generation status."""
    book_id: int
    status: str
    progress: Optional[float] = None
    message: Optional[str] = None


# --- Questions Models ---

class QuestionResponse(BaseModel):
    """Single question."""
    id: str
    type: str
    question: str
    week: int
    theme: str


class WeekQuestionsResponse(BaseModel):
    """Questions for a week."""
    week: int
    theme: str
    questions: List[QuestionResponse]


class AllQuestionsResponse(BaseModel):
    """All questions."""
    weeks: List[WeekQuestionsResponse]
    total_questions: int
