"""
Web app routes for Polly Connect caretaker portal.
FastAPI + Jinja2 templates + Tailwind CSS.
"""

import json
import logging
import os
import uuid
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.web_auth import get_web_session, require_login, hash_password, verify_password
from core.auth import generate_api_key
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Templates directory is at server/templates/
templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


# ── Auth routes (no session required) ──

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = await get_web_session(request)
    if session:
        return RedirectResponse("/web/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request, "error": None, "email": "", "session": None,
    })


@router.post("/login")
async def login_submit(request: Request, email: str = Form(...),
                        password: str = Form(...)):
    db = request.app.state.db
    account = db.get_account_by_email(email.strip().lower())
    if not account or not verify_password(password, account["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password.",
            "email": email,
            "session": None,
        })

    # Create session
    session_id = db.create_web_session(
        account["id"], account["tenant_id"],
        duration_hours=settings.SESSION_DURATION_HOURS,
    )
    db.update_account_login(account["id"])

    response = RedirectResponse("/web/dashboard", status_code=302)
    response.set_cookie(
        "polly_session", session_id,
        max_age=settings.SESSION_DURATION_HOURS * 3600,
        httponly=True, samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("polly_session")
    if session_id:
        request.app.state.db.delete_web_session(session_id)
    response = RedirectResponse("/web/login", status_code=302)
    response.delete_cookie("polly_session")
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    session = await get_web_session(request)
    if session:
        return RedirectResponse("/web/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {
        "request": request, "error": None, "name": "", "email": "",
        "household_name": "", "session": None,
    })


@router.post("/register")
async def register_submit(request: Request, name: str = Form(...),
                            household_name: str = Form(...),
                            email: str = Form(...), password: str = Form(...),
                            password_confirm: str = Form(...)):
    db = request.app.state.db
    email = email.strip().lower()

    # Validation
    if password != password_confirm:
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Passwords don't match.",
            "name": name, "email": email, "household_name": household_name,
            "session": None,
        })
    if len(password) < 6:
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Password must be at least 6 characters.",
            "name": name, "email": email, "household_name": household_name,
            "session": None,
        })
    if db.get_account_by_email(email):
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "An account with this email already exists.",
            "name": name, "email": email, "household_name": household_name,
            "session": None,
        })

    # If no accounts exist yet, use tenant #1 (Default). Otherwise create new tenant.
    if not db.has_accounts():
        tenant_id = 1
        # Update the default tenant name
        conn = db._get_connection()
        try:
            conn.execute("UPDATE tenants SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                         (household_name,))
            conn.commit()
        finally:
            if not db._conn:
                conn.close()
    else:
        tenant_id = db.create_tenant(household_name)

    # Create account
    pw_hash = hash_password(password)
    account_id = db.create_account(email, pw_hash, name, tenant_id, role="owner")

    # Ensure a user_profile exists for this tenant
    db.get_or_create_user(name=name, tenant_id=tenant_id)

    # Auto-login
    session_id = db.create_web_session(
        account_id, tenant_id,
        duration_hours=settings.SESSION_DURATION_HOURS,
    )
    db.update_account_login(account_id)

    response = RedirectResponse("/web/dashboard", status_code=302)
    response.set_cookie(
        "polly_session", session_id,
        max_age=settings.SESSION_DURATION_HOURS * 3600,
        httponly=True, samesite="lax",
    )
    return response


# ── Protected routes (session required) ──

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    stories = db.get_stories(limit=5, tenant_id=tid)
    medications = db.get_medications(tenant_id=tid)
    items = db.list_all(tenant_id=tid)
    stats = db.get_stats(tenant_id=tid)

    # Count question sessions
    conn = db._get_connection()
    try:
        q_count = conn.execute(
            "SELECT COUNT(*) FROM question_sessions WHERE answered = 1 AND tenant_id = ?",
            (tid,)
        ).fetchone()[0]
    except Exception:
        q_count = 0
    finally:
        if not db._conn:
            conn.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "stories": stories,
        "medications": medications,
        "story_count": len(stories),
        "question_count": q_count,
        "item_count": stats.get("total_items", 0),
    })


@router.get("/stories", response_class=HTMLResponse)
async def stories_list(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    stories = db.get_stories(limit=50, tenant_id=session["tenant_id"])
    return templates.TemplateResponse("stories.html", {
        "request": request,
        "session": session,
        "stories": stories,
    })


@router.get("/stories/{story_id}/edit", response_class=HTMLResponse)
async def story_edit(request: Request, story_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        story = conn.execute(
            "SELECT * FROM stories WHERE id = ? AND tenant_id = ?",
            (story_id, session["tenant_id"])
        ).fetchone()
        story = dict(story) if story else None
    finally:
        if not db._conn:
            conn.close()

    if not story:
        return RedirectResponse("/web/stories")

    return templates.TemplateResponse("story_edit.html", {
        "request": request,
        "session": session,
        "story": story,
    })


@router.post("/stories/{story_id}/edit")
async def story_edit_save(request: Request, story_id: int,
                          transcript: str = Form(""), speaker_name: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE stories SET transcript = ?, speaker_name = ?
            WHERE id = ? AND tenant_id = ?
        """, (transcript, speaker_name or None, story_id, session["tenant_id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse(f"/web/stories/{story_id}/edit", status_code=303)


@router.get("/medications", response_class=HTMLResponse)
async def medications_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    medications = db.get_medications(tenant_id=session["tenant_id"])
    return templates.TemplateResponse("medications.html", {
        "request": request,
        "session": session,
        "medications": medications,
    })


@router.post("/medications/add")
async def medication_add(request: Request, name: str = Form(...),
                         dosage: str = Form(""), times: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)
    # Parse comma-separated times into JSON
    time_list = [t.strip() for t in times.split(",") if t.strip()]
    db.add_medication(user["id"], name, dosage, json.dumps(time_list), tenant_id=tid)
    return RedirectResponse("/web/medications", status_code=303)


@router.get("/memory", response_class=HTMLResponse)
async def memory_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    items = db.list_all(tenant_id=tid)
    # Build unique location list for autocomplete suggestions
    locations = sorted(set(item["location"] for item in items if item.get("location")))
    return templates.TemplateResponse("memory.html", {
        "request": request,
        "session": session,
        "items": items,
        "locations": locations,
    })


@router.post("/memory/add")
async def memory_add(request: Request, item: str = Form(...), location: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.store_item(item, location, tenant_id=session["tenant_id"])
    return RedirectResponse("/web/memory", status_code=303)


@router.post("/memory/delete/{item_id}")
async def memory_delete(request: Request, item_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_by_id(item_id)
    return RedirectResponse("/web/memory", status_code=303)


@router.post("/memory/scan")
async def memory_scan(request: Request,
                      photo: UploadFile = File(...),
                      default_location: str = Form("")):
    """Send a photo to OpenAI Vision and return detected items."""
    from fastapi.responses import JSONResponse

    session = await get_web_session(request)
    if not session:
        return JSONResponse({"items": [], "error": "Not authenticated"}, status_code=401)

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

    session = await get_web_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]
    body = await request.json()
    items = body.get("items", [])
    count = 0
    for entry in items:
        item_name = entry.get("item", "").strip()
        location = entry.get("location", "").strip()
        if item_name and location:
            db.store_item(item_name, location, tenant_id=tid)
            count += 1
    return JSONResponse({"count": count})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "session": session,
        "user": user,
    })


@router.post("/settings")
async def settings_save(request: Request, name: str = Form(...),
                        familiar_name: str = Form(""),
                        bible_topic_preference: str = Form(""),
                        music_genre_preference: str = Form(""),
                        memory_care_mode: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])

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
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "session": session,
        "user": user,
    })


@router.post("/setup")
async def setup_save(request: Request, owner_name: str = Form(...),
                     owner_email: str = Form(""),
                     caretaker_name: str = Form(""),
                     caretaker_email: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    db.update_user_setup(user["id"], owner_name, owner_email,
                         caretaker_name, caretaker_email)
    return RedirectResponse("/web/setup", status_code=303)


# ── Transcription Review ──

@router.get("/transcriptions", response_class=HTMLResponse)
async def transcriptions_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    filter_val = request.query_params.get("filter", "all")

    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        if filter_val == "verified":
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories WHERE verified = 1 AND tenant_id = ? ORDER BY created_at DESC LIMIT 100",
                (tid,)
            ).fetchall()]
        elif filter_val == "unverified":
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories WHERE (verified = 0 OR verified IS NULL) AND tenant_id = ? ORDER BY created_at DESC LIMIT 100",
                (tid,)
            ).fetchall()]
        else:
            stories = [dict(r) for r in conn.execute(
                "SELECT * FROM stories WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 100",
                (tid,)
            ).fetchall()]
    finally:
        if not db._conn:
            conn.close()

    return templates.TemplateResponse("transcriptions.html", {
        "request": request,
        "session": session,
        "stories": stories,
        "filter": filter_val,
    })


@router.post("/transcriptions/{story_id}/verify")
async def transcription_verify(request: Request, story_id: int,
                                speaker_name: str = Form(""),
                                corrected_transcript: str = Form(""),
                                verified_by: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Update speaker name if changed
    conn = db._get_connection()
    try:
        conn.execute(
            "UPDATE stories SET speaker_name = ? WHERE id = ? AND tenant_id = ?",
            (speaker_name or None, story_id, tid)
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
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    photos = db.get_photos(limit=100, tenant_id=tid)
    stories = db.get_stories(limit=200, tenant_id=tid)

    # Parse tags JSON for template display
    for photo in photos:
        try:
            photo["tag_list"] = json.loads(photo.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            photo["tag_list"] = []

    return templates.TemplateResponse("photos.html", {
        "request": request,
        "session": session,
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
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

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
    user = db.get_or_create_user(tenant_id=tid)
    db.save_photo(
        filename=unique_name,
        original_name=photo.filename,
        caption=caption or None,
        date_taken=date_taken or None,
        tags=json.dumps(tag_list),
        story_id=int(story_id) if story_id else None,
        uploaded_by=uploaded_by or None,
        user_id=user["id"],
        tenant_id=tid,
    )

    return RedirectResponse("/web/photos", status_code=303)


@router.post("/photos/{photo_id}/delete")
async def photo_delete(request: Request, photo_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    photo = db.get_photo_by_id(photo_id)
    if photo and photo.get("tenant_id") == session["tenant_id"]:
        # Delete file from disk
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
        filepath = os.path.join(uploads_dir, photo["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
        db.delete_photo(photo_id)
    return RedirectResponse("/web/photos", status_code=303)


# ── Device Management ──

@router.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    devices = db.get_devices_by_tenant(tid)

    # Check for flash message about new device
    new_api_key = request.query_params.get("new_key")
    new_device_id = request.query_params.get("new_device_id")

    return templates.TemplateResponse("devices.html", {
        "request": request,
        "session": session,
        "devices": devices,
        "new_api_key": new_api_key,
        "new_device_id": new_device_id,
    })


@router.post("/devices/add")
async def device_add(request: Request, device_name: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Generate unique device_id and API key
    device_id = f"polly-{uuid.uuid4().hex[:8]}"
    api_key = generate_api_key()

    db.register_device(device_id, tid, name=device_name, api_key=api_key)

    # Redirect back with the key shown once
    return RedirectResponse(
        f"/web/devices?new_key={api_key}&new_device_id={device_id}",
        status_code=303,
    )


@router.post("/devices/{device_id}/delete")
async def device_delete(request: Request, device_id: str):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_device(device_id, session["tenant_id"])
    return RedirectResponse("/web/devices", status_code=303)
