"""
Web app routes for Polly Connect caretaker portal.
FastAPI + Jinja2 templates + Tailwind CSS.
"""

import asyncio
import io
import json
import logging
import os
import struct
import uuid
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.web_auth import get_web_session, require_login, require_owner, require_admin, hash_password, verify_password
from core.auth import generate_api_key
from core.medications import format_time_12hr, _get_local_now
from core.subscription import check_feature, get_subscription
from config import settings


def _gate_feature(db, session, feature: str, upgrade_msg: str = None):
    """Check if tenant can use a feature. Returns RedirectResponse if blocked, None if allowed."""
    tid = session.get("tenant_id")
    if not tid:
        return None
    if check_feature(db, tid, feature):
        return None
    # Blocked — redirect with upgrade message
    sub = get_subscription(db, tid)
    if sub.get("status") == "expired":
        msg = "Your free trial has ended. Subscribe to keep adding new content."
    elif feature == "book_export":
        msg = "Upgrade to Polly Legacy to export your book as a print-ready PDF."
    elif upgrade_msg:
        msg = upgrade_msg
    else:
        msg = "You've reached your plan limit. Upgrade to add more."
    return RedirectResponse(f"/web/pricing?msg={msg}", status_code=303)

import re
import urllib.request
import urllib.parse


def _geocode_city(city: str):
    """Geocode a city name to (lat, lon) using Nominatim (free, no key)."""
    try:
        q = urllib.parse.quote(city)
        url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "PollyConnect/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logging.getLogger(__name__).error(f"Geocode error for '{city}': {e}")
    return None


def parse_time_input(raw: str) -> str:
    """Convert user-friendly time ('8am', '2:30 PM', '2 PM', '14:00') to 24hr 'HH:MM'."""
    raw = raw.strip().lower()
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', raw)
    if not m:
        return raw  # return as-is if unparseable
    h = int(m.group(1))
    mins = int(m.group(2)) if m.group(2) else 0
    period = m.group(3)
    if period == 'pm' and h < 12:
        h += 12
    elif period == 'am' and h == 12:
        h = 0
    elif period is None and h <= 12:
        pass  # assume 24hr if no am/pm
    return f"{h:02d}:{mins:02d}"

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

    # Auto-upgrade legacy SHA-256 hash to bcrypt on successful login
    from core.web_auth import needs_rehash
    if needs_rehash(account["password_hash"]):
        new_hash = hash_password(password)
        conn = db._get_connection()
        try:
            conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?",
                         (new_hash, account["id"]))
            conn.commit()
        finally:
            if not db._conn:
                conn.close()

    # Create session
    session_id = db.create_web_session(
        account["id"], account["tenant_id"],
        duration_hours=settings.SESSION_DURATION_HOURS,
    )
    db.update_account_login(account["id"])

    # Check if owner needs onboarding
    dest = "/web/dashboard"
    if account.get("role") == "owner" and not account.get("is_admin"):
        user = db.get_or_create_user(tenant_id=account["tenant_id"])
        if not user.get("setup_complete"):
            dest = "/web/welcome"

    response = RedirectResponse(dest, status_code=302)
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
    if len(password) < 10:
        return templates.TemplateResponse("register.html", {
            "request": request, "error": "Password must be at least 10 characters.",
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
        # Start 30-day free trial for new tenants
        from core.subscription import start_trial
        start_trial(db, tenant_id, days=30)

    # Create account
    pw_hash = hash_password(password)
    account_id = db.create_account(email, pw_hash, name, tenant_id, role="owner")

    # Ensure a user_profile exists for this tenant
    db.get_or_create_user(name=name, tenant_id=tenant_id)

    # Notify admin of new registration
    try:
        from core.notify import notify_new_registration
        import threading
        threading.Thread(
            target=notify_new_registration,
            args=(name, email, household_name),
            daemon=True,
        ).start()
    except Exception:
        pass

    # Auto-login
    session_id = db.create_web_session(
        account_id, tenant_id,
        duration_hours=settings.SESSION_DURATION_HOURS,
    )
    db.update_account_login(account_id)

    response = RedirectResponse("/web/welcome", status_code=302)
    response.set_cookie(
        "polly_session", session_id,
        max_age=settings.SESSION_DURATION_HOURS * 3600,
        httponly=True, samesite="lax",
    )
    return response


# ── Welcome / Onboarding (first login) ──

@router.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect
    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    # Allow preview even if setup_complete (skip auto-redirect)
    return templates.TemplateResponse("welcome.html", {
        "request": request,
        "session": session,
        "user": user,
        "claim_code": "",
        "claim_error": None,
        "claim_success": None,
    })


@router.post("/welcome")
async def welcome_save(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    form = await request.form()
    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)

    name = form.get("name", "").strip()
    familiar_name = form.get("familiar_name", "").strip()
    hometown = form.get("hometown", "").strip()
    birth_year = form.get("birth_year", "").strip()
    location_city = form.get("location_city", "").strip()

    # Parse birth year
    birth_year_int = None
    if birth_year:
        try:
            birth_year_int = int(birth_year)
            birth_year_int = max(1800, min(2026, birth_year_int))
        except ValueError:
            pass

    # Geocode location
    location_lat = None
    location_lon = None
    if location_city:
        coords = _geocode_city(location_city)
        if coords:
            location_lat, location_lon = coords

    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE user_profiles SET name = ?, familiar_name = ?,
            hometown = ?, birth_year = ?,
            location_city = ?, location_lat = ?, location_lon = ?,
            setup_complete = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (name or user.get("name"), familiar_name or None,
              hometown or None, birth_year_int,
              location_city or None, location_lat, location_lon,
              user["id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    # Claim device if code provided
    claim_code = form.get("claim_code", "").strip()
    if claim_code and len(claim_code) == 6 and claim_code.isdigit():
        device = db.claim_device(claim_code, tid)
        if not device:
            # Code invalid — still save profile but show error on dashboard
            return RedirectResponse("/web/dashboard?claim_error=Invalid+or+already+claimed+code", status_code=303)

    return RedirectResponse("/web/dashboard", status_code=303)


# ── Family access routes ──

@router.get("/family", response_class=HTMLResponse)
async def family_login_page(request: Request):
    session = await get_web_session(request)
    if session:
        return RedirectResponse("/web/dashboard", status_code=302)
    return templates.TemplateResponse("family_login.html", {
        "request": request, "error": None, "name": "", "code": "", "session": None,
    })


@router.post("/family")
async def family_login_submit(request: Request, name: str = Form(...),
                               code: str = Form(...)):
    db = request.app.state.db
    code = code.strip()
    name = name.strip()

    if not name:
        return templates.TemplateResponse("family_login.html", {
            "request": request, "error": "Please enter your name.",
            "name": name, "code": code, "session": None,
        })

    result = db.validate_family_code(code)
    if not result:
        return templates.TemplateResponse("family_login.html", {
            "request": request, "error": "Invalid access code.",
            "name": name, "code": code, "session": None,
        })

    tenant = result["tenant"]
    member = result.get("member")

    # Personal code — use the member's name regardless of what was typed
    if member:
        name = member["name"]

    session_id = db.create_family_session(
        tenant["id"], name,
        family_member_id=member["id"] if member else None,
        duration_hours=settings.SESSION_DURATION_HOURS,
    )

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

    # Redirect owners to welcome page if they haven't completed first-time setup
    if session.get("role") == "owner" and not session.get("is_admin"):
        user = db.get_or_create_user(tenant_id=tid)
        if not user.get("setup_complete"):
            return RedirectResponse("/web/welcome", status_code=302)

    # Subscription status
    from core.subscription import get_subscription
    subscription = get_subscription(db, tid)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "subscription": subscription,
    })


# ── Hub pages (Jitterbug navigation) ──

@router.get("/hub/stories", response_class=HTMLResponse)
async def hub_stories(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    book_builder = getattr(request.app.state, "book_builder", None)
    book_progress = book_builder.get_book_progress(tenant_id=session["tenant_id"]) if book_builder else None
    return templates.TemplateResponse("hub_stories.html", {
        "request": request,
        "session": session,
        "book_progress": book_progress,
    })


@router.get("/hub/family", response_class=HTMLResponse)
async def hub_family(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    book_builder = getattr(request.app.state, "book_builder", None)
    book_progress = book_builder.get_book_progress(tenant_id=session["tenant_id"]) if book_builder else None
    return templates.TemplateResponse("hub_family.html", {
        "request": request,
        "session": session,
        "book_progress": book_progress,
    })


@router.get("/hub/care", response_class=HTMLResponse)
async def hub_care(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    if session.get("role") == "family":
        return RedirectResponse("/web/dashboard", status_code=302)
    db = request.app.state.db
    medications = db.get_medications(tenant_id=session["tenant_id"])
    book_builder = getattr(request.app.state, "book_builder", None)
    book_progress = book_builder.get_book_progress(tenant_id=session["tenant_id"]) if book_builder else None
    return templates.TemplateResponse("hub_care.html", {
        "request": request,
        "session": session,
        "medications": medications,
        "book_progress": book_progress,
    })


@router.get("/hub/settings", response_class=HTMLResponse)
async def hub_settings(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    if session.get("role") == "family":
        return RedirectResponse("/web/dashboard", status_code=302)
    book_builder = getattr(request.app.state, "book_builder", None)
    book_progress = book_builder.get_book_progress(tenant_id=session["tenant_id"]) if book_builder else None
    return templates.TemplateResponse("hub_settings.html", {
        "request": request,
        "session": session,
        "book_progress": book_progress,
    })


@router.get("/hub/memory", response_class=HTMLResponse)
async def hub_memory(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    if session.get("role") == "family":
        return RedirectResponse("/web/dashboard", status_code=302)
    db = request.app.state.db
    tid = session["tenant_id"]
    items = db.list_all(tenant_id=tid)
    return templates.TemplateResponse("hub_memory.html", {
        "request": request,
        "session": session,
        "item_count": len(items),
    })


@router.get("/memory/items", response_class=HTMLResponse)
async def memory_items_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    tid = session["tenant_id"]
    query = request.query_params.get("q", "").strip()
    saved = request.query_params.get("saved")
    deleted = request.query_params.get("deleted")
    if query:
        items = db.find_item(query, tenant_id=tid)
        if not items:
            items = db.find_by_location(query, tenant_id=tid)
    else:
        items = db.list_all(tenant_id=tid)
    return templates.TemplateResponse("memory_items.html", {
        "request": request,
        "session": session,
        "items": items,
        "query": query,
        "saved": saved,
        "deleted": deleted,
    })


@router.post("/memory/items/add")
async def memory_items_add(request: Request,
                           item: str = Form(...),
                           location: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    tid = session["tenant_id"]
    db.store_item(item.strip(), location.strip(), tenant_id=tid)
    return RedirectResponse("/web/memory/items?saved=1", status_code=303)


@router.post("/memory/items/delete")
async def memory_items_delete(request: Request,
                              item_name: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    tid = session["tenant_id"]
    db.delete_item(item_name.strip(), tenant_id=tid)
    return RedirectResponse("/web/memory/items?deleted=1", status_code=303)


@router.get("/memory/photo-index", response_class=HTMLResponse)
async def memory_photo_index_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    tid = session["tenant_id"]
    conn = db._get_connection()
    try:
        import sqlite3 as _sq
        conn.row_factory = _sq.Row
        indexed_photos = [dict(r) for r in conn.execute(
            "SELECT * FROM photo_indexes WHERE tenant_id = ? ORDER BY created_at DESC",
            (tid,)
        ).fetchall()]
    finally:
        if not db._conn:
            conn.close()
    error = request.query_params.get("error")
    return templates.TemplateResponse("memory_photo_index.html", {
        "request": request,
        "session": session,
        "indexed_photos": indexed_photos,
        "result": None,
        "error": error,
    })


@router.post("/memory/photo-index", response_class=HTMLResponse)
async def memory_photo_index_upload(request: Request,
                                    photo: UploadFile = File(...),
                                    location: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    tid = session["tenant_id"]

    # Save photo to uploads
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    import uuid
    ext = os.path.splitext(photo.filename or "photo.jpg")[1] or ".jpg"
    filename = f"idx_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(uploads_dir, filename)
    photo_data = await photo.read()
    if len(photo_data) > 10 * 1024 * 1024:
        return RedirectResponse("/web/memory/photo-index?error=Photo+too+large+(max+10MB)", status_code=303)
    with open(filepath, "wb") as f:
        f.write(photo_data)

    # Send to GPT-4 Vision to identify items
    import base64
    b64 = base64.b64encode(photo_data).decode()
    content_type = photo.content_type or "image/jpeg"

    indexed_items = []
    description = ""
    try:
        import openai
        client = openai.OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        f"This is a photo of: {location.strip()}. "
                        "List every identifiable item you can see and its specific location within the photo. "
                        "Format each item on its own line as: ITEM: item name | LOCATION: where in the space "
                        "(e.g. 'ITEM: cordless drill | LOCATION: top shelf left side'). "
                        "Be specific about positions. Only list physical items, not the space itself."
                    )},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{content_type};base64,{b64}",
                        "detail": "high",
                    }},
                ],
            }],
            max_tokens=1000,
        )
        raw = resp.choices[0].message.content or ""
        description = raw

        # Parse items from GPT response
        for line in raw.split("\n"):
            line = line.strip()
            if "ITEM:" in line and "LOCATION:" in line:
                parts = line.split("LOCATION:")
                item_part = parts[0].split("ITEM:")[-1].strip().rstrip("|").strip()
                loc_part = parts[1].strip()
                if item_part and loc_part:
                    full_location = f"{location.strip()} - {loc_part}"
                    db.store_item(item_part, full_location,
                                 context=f"Indexed from photo of {location.strip()}",
                                 tenant_id=tid)
                    indexed_items.append({"item": item_part, "location": full_location})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Photo index error: {e}")
        description = f"Error: {e}"

    # Save photo index record
    conn = db._get_connection()
    try:
        conn.execute(
            "INSERT INTO photo_indexes (tenant_id, filename, location, description, item_count) VALUES (?, ?, ?, ?, ?)",
            (tid, filename, location.strip(), description[:2000], len(indexed_items))
        )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    # Re-fetch indexed photos for display
    conn = db._get_connection()
    try:
        import sqlite3 as _sq
        conn.row_factory = _sq.Row
        indexed_photos = [dict(r) for r in conn.execute(
            "SELECT * FROM photo_indexes WHERE tenant_id = ? ORDER BY created_at DESC",
            (tid,)
        ).fetchall()]
    finally:
        if not db._conn:
            conn.close()

    return templates.TemplateResponse("memory_photo_index.html", {
        "request": request,
        "session": session,
        "indexed_photos": indexed_photos,
        "result": {"item_count": len(indexed_items), "items": indexed_items},
        "error": None,
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

    audio_url = f"https://polly-connect.com/static/recordings/{story['audio_s3_key']}" if story.get('audio_s3_key') else None
    return templates.TemplateResponse("story_edit.html", {
        "request": request,
        "session": session,
        "story": story,
        "audio_url": audio_url,
    })


@router.post("/stories/{story_id}/edit")
async def story_edit_save(request: Request, story_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    form = await request.form()
    transcript = form.get("transcript", "")
    speaker_name = form.get("speaker_name", "")
    question_text = form.get("question_text")
    qr_in_book = 1 if form.get("qr_in_book") else 0
    photo_in_book = 1 if form.get("photo_in_book") else 0

    db = request.app.state.db
    conn = db._get_connection()
    try:
        if question_text is not None:
            conn.execute("""
                UPDATE stories SET transcript = ?, speaker_name = ?, question_text = ?,
                       qr_in_book = ?, photo_in_book = ?
                WHERE id = ? AND tenant_id = ?
            """, (transcript, speaker_name or None, question_text or None,
                  qr_in_book, photo_in_book, story_id, session["tenant_id"]))
        else:
            conn.execute("""
                UPDATE stories SET transcript = ?, speaker_name = ?, qr_in_book = ?, photo_in_book = ?
                WHERE id = ? AND tenant_id = ?
            """, (transcript, speaker_name or None, qr_in_book, photo_in_book, story_id, session["tenant_id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse(f"/web/stories/{story_id}/edit", status_code=303)


@router.get("/stories/{story_id}/qr.png")
async def story_qr_code(request: Request, story_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        story = conn.execute(
            "SELECT audio_s3_key FROM stories WHERE id = ? AND tenant_id = ?",
            (story_id, session["tenant_id"])
        ).fetchone()
    finally:
        if not db._conn:
            conn.close()

    if not story or not story["audio_s3_key"]:
        from fastapi.responses import Response
        return Response(status_code=404)

    url = f"https://polly-connect.com/static/recordings/{story['audio_s3_key']}"
    try:
        import qrcode
        import io
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=6, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        from fastapi.responses import Response
        return Response(content=buf.read(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        from fastapi.responses import Response
        return Response(status_code=500)


@router.post("/stories/{story_id}/delete")
async def story_delete(request: Request, story_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        story = conn.execute(
            "SELECT audio_s3_key FROM stories WHERE id = ? AND tenant_id = ?",
            (story_id, session["tenant_id"])
        ).fetchone()

        conn.execute("DELETE FROM memories WHERE story_id = ? AND tenant_id = ?",
                     (story_id, session["tenant_id"]))
        conn.execute("DELETE FROM stories WHERE id = ? AND tenant_id = ?",
                     (story_id, session["tenant_id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    if story and story["audio_s3_key"]:
        import os
        audio_path = os.path.join("server", "static", "recordings", story["audio_s3_key"])
        if os.path.exists(audio_path):
            os.remove(audio_path)

    return RedirectResponse("/web/stories", status_code=303)


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
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)
    # Parse comma-separated times (supports "8am", "2:30 PM", "14:00")
    time_list = [parse_time_input(t) for t in times.split(",") if t.strip()]
    db.add_medication(user["id"], name, dosage, json.dumps(time_list), tenant_id=tid)
    return RedirectResponse("/web/medications", status_code=303)


@router.get("/medications/calendar")
async def medications_calendar(request: Request):
    """Generate .ics calendar file with medication reminders."""
    from fastapi.responses import Response

    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    medications = db.get_medications(tenant_id=tid)

    now = _get_local_now()
    tz_name = settings.TIMEZONE

    day_map = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH",
               "fri": "FR", "sat": "SA", "sun": "SU"}

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Polly Connect//Medication Reminders//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{tz_name}",
    ]

    for med in medications:
        times = json.loads(med["times"]) if isinstance(med["times"], str) else med["times"]
        active_days = json.loads(med["active_days"]) if isinstance(med["active_days"], str) else med["active_days"]

        byday = ",".join(day_map.get(d, "") for d in active_days if d in day_map)
        if not byday:
            byday = "MO,TU,WE,TH,FR,SA,SU"

        dosage_str = f" ({med.get('dosage', '')})" if med.get("dosage") else ""

        for med_time in times:
            try:
                h, m = med_time.split(":")
                h, m = int(h), int(m)
            except (ValueError, AttributeError):
                continue

            time_display = format_time_12hr(med_time)
            uid = f"polly-med-{med['id']}-{med_time.replace(':', '')}@polly-connect.com"
            dtstart = now.strftime(f"%Y%m%dT{h:02d}{m:02d}00")
            end_m = m + 15
            end_h = h + (end_m // 60)
            end_m = end_m % 60
            dtend = now.strftime(f"%Y%m%dT{end_h:02d}{end_m:02d}00")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART;TZID={tz_name}:{dtstart}",
                f"DTEND;TZID={tz_name}:{dtend}",
                f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
                f"SUMMARY:Take {med['name']}{dosage_str}",
                f"DESCRIPTION:Polly reminder: Take {med['name']}{dosage_str} at {time_display}",
                "BEGIN:VALARM",
                "TRIGGER:-PT5M",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Time to take {med['name']}{dosage_str}",
                "END:VALARM",
                "END:VEVENT",
            ])

    lines.append("END:VCALENDAR")
    ics_content = "\r\n".join(lines) + "\r\n"

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=polly-medications.ics"},
    )


@router.get("/medications/{med_id}/edit", response_class=HTMLResponse)
async def medication_edit(request: Request, med_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    med = db.get_medication_by_id(med_id, tenant_id=tid)
    if not med:
        return RedirectResponse("/web/medications", status_code=302)

    # Parse times/days for the form
    times = json.loads(med["times"]) if isinstance(med["times"], str) else med["times"]
    active_days = json.loads(med["active_days"]) if isinstance(med["active_days"], str) else med["active_days"]

    # Show times in 12hr format for the edit form
    times_display = [format_time_12hr(t) for t in times]

    return templates.TemplateResponse("medication_edit.html", {
        "request": request,
        "session": session,
        "med": med,
        "times_str": ", ".join(times_display),
        "active_days": active_days,
    })


@router.post("/medications/{med_id}/edit")
async def medication_edit_save(request: Request, med_id: int,
                                name: str = Form(...), dosage: str = Form(""),
                                times: str = Form(...), active_days: list = Form(None)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Parse form data (supports "8am", "2:30 PM", "14:00")
    time_list = [parse_time_input(t) for t in times.split(",") if t.strip()]

    # active_days comes from checkboxes
    form_data = await request.form()
    day_list = form_data.getlist("active_days")
    if not day_list:
        day_list = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    db.update_medication(
        med_id, name, dosage,
        json.dumps(time_list), json.dumps(day_list),
        tenant_id=tid,
    )
    return RedirectResponse("/web/medications", status_code=303)


@router.post("/medications/{med_id}/delete")
async def medication_delete(request: Request, med_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_medication(med_id, tenant_id=session["tenant_id"])
    return RedirectResponse("/web/medications", status_code=303)


@router.get("/api/medications/upcoming")
async def medications_upcoming(request: Request):
    """JSON endpoint: today's medications with countdown and status badges."""
    from fastapi.responses import JSONResponse

    session = await get_web_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]
    medications = db.get_medications(tenant_id=tid)

    now = _get_local_now()
    current_minutes = now.hour * 60 + now.minute
    current_day = now.strftime("%a").lower()

    result = []
    for med in medications:
        times = json.loads(med["times"]) if isinstance(med["times"], str) else med["times"]
        active_days = json.loads(med["active_days"]) if isinstance(med["active_days"], str) else med["active_days"]

        active_today = current_day in active_days

        for med_time in times:
            try:
                h, m = med_time.split(":")
                med_minutes = int(h) * 60 + int(m)
            except (ValueError, AttributeError):
                continue

            diff = med_minutes - current_minutes
            if active_today:
                if diff < -30:
                    badge = "overdue"
                elif diff <= 30:
                    badge = "soon"
                else:
                    badge = "scheduled"
            else:
                badge = "inactive"

            result.append({
                "id": med["id"],
                "name": med["name"],
                "dosage": med.get("dosage", ""),
                "time_24": med_time,
                "time_display": format_time_12hr(med_time),
                "countdown_minutes": diff if active_today else None,
                "badge": badge,
            })

    # Sort: overdue first, then by time
    badge_order = {"overdue": 0, "soon": 1, "scheduled": 2, "inactive": 3}
    result.sort(key=lambda x: (badge_order.get(x["badge"], 9), x["time_24"]))

    return JSONResponse({"medications": result, "current_time": now.strftime("%I:%M %p")})


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
    gate = _gate_feature(db, session, "add_item")
    if gate:
        return gate
    db.store_item(item, location, tenant_id=session["tenant_id"])
    return RedirectResponse("/web/memory", status_code=303)


@router.post("/memory/delete/{item_id}")
async def memory_delete(request: Request, item_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
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
    if session.get("role") == "family":
        return JSONResponse({"items": [], "error": "Not authorized"}, status_code=403)

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
    if session.get("role") == "family":
        return JSONResponse({"error": "Not authorized"}, status_code=403)

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


# ── Message Board routes ──

@router.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    messages = db.get_messages_for(tenant_id=session["tenant_id"])
    family_members = db.get_family_members(tenant_id=session["tenant_id"])
    return templates.TemplateResponse("messages.html", {
        "request": request,
        "session": session,
        "messages": messages,
        "family_members": family_members,
    })


@router.post("/messages/send")
async def messages_send(request: Request, from_name: str = Form(...), to_name: str = Form(""), message: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    db.save_message(
        from_name=from_name,
        message=message,
        to_name=to_name if to_name else None,
        tenant_id=session["tenant_id"],
    )
    return RedirectResponse("/web/messages", status_code=303)


@router.post("/messages/{message_id}/delete")
async def messages_delete(request: Request, message_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect
    db = request.app.state.db
    db.delete_message(message_id, tenant_id=session["tenant_id"])
    return RedirectResponse("/web/messages", status_code=303)


@router.post("/messages/clear-all")
async def messages_clear_all(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect
    db = request.app.state.db
    db.clear_all_messages(tenant_id=session["tenant_id"])
    return RedirectResponse("/web/messages", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    tenant = db.get_tenant(session["tenant_id"])

    # Check if any device is currently snoozed
    squawk_mgr = getattr(request.app.state, "squawk", None)
    is_snoozed = False
    if squawk_mgr:
        for dev_id in squawk_mgr._active_devices:
            if squawk_mgr.is_snoozed(dev_id):
                is_snoozed = True
                break

    pronunciations = db.get_pronunciations(session["tenant_id"])

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "session": session,
        "user": user,
        "tenant": tenant,
        "is_snoozed": is_snoozed,
        "pronunciations": pronunciations,
    })


@router.post("/settings")
async def settings_save(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])

    # Parse form data — each section only sends its own fields
    form = await request.form()

    # Start with current DB values as defaults
    name = form.get("name", user.get("name") or "")
    familiar_name = form.get("familiar_name", user.get("familiar_name") or "")
    hometown = form.get("hometown", user.get("hometown") or "")
    birth_year = form.get("birth_year", str(user.get("birth_year") or ""))
    bible_topic_preference = form.get("bible_topic_preference", user.get("bible_topic_preference") or "")
    music_genre_preference = form.get("music_genre_preference", user.get("music_genre_preference") or "")
    location_city = form.get("location_city", user.get("location_city") or "")
    # Checkbox: only present in form if checked AND this is the prefs section
    section = form.get("_section", "")
    if section == "prefs":
        memory_care_mode = form.get("memory_care_mode", "")
    else:
        memory_care_mode = "1" if user.get("memory_care_mode") else ""
    squawk_interval = int(form.get("squawk_interval", user.get("squawk_interval") or 10))
    chatter_interval = int(form.get("chatter_interval", user.get("chatter_interval") or 45))
    quiet_hours_start = int(form.get("quiet_hours_start",
                            user.get("quiet_hours_start") if user.get("quiet_hours_start") is not None else 21))
    quiet_hours_end = int(form.get("quiet_hours_end",
                          user.get("quiet_hours_end") if user.get("quiet_hours_end") is not None else 7))
    squawk_volume = int(form.get("squawk_volume",
                        user.get("squawk_volume") if user.get("squawk_volume") is not None else 30))
    voice_volume = int(form.get("voice_volume",
                       user.get("voice_volume") if user.get("voice_volume") is not None else 100))
    rms_threshold = int(form.get("rms_threshold",
                        user.get("rms_threshold") if user.get("rms_threshold") is not None else 200))

    # Clamp intervals to reasonable bounds
    squawk_interval = max(0, min(60, squawk_interval))
    chatter_interval = max(0, min(240, chatter_interval))
    quiet_hours_start = max(0, min(23, quiet_hours_start))
    quiet_hours_end = max(0, min(23, quiet_hours_end))
    squawk_volume = max(0, min(100, squawk_volume))
    voice_volume = max(10, min(100, voice_volume))
    rms_threshold = max(50, min(2000, rms_threshold))

    # Geocode location if changed
    location_lat = user.get("location_lat")
    location_lon = user.get("location_lon")
    if location_city and location_city.strip():
        location_city = location_city.strip()
        if location_city != (user.get("location_city") or ""):
            coords = _geocode_city(location_city)
            if coords:
                location_lat, location_lon = coords
    else:
        location_city = None
        location_lat = None
        location_lon = None

    # Parse birth_year
    birth_year_int = None
    if birth_year and birth_year.strip():
        try:
            birth_year_int = int(birth_year.strip())
            birth_year_int = max(1800, min(2026, birth_year_int))
        except ValueError:
            pass

    conn = db._get_connection()
    try:
        conn.execute("""
            UPDATE user_profiles SET name = ?, familiar_name = ?,
            bible_topic_preference = ?, music_genre_preference = ?,
            memory_care_mode = ?, squawk_interval = ?, chatter_interval = ?,
            quiet_hours_start = ?, quiet_hours_end = ?,
            location_city = ?, location_lat = ?, location_lon = ?,
            squawk_volume = ?, voice_volume = ?, rms_threshold = ?,
            hometown = ?, birth_year = ?,
            updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (name, familiar_name or None, bible_topic_preference or None,
              music_genre_preference or None, 1 if memory_care_mode else 0,
              squawk_interval, chatter_interval,
              quiet_hours_start, quiet_hours_end,
              location_city, location_lat, location_lon,
              squawk_volume, voice_volume, rms_threshold,
              hometown.strip() or None, birth_year_int,
              user["id"]))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    # Update live squawk manager if devices are connected
    squawk_mgr = getattr(request.app.state, "squawk", None)
    if squawk_mgr:
        for dev_id in list(squawk_mgr._active_devices.keys()):
            squawk_mgr.update_intervals(dev_id, squawk_interval, chatter_interval,
                                        quiet_hours_start, quiet_hours_end,
                                        squawk_volume=squawk_volume)

    # Update live VAD threshold if devices are connected
    detector = getattr(request.app.state, "wake_word_detector", None)
    if detector:
        from core.vad_wakeword import VADWakeWordDetector
        if isinstance(detector, VADWakeWordDetector):
            detector.rms_threshold = rms_threshold
            logger.info(f"RMS threshold updated to {rms_threshold} from settings")

    # Update live voice volume on connected devices
    cmd = getattr(request.app.state, "cmd", None)
    if cmd:
        for dev_id in list(getattr(cmd, "_states", {}).keys()):
            state = cmd._get_state(dev_id)
            if getattr(state, "tenant_id", None) == session["tenant_id"]:
                state.voice_volume = voice_volume
                logger.info(f"Voice volume updated to {voice_volume}% for device {dev_id}")

    return RedirectResponse("/web/settings?saved=1", status_code=303)


@router.post("/settings/pronunciation/add")
async def pronunciation_add(request: Request, word: str = Form(...), phonetic: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect
    word = word.strip()
    phonetic = phonetic.strip()
    if word and phonetic:
        db = request.app.state.db
        db.add_pronunciation(session["tenant_id"], word, phonetic)
    return RedirectResponse("/web/settings#pronunciation", status_code=303)


@router.post("/settings/pronunciation/delete")
async def pronunciation_delete(request: Request, pronunciation_id: int = Form(...)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect
    db = request.app.state.db
    db.delete_pronunciation(pronunciation_id)
    return RedirectResponse("/web/settings#pronunciation", status_code=303)


@router.post("/settings/squawk-snooze")
async def squawk_snooze(request: Request, duration: int = Form(30)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    duration = max(5, min(480, duration))  # 5 min to 8 hours
    squawk_mgr = getattr(request.app.state, "squawk", None)
    if squawk_mgr:
        for dev_id in list(squawk_mgr._active_devices.keys()):
            squawk_mgr.snooze(dev_id, duration)

    return RedirectResponse("/web/settings", status_code=303)


@router.post("/settings/squawk-unsnooze")
async def squawk_unsnooze(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    squawk_mgr = getattr(request.app.state, "squawk", None)
    if squawk_mgr:
        for dev_id in list(squawk_mgr._active_devices.keys()):
            squawk_mgr.unsnooze(dev_id)

    return RedirectResponse("/web/settings", status_code=303)


# ── Setup ──

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
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
    redirect = require_owner(session)
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

    # Family members can only verify their own stories
    if session.get("role") == "family":
        story = db.get_story_by_id(story_id, tenant_id=tid)
        member_id = session.get("family_member_id")
        if not story or not member_id or story.get("recorded_by_member_id") != member_id:
            return RedirectResponse("/web/transcriptions", status_code=303)

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
    db.verify_story(story_id, verified_by, corrected_transcript or None,
                     tenant_id=tid)
    return RedirectResponse("/web/transcriptions", status_code=303)


@router.post("/transcriptions/{story_id}/delete")
async def transcription_delete(request: Request, story_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    conn = db._get_connection()
    try:
        conn.execute("DELETE FROM stories WHERE id = ? AND tenant_id = ?", (story_id, tid))
        conn.execute("DELETE FROM memories WHERE story_id = ? AND tenant_id = ?", (story_id, tid))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

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

    # Parse tags JSON and attach all stories for each photo
    conn = db._get_connection()
    import sqlite3 as _sqlite3
    conn.row_factory = _sqlite3.Row
    for photo in photos:
        try:
            photo["tag_list"] = json.loads(photo.get("tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            photo["tag_list"] = []
        # Get all stories linked to this photo
        photo_stories = conn.execute(
            "SELECT id, COALESCE(corrected_transcript, transcript) as transcript, speaker_name, audio_s3_key "
            "FROM stories WHERE photo_id = ? AND tenant_id = ? ORDER BY id",
            (photo["id"], tid)
        ).fetchall()
        photo["stories"] = [dict(s) for s in photo_stories]

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
    gate = _gate_feature(db, session, "add_photo")
    if gate:
        return gate
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
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    photo = db.get_photo_by_id(photo_id, tenant_id=tid)
    if photo:
        # Delete file from disk
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
        filepath = os.path.join(uploads_dir, photo["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
        db.delete_photo(photo_id, tenant_id=tid)
    return RedirectResponse("/web/photos", status_code=303)


@router.post("/photos/{photo_id}/toggle-book")
async def photo_toggle_book(request: Request, photo_id: int):
    """Toggle whether a photo appears in the legacy book."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    photo = db.get_photo_by_id(photo_id, tenant_id=tid)
    if not photo:
        return RedirectResponse("/web/photos", status_code=303)

    conn = db._get_connection()
    try:
        # Toggle on photos table
        new_val = 0 if photo.get("in_book", 1) else 1
        conn.execute("UPDATE photos SET in_book = ? WHERE id = ? AND tenant_id = ?",
                     (new_val, photo_id, tid))
        # Also sync to linked story if exists
        if photo.get("story_id"):
            conn.execute("UPDATE stories SET photo_in_book = ? WHERE id = ? AND tenant_id = ?",
                         (new_val, photo["story_id"], tid))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse("/web/photos", status_code=303)


# ── Photo Story Recording (browser mic) ──

MAX_AUDIO_SIZE = 30 * 1024 * 1024  # 30MB (~5 min at 16kHz mono)

def _build_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM int16 bytes in a WAV header."""
    buf = io.BytesIO()
    data_size = len(pcm_bytes)
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))  # chunk size
    buf.write(struct.pack('<H', 1))   # PCM format
    buf.write(struct.pack('<H', channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', sample_rate * channels * sample_width))
    buf.write(struct.pack('<H', channels * sample_width))
    buf.write(struct.pack('<H', sample_width * 8))
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_bytes)
    return buf.getvalue()


@router.post("/stories/record")
async def web_record_story(request: Request):
    """Record a memory directly from the phone — audio is always kept even without transcription."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]

    if not check_feature(db, tid, "add_story"):
        return JSONResponse({"error": "Plan limit reached. Upgrade to keep recording."}, status_code=403)

    form = await request.form()
    audio = form.get("audio")
    speaker_name = form.get("speaker_name", "")

    audio_data = await audio.read()
    if len(audio_data) > MAX_AUDIO_SIZE:
        return JSONResponse({"error": "Audio too large (max 5 minutes)"}, status_code=413)
    if len(audio_data) < 1000:
        return JSONResponse({"error": "Audio too short"}, status_code=400)

    content_type = audio.content_type or ""
    if "octet-stream" in content_type or "raw" in content_type:
        wav_bytes = _build_wav(audio_data, sample_rate=16000)
    elif "wav" in content_type:
        wav_bytes = audio_data
    else:
        wav_bytes = audio_data if audio_data[:4] == b'RIFF' else _build_wav(audio_data)

    # Save WAV file
    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    wav_filename = f"web_{uuid.uuid4().hex[:8]}.wav"
    wav_path = os.path.join(recordings_dir, wav_filename)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)

    # Try to transcribe, but keep audio regardless
    transcriber = request.app.state.transcriber
    transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
    if not transcription or len(transcription.strip()) < 5:
        transcription = "[Audio memory]"

    # Auto-set speaker name from family member if not provided
    member_id = session.get("family_member_id")
    if not speaker_name and member_id:
        member = db.get_family_member_by_id(member_id)
        if member:
            speaker_name = member.get("name", "")

    # Save as story
    user = db.get_or_create_user(tenant_id=tid)
    story_id = db.save_story(
        transcript=transcription,
        audio_s3_key=wav_filename,
        speaker_name=speaker_name or None,
        source="web_recording",
        user_id=user["id"],
        tenant_id=tid,
        recorded_by_member_id=member_id,
    )

    # Extract memory if transcription is real
    if transcription != "[Audio memory]":
        memory_extractor = getattr(request.app.state, "memory_extractor", None)
        if memory_extractor:
            try:
                await asyncio.to_thread(
                    memory_extractor.extract_and_save_memories,
                    db, transcription, user["id"], tid,
                    speaker_name=speaker_name or None,
                    question_text=None,
                )
            except Exception as e:
                logger.error(f"Memory extraction failed for web recording: {e}")

    return JSONResponse({"transcript": transcription, "story_id": story_id})


@router.post("/photos/{photo_id}/record-story")
async def photo_record_story(request: Request, photo_id: int,
                              audio: UploadFile = File(...),
                              speaker_name: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]

    if not check_feature(db, tid, "add_photo_story"):
        return JSONResponse({"error": "Plan limit reached. Upgrade to keep recording."}, status_code=403)

    # Verify photo belongs to this tenant
    photo = db.get_photo_by_id(photo_id, tenant_id=tid)
    if not photo:
        return JSONResponse({"error": "Photo not found"}, status_code=404)

    # Read audio data
    audio_data = await audio.read()
    if len(audio_data) > MAX_AUDIO_SIZE:
        return JSONResponse({"error": "Audio too large (max 5 minutes)"}, status_code=413)
    if len(audio_data) < 1000:
        return JSONResponse({"error": "Audio too short"}, status_code=400)

    content_type = audio.content_type or ""
    # Browser sends raw PCM int16 at 16kHz from our JS recorder
    if "octet-stream" in content_type or "raw" in content_type:
        wav_bytes = _build_wav(audio_data, sample_rate=16000)
    elif "wav" in content_type:
        wav_bytes = audio_data
    else:
        # Try treating as WAV anyway (browser might label it oddly)
        wav_bytes = audio_data if audio_data[:4] == b'RIFF' else _build_wav(audio_data)

    # Save WAV file for playback
    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    wav_filename = f"photo_{photo_id}_{uuid.uuid4().hex[:8]}.wav"
    wav_path = os.path.join(recordings_dir, wav_filename)
    with open(wav_path, "wb") as f:
        f.write(wav_bytes)

    # Transcribe
    transcriber = request.app.state.transcriber
    transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)

    if not transcription or len(transcription.strip()) < 5:
        transcription = "[Audio memory]"

    # Build question context from photo caption + tags
    caption = photo.get("caption") or "this photo"
    question_text = f"Tell me about {caption}"

    # Auto-set speaker name from family member if not provided
    member_id = session.get("family_member_id")
    if not speaker_name and member_id:
        member = db.get_family_member_by_id(member_id)
        if member:
            speaker_name = member.get("name", "")

    # Save as story linked to the photo
    user = db.get_or_create_user(tenant_id=tid)
    story_id = db.save_story(
        transcript=transcription,
        audio_s3_key=wav_filename,
        speaker_name=speaker_name or None,
        source="photo_story",
        user_id=user["id"],
        tenant_id=tid,
        question_text=question_text,
        photo_id=photo_id,
        recorded_by_member_id=member_id,
    )

    # Link story to photo (bidirectional)
    db.link_photo_story(photo_id, story_id, tenant_id=tid)

    # Extract structured memory for the legacy book
    memory_extractor = getattr(request.app.state, "memory_extractor", None)
    if memory_extractor:
        date_taken = photo.get("date_taken") or ""

        # Build enriched context: photo caption + tags as question hint
        tags_str = ""
        try:
            tag_list = json.loads(photo.get("tags") or "[]")
            if tag_list:
                tags_str = ", ".join(tag_list)
        except (json.JSONDecodeError, TypeError):
            pass
        enriched_question = question_text
        if tags_str:
            enriched_question += f" (tags: {tags_str})"
        if date_taken:
            enriched_question += f" (from {date_taken})"

        mem_data = memory_extractor.extract(
            text=transcription,
            question=enriched_question,
            speaker=speaker_name or None,
        )


        fingerprint = memory_extractor.compute_fingerprint(mem_data)
        db.save_memory(
            story_id=story_id,
            speaker=speaker_name or None,
            bucket=mem_data["bucket"],
            life_phase=mem_data["life_phase"],
            text_summary=mem_data["text_summary"],
            text=transcription,
            people=mem_data["people"],
            locations=mem_data["locations"],
            emotions=mem_data["emotions"],
            fingerprint=fingerprint,
            tenant_id=tid,
        )

    # Add photo tags as story tags
    try:
        tag_list = json.loads(photo.get("tags") or "[]")
        for tag in tag_list:
            db.add_story_tag(story_id, "photo_tag", tag, tenant_id=tid)
    except (json.JSONDecodeError, TypeError):
        pass

    return JSONResponse({
        "success": True,
        "story_id": story_id,
        "transcript": transcription,
        "photo_id": photo_id,
    })


# ── Family Code Management ──

@router.post("/settings/family-code/generate")
async def family_code_generate(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.generate_family_code(session["tenant_id"])
    return RedirectResponse("/web/settings", status_code=303)


@router.post("/settings/family-code/revoke")
async def family_code_revoke(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.revoke_family_code(session["tenant_id"])
    return RedirectResponse("/web/settings", status_code=303)


# ── Photo Edit ──

@router.get("/photos/{photo_id}/edit", response_class=HTMLResponse)
async def photo_edit_page(request: Request, photo_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    photo = db.get_photo_by_id(photo_id, tenant_id=tid)
    if not photo:
        return RedirectResponse("/web/photos", status_code=303)

    # Parse tags for display
    try:
        tag_list = json.loads(photo.get("tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        tag_list = []

    stories = db.get_stories(limit=200, tenant_id=tid)
    family_members = db.get_family_members(tenant_id=tid)

    return templates.TemplateResponse("photo_edit.html", {
        "request": request,
        "session": session,
        "photo": photo,
        "tag_list": tag_list,
        "stories": stories,
        "family_members": family_members,
    })


@router.post("/photos/{photo_id}/edit")
async def photo_edit_save(request: Request, photo_id: int,
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
    photo = db.get_photo_by_id(photo_id, tenant_id=tid)
    if not photo:
        return RedirectResponse("/web/photos", status_code=303)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    db.update_photo(
        photo_id,
        caption=caption or None,
        date_taken=date_taken or None,
        tags=json.dumps(tag_list),
        story_id=int(story_id) if story_id else None,
        tenant_id=tid,
    )
    return RedirectResponse("/web/photos", status_code=303)


# ── Family Tree ──

RELATIONSHIP_CHOICES = [
    # -- Ancestors (above owner) --
    ("great-great-grandfather", "Great-Great-Grandfather"),
    ("great-great-grandmother", "Great-Great-Grandmother"),
    ("great-grandfather", "Great-Grandfather"),
    ("great-grandmother", "Great-Grandmother"),
    ("grandfather", "Grandfather"),
    ("grandmother", "Grandmother"),
    ("father", "Father"),
    ("mother", "Mother"),
    ("father-in-law", "Father-in-law"),
    ("mother-in-law", "Mother-in-law"),
    # -- Same generation --
    ("owner", "This is me (the owner)"),
    ("husband", "Husband"),
    ("wife", "Wife"),
    ("spouse", "Spouse / Partner"),
    ("brother", "Brother"),
    ("sister", "Sister"),
    ("brother-in-law", "Brother-in-law"),
    ("sister-in-law", "Sister-in-law"),
    ("cousin", "Cousin"),
    ("uncle", "Uncle"),
    ("aunt", "Aunt"),
    ("great-uncle", "Great-Uncle"),
    ("great-aunt", "Great-Aunt"),
    # -- Children & below --
    ("son", "Son"),
    ("daughter", "Daughter"),
    ("son-in-law", "Son-in-law"),
    ("daughter-in-law", "Daughter-in-law"),
    ("stepson", "Stepson"),
    ("stepdaughter", "Stepdaughter"),
    ("nephew", "Nephew"),
    ("niece", "Niece"),
    ("grandson", "Grandson"),
    ("granddaughter", "Granddaughter"),
    ("great-grandson", "Great-grandson"),
    ("great-granddaughter", "Great-granddaughter"),
    ("great-great-grandson", "Great-Great-Grandson"),
    ("great-great-granddaughter", "Great-Great-Granddaughter"),
    # -- Non-family --
    ("friend", "Friend"),
    ("neighbor", "Neighbor"),
    ("caretaker", "Caretaker"),
    ("other", "Other"),
]

# Generation levels relative to owner (0). Negative = older generation.
RELATION_GENERATION = {
    "great-great-grandfather": -4, "great-great-grandmother": -4,
    "great-grandfather": -3, "great-grandmother": -3,
    "grandfather": -2, "grandmother": -2,
    "father": -1, "mother": -1,
    "father-in-law": -1, "mother-in-law": -1,
    "uncle": -1, "aunt": -1,
    "great-uncle": -2, "great-aunt": -2,
    "owner": 0, "husband": 0, "wife": 0, "spouse": 0,
    "brother": 0, "sister": 0, "brother-in-law": 0, "sister-in-law": 0,
    "cousin": 0,
    "son": 1, "daughter": 1, "son-in-law": 1, "daughter-in-law": 1,
    "stepson": 1, "stepdaughter": 1,
    "nephew": 1, "niece": 1,
    "grandson": 2, "granddaughter": 2,
    "great-grandson": 3, "great-granddaughter": 3,
    "great-great-grandson": 4, "great-great-granddaughter": 4,
    "friend": 0, "neighbor": 0, "caretaker": 0, "other": 0,
}


@router.get("/family-tree", response_class=HTMLResponse)
async def family_tree_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    members = db.get_family_members(tenant_id=tid)

    # Get owner name from setup
    conn = db._get_connection()
    try:
        conn.row_factory = __import__("sqlite3").Row
        profile = conn.execute(
            "SELECT * FROM user_profiles WHERE tenant_id = ? LIMIT 1", (tid,)
        ).fetchone()
        owner_name = profile["name"] if profile and profile["name"] else "The Owner"
    finally:
        if not db._conn:
            conn.close()

    # Build tree structure: group by generation
    tree = {}
    for m in members:
        gen = m.get("generation") or RELATION_GENERATION.get(m.get("relation_to_owner", ""), 0)
        if gen not in tree:
            tree[gen] = []
        tree[gen].append(m)

    return templates.TemplateResponse("family_tree.html", {
        "request": request,
        "session": session,
        "members": members,
        "tree": tree,
        "owner_name": owner_name,
        "relationship_choices": RELATIONSHIP_CHOICES,
    })


@router.post("/family-tree/add")
async def family_tree_add(request: Request,
                           name: str = Form(...),
                           relation_to_owner: str = Form(...),
                           parent_member_id: str = Form(""),
                           spouse_name: str = Form(""),
                           bio: str = Form(""),
                           deceased: str = Form(""),
                           birth_year: str = Form(""),
                           deceased_year: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    generation = RELATION_GENERATION.get(relation_to_owner, 0)
    parent_id = int(parent_member_id) if parent_member_id else None

    # Parse birth_year / deceased_year
    by = None
    if birth_year and birth_year.strip().isdigit():
        by = max(1800, min(2026, int(birth_year.strip())))
    dy = None
    if deceased_year and deceased_year.strip().isdigit():
        dy = max(1800, min(2026, int(deceased_year.strip())))

    # Use add_family_member to create or update
    member_id = db.add_family_member(
        name=name.strip(),
        relationship=relation_to_owner,
        tenant_id=tid,
    )
    # Set tree-specific fields + track who added this member
    added_by_name = session.get("name", "")
    db.update_family_member(
        member_id,
        relation_to_owner=relation_to_owner,
        parent_member_id=parent_id,
        generation=generation,
        spouse_name=spouse_name.strip(),
        bio=bio.strip(),
        deceased=1 if deceased else 0,
        added_by=added_by_name,
        birth_year=by or 0,
        deceased_year=dy or 0,
    )

    return RedirectResponse("/web/family-tree", status_code=303)


@router.post("/family-tree/{member_id}/edit")
async def family_tree_edit(request: Request, member_id: int,
                            name: str = Form(...),
                            relation_to_owner: str = Form(...),
                            parent_member_id: str = Form(""),
                            spouse_name: str = Form(""),
                            bio: str = Form(""),
                            deceased: str = Form(""),
                            birth_year: str = Form(""),
                            deceased_year: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return RedirectResponse("/web/family-tree", status_code=303)

    # Family role can only edit members they added
    if session.get("role") == "family":
        if member.get("added_by") != session.get("name"):
            return RedirectResponse("/web/family-tree", status_code=303)

    generation = RELATION_GENERATION.get(relation_to_owner, 0)
    parent_id = int(parent_member_id) if parent_member_id else None

    by = None
    if birth_year and birth_year.strip().isdigit():
        by = max(1800, min(2026, int(birth_year.strip())))
    dy = None
    if deceased_year and deceased_year.strip().isdigit():
        dy = max(1800, min(2026, int(deceased_year.strip())))

    db.update_family_member(
        member_id,
        name=name.strip(),
        relationship=relation_to_owner,
        relation_to_owner=relation_to_owner,
        parent_member_id=parent_id,
        generation=generation,
        spouse_name=spouse_name.strip(),
        bio=bio.strip(),
        deceased=1 if deceased else 0,
        birth_year=by or 0,
        deceased_year=dy or 0,
    )

    return RedirectResponse("/web/family-tree", status_code=303)


@router.post("/family-tree/{member_id}/delete")
async def family_tree_delete(request: Request, member_id: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return RedirectResponse("/web/family-tree", status_code=303)

    # Family role can only delete members they added
    if session.get("role") == "family":
        if member.get("added_by") != session.get("name"):
            return RedirectResponse("/web/family-tree", status_code=303)

    db.delete_family_member(member_id)
    return RedirectResponse("/web/family-tree", status_code=303)


@router.post("/family-tree/{member_id}/claim")
async def family_tree_claim(request: Request, member_id: int):
    """Family member claims their identity — generates a personal access code."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    # Only anonymous family sessions can claim (not already identified)
    if session.get("role") != "family" or session.get("family_member_id"):
        return RedirectResponse("/web/family-tree", status_code=303)

    db = request.app.state.db
    tid = session["tenant_id"]
    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return RedirectResponse("/web/family-tree", status_code=303)

    # Can't claim deceased members or members that already have a code
    if member.get("deceased") or member.get("access_code"):
        return RedirectResponse("/web/family-tree", status_code=303)

    code = db.generate_member_access_code(member_id, tid)
    return RedirectResponse(f"/web/family-tree?claimed={code}&name={member['name']}", status_code=303)


@router.post("/family-tree/{member_id}/generate-code")
async def family_tree_generate_code(request: Request, member_id: int):
    """Owner generates a personal access code for a family member."""
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return RedirectResponse("/web/family-tree", status_code=303)

    if member.get("access_code"):
        return RedirectResponse("/web/family-tree", status_code=303)

    db.generate_member_access_code(member_id, tid)
    return RedirectResponse("/web/family-tree", status_code=303)


@router.post("/family-tree/{member_id}/revoke-code")
async def family_tree_revoke_code(request: Request, member_id: int):
    """Owner revokes a family member's personal access code."""
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return RedirectResponse("/web/family-tree", status_code=303)

    db.revoke_member_access_code(member_id, tid)
    return RedirectResponse("/web/family-tree", status_code=303)


@router.get("/api/family-tree/{member_id}/photos")
async def family_member_photos(request: Request, member_id: int):
    session = await get_web_session(request)
    if not session:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]
    member = db.get_family_member_by_id(member_id)
    if not member or member.get("tenant_id") != tid:
        return JSONResponse({"error": "Not found"}, status_code=404)

    photos = db.get_photos_by_tag(member["name"], tenant_id=tid)
    # Also search by first name if full name has multiple words
    first_name = member["name"].split()[0] if " " in member["name"] else None
    if first_name:
        first_photos = db.get_photos_by_tag(first_name, tenant_id=tid)
        seen_ids = {p["id"] for p in photos}
        for p in first_photos:
            if p["id"] not in seen_ids:
                photos.append(p)
    return JSONResponse({
        "member_name": member["name"],
        "relation": member.get("relation_to_owner") or member.get("relationship") or "",
        "photos": [
            {
                "id": p["id"],
                "filename": p["filename"],
                "caption": p.get("caption") or "",
                "date_taken": p.get("date_taken") or "",
                "story_id": p.get("story_id"),
            }
            for p in photos
        ],
    })


# ── Prayer Requests ──

@router.get("/prayers", response_class=HTMLResponse)
async def prayers_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    requests_list = db.get_prayer_requests(tid, active_only=False)

    return templates.TemplateResponse("prayers.html", {
        "request": request,
        "session": session,
        "prayer_requests": requests_list,
    })


@router.post("/prayers/add")
async def prayers_add(request: Request,
                       name: str = Form(...),
                       prayer_request: str = Form("")):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    db.add_prayer_request(name.strip(), prayer_request.strip() or None, tenant_id=tid)
    return RedirectResponse("/web/prayers", status_code=303)


@router.post("/prayers/{request_id}/delete")
async def prayers_delete(request: Request, request_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_prayer_request(request_id)
    return RedirectResponse("/web/prayers", status_code=303)


# ── Nostalgia Snippets ──

@router.get("/nostalgia", response_class=HTMLResponse)
async def nostalgia_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)
    snippets = db.get_nostalgia_snippets(tid)
    generating = request.query_params.get("generated") == "1"

    # Parse nostalgia profile JSON
    import json
    profile = {}
    if user.get("nostalgia_profile"):
        try:
            profile = json.loads(user["nostalgia_profile"])
        except Exception:
            pass

    return templates.TemplateResponse("nostalgia.html", {
        "request": request,
        "session": session,
        "user": user,
        "snippets": snippets,
        "generating": generating,
        "profile": profile,
    })


@router.post("/nostalgia/profile")
async def nostalgia_profile_save(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    import json
    form = await request.form()
    profile = {
        "kid_type": form.get("kid_type", "").strip(),
        "military": form.get("military", "").strip(),
        "sports": form.get("sports", "").strip(),
        "high_school": form.get("high_school", "").strip(),
        "hangouts": form.get("hangouts", "").strip(),
        "restaurants": form.get("restaurants", "").strip(),
        "cars": form.get("cars", "").strip(),
        "jobs": form.get("jobs", "").strip(),
        "extra_notes": form.get("extra_notes", "").strip(),
    }
    # Remove empty values
    profile = {k: v for k, v in profile.items() if v}

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)

    conn = db._get_connection()
    try:
        conn.execute(
            "UPDATE user_profiles SET nostalgia_profile = ? WHERE id = ?",
            (json.dumps(profile), user["id"])
        )
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse("/web/nostalgia", status_code=303)


@router.post("/nostalgia/generate")
async def nostalgia_generate(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)

    hometown = user.get("hometown", "")
    birth_year = user.get("birth_year")
    familiar_name = user.get("familiar_name") or user.get("name") or "the owner"

    if not hometown or not birth_year:
        return RedirectResponse("/web/nostalgia", status_code=303)

    current_year = 2026
    teen_start = birth_year + 13
    teen_end = birth_year + 19

    # Load nostalgia profile
    import json as _json
    profile = {}
    if user.get("nostalgia_profile"):
        try:
            profile = _json.loads(user["nostalgia_profile"])
        except Exception:
            pass

    # Build personality/background context
    background_lines = []
    kid_type_labels = {
        "jock": "a jock / sports kid", "nerd": "a bookworm / nerd", "burnout": "a burnout / rebel",
        "country": "a country kid / farm life", "church": "a church kid", "gearhead": "a gearhead / car enthusiast",
        "band": "a band kid / musician", "hunter": "a hunter / outdoorsman", "worker": "a working kid who had jobs early",
        "troublemaker": "a troublemaker / class clown", "social": "a social butterfly / popular kid",
        "quiet": "a quiet kid who kept to themselves", "creative": "a creative / artistic kid",
        "military_brat": "a military brat who moved around",
    }
    if profile.get("kid_type"):
        background_lines.append(f"They were {kid_type_labels.get(profile['kid_type'], profile['kid_type'])} growing up.")
    if profile.get("military"):
        mil_labels = {"army": "the Army", "navy": "the Navy", "marines": "the Marines", "air_force": "the Air Force",
                      "coast_guard": "the Coast Guard", "national_guard": "the National Guard",
                      "drafted": "the draft (Vietnam era)", "reserves": "the Reserves"}
        background_lines.append(f"They served in {mil_labels.get(profile['military'], profile['military'])}.")
    if profile.get("sports"):
        background_lines.append(f"Sports: {profile['sports']}.")
    if profile.get("high_school"):
        background_lines.append(f"High school: {profile['high_school']}.")
    if profile.get("hangouts"):
        background_lines.append(f"Hangout spots: {profile['hangouts']}.")
    if profile.get("restaurants"):
        background_lines.append(f"Restaurants/diners they loved: {profile['restaurants']}.")
    if profile.get("cars"):
        background_lines.append(f"Cars they drove or loved: {profile['cars']}.")
    if profile.get("jobs"):
        background_lines.append(f"Jobs/work: {profile['jobs']}.")
    if profile.get("extra_notes"):
        background_lines.append(f"Other details: {profile['extra_notes']}.")

    background_section = "\n".join(background_lines) if background_lines else "No additional background provided."

    # Build category list dynamically based on profile
    categories = []
    categories.append(f'1. "hometown" - Roads, landmarks, parks, and places specific to {hometown}. Reference actual streets, neighborhoods, and geography.')
    if profile.get("sports") or profile.get("high_school"):
        categories.append(f'2. "sports" - Sports they played or watched, high school games, rivalries, coaches, Friday night lights, state tournaments.')
    else:
        categories.append(f'2. "sports" - Popular sports and local teams from {hometown} in the {teen_start//10*10}s-{teen_end//10*10}s era.')
    if profile.get("cars"):
        categories.append(f'3. "cars" - Cruising, drag racing, car shows, fixing up cars, drive-ins, the cars of the {teen_start//10*10}s-{teen_end//10*10}s.')
    else:
        categories.append(f'3. "cars" - Iconic cars of the {teen_start//10*10}s-{teen_end//10*10}s, cruising culture, gas stations, drive-ins.')
    categories.append(f'4. "music" - Songs, artists, bands, jukeboxes, and radio from the {teen_start//10*10}s-{teen_end//10*10}s.')
    categories.append(f'5. "food" - Foods, recipes, restaurants, diners, snacks, and kitchen memories from that era and {hometown}.')
    categories.append(f'6. "culture" - Movies, TV shows, world events, fashion, and fads from their youth.')
    categories.append(f'7. "childhood" - Games, outdoor adventures, neighborhood life, school, and daily routines for kids in that era.')
    if profile.get("military"):
        categories.append(f'8. "military" - Military service memories, boot camp, the draft, coming home, veteran life, buddies from service.')
    if profile.get("jobs"):
        categories.append(f'9. "work" - First jobs, work ethic, paychecks, bosses, coworkers, the hustle of making a living back then.')

    cat_count = len(categories)
    snippets_per_cat = 3 if cat_count >= 7 else 5
    total_snippets = cat_count * snippets_per_cat

    categories_text = "\n".join(categories)

    # Build learning context from existing + deleted snippets
    existing_snippets = db.get_nostalgia_snippets(tid)
    deleted_snippets = db.get_nostalgia_deleted(tid)
    is_first_gen = len(existing_snippets) == 0

    confirmed_lines = []
    kept_lines = []
    for s in existing_snippets:
        if s.get("original_text") and s["original_text"] != s["text"]:
            # User edited this — it's a confirmed correction
            confirmed_lines.append(f'- [{s["category"]}] CORRECTED from "{s["original_text"]}" TO "{s["text"]}"')
        else:
            kept_lines.append(f'- [{s["category"]}] {s["text"]}')

    deleted_lines = [f'- [{d["category"]}] {d["text"]}' for d in deleted_snippets[:30]]

    learning_section = ""
    if confirmed_lines or kept_lines or deleted_lines:
        learning_section = "\n\nLEARNING FROM USER FEEDBACK:"
        if confirmed_lines:
            learning_section += f"\n\nUSER-CORRECTED FACTS (treat these as GROUND TRUTH — use these names, places, and details in new snippets):\n" + "\n".join(confirmed_lines)
        if kept_lines:
            learning_section += f"\n\nKEPT SNIPPETS (user liked these — generate more in similar themes, but don't repeat them):\n" + "\n".join(kept_lines[:20])
        if deleted_lines:
            learning_section += f"\n\nDELETED SNIPPETS (user rejected these — AVOID similar topics, names, or tones):\n" + "\n".join(deleted_lines)

    if is_first_gen:
        snippets_per_cat = 3 if cat_count >= 7 else 5
    else:
        snippets_per_cat = 2  # Fewer per batch when adding more

    total_snippets = cat_count * snippets_per_cat

    prompt = f"""You are creating nostalgic conversation snippets for an elderly person named {familiar_name}.
They were born in {birth_year} and grew up in {hometown}.
Their teen years were roughly {teen_start}-{teen_end}.

PERSONAL BACKGROUND:
{background_section}
{learning_section}

Generate exactly {total_snippets} NEW short nostalgia snippets (2-3 sentences each, 20-40 words).
{snippets_per_cat} snippets per category:

{categories_text}

IMPORTANT RULES:
- Use the personal background above to make snippets SPECIFIC to this person — reference their actual hangouts, restaurants, cars, sports, school by name when provided
- If the user corrected a name or detail (see CORRECTED FACTS above), ALWAYS use the corrected version — never the original
- Do NOT repeat any kept snippets — generate completely new ones on different specific details
- Do NOT generate anything similar to deleted snippets — the user doesn't want those topics
- Search your knowledge for real historical details: actual restaurants that existed in {hometown}, real street names, real local events, newspaper-worthy moments from that era
- Be warm and conversational, as if a friendly parrot companion is reminiscing with them
- Start with phrases like "Hey {familiar_name}, remember when...", "Did you know...", "Back in the day..."
- Be historically accurate for the time period and location
- Be TTS-friendly: no abbreviations, no special characters, spell out numbers
- Each variation must cover DIFFERENT specific details — no repetition
- If they had a specific car, mention it. If they hung out at a specific place, reference it. Make it PERSONAL.

Return ONLY a JSON array of objects: [{{"category": "hometown", "variation": 1, "text": "..."}}, ...]
All {total_snippets} objects, nothing else."""

    try:
        followup_gen = request.app.state.followup_gen
        response = followup_gen._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.9,
        )
        import json
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        snippets = json.loads(raw)
        if isinstance(snippets, list) and len(snippets) > 0:
            db.save_nostalgia_snippets(tid, snippets, append=not is_first_gen)
            logger.info(f"Generated {len(snippets)} nostalgia snippets for tenant {tid} (append={not is_first_gen})")
    except Exception as e:
        logger.error(f"Nostalgia generation failed: {e}")

    return RedirectResponse("/web/nostalgia?generated=1", status_code=303)


@router.post("/nostalgia/{snippet_id}/edit")
async def nostalgia_edit(request: Request, snippet_id: int, text: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.update_nostalgia_snippet(snippet_id, text.strip())
    return RedirectResponse("/web/nostalgia", status_code=303)


@router.post("/nostalgia/{snippet_id}/delete")
async def nostalgia_delete(request: Request, snippet_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_nostalgia_snippet(snippet_id)
    return RedirectResponse("/web/nostalgia", status_code=303)


# ── Story Narratives (cached GPT stories) ──

@router.get("/narratives", response_class=HTMLResponse)
async def narratives_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    filter_status = request.query_params.get("filter", "all")
    if filter_status in ("draft", "kept"):
        narratives = db.get_narratives(tid, status=filter_status)
    else:
        narratives = db.get_narratives(tid)

    return templates.TemplateResponse("narratives.html", {
        "request": request,
        "session": session,
        "narratives": narratives,
        "filter": filter_status,
    })


@router.post("/narratives/{narrative_id}/keep")
async def narrative_keep(request: Request, narrative_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    form = await request.form()
    edited_text = form.get("narrative", "").strip()
    db = request.app.state.db
    if edited_text:
        db.update_narrative(narrative_id, narrative=edited_text, status="kept")
    else:
        db.update_narrative(narrative_id, status="kept")
    return RedirectResponse("/web/narratives", status_code=303)


@router.post("/narratives/{narrative_id}/unkeep")
async def narrative_unkeep(request: Request, narrative_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.update_narrative(narrative_id, status="draft")
    return RedirectResponse("/web/narratives", status_code=303)


@router.post("/narratives/{narrative_id}/delete")
async def narrative_delete(request: Request, narrative_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_narrative(narrative_id)
    return RedirectResponse("/web/narratives", status_code=303)


# ── Device Management ──

@router.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    if session.get("is_admin"):
        devices = db.get_all_devices()
    else:
        devices = db.get_devices_by_tenant(tid)

    # Check for flash messages
    new_device_id = request.query_params.get("new_device_id")
    new_claim_code = request.query_params.get("new_claim_code")
    claim_error = request.query_params.get("claim_error")
    claim_success = request.query_params.get("claim_success")

    return templates.TemplateResponse("devices.html", {
        "request": request,
        "session": session,
        "devices": devices,
        "new_device_id": new_device_id,
        "new_claim_code": new_claim_code,
        "claim_error": claim_error,
        "claim_success": claim_success,
    })


@router.post("/devices/add")
async def device_add(request: Request, device_name: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Generate unique device_id and API key
    device_id = f"polly-{uuid.uuid4().hex[:8]}"
    api_key = generate_api_key()

    if session.get("is_admin"):
        # Admin-created devices are unassigned until customer claims
        db.register_device(device_id, None, name=device_name, api_key=api_key)
        claim_code = db.generate_claim_code(device_id)
    else:
        db.register_device(device_id, tid, name=device_name, api_key=api_key)
        claim_code = None

    redirect_url = f"/web/devices?new_device_id={device_id}"
    if claim_code:
        redirect_url += f"&new_claim_code={claim_code}"
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/devices/setup-card-preview", response_class=HTMLResponse)
async def device_setup_card_preview(request: Request):
    """Preview setup card with sample data (admin only)."""
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect
    return templates.TemplateResponse("setup_card.html", {
        "request": request,
        "device_name": "Grandma's Polly",
        "claim_code": "324238",
    })


@router.get("/devices/{device_id}/setup-card", response_class=HTMLResponse)
async def device_setup_card(request: Request, device_id: str):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    db = request.app.state.db
    device = db.get_device(device_id)
    if not device or not device.get("claim_code"):
        return RedirectResponse("/web/devices", status_code=303)

    return templates.TemplateResponse("setup_card.html", {
        "request": request,
        "device_name": device.get("name") or device_id,
        "claim_code": device["claim_code"],
    })


@router.post("/devices/{device_id}/delete")
async def device_delete(request: Request, device_id: str):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_device(device_id, session["tenant_id"], is_admin=session.get("is_admin", False))
    return RedirectResponse("/web/devices", status_code=303)


@router.post("/devices/claim")
async def device_claim(request: Request, claim_code: str = Form(...)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    code = claim_code.strip()

    if not code or len(code) != 6 or not code.isdigit():
        return RedirectResponse(
            "/web/devices?claim_error=Please+enter+a+valid+6-digit+claim+code",
            status_code=303)

    device = db.claim_device(code, tid)
    if not device:
        return RedirectResponse(
            "/web/devices?claim_error=Invalid+or+already+claimed+code",
            status_code=303)

    name = device.get("name") or device["device_id"]
    return RedirectResponse(
        f"/web/devices?claim_success={name}",
        status_code=303)


# ── Legacy Book ──

BUCKET_LABELS = {
    "ordinary_world": "Everyday Life",
    "call_to_adventure": "Turning Points",
    "crossing_threshold": "Big Decisions",
    "trials_allies_enemies": "Challenges & Helpers",
    "transformation": "How You Changed",
    "return_with_knowledge": "Wisdom & Lessons",
}

PHASE_LABELS = {
    "childhood": "Childhood",
    "adolescence": "Adolescence",
    "young_adult": "Young Adult",
    "adult": "Adult",
    "midlife": "Midlife",
    "elder": "Elder",
    "reflection": "Reflection",
}

BUCKET_TARGETS = {
    "ordinary_world": 15,
    "call_to_adventure": 10,
    "crossing_threshold": 10,
    "trials_allies_enemies": 15,
    "transformation": 10,
    "return_with_knowledge": 10,
}


@router.get("/book", response_class=HTMLResponse)
async def book_overview(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    book_builder = request.app.state.book_builder
    narrative_arc = request.app.state.narrative_arc
    engagement = request.app.state.engagement

    progress = book_builder.get_book_progress(tenant_id=tid)
    chapters = book_builder.generate_chapter_outline(tenant_id=tid)

    # Check which chapters already have drafts
    existing_drafts = {d["chapter_number"]: d for d in db.get_chapter_drafts(tenant_id=tid)}
    for ch in chapters:
        ch["bucket_label"] = BUCKET_LABELS.get(ch["bucket"], ch["bucket"])
        ch["phase_label"] = PHASE_LABELS.get(ch["life_phase"], ch["life_phase"])
        if ch["chapter_number"] in existing_drafts:
            ch["status"] = "has_draft"

    # Arc coverage
    bucket_coverage = narrative_arc.get_bucket_coverage(tenant_id=tid)
    arc_coverage = {}
    for bucket_key, count in bucket_coverage.items():
        arc_coverage[bucket_key] = {
            "label": BUCKET_LABELS.get(bucket_key, bucket_key),
            "count": count,
            "target": BUCKET_TARGETS.get(bucket_key, 10),
        }

    # Life phase coverage
    phase_cov = narrative_arc.get_life_phase_coverage(tenant_id=tid)
    phase_coverage = {}
    for phase_key, count in phase_cov.items():
        phase_coverage[phase_key] = {
            "label": PHASE_LABELS.get(phase_key, phase_key),
            "count": count,
        }

    gap_report = engagement.get_gap_report(tenant_id=tid)

    return templates.TemplateResponse("book.html", {
        "request": request,
        "session": session,
        "progress": progress,
        "chapters": chapters,
        "arc_coverage": arc_coverage,
        "phase_coverage": phase_coverage,
        "gap_report": gap_report,
    })


@router.get("/book/chapters", response_class=HTMLResponse)
async def book_chapters_list(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    book_builder = request.app.state.book_builder

    chapters = book_builder.generate_chapter_outline(tenant_id=tid)
    existing_drafts = {d["chapter_number"]: d for d in db.get_chapter_drafts(tenant_id=tid)}

    for ch in chapters:
        ch["bucket_label"] = BUCKET_LABELS.get(ch["bucket"], ch["bucket"])
        ch["phase_label"] = PHASE_LABELS.get(ch["life_phase"], ch["life_phase"])
        if ch["chapter_number"] in existing_drafts:
            ch["status"] = "has_draft"

    return templates.TemplateResponse("book_chapters.html", {
        "request": request,
        "session": session,
        "chapters": chapters,
    })


@router.get("/book/chapters/{chapter_num}", response_class=HTMLResponse)
async def book_chapter_detail(request: Request, chapter_num: int):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    book_builder = request.app.state.book_builder

    chapters = book_builder.generate_chapter_outline(tenant_id=tid)
    chapter = None
    for ch in chapters:
        if ch["chapter_number"] == chapter_num:
            chapter = ch
            break

    if not chapter:
        return RedirectResponse("/web/book/chapters", status_code=302)

    chapter["bucket_label"] = BUCKET_LABELS.get(chapter["bucket"], chapter["bucket"])
    chapter["phase_label"] = PHASE_LABELS.get(chapter["life_phase"], chapter["life_phase"])

    # Fetch full memories with audio keys from linked stories
    memories = []
    for mid in chapter.get("memory_ids", []):
        mem = db.get_memory_by_id(mid, tenant_id=tid)
        if mem:
            # Look up audio from linked story
            if mem.get("story_id"):
                story = db.get_story_by_id(mem["story_id"], tenant_id=tid)
                mem["audio_key"] = story.get("audio_s3_key") if story else None
            else:
                mem["audio_key"] = None
            memories.append(mem)

    # Check for existing draft
    existing_drafts = db.get_chapter_drafts(tenant_id=tid)
    draft = None
    for d in existing_drafts:
        if d["chapter_number"] == chapter_num:
            draft = d
            break

    if draft:
        chapter["status"] = "has_draft"

    ai_available = getattr(request.app.state, "followup_gen", None)
    ai_available = ai_available and ai_available.available if ai_available else False

    # Get generated song for this chapter
    song = None
    try:
        import sqlite3 as _sq
        _conn = db._get_connection()
        _conn.row_factory = _sq.Row
        song_row = _conn.execute(
            "SELECT * FROM song_briefs WHERE tenant_id = ? AND chapter_number = ? ORDER BY id DESC LIMIT 1",
            (tid, chapter_num)
        ).fetchone()
        if song_row:
            song = dict(song_row)
            try:
                song["lyrics"] = json.loads(song.get("lyrics_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                song["lyrics"] = {}
    except Exception:
        pass

    message = request.query_params.get("msg")

    return templates.TemplateResponse("book_chapter_detail.html", {
        "request": request,
        "session": session,
        "chapter": chapter,
        "memories": memories,
        "draft": draft,
        "song": song,
        "ai_available": ai_available,
        "message": message,
    })


@router.post("/book/chapters/{chapter_num}/generate")
async def book_chapter_generate(request: Request, chapter_num: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Check chapter limit (trial/basic get 2 preview chapters)
    from core.subscription import get_tier_limits, get_subscription
    sub = get_subscription(db, tid)
    limits = get_tier_limits(sub["tier"])
    if sub["status"] in ("expired", "canceled"):
        return RedirectResponse("/web/pricing?msg=Subscribe to generate chapters.", status_code=303)
    if chapter_num > limits["book_preview_chapters"]:
        return RedirectResponse("/web/pricing?msg=Upgrade to Polly Legacy to generate all chapters.", status_code=303)

    book_builder = request.app.state.book_builder

    chapters = book_builder.generate_chapter_outline(tenant_id=tid)
    chapter = None
    for ch in chapters:
        if ch["chapter_number"] == chapter_num:
            chapter = ch
            break

    if not chapter:
        return RedirectResponse("/web/book/chapters", status_code=302)

    # Gather previous chapter summaries for continuity
    existing_drafts = db.get_chapter_drafts(tenant_id=tid)
    previous_summaries = []
    for d in sorted(existing_drafts, key=lambda x: x.get("chapter_number", 0)):
        if d.get("chapter_number", 0) < chapter_num and d.get("summary"):
            previous_summaries.append(d["summary"])

    # Generate AI draft with timeline + photo placement
    content = await book_builder.generate_chapter_draft(
        chapter, tenant_id=tid,
        previous_summaries=previous_summaries if previous_summaries else None,
    )

    if content:
        import json as _json
        # Delete any existing draft for this chapter so we don't pile up stale copies
        conn = db._get_connection()
        conn.execute(
            "DELETE FROM chapter_drafts WHERE chapter_number = ? AND tenant_id = ?",
            (chapter_num, tid)
        )
        conn.commit()

        db.save_chapter_draft(
            chapter_number=chapter_num,
            title=chapter["title"],
            bucket=chapter["bucket"],
            life_phase=chapter["life_phase"],
            memory_ids=_json.dumps(chapter.get("memory_ids", [])),
            content=content,
            tenant_id=tid,
        )

        # Generate and save summary for continuity with later chapters
        summary = await book_builder.generate_chapter_summary(content)
        if summary:
            drafts_after = db.get_chapter_drafts(tenant_id=tid)
            for d in drafts_after:
                if d.get("chapter_number") == chapter_num:
                    db.update_chapter_summary(d["id"], summary)
                    break
        msg = "Draft generated successfully!"
    else:
        msg = "Could not generate draft. Make sure OPENAI_API_KEY is set."

    return RedirectResponse(
        f"/web/book/chapters/{chapter_num}?msg={msg}",
        status_code=303,
    )


@router.post("/book/chapters/{chapter_num}/save")
async def book_chapter_save(request: Request, chapter_num: int,
                             content: str = Form("")):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Update existing draft content
    conn = db._get_connection()
    try:
        import sqlite3
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT * FROM chapter_drafts WHERE chapter_number = ? AND tenant_id = ?",
            (chapter_num, tid)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE chapter_drafts SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (content, existing["id"])
            )
        else:
            conn.execute("""
                INSERT INTO chapter_drafts (chapter_number, title, bucket, life_phase, memory_ids, content, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chapter_num, f"Chapter {chapter_num}", "", "", "[]", content, tid))
        conn.commit()
    finally:
        if not db._conn:
            conn.close()

    return RedirectResponse(
        f"/web/book/chapters/{chapter_num}?msg=Changes saved.",
        status_code=303,
    )


@router.get("/book/export")
async def book_export_pdf(request: Request):
    """Generate and download the legacy book as a print-ready 6x9 PDF."""
    from fastapi.responses import Response

    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    gate = _gate_feature(db, session, "book_export",
                         "Upgrade to Polly Legacy to export your book as a print-ready PDF.")
    if gate:
        return gate
    tid = session["tenant_id"]
    book_builder = request.app.state.book_builder

    # Get speaker name from user profile
    user = db.get_or_create_user(tenant_id=tid)
    speaker_name = user.get("name", "")

    # Get optional params from query string
    title = request.query_params.get("title") or None
    subtitle = request.query_params.get("subtitle") or None
    dedication = request.query_params.get("dedication") or None
    include_qr = request.query_params.get("qr", "0") == "1"

    from core.book_pdf import LegacyBookPDF
    pdf_gen = LegacyBookPDF(db, book_builder, tenant_id=tid)

    try:
        pdf_bytes = pdf_gen.generate(
            speaker_name=speaker_name,
            book_title=title,
            subtitle=subtitle,
            dedication=dedication,
            include_qr_codes=include_qr,
        )
    except Exception as e:
        logger.error(f"PDF export failed: {e}")
        return RedirectResponse(
            f"/web/book?msg=PDF generation failed: {e}",
            status_code=303,
        )

    safe_name = speaker_name.replace(" ", "_").lower() if speaker_name else "legacy"
    filename = f"polly_book_{safe_name}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Song Generation ──

@router.post("/book/chapters/{chapter_num}/generate-song")
async def generate_chapter_song(request: Request, chapter_num: int):
    """Generate song lyrics from a chapter draft using the GPT pipeline."""
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    # Get the chapter draft
    drafts = db.get_chapter_drafts(tenant_id=tid)
    draft = None
    for d in drafts:
        if d.get("chapter_number") == chapter_num:
            draft = d
            break

    if not draft or not draft.get("content"):
        return RedirectResponse(
            f"/web/book/chapters/{chapter_num}?msg=Generate a chapter draft first.",
            status_code=303)

    # Get speaker name
    user = db.get_or_create_user(tenant_id=tid)
    speaker_name = user.get("name", "Someone")

    # Get pronunciation guide for phonetic lyrics
    pronunciations = db.get_pronunciations(tid)

    try:
        from core.song_pipeline import chapter_to_song
        import asyncio

        result = await asyncio.to_thread(
            chapter_to_song,
            chapter_text=draft["content"],
            chapter_title=draft.get("title", f"Chapter {chapter_num}"),
            person_name=speaker_name,
            genre_preference="auto",
            generate_audio_file=False,
        )

        # Apply phonetic replacements to lyrics for audio prompt
        lyrics_display = result["lyrics"]
        lyrics_audio = dict(result["lyrics"])  # copy for phonetic version
        for pron in pronunciations:
            word = pron.get("word", "")
            phonetic = pron.get("phonetic", "")
            if word and phonetic:
                for section in lyrics_audio:
                    if isinstance(lyrics_audio[section], str):
                        lyrics_audio[section] = lyrics_audio[section].replace(word, phonetic)

        # Save to database
        conn = db._get_connection()
        # Delete old song for this chapter
        conn.execute(
            "DELETE FROM song_briefs WHERE tenant_id = ? AND chapter_number = ?",
            (tid, chapter_num))
        conn.execute("""
            INSERT INTO song_briefs (tenant_id, chapter_number, chapter_title,
                song_title, genre, jungian_stage, lyrics_json, style_prompt, essence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tid, chapter_num, draft.get("title", ""),
              result["song_title"], result["genre"], result["jungian_stage"],
              json.dumps(lyrics_display), result["style_prompt"],
              json.dumps(result.get("song_brief", {}).get("essence", {}))))
        conn.commit()

        msg = f"Song generated: {result['song_title']} ({result['genre']})"
    except Exception as e:
        logger.error(f"Song generation failed: {e}")
        msg = f"Song generation failed: {e}"

    return RedirectResponse(
        f"/web/book/chapters/{chapter_num}?msg={msg}",
        status_code=303)


@router.post("/book/chapters/{chapter_num}/save-song")
async def save_chapter_song(request: Request, chapter_num: int):
    """Save edited song lyrics."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]

    form = await request.form()
    song_title = form.get("song_title", "")
    genre = form.get("genre", "")
    style_prompt = form.get("style_prompt", "")

    lyrics = {
        "verse1": form.get("lyrics_verse1", ""),
        "chorus": form.get("lyrics_chorus", ""),
        "verse2": form.get("lyrics_verse2", ""),
        "bridge": form.get("lyrics_bridge", ""),
        "outro": form.get("lyrics_outro", ""),
    }

    conn = db._get_connection()
    conn.execute("""
        UPDATE song_briefs SET song_title = ?, genre = ?, style_prompt = ?, lyrics_json = ?
        WHERE tenant_id = ? AND chapter_number = ?
    """, (song_title, genre, style_prompt, json.dumps(lyrics), tid, chapter_num))
    conn.commit()

    return RedirectResponse(
        f"/web/book/chapters/{chapter_num}?msg=Song lyrics saved.",
        status_code=303)


@router.get("/book/album", response_class=HTMLResponse)
async def book_album_page(request: Request):
    """View all generated songs as an album."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)
    speaker_name = user.get("name", "Someone")

    # Get all songs for this tenant
    conn = db._get_connection()
    import sqlite3 as _sq
    conn.row_factory = _sq.Row
    songs = conn.execute(
        "SELECT * FROM song_briefs WHERE tenant_id = ? ORDER BY chapter_number",
        (tid,)
    ).fetchall()
    songs = [dict(s) for s in songs]

    # Parse lyrics JSON
    for s in songs:
        try:
            s["lyrics"] = json.loads(s.get("lyrics_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            s["lyrics"] = {}

    message = request.query_params.get("msg")

    return templates.TemplateResponse("book_album.html", {
        "request": request,
        "session": session,
        "songs": songs,
        "speaker_name": speaker_name,
        "message": message,
    })


@router.post("/book/album/generate-all")
async def generate_all_songs(request: Request):
    """Generate songs for all chapters at once."""
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    user = db.get_or_create_user(tenant_id=tid)
    speaker_name = user.get("name", "Someone")
    book_builder = request.app.state.book_builder

    chapters = book_builder.generate_chapter_outline(tenant_id=tid)
    drafts = {d["chapter_number"]: d for d in db.get_chapter_drafts(tenant_id=tid)}

    from core.song_pipeline import chapter_to_song
    import asyncio

    generated = 0
    for ch in chapters:
        cn = ch["chapter_number"]
        draft = drafts.get(cn)
        if not draft or not draft.get("content"):
            continue

        try:
            result = await asyncio.to_thread(
                chapter_to_song,
                chapter_text=draft["content"],
                chapter_title=draft.get("title", f"Chapter {cn}"),
                person_name=speaker_name,
                genre_preference="auto",
                generate_audio_file=False,
            )

            conn = db._get_connection()
            conn.execute("DELETE FROM song_briefs WHERE tenant_id = ? AND chapter_number = ?", (tid, cn))
            conn.execute("""
                INSERT INTO song_briefs (tenant_id, chapter_number, chapter_title,
                    song_title, genre, jungian_stage, lyrics_json, style_prompt, essence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (tid, cn, draft.get("title", ""),
                  result["song_title"], result["genre"], result["jungian_stage"],
                  json.dumps(result["lyrics"]), result["style_prompt"],
                  json.dumps(result.get("song_brief", {}).get("essence", {}))))
            conn.commit()
            generated += 1
        except Exception as e:
            logger.error(f"Song generation failed for ch{cn}: {e}")

    return RedirectResponse(
        f"/web/book/album?msg=Generated {generated} songs!",
        status_code=303)


# ── Prayer Recordings ──

@router.get("/prayer-recordings", response_class=HTMLResponse)
async def prayer_recordings_page(request: Request):
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    recordings = db.get_prayer_recordings(tid)
    message = request.query_params.get("msg")

    return templates.TemplateResponse("prayer_recordings.html", {
        "request": request,
        "session": session,
        "recordings": recordings,
        "message": message,
    })


@router.post("/prayer-recordings/record")
async def prayer_recording_save(request: Request):
    """Record a prayer/blessing from the phone."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    db = request.app.state.db
    tid = session["tenant_id"]

    form = await request.form()
    audio = form.get("audio")
    speaker_name = form.get("speaker_name", "")
    category = form.get("category", "general")
    title = form.get("title", "")
    schedule_time = form.get("schedule_time", "")
    schedule_days = form.get("schedule_days", "0,1,2,3,4,5,6")

    if not audio:
        return JSONResponse({"error": "No audio received"}, status_code=400)

    audio_data = await audio.read()
    if len(audio_data) < 1000:
        return JSONResponse({"error": "Recording too short"}, status_code=400)

    # Convert webm to wav if needed
    content_type = audio.content_type or ""
    if "webm" in content_type or "ogg" in content_type:
        # Browser sends webm — convert via ffmpeg if available, otherwise save as-is
        try:
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
                tmp_in.write(audio_data)
                tmp_in_path = tmp_in.name
            tmp_out_path = tmp_in_path.replace(".webm", ".wav")
            result = subprocess.run(
                ["ffmpeg", "-i", tmp_in_path, "-ar", "16000", "-ac", "1", "-y", tmp_out_path],
                capture_output=True, timeout=30
            )
            if result.returncode == 0:
                with open(tmp_out_path, "rb") as f:
                    wav_bytes = f.read()
            else:
                # ffmpeg not available — save raw webm and note it
                wav_bytes = audio_data
            # Cleanup
            try:
                os.unlink(tmp_in_path)
                os.unlink(tmp_out_path)
            except Exception:
                pass
        except Exception:
            wav_bytes = audio_data
    elif "octet-stream" in content_type or "raw" in content_type:
        wav_bytes = _build_wav(audio_data, sample_rate=16000)
    else:
        wav_bytes = audio_data if audio_data[:4] == b'RIFF' else audio_data

    # Save audio file
    recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    filename = f"prayer_{tid}_{uuid.uuid4().hex[:8]}.wav"
    filepath = os.path.join(recordings_dir, filename)
    with open(filepath, "wb") as f:
        f.write(wav_bytes)

    # Transcribe
    transcript = ""
    try:
        transcriber = request.app.state.transcriber
        if wav_bytes[:4] == b'RIFF':
            transcript = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
    except Exception:
        pass

    # Save to database
    rec_id = db.save_prayer_recording(
        tenant_id=tid,
        speaker_name=speaker_name,
        category=category,
        title=title or f"{speaker_name}'s {category}",
        audio_filename=filename,
        transcript=transcript,
        schedule_time=schedule_time if schedule_time else None,
        schedule_days=schedule_days,
    )

    return JSONResponse({"success": True, "id": rec_id, "transcript": transcript or ""})


@router.post("/prayer-recordings/{recording_id}/delete")
async def prayer_recording_delete(request: Request, recording_id: int):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_prayer_recording(recording_id)
    return RedirectResponse("/web/prayer-recordings?msg=Recording deleted.", status_code=303)


@router.post("/prayer-recordings/{recording_id}/schedule")
async def prayer_recording_schedule(request: Request, recording_id: int,
                                      schedule_time: str = Form(""),
                                      schedule_days: str = Form("0,1,2,3,4,5,6"),
                                      active: int = Form(1)):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.update_prayer_recording_schedule(
        recording_id,
        schedule_time=schedule_time if schedule_time else None,
        schedule_days=schedule_days,
        active=active,
    )
    return RedirectResponse("/web/prayer-recordings?msg=Schedule updated.", status_code=303)


# ── Owner's Guide ──

@router.get("/guide")
async def owners_guide(request: Request):
    """Owner's Guide — opens PDF in browser's native viewer with back support."""
    from fastapi.responses import FileResponse
    import os

    pdf_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "static", "Polly_User_Guide.pdf"
    )
    # Serve inline so the browser's own PDF viewer handles it (scrollable, zoomable)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=Polly_User_Guide.pdf"},
    )


# ── Photo Listen Page (multi-voice) ──

@router.get("/photo-listen/{photo_id}", response_class=HTMLResponse)
async def photo_listen_page(request: Request, photo_id: int):
    """Landing page for book QR codes — shows photo + all voice recordings."""
    db = request.app.state.db

    photo = db.get_photo_by_id(photo_id)
    if not photo:
        return HTMLResponse("<h2>Photo not found</h2>", status_code=404)

    # Scope story query to the photo's tenant
    photo_tenant = photo.get("tenant_id")
    conn = db._get_connection()
    try:
        import sqlite3
        conn.row_factory = sqlite3.Row
        stories = conn.execute(
            "SELECT s.id, s.audio_s3_key, s.question_text, "
            "COALESCE(s.corrected_transcript, s.transcript) as transcript, "
            "m.speaker FROM stories s "
            "LEFT JOIN memories m ON m.story_id = s.id "
            "WHERE s.photo_id = ? AND s.tenant_id = ? AND s.audio_s3_key IS NOT NULL ORDER BY s.id",
            (photo_id, photo_tenant)
        ).fetchall()
        stories = [dict(s) for s in stories]
    finally:
        if not db._conn:
            conn.close()

    caption = photo.get("caption") or "Family Photo"
    caption_safe = caption.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    filename = photo.get("filename", "")

    # Build audio player blocks
    players_html = ""
    for s in stories:
        speaker = s.get("speaker") or "Someone"
        speaker_safe = speaker.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        transcript = (s.get("transcript") or "")[:120]
        transcript_safe = transcript.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        audio_key = s.get("audio_s3_key", "")
        players_html += f"""
        <div style="border-top: 1px solid #eee; padding: 16px 0;">
            <p style="font-weight: 600; font-size: 15px; color: #1a1a1a; margin: 0 0 4px;">{speaker_safe}</p>
            <p style="font-size: 12px; color: #888; margin: 0 0 10px; font-style: italic;">{transcript_safe}{"..." if len(transcript) >= 120 else ""}</p>
            <audio controls preload="auto" style="width: 100%;">
                <source src="/static/recordings/{audio_key}" type="audio/wav">
            </audio>
            <a href="/web/audio/download/{audio_key}" style="display: inline-block; margin-top: 8px; font-size: 12px; color: #059669; text-decoration: none;">Save this recording</a>
        </div>"""

    if not players_html:
        players_html = '<p style="color: #999; text-align: center; padding: 20px;">No recordings yet.</p>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{caption_safe} - Polly Connect</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%);
               margin: 0; padding: 20px; min-height: 100vh; }}
        .card {{ background: white; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.1);
                 max-width: 500px; margin: 0 auto; overflow: hidden; }}
        .photo {{ width: 100%; max-height: 300px; object-fit: cover; }}
        .content {{ padding: 20px; }}
        .logo {{ width: 60px; height: 60px; display: block; margin: 0 auto 12px; }}
        h1 {{ font-size: 20px; color: #1a1a1a; margin: 0 0 4px; text-align: center; }}
        .count {{ font-size: 13px; color: #666; text-align: center; margin-bottom: 8px; }}
        .footer {{ text-align: center; padding: 16px; font-size: 12px; color: #999; }}
        .footer a {{ color: #059669; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/uploads/{filename}" alt="{caption_safe}" class="photo">
        <div class="content">
            <img src="/static/polly_logo.png" alt="Polly" class="logo">
            <h1>{caption_safe}</h1>
            <p class="count">{len(stories)} voice recording{"s" if len(stories) != 1 else ""}</p>
            {players_html}
        </div>
        <div class="footer">Captured with <a href="https://polly-connect.com">Polly Connect</a></div>
    </div>
</body>
</html>""")


# ── Audio Listen & Download ──

@router.get("/listen/{audio_key}", response_class=HTMLResponse)
async def listen_page(request: Request, audio_key: str):
    """Public landing page for QR code scans — plays audio + download button."""
    import os

    safe_key = os.path.basename(audio_key)
    recordings_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "static", "recordings"
    )
    file_path = os.path.join(recordings_dir, safe_key)

    if not os.path.exists(file_path):
        return HTMLResponse("<h2>Recording not found</h2>", status_code=404)

    # Look up who told this story
    db = request.app.state.db
    conn = db._get_connection()
    try:
        import sqlite3 as _sqlite3
        conn.row_factory = _sqlite3.Row
        story = conn.execute(
            "SELECT id, question_text, recorded_at, tenant_id FROM stories WHERE audio_s3_key = ?",
            (safe_key,)
        ).fetchone()
        # Get memory speaker — scoped to same tenant as the story
        speaker = ""
        story_question = ""
        if story:
            story_question = story["question_text"] or ""
            story_tid = story["tenant_id"]
            mem = conn.execute(
                "SELECT speaker FROM memories WHERE story_id = ? AND tenant_id = ?",
                (story["id"], story_tid)
            ).fetchone()
            if mem:
                speaker = mem["speaker"] or ""
    except Exception:
        speaker = ""
        story_question = ""
    finally:
        if not db._conn:
            conn.close()

    title = f"{speaker}'s Voice" if speaker else "A Family Voice"

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Polly Connect</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%);
               margin: 0; padding: 20px; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }}
        .card {{ background: white; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,0.1);
                 padding: 32px; max-width: 400px; width: 100%; text-align: center; }}
        .logo {{ width: 80px; height: 80px; margin-bottom: 8px; }}
        h1 {{ font-size: 22px; color: #1a1a1a; margin: 0 0 4px; }}
        .subtitle {{ font-size: 14px; color: #666; margin-bottom: 24px; }}
        audio {{ width: 100%; margin-bottom: 20px; }}
        .download {{ display: inline-flex; align-items: center; gap: 8px;
                     background: #059669; color: white; padding: 12px 24px;
                     border-radius: 8px; text-decoration: none; font-weight: 600;
                     font-size: 16px; transition: background 0.2s; }}
        .download:hover {{ background: #047857; }}
        .footer {{ margin-top: 24px; font-size: 12px; color: #999; }}
        .footer a {{ color: #059669; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="card">
        <img src="/static/polly_logo.png" alt="Polly" class="logo">
        <h1>{title}</h1>
        <p class="subtitle">{"" if not story_question else story_question}</p>
        <audio controls autoplay preload="auto">
            <source src="/static/recordings/{safe_key}" type="audio/wav">
            Your browser does not support audio playback.
        </audio>
        <a href="/web/audio/download/{safe_key}" class="download">
            <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
            </svg>
            Save to Phone
        </a>
        <p class="footer">Captured with <a href="https://polly-connect.com">Polly Connect</a></p>
    </div>
</body>
</html>""")


@router.get("/audio/download/{audio_key}")
async def download_audio(request: Request, audio_key: str):
    """Download a voice recording WAV file (from QR code or story page)."""
    from fastapi.responses import FileResponse
    import os

    # No login required — QR codes are public links from printed books

    # Sanitize filename to prevent path traversal
    safe_key = os.path.basename(audio_key)
    recordings_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "static", "recordings"
    )
    file_path = os.path.join(recordings_dir, safe_key)

    if not os.path.exists(file_path):
        return RedirectResponse("/web/dashboard?msg=Recording not found", status_code=302)

    return FileResponse(
        path=file_path,
        media_type="audio/wav",
        filename=safe_key,
        headers={"Content-Disposition": f"attachment; filename={safe_key}"},
    )


# ── Subscription & Billing ──

@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    """Pricing page — shows plans and current subscription status."""
    session = await get_web_session(request)
    subscription = None
    if session:
        from core.subscription import get_subscription
        db = request.app.state.db
        subscription = get_subscription(db, session["tenant_id"])

    message = request.query_params.get("msg")
    return templates.TemplateResponse("pricing.html", {
        "request": request,
        "session": session,
        "subscription": subscription,
        "message": message,
    })


@router.post("/subscribe")
async def subscribe(request: Request, tier: str = Form("basic"),
                     interval: str = Form("month")):
    """Start Stripe Checkout for a subscription."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    from core.subscription import create_checkout_session
    db = request.app.state.db
    tid = session["tenant_id"]

    checkout_url = create_checkout_session(
        db, tid, tier, interval,
        success_url="https://polly-connect.com/web/billing?success=1",
        cancel_url="https://polly-connect.com/web/pricing?msg=Checkout canceled",
    )

    if checkout_url:
        return RedirectResponse(checkout_url, status_code=303)

    return RedirectResponse(
        "/web/pricing?msg=Could not start checkout. Please try again.",
        status_code=303,
    )


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """Billing management page."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    from core.subscription import get_subscription
    db = request.app.state.db
    tid = session["tenant_id"]
    subscription = get_subscription(db, tid)

    # Get usage counts
    conn = db._get_connection()
    try:
        stories = conn.execute("SELECT COUNT(*) FROM stories WHERE tenant_id=?", (tid,)).fetchone()[0]
        photos = conn.execute("SELECT COUNT(*) FROM photos WHERE tenant_id=?", (tid,)).fetchone()[0]
        items = conn.execute("SELECT COUNT(*) FROM items WHERE tenant_id=?", (tid,)).fetchone()[0]
        family = conn.execute("SELECT COUNT(*) FROM family_members WHERE tenant_id=?", (tid,)).fetchone()[0]
    except Exception:
        stories = photos = items = family = 0
    finally:
        if not db._conn:
            conn.close()

    message = None
    if request.query_params.get("success"):
        # Sync subscription from Stripe in case webhook hasn't fired yet
        try:
            from core.subscription import _get_stripe
            stripe = _get_stripe()
            if stripe and subscription.get("stripe_customer_id"):
                subs = stripe.Subscription.list(
                    customer=subscription["stripe_customer_id"], limit=1
                )
                if subs.data:
                    sub = subs.data[0]
                    tier = "legacy" if sub.plan.amount >= 1999 else "basic"
                    conn = db._get_connection()
                    conn.execute(
                        "UPDATE tenants SET subscription_tier=?, subscription_status=?, stripe_subscription_id=?, trial_ends_at=NULL WHERE id=?",
                        (tier, sub.status, sub.id, tid)
                    )
                    conn.commit()
                    subscription = get_subscription(db, tid)
        except Exception as e:
            logger.warning(f"Stripe sync on success failed: {e}")
        message = "Subscription activated! Welcome to Polly."

    return templates.TemplateResponse("billing.html", {
        "request": request,
        "session": session,
        "subscription": subscription,
        "usage": {"stories": stories, "photos": photos, "items": items, "family": family},
        "message": message,
    })


@router.post("/billing/portal")
async def billing_portal(request: Request):
    """Redirect to Stripe Customer Portal for payment management."""
    session = await get_web_session(request)
    redirect = require_login(session)
    if redirect:
        return redirect

    from core.subscription import create_billing_portal_session
    db = request.app.state.db
    portal_url = create_billing_portal_session(db, session["tenant_id"])

    if portal_url:
        return RedirectResponse(portal_url, status_code=303)

    return RedirectResponse(
        "/web/billing?msg=Could not open billing portal.",
        status_code=303,
    )


# ── Admin Dashboard (cross-tenant) ──

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    db = request.app.state.db
    stats = db.get_admin_dashboard_stats()
    devices = db.get_admin_device_list()
    intents = db.get_admin_intent_stats(days=7)
    errors = db.get_admin_error_log(limit=50)

    # Add is_online flag for template
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    for d in devices:
        if d.get("last_seen"):
            try:
                ls = datetime.fromisoformat(d["last_seen"])
                d["is_online"] = (now - ls) < timedelta(minutes=5)
            except Exception:
                d["is_online"] = False
        else:
            d["is_online"] = False

    # Milestone alert: time to switch to on-device wake word
    if stats.get("total_devices", 0) >= 20:
        logger.warning(
            f"MILESTONE: {stats['total_devices']} devices registered! "
            "Time to switch to on-device wake word (microWakeWord TFLite on ESP32-S3). "
            "Training data ready in wake-word/. See WAKE_WORD_STATUS.md."
        )

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "session": session,
        "stats": stats,
        "devices": devices,
        "intents": intents,
        "errors": errors,
    })


# ── Firmware OTA Management ──

@router.get("/firmware", response_class=HTMLResponse)
async def firmware_page(request: Request):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    db = request.app.state.db
    tid = session["tenant_id"]
    firmware_versions = db.get_firmware_versions()
    devices = db.get_devices_by_tenant(tid)

    # Enrich devices with update status
    active_versions = {}
    for fw in firmware_versions:
        if fw["is_active"]:
            active_versions[fw["variant"]] = fw["version"]

    for d in devices:
        d = dict(d) if not isinstance(d, dict) else d
        variant = d.get("fw_variant")
        current = d.get("fw_version")
        if variant and current and variant in active_versions:
            active_v = active_versions[variant]
            try:
                cur = tuple(int(x) for x in current.split("."))
                act = tuple(int(x) for x in active_v.split("."))
                d["needs_update"] = act > cur
            except (ValueError, AttributeError):
                d["needs_update"] = False
        else:
            d["needs_update"] = False

    message = request.query_params.get("msg")
    error = request.query_params.get("err")

    return templates.TemplateResponse("firmware.html", {
        "request": request,
        "session": session,
        "firmware_versions": firmware_versions,
        "devices": devices,
        "message": message,
        "error": error,
    })


@router.post("/firmware/upload")
async def firmware_upload(
    request: Request,
    variant: str = Form(...),
    version: str = Form(...),
    release_notes: str = Form(""),
    file: UploadFile = File(...),
):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    import hashlib
    db = request.app.state.db

    # Read file
    content = await file.read()
    if len(content) < 1024:
        return RedirectResponse("/web/firmware?err=File too small — is this a valid firmware binary?", status_code=303)

    # Save to disk
    firmware_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "firmware")
    os.makedirs(firmware_dir, exist_ok=True)
    filename = f"{variant}_{version}.bin"
    filepath = os.path.join(firmware_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    file_hash = hashlib.sha256(content).hexdigest()

    db.save_firmware_version(
        variant=variant,
        version=version,
        filename=filename,
        file_size=len(content),
        file_hash=file_hash,
        release_notes=release_notes or None,
    )

    return RedirectResponse(f"/web/firmware?msg=Uploaded {variant} v{version} ({len(content) // 1024}KB)", status_code=303)


@router.post("/firmware/{fw_id}/activate")
async def firmware_activate(request: Request, fw_id: int):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    db = request.app.state.db
    fw = db.get_firmware_by_id(fw_id)
    if not fw:
        return RedirectResponse("/web/firmware?err=Firmware not found", status_code=303)

    db.set_active_firmware(fw_id)
    return RedirectResponse(f"/web/firmware?msg=Activated {fw['variant']} v{fw['version']} — devices will update within 1 hour", status_code=303)


@router.post("/firmware/{fw_id}/delete")
async def firmware_delete(request: Request, fw_id: int):
    session = await get_web_session(request)
    redirect = require_admin(session)
    if redirect:
        return redirect

    db = request.app.state.db
    filename = db.delete_firmware_version(fw_id)
    if filename is None:
        return RedirectResponse("/web/firmware?err=Cannot delete active firmware", status_code=303)

    # Delete file from disk
    firmware_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "firmware")
    filepath = os.path.join(firmware_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    return RedirectResponse("/web/firmware?msg=Firmware deleted", status_code=303)
