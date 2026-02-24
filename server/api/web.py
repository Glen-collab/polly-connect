"""
Web app routes for Polly Connect caretaker portal.
FastAPI + Jinja2 templates + Tailwind CSS.
"""

import json
import logging
import os
from fastapi import APIRouter, Request, Form
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
    return templates.TemplateResponse("memory.html", {
        "request": request,
        "items": items,
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
