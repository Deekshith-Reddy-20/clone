"""HMAC verification for Outpero post-call webhooks.

Official scheme (Outpero Post-Call Webhooks docs):
  X-Outpero-Timestamp
  X-Outpero-Signature: sha256=<hex>
  Signature = HMAC-SHA256(secret, f"{timestamp}.{raw_body}")
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)


def verify_outpero_signature(
    *,
    secret: str,
    timestamp: str | None,
    signature_header: str | None,
    raw_body: bytes,
    max_age_seconds: int = 300,
) -> bool:
    if not secret:
        logger.warning("outpero_webhook_missing_secret")
        return False
    if not timestamp or not signature_header:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > max_age_seconds:
        logger.info("outpero_webhook_timestamp_skew age=%s", abs(now - ts))
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()

    provided = signature_header.strip()
    if provided.startswith("sha256="):
        provided = provided[len("sha256=") :]

    return hmac.compare_digest(expected, provided)


def mask_secret(value: str | None, *, visible: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= visible:
        return "*" * len(value)
    return f"{'*' * max(0, len(value) - visible)}{value[-visible:]}"
