"""HMAC verification for Outpero post-call webhooks.

Official scheme (Outpero Post-Call Webhooks docs):
  X-Outpero-Timestamp
  X-Outpero-Signature: sha256=<hex>
  Signature = HMAC-SHA256(secret, f"{timestamp}.{raw_body}")

Outpero Test Send has been observed to vary timestamp units; we accept
seconds or milliseconds in the header and try both signed forms.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_provided_signature(signature_header: str) -> list[str]:
    """Return candidate digests to compare (hex and/or base64 forms)."""
    provided = signature_header.strip()
    candidates: list[str] = []
    if not provided:
        return candidates
    lower = provided.lower()
    if lower.startswith("sha256="):
        provided = provided[len("sha256=") :]
    candidates.append(provided)
    return candidates


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _hmac_b64(secret: str, message: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _hmac_b64url(secret: str, message: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _timestamp_message_variants(timestamp: str, raw_body: bytes) -> list[tuple[str, bytes]]:
    """Build (label, message_bytes) candidates for HMAC."""
    variants: list[tuple[str, bytes]] = []
    variants.append(("ts_raw_dot_body", f"{timestamp}.".encode("utf-8") + raw_body))

    try:
        ts_raw = int(timestamp)
    except ValueError:
        return variants

    ts_seconds = ts_raw // 1000 if ts_raw > 10_000_000_000 else ts_raw
    ts_ms = ts_raw if ts_raw > 10_000_000_000 else ts_raw * 1000

    for label, ts_str in (
        ("ts_seconds_dot_body", str(ts_seconds)),
        ("ts_ms_dot_body", str(ts_ms)),
    ):
        msg = f"{ts_str}.".encode("utf-8") + raw_body
        if msg != variants[0][1]:
            variants.append((label, msg))

    # Rare variants seen in other providers / mis-documented clients
    variants.append(("ts_raw_no_dot_body", f"{timestamp}".encode("utf-8") + raw_body))
    variants.append(("body_only", raw_body))
    return variants


def diagnose_outpero_signature(
    *,
    secret: str,
    timestamp: str | None,
    signature_header: str | None,
    raw_body: bytes,
    max_age_seconds: int = 300,
) -> dict[str, Any]:
    """Return verification diagnostics (no secret values)."""
    info: dict[str, Any] = {
        "ok": False,
        "reason": "unknown",
        "has_secret": bool(secret),
        "has_timestamp": bool(timestamp),
        "has_signature": bool(signature_header),
        "timestamp": timestamp,
        "signature_prefix": (signature_header or "")[:16],
        "signature_len": len(signature_header or ""),
        "body_len": len(raw_body),
        "body_sha256": hashlib.sha256(raw_body).hexdigest()[:16],
        "matched_variant": None,
    }
    if not secret:
        info["reason"] = "missing_secret"
        return info
    if not timestamp or not signature_header:
        info["reason"] = "missing_headers"
        return info

    try:
        ts_raw = int(timestamp)
    except ValueError:
        info["reason"] = "timestamp_not_int"
        return info

    ts_seconds = ts_raw // 1000 if ts_raw > 10_000_000_000 else ts_raw
    age = abs(int(time.time()) - ts_seconds)
    info["age_seconds"] = age
    if age > max_age_seconds:
        info["reason"] = "timestamp_skew"
        return info

    provided_list = _normalize_provided_signature(signature_header)
    for label, message in _timestamp_message_variants(timestamp, raw_body):
        expected_hex = _hmac_hex(secret, message)
        expected_b64 = _hmac_b64(secret, message)
        expected_b64url = _hmac_b64url(secret, message)
        for provided in provided_list:
            for expected in (expected_hex, expected_b64, expected_b64url):
                if len(provided) == len(expected) and hmac.compare_digest(expected, provided):
                    info["ok"] = True
                    info["reason"] = "ok"
                    info["matched_variant"] = label
                    return info

    info["reason"] = "digest_mismatch"
    return info


def verify_outpero_signature(
    *,
    secret: str,
    timestamp: str | None,
    signature_header: str | None,
    raw_body: bytes,
    max_age_seconds: int = 300,
) -> bool:
    result = diagnose_outpero_signature(
        secret=secret,
        timestamp=timestamp,
        signature_header=signature_header,
        raw_body=raw_body,
        max_age_seconds=max_age_seconds,
    )
    if not result["ok"]:
        logger.info(
            "outpero_webhook_signature_fail reason=%s ts=%s sig_prefix=%s body_len=%s age=%s",
            result.get("reason"),
            result.get("timestamp"),
            result.get("signature_prefix"),
            result.get("body_len"),
            result.get("age_seconds"),
        )
        if result.get("reason") == "timestamp_skew":
            logger.info("outpero_webhook_timestamp_skew age=%s", result.get("age_seconds"))
    elif result.get("matched_variant") and result["matched_variant"] != "ts_raw_dot_body":
        logger.info(
            "outpero_webhook_signature_alt_ok variant=%s",
            result["matched_variant"],
        )
    return bool(result["ok"])


def mask_secret(value: str | None, *, visible: int = 4) -> str | None:
    if not value:
        return None
    if len(value) <= visible:
        return "*" * len(value)
    return f"{'*' * max(0, len(value) - visible)}{value[-visible:]}"
