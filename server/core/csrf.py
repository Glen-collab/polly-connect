"""CSRF protection for Polly Connect web forms."""

import hashlib
import hmac
import logging
import secrets
import time

logger = logging.getLogger(__name__)

# Secret key for CSRF tokens — generated once at startup
_csrf_secret = secrets.token_hex(32)

# Token validity: 4 hours
TOKEN_MAX_AGE = 4 * 3600


def generate_csrf_token(session_id: str) -> str:
    """Generate a CSRF token tied to the user's session."""
    timestamp = str(int(time.time()))
    payload = f"{session_id}:{timestamp}"
    signature = hmac.new(
        _csrf_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{timestamp}.{signature}"


def validate_csrf_token(token: str, session_id: str) -> bool:
    """Validate a CSRF token against the session."""
    if not token or "." not in token:
        return False
    try:
        timestamp_str, signature = token.split(".", 1)
        timestamp = int(timestamp_str)
    except (ValueError, IndexError):
        return False

    # Check age
    if time.time() - timestamp > TOKEN_MAX_AGE:
        logger.warning("CSRF token expired")
        return False

    # Verify signature
    payload = f"{session_id}:{timestamp_str}"
    expected = hmac.new(
        _csrf_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]

    if not hmac.compare_digest(signature, expected):
        logger.warning("CSRF token signature mismatch")
        return False

    return True
