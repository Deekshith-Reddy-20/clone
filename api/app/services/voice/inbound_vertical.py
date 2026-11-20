"""Detect lodging vs hospital vs general from published employee snapshot on the call."""

from __future__ import annotations

from typing import Literal

Vertical = Literal["lodging", "hospital", "general"]


_LODGING_MARKERS = (
    "resort",
    "hotel",
    "lodge",
    "villa",
    "homestay",
    "check-in",
    "check in",
    "checkout",
    "check out",
    "room inventory",
    "guest count",
    "స్టే",
    "రిసార్ట్",
    "హోటల్",
    "గది",
    "చెక్-ఇన్",
    "చెక్ ఇన్",
)

_HOSPITAL_MARKERS = (
    "hospital",
    "opd",
    "outpatient",
    "clinic",
    "doctor",
    "department",
    "icu",
    "emergency ward",
    "ఆసుపత్రి",
    "హాస్పిటల్",
    "డాక్టర్",
    "ఓపీడీ",
    "అపాయింట్",
    "op appointment",
)


def _corpus(fields: dict) -> str:
    parts = [
        str(fields.get("employee_brief") or ""),
        str(fields.get("employee_website_knowledge") or ""),
        str(fields.get("employee_workspace_knowledge") or fields.get("workspace_knowledge") or ""),
    ]
    return "\n".join(p for p in parts if p).lower()


def inbound_vertical(fields: dict) -> Vertical:
    corpus = _corpus(fields)
    if not corpus.strip():
        return "general"
    lod = sum(1 for m in _LODGING_MARKERS if m in corpus)
    hos = sum(1 for m in _HOSPITAL_MARKERS if m in corpus)
    if hos >= 2 and lod == 0:
        return "hospital"
    if lod >= 2 and hos == 0:
        return "lodging"
    if hos >= 1 and lod == 0:
        return "hospital"
    if lod >= 1 and hos == 0:
        return "lodging"
    if hos > lod:
        return "hospital"
    if lod > hos:
        return "lodging"
    return "general"