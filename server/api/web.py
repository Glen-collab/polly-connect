"""
Web app routes for Polly Connect caretaker portal.
FastAPI + Jinja2 templates + Tailwind CSS.
"""

import json
import logging
import os
import shutil
import uuid
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()

# Templates directory is at server/templates/
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = request.app.state.db

    stories = db.get_stories(limit=5)
    medications = db.get_medications()
    items = db.list_all()
    stats = db.get_stats()

    # Count question sessions
    conn = db._get_connection()
    try:
        q_count = conn.execute("SELECT COUNT(*) FROM question_sessions WHERE answered = 1").fetchone()[0]
    except Exception:
        q_count = 0
    finally:
        if not db._conn:
            conn.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stories": stories,
        "medications": medications,
        "story_count": len(stories),
        "question_count": q_count,
        "item_count": stats.get("total_items", 0),
    })


@router.get("/stories", response_class=HTMLResponse)
async def stories_list(request: Request):
    db = request.app.state.db
    stories = db.get_stories(limit=50)
    return templates.TemplateResponse("stories.html", {
        "request": request,
        "stories": stories,
    })


@router.get("/stories/{story_id}/edit", response_class=HTMLResponse)
async def story_edit(request: Request, story_id: int):
    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        story = dict(story) if story else None
    finally:
        if not db._conn:
            conn.close()

    if not story:
        return RedirectResponse("/web/stories")

    return templates.TemplateResponse("story_edit.html", {
        "request": request,
        "story": story,
    })


@router.post("/stories/{story_id}/edit")
async def story_edit_save(request: Request, story_id: int,
                          transcript: str = Form(""), speaker_name: str = Form("")):
    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE stories SET transcript = ?, speaker_name = ? WHERE id = ?
        """, (transcript, speaker_name or None, story_id))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse(f"/web/stories/{story_id}/edit", status_code=303)


@router.get("/medications", response_class=HTMLResponse)
async def medications_page(request: Request):
    db = request.app.state.db
    medications = db.get_medications()
    return templates.TemplateResponse("medications.html", {
        "request": request,
        "medications": medications,
    })


@router.post("/medications/add")
async def medication_add(request: Request, name: str = Form(...),
                         dosage: str = Form(""), times: str = Form(...)):
    db = request.app.state.db
    user = db.get_or_create_user()
    # Parse comma-separated times into JSON
    time_list = [t.strip() for t in times.split(",") if t.strip()]
    db.add_medication(user["id"], name, dosage, json.dumps(time_list))
    return RedirectResponse("/web/medications", status_code=303)


@router.get("/memory", response_class=HTMLResponse)
async def memory_page(request: Request):
    db = request.app.state.db
    items = db.list_all()
    # Build unique location list for autocomplete suggestions
    locations = sorted(set(item["location"] for item in items if item.get("location")))
    return templates.TemplateResponse("memory.html", {
        "request": request,
        "items": items,
        "locations": locations,
    })


@router.post("/memory/add")
async def memory_add(request: Request, item: str = Form(...), location: str = Form(...)):
    db = request.app.state.db
    db.store_item(item, location)
    return RedirectResponse("/web/memory", status_code=303)


@router.post("/memory/delete/{item_id}")
async def memory_delete(request: Request, item_id: int):
    db = request.app.state.db
    db.delete_by_id(item_id)
    return RedirectResponse("/web/memory", status_code=303)


@router.post("/memory/scan")
async def memory_scan(request: Request,
                      photo: UploadFile = File(...),
                      default_location: str = Form("")):
    """Send a photo to OpenAI Vision and return detected items."""
    from fastapi.responses import JSONResponse

    vision = getattr(request.app.state, "vision", None)
    if not vision or not vision.available:
        return JSONResponse({"items": [], "error": "Vision service not available. Set OPENAI_API_KEY."})

    content = await photo.read()
    if len(content) > 10 * 1024 * 1024:
        return JSONResponse({"items": [], "error": "Photo too large (max 10MB)."})

    items = vision.identify_items(content, default_location)
    return JSONResponse({"items": items})


@router.post("/memory/save-batch")
async def memory_save_batch(request: Request):
    """Save multiple items at once from the photo scan."""
    from fastapi.responses import JSONResponse

    db = request.app.state.db
    body = await request.json()
    items = body.get("items", [])
    count = 0
    for entry in items:
        item_name = entry.get("item", "").strip()
        location = entry.get("location", "").strip()
        if item_name and location:
            db.store_item(item_name, location)
            count += 1
    return JSONResponse({"count": count})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    db = request.app.state.db
    user = db.get_or_create_user()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
    })


@router.post("/settings")
async def settings_save(request: Request, name: str = Form(...),
                        familiar_name: str = Form(""),
                        bible_topic_preference: str = Form(""),
                        music_genre_preference: str = Form(""),
                        memory_care_mode: str = Form("")):
    db = request.app.state.db
    user = db.get_or_create_user()

    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE user_profiles SET name = ?, familiar_name = ?,
            bible_topic_preference = ?, music_genre_preference = ?,
            memory_care_mode = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (name, familiar_name or None, bible_topic_preference or None,
              music_genre_preference or None, 1 if memory_care_mode else 0, user["id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse("/web/settings", status_code=303)


# ── Setup ──

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    db = request.app.state.db
    user = db.get_or_create_user()
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "user": user,
    })


@router.post("/setup")
async def setup_save(request: Request, owner_name: str = Form(...),
                     owner_email: str = Form(""),
                     caretaker_name: str = Form(""),
                     caretaker_email: str = Form("")):
    db = request.app.state.db
    user = db.get_or_create_user()
    db.update_user_setup(user["id"], owner_name, owner_email,
                         caretaker_name, caretaker_email)
    return RedirectResponse("/web/setup", status_code=303)


# ── Transcription Review ──

@router.get("/transcriptions", response_class=HTMLResponse)
async def transcriptions_page(request: Request):
    db = request.app.state.db
    filter_val = request.query_params.get("filter", "all")

    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        if filter_val == "verified":
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories WHERE verified = 1 ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]
        elif filter_val == "unverified":
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories WHERE verified = 0 OR verified IS NULL ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]
        else:
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]
    finally:
        if not db._conn:
            conn.close()

    return templates.TemplateResponse("transcriptions.html", {
        "request": request,
        "stories": stories,
        "filter": filter_val,
    })


@router.post("/transcriptions/{story_id}/verify")
async def transcription_verify(request: Request, story_id: int,
                                speaker_name: str = Form(""),
                                corrected_transcript: str = Form(""),
                                verified_by: str = Form(...)):
    db = request.app.state.db

    # Update speaker name if changed
    conn = db._get_connection()
    try:
        conn.execute(
            "UPDATE stories SET speaker_name = ? WHERE id = ?",
            (speaker_name or None, story_id)
        )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    # Mark verified
    db.verify_story(story_id, verified_by, corrected_transcript or None)
    return RedirectResponse("/web/transcriptions", status_code=303)


# ── Photos ──

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB


@router.get("/photos", response_class=HTMLResponse)
async def photos_page(request: Request):
    db = request.app.state.db
    photos = db.get_photos(limit=100)
    stories = db.get_stories(limit=200)

    # Parse tags JSON for template display
    for photo in photos:
        try:
            photo["tag_list"] = json.loads(photo.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            photo["tag_list"] = []

    return templates.TemplateResponse("photos.html", {
        "request": request,
        "photos": photos,
        "stories": stories,
    })


@router.post("/photos/upload")
async def photo_upload(request: Request,
                       photo: UploadFile = File(...),
                       caption: str = Form(""),
                       date_taken: str = Form(""),
                       tags: str = Form(""),
                       story_id: str = Form(""),
                       uploaded_by: str = Form("")):
    db = request.app.state.db

    # Validate file extension
    ext = os.path.splitext(photo.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return RedirectResponse("/web/photos", status_code=303)

    # Read file content (with size limit)
    content = await photo.read()
    if len(content) > MAX_PHOTO_SIZE:
        return RedirectResponse("/web/photos", status_code=303)

    # Generate unique filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    filepath = os.path.join(uploads_dir, unique_name)

    # Save file
    with open(filepath, "wb") as f:
        f.write(content)

    # Parse tags to JSON
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    # Save to DB
    user = db.get_or_create_user()
    db.save_photo(
        filename=unique_name,
        original_name=photo.filename,
        caption=caption or None,
        date_taken=date_taken or None,
        tags=json.dumps(tag_list),
        story_id=int(story_id) if story_id else None,
        uploaded_by=uploaded_by or None,
        user_id=user["id"],
    )

    return RedirectResponse("/web/photos", status_code=303)


@router.post("/photos/{photo_id}/delete")
async def photo_delete(request: Request, photo_id: int):
    db = request.app.state.db
    photo = db.get_photo_by_id(photo_id)
    if photo:
        # Delete file from disk
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
        filepath = os.path.join(uploads_dir, photo["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
        db.delete_photo(photo_id)
    return RedirectResponse("/web/photos", status_code=303)
