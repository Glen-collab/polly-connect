"""
Web authentication for Polly Connect caretaker portal.
Cookie-based sessions with password hashing.
"""

import hashlib
import logging
from typing import Optional, Dict

from fastapi import Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with a salt prefix.
    Uses hashlib (stdlib) so no extra dependencies needed."""
    import secrets
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash."""
    if ":" not in password_hash:
        return False
    salt, stored_hash = password_hash.split(":", 1)
    check_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return check_hash == stored_hash


async def get_web_session(request: Request) -> Optional[Dict]:
    """
    Check for a valid session cookie and return session info.
    Returns dict with account_id, tenant_id, name, email, role or None.
    """
    session_id = request.cookies.get("polly_session")
    if not session_id:
        return None

    db = request.app.state.db
    session = db.get_web_session(session_id)
    if not session:
        return None

    # Touch session to keep it active
    db.touch_web_session(session_id)

    return {
        "session_id": session["id"],
        "account_id": session["account_id"],
        "tenant_id": session["tenant_id"],
        "name": session["account_name"],
        "email": session["account_email"],
        "role": session["role"],
    }


def require_login(session: Optional[Dict]) -> Optional[RedirectResponse]:
    """If session is None, return a redirect to login page. Otherwise return None."""
    if session is None:
        return RedirectResponse("/web/login", status_code=302)
    return None
