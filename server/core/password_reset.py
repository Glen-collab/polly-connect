"""Password reset token generation and validation."""

import hashlib
import hmac
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

# Secret for signing reset tokens — PERSISTED so live reset links survive a
# process restart (this box restarts often). Mirrors csrf.py's approach.
_reset_secret_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".reset_secret")
if os.path.exists(_reset_secret_file):
    with open(_reset_secret_file, "r") as f:
        _reset_secret = f.read().strip()
else:
    _reset_secret = secrets.token_hex(32)
    try:
        with open(_reset_secret_file, "w") as f:
            f.write(_reset_secret)
    except Exception:
        pass  # if we can't write, it'll regenerate next restart

# Token valid for 1 hour
TOKEN_MAX_AGE = 3600


def _hash_fingerprint(password_hash: str) -> str:
    """Short fingerprint of the current password hash, mixed into the token so
    the token becomes single-use: once the password changes, the hash changes
    and the old token no longer validates."""
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def generate_reset_token(account_id: int, email: str, password_hash: str = "") -> str:
    """Generate a signed, single-use password reset token bound to the current
    password hash (so it dies the moment the password is changed)."""
    timestamp = str(int(time.time()))
    fp = _hash_fingerprint(password_hash)
    payload = f"{account_id}:{email}:{timestamp}:{fp}"
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

    # Verify signature — bound to the current password hash, so a used/old
    # token (issued against a now-changed password) fails here.
    fp = _hash_fingerprint(account.get("password_hash") or "")
    payload = f"{account_id}:{account['email']}:{timestamp_str}:{fp}"
    expected = hmac.new(
        _reset_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]

    if not hmac.compare_digest(signature, expected):
        logger.warning("Reset token signature mismatch")
        return None

    return account
