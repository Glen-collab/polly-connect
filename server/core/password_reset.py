"""Password reset token generation and validation."""

import hashlib
import hmac
import logging
import secrets
import time

logger = logging.getLogger(__name__)

# Secret for signing reset tokens — generated at startup
_reset_secret = secrets.token_hex(32)

# Token valid for 1 hour
TOKEN_MAX_AGE = 3600


def generate_reset_token(account_id: int, email: str) -> str:
    """Generate a signed password reset token."""
    timestamp = str(int(time.time()))
    payload = f"{account_id}:{email}:{timestamp}"
    signature = hmac.new(
        _reset_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{account_id}.{timestamp}.{signature}"


def validate_reset_token(token: str, db) -> dict:
    """Validate a reset token. Returns account dict or None."""
    if not token or token.count(".") != 2:
        return None
    try:
        account_id_str, timestamp_str, signature = token.split(".", 2)
        account_id = int(account_id_str)
        timestamp = int(timestamp_str)
    except (ValueError, IndexError):
        return None

    # Check age
    if time.time() - timestamp > TOKEN_MAX_AGE:
        logger.warning("Reset token expired")
        return None

    # Look up account
    account = db.get_account_by_id(account_id)
    if not account:
        return None

    # Verify signature
    payload = f"{account_id}:{account['email']}:{timestamp_str}"
    expected = hmac.new(
        _reset_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]

    if not hmac.compare_digest(signature, expected):
        logger.warning("Reset token signature mismatch")
        return None

    return account
