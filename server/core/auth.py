"""
API key authentication for Polly Connect.
ESP32 sends key in WebSocket connect message.
REST endpoints require X-API-Key header.
"""

import hashlib
import logging
import os
import secrets
from typing import Optional

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# API key from environment (generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))")
API_KEY = os.getenv("POLLY_API_KEY", "")
# Only for a laptop with no key: POLLY_AUTH_DISABLED=1. Without it, a missing key
# means NOTHING authenticates (fail closed), never "everything does".
AUTH_DISABLED = os.getenv("POLLY_AUTH_DISABLED", "") == "1"
if not API_KEY and not AUTH_DISABLED:
    logger.warning("POLLY_API_KEY is not set: only per-device keys will authenticate")

# Paths that don't require API key auth
# Web portal uses its own cookie-based session auth
# Stripe signs its webhook; the handler verifies that signature itself.
PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc", "/api/devices/provision",
                "/api/stripe/webhook"}
PUBLIC_PREFIXES = ["/web/", "/static/", "/api/firmware/"]


def verify_api_key(key: str) -> bool:
    """Constant-time comparison against the global key. No key configured = no match."""
    if AUTH_DISABLED:
        return True
    if not API_KEY or not key:
        return False
    return secrets.compare_digest(key, API_KEY)


def verify_websocket_key(connect_data: dict) -> bool:
    """Check API key from WebSocket connect event payload."""
    key = connect_data.get("api_key", "")
    return verify_api_key(key)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Checks X-API-Key on non-WebSocket requests. Accepts the global key or a
    per-device key, and puts the caller on request.state.api_auth
    ({device_id, tenant_id, user_id, is_global}) so routes can scope to it."""

    async def dispatch(self, request: Request, call_next):
        # Skip public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip public prefixes (web app)
        if any(request.url.path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Skip WebSocket upgrades (handled in WS handlers)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        key = request.headers.get("X-API-Key", "")
        info = verify_device_api_key(key, request.app.state.db)
        if info and info.get("claim_code") and not info.get("claimed_at"):
            info = None  # an unclaimed device belongs to nobody yet
        if not info:
            # A JSONResponse, not HTTPException: raised inside BaseHTTPMiddleware
            # that becomes a 500 instead of a 401.
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        info["is_global"] = info.get("device_id") is None
        request.state.api_auth = info
        return await call_next(request)


def generate_api_key() -> str:
    """Generate a new random API key."""
    return secrets.token_urlsafe(32)


def verify_device_api_key(key: str, db) -> Optional[dict]:
    """
    Look up a per-device API key in the database.
    Returns {device_id, tenant_id, user_id} or None.
    Falls back to global API key → tenant #1 for backward compat.
    """
    if AUTH_DISABLED:
        return {"device_id": None, "tenant_id": 1, "user_id": None}
    if not key:
        return None

    # Try per-device key first
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    device = db.get_device_by_api_key_hash(key_hash)
    if device:
        db.update_device_last_seen(device["device_id"])
        return {
            "device_id": device["device_id"],
            "tenant_id": device.get("tenant_id") or 1,
            "user_id": device.get("user_id"),
            "claim_code": device.get("claim_code"),
            "claimed_at": device.get("claimed_at"),
        }

    # Fallback: global API key maps to tenant #1
    if verify_api_key(key):
        return {
            "device_id": None,
            "tenant_id": 1,
            "user_id": None,
        }

    return None
