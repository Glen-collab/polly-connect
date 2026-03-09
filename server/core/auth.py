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
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# API key from environment (generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))")
API_KEY = os.getenv("POLLY_API_KEY", "")

# Paths that don't require API key auth
# Web portal uses its own cookie-based session auth
PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}
PUBLIC_PREFIXES = ["/web/", "/static/", "/api/firmware/"]


def verify_api_key(key: str) -> bool:
    """Constant-time comparison of API key."""
    if not API_KEY:
        # No key configured = auth disabled (local dev)
        return True
    return secrets.compare_digest(key, API_KEY)


def verify_websocket_key(connect_data: dict) -> bool:
    """Check API key from WebSocket connect event payload."""
    key = connect_data.get("api_key", "")
    return verify_api_key(key)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware that checks X-API-Key header on non-WebSocket requests."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth if no key configured (local dev mode)
        if not API_KEY:
            return await call_next(request)

        # Skip public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Skip public prefixes (web app)
        if any(request.url.path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Skip WebSocket upgrades (handled in WS handlers)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check API key header
        key = request.headers.get("X-API-Key", "")
        if not verify_api_key(key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

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
        }

    # Fallback: global API key maps to tenant #1
    if verify_api_key(key):
        return {
            "device_id": None,
            "tenant_id": 1,
            "user_id": None,
        }

    return None
