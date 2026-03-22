"""Simple in-memory rate limiter for login/register endpoints."""

import time
from collections import defaultdict

# Track attempts: ip -> list of timestamps
_attempts = defaultdict(list)

# Max 5 attempts per 15 minutes
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 900  # 15 minutes


def is_rate_limited(ip: str) -> bool:
    """Check if an IP has exceeded the login attempt limit."""
    now = time.time()
    # Clean old entries
    _attempts[ip] = [t for t in _attempts[ip] if now - t < WINDOW_SECONDS]
    return len(_attempts[ip]) >= MAX_ATTEMPTS


def record_attempt(ip: str):
    """Record a failed login/register attempt."""
    _attempts[ip].append(time.time())


def get_remaining_lockout(ip: str) -> int:
    """Get seconds remaining until rate limit resets."""
    if not _attempts[ip]:
        return 0
    oldest = min(_attempts[ip])
    remaining = WINDOW_SECONDS - (time.time() - oldest)
    return max(0, int(remaining))
