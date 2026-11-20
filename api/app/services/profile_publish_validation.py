"""Block publishing test/invented business profile data to production."""

from __future__ import annotations

from typing import Any

_BLOCKED_SOURCE_TOKENS = frozenset(
    {
        "seed",
        "invented",
        "vfarms_fixture",
        "college_fixture",
        "realestate_fixture",
        "manual",
        "fixture",
    }
)


def _source_is_blocked(url: str, page: str, field: str) -> bool:
    blob = " ".join((url or "", page or "", field or "")).lower()
    return any(t in blob for t in _BLOCKED_SOURCE_TOKENS)


def validate_profile_publishable(profile: dict[str, Any] | None) -> list[str]:
    """Return human-readable errors; empty list = OK to publish."""
    if not profile:
        return []
    errors: list[str] = []
    if profile.get("test_only") is True:
        errors.append("Profile is marked test_only — not publishable.")
    for src in profile.get("sources") or []:
        if not isinstance(src, dict):
            continue
        if _source_is_blocked(str(src.get("url", "")), str(src.get("page", "")), str(src.get("field", ""))):
            errors.append(
                f"Profile source blocked for publish: {src.get('url') or src.get('page') or src}"
            )
    return errors