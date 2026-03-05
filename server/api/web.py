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

from core.web_auth import get_web_session, require_login, require_owner, hash_password, verify_password
from core.auth import generate_api_key
from core.medications import format_time_12hr, _get_local_now
from config import settings

import re

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

    tenant = db.validate_family_code(code)
    if not tenant:
        return templates.TemplateResponse("family_login.html", {
            "request": request, "error": "Invalid access code.",
            "name": name, "code": code, "session": None,
        })

    session_id = db.create_family_session(
        tenant["id"], name,
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

    # Book progress
    book_builder = getattr(request.app.state, "book_builder", None)
    book_progress = book_builder.get_book_progress() if book_builder else None

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session": session,
        "stories": stories,
        "medications": medications,
        "story_count": len(stories),
        "question_count": q_count,
        "item_count": stats.get("total_items", 0),
        "book_progress": book_progress,
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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    user = db.get_or_create_user(tenant_id=session["tenant_id"])
    tenant = db.get_tenant(session["tenant_id"])
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "session": session,
        "user": user,
        "tenant": tenant,
    })


@router.post("/settings")
async def settings_save(request: Request, name: str = Form(...),
                        familiar_name: str = Form(""),
                        bible_topic_preference: str = Form(""),
                        music_genre_preference: str = Form(""),
                        memory_care_mode: str = Form("")):
    session = await get_web_session(request)
    redirect = require_owner(session)
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
    redirect = require_owner(session)
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


# ── Device Management ──

@router.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    session = await get_web_session(request)
    redirect = require_owner(session)
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
    redirect = require_owner(session)
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
    redirect = require_owner(session)
    if redirect:
        return redirect

    db = request.app.state.db
    db.delete_device(device_id, session["tenant_id"])
    return RedirectResponse("/web/devices", status_code=303)


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

    progress = book_builder.get_book_progress()
    chapters = book_builder.generate_chapter_outline()

    # Check which chapters already have drafts
    existing_drafts = {d["chapter_number"]: d for d in db.get_chapter_drafts(tenant_id=tid)}
    for ch in chapters:
        ch["bucket_label"] = BUCKET_LABELS.get(ch["bucket"], ch["bucket"])
        ch["phase_label"] = PHASE_LABELS.get(ch["life_phase"], ch["life_phase"])
        if ch["chapter_number"] in existing_drafts:
            ch["status"] = "has_draft"

    # Arc coverage
    bucket_coverage = narrative_arc.get_bucket_coverage()
    arc_coverage = {}
    for bucket_key, count in bucket_coverage.items():
        arc_coverage[bucket_key] = {
            "label": BUCKET_LABELS.get(bucket_key, bucket_key),
            "count": count,
            "target": BUCKET_TARGETS.get(bucket_key, 10),
        }

    # Life phase coverage
    phase_cov = narrative_arc.get_life_phase_coverage()
    phase_coverage = {}
    for phase_key, count in phase_cov.items():
        phase_coverage[phase_key] = {
            "label": PHASE_LABELS.get(phase_key, phase_key),
            "count": count,
        }

    gap_report = engagement.get_gap_report()

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

    chapters = book_builder.generate_chapter_outline()
    existing_drafts = {d["chapter_number"]: d for d in db.get_chapter_drafts(tenant_id=tid)}

    for ch in chapters:
        ch["bucket_label"] = BUCKET_LABELS.get(ch["bucket"], ch["bucket"])
        ch["phase_label"] = PHASE_LABELS.get(ch["life_phase"], ch["life_phase"])
        if ch["chapter_number"] in existing_drafts:
            ch["status"] = "has_draft"
        # Fetch memory previews
        ch["memories"] = []
        for mid in ch.get("memory_ids", []):
            mem = db.get_memory_by_id(mid)
            if mem:
                ch["memories"].append(mem)

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

    chapters = book_builder.generate_chapter_outline()
    chapter = None
    for ch in chapters:
        if ch["chapter_number"] == chapter_num:
            chapter = ch
            break

    if not chapter:
        return RedirectResponse("/web/book/chapters", status_code=302)

    chapter["bucket_label"] = BUCKET_LABELS.get(chapter["bucket"], chapter["bucket"])
    chapter["phase_label"] = PHASE_LABELS.get(chapter["life_phase"], chapter["life_phase"])

    # Fetch full memories
    memories = []
    for mid in chapter.get("memory_ids", []):
        mem = db.get_memory_by_id(mid)
        if mem:
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

    message = request.query_params.get("msg")

    return templates.TemplateResponse("book_chapter_detail.html", {
        "request": request,
        "session": session,
        "chapter": chapter,
        "memories": memories,
        "draft": draft,
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
    book_builder = request.app.state.book_builder

    chapters = book_builder.generate_chapter_outline()
    chapter = None
    for ch in chapters:
        if ch["chapter_number"] == chapter_num:
            chapter = ch
            break

    if not chapter:
        return RedirectResponse("/web/book/chapters", status_code=302)

    # Generate AI draft
    content = await book_builder.generate_chapter_draft(chapter)

    if content:
        book_builder.save_chapter_draft(
            chapter_number=chapter_num,
            title=chapter["title"],
            bucket=chapter["bucket"],
            life_phase=chapter["life_phase"],
            memory_ids=chapter.get("memory_ids", []),
            content=content,
        )
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
