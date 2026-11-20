"""Detect replies that assert prices/amenities/entities not present in FACTS."""

from __future__ import annotations

import re

_PRICE_RE = re.compile(r"(?:rs\.?|₹|inr)\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_DENY_RE = re.compile(
    r"(లేదు|లేని|లేనప్పుడు|కాదు|not available|don't have|do not have|we don't|no helipad|no rera|isn't|is not|without a| లేదు)",
    re.I,
)

_TOPIC_STEMS = (
    "helipad",
    "heli pad",
    "rera",
    "aviation",
    "mba",
    "approval number",
    "registration number",
    "spa",
    "gym",
    "casino",
    "nightclub",
    "pool",
    "swimming",
    "jacuzzi",
    "sauna",
    "helipad",
)

_POSITIVE_FEATURE = re.compile(
    r"(మాకు\s+.+?\s+ఉంది|మాకు\s+.+?\s+ఉన్నాయి|we have\b|we've got|"
    r"ఉన్నాయి\s+అండి|ఉంది\s+అండి|is\s+available\b|are\s+available\b)",
    re.I,
)


def _facts_corpus(facts: str) -> str:
    return (facts or "").lower()


def _amounts(text: str) -> set[str]:
    return {m.group(1).replace(",", "") for m in _PRICE_RE.finditer(text or "")}


def facts_explicitly_denies(stem: str, spoken_facts: str) -> bool:
    f = _facts_corpus(spoken_facts)
    stem = stem.lower()
    return any(
        phrase in f
        for phrase in (
            f"no {stem}",
            f"without {stem}",
            f"{stem}: no",
            f"{stem} not",
            f"no {stem.replace(' ', '')}",
        )
    )


def reply_asserts_ungrounded_price(reply: str, spoken_facts: str) -> bool:
    reply_amts = _amounts(reply)
    if not reply_amts:
        return False
    fact_amts = _amounts(spoken_facts)
    if not fact_amts:
        return True
    return not reply_amts.issubset(fact_amts)


def reply_invented_negative(reply: str, spoken_facts: str) -> bool:
    """Agent says X is absent though FACTS do not state that (invented negative)."""
    r = (reply or "").lower()
    if not _DENY_RE.search(r):
        return False
    f = _facts_corpus(spoken_facts)
    for stem in _TOPIC_STEMS:
        if stem not in r:
            continue
        if stem in f and facts_explicitly_denies(stem, spoken_facts):
            continue
        if stem not in f:
            return True
    return False


def _stem_in_facts(stem: str, spoken_facts: str) -> bool:
    f = _facts_corpus(spoken_facts)
    stem = stem.lower()
    if stem in f:
        return True
    if stem in ("pool", "swimming") and ("pool" in f or "swimming" in f):
        return True
    if stem == "jacuzzi" and "jacuzzi" in f:
        return True
    return False


def reply_asserts_ungrounded_topic(reply: str, spoken_facts: str) -> bool:
    r = (reply or "").lower()
    for stem in _TOPIC_STEMS:
        if stem not in r:
            continue
        if not _stem_in_facts(stem, spoken_facts):
            return True
    return False


def reply_asserts_ungrounded_feature(reply: str, spoken_facts: str) -> bool:
    """Positive amenity/offering claim (మాకు X ఉంది / we have X) not in FACTS."""
    raw = reply or ""
    r = raw.lower()
    if not raw.strip():
        return False
    asserts = bool(_POSITIVE_FEATURE.search(raw)) or bool(
        re.search(r"(pool|spa|gym|jacuzzi|helipad).{0,20}(ఉంది|ఉన్నాయి)", raw, re.I)
    )
    if not asserts and "available" not in r:
        return False
    for stem in _TOPIC_STEMS:
        if stem not in r:
            continue
        if not _stem_in_facts(stem, spoken_facts):
            return True
    return reply_asserts_ungrounded_topic(reply, spoken_facts)


def reply_mentions_ungrounded_entity(reply: str, spoken_facts: str) -> bool:
    if not (reply or "").strip():
        return False
    if reply_invented_negative(reply, spoken_facts):
        return True
    if reply_asserts_ungrounded_price(reply, spoken_facts):
        return True
    if reply_asserts_ungrounded_feature(reply, spoken_facts):
        return True
    return reply_asserts_ungrounded_topic(reply, spoken_facts)


def caller_asks_missing_fact(caller_text: str, spoken_facts: str) -> bool:
    c = (caller_text or "").lower()
    f = _facts_corpus(spoken_facts)
    for stem in _TOPIC_STEMS:
        if stem in c and stem not in f:
            return True
    if _PRICE_RE.search(c) and not _amounts(spoken_facts):
        return True
    return False


def classify_save_lead_miss(
    caller_text: str,
    reply: str,
    spoken_facts: str,
    *,
    save_lead_called: bool,
) -> str:
    if save_lead_called:
        return "c"
    if reply_invented_negative(reply, spoken_facts):
        return "a"
    if reply_mentions_ungrounded_entity(reply, spoken_facts) and not _DENY_RE.search(reply or ""):
        return "a"
    return "b"