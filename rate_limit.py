"""
In-memory per-user rate limiter (token bucket).

Usage:
    from rate_limit import check_rate_limit

    allowed, wait = check_rate_limit(user_email)
    if not allowed:
        st.warning(f"Troppi messaggi. Riprova tra {wait:.0f} secondi.")
        return
"""
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Defaults: 10 requests per 60 seconds per user
DEFAULT_MAX_TOKENS = 10
DEFAULT_REFILL_SECONDS = 60.0


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


_buckets: dict[str, _Bucket] = {}


def check_rate_limit(
    user_key: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    refill_seconds: float = DEFAULT_REFILL_SECONDS,
) -> tuple[bool, float]:
    """Check if user_key is within rate limit.

    Returns:
        (allowed, wait_seconds)
        - allowed=True, wait=0.0 → request can proceed
        - allowed=False, wait=N  → retry after N seconds
    """
    now = time.monotonic()
    bucket = _buckets.get(user_key)

    if bucket is None:
        bucket = _Bucket(tokens=max_tokens, last_refill=now)
        _buckets[user_key] = bucket

    # Refill tokens based on elapsed time
    elapsed = now - bucket.last_refill
    refill = elapsed * (max_tokens / refill_seconds)
    bucket.tokens = min(max_tokens, bucket.tokens + refill)
    bucket.last_refill = now

    if bucket.tokens >= 1.0:
        bucket.tokens -= 1.0
        return True, 0.0

    # Calculate wait time until 1 token is available
    deficit = 1.0 - bucket.tokens
    wait = deficit * (refill_seconds / max_tokens)
    logger.warning(
        "Rate limit hit for %s (%.1f tokens remaining, wait %.1fs)",
        user_key[:16], bucket.tokens, wait,
    )
    return False, wait
