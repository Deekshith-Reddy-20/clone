"""Separate operator instructions from speakable business FACTS for the voice LLM."""

from __future__ import annotations

import re

_INSTRUCTION_LINE = re.compile(
    r"^\s*(you are|you're|your name is|your job|never |always |instructions?|playbook|"
    r"use the live booking|internal )",
    re.I,
)


def split_brief_instructions_and_facts(brief: str) -> tuple[str, str]:
    """Returns (instructions_block, facts_block) from employee brief."""
    raw = (brief or "").strip()
    if not raw:
        return "", ""
    inst: list[str] = []
    facts: list[str] = []
    for line in re.split(r"[\n.]+", raw):
        s = line.strip()
        if not s:
            continue
        if _INSTRUCTION_LINE.search(s):
            inst.append(s)
        else:
            facts.append(s)
    # Single-line briefs like "Your name is Maya for V Farms Resort."
    if not facts and inst:
        m = re.search(
            r"(?:your name is|you are)\s+([A-Za-z]+)\s+(?:for|at)\s+(.+)",
            raw,
            re.I,
        )
        if m:
            return raw, f"Business: {m.group(2).strip()}."
        return raw, ""
    if not inst and _INSTRUCTION_LINE.search(raw):
        return raw, ""
    return ". ".join(inst), ". ".join(facts)


def build_spoken_facts_block(
    *,
    brief: str,
    website_knowledge: str | None,
    workspace_knowledge: str | None = None,
    strip_hacks: bool = True,
) -> str:
    """FACTS section only — never includes operator instructions."""
    _inst, brief_facts = split_brief_instructions_and_facts(brief)
    parts = [p for p in (brief_facts, (website_knowledge or "").strip(), (workspace_knowledge or "").strip()) if p]
    merged = "\n\n".join(parts)
    if strip_hacks:
        merged = _strip_operator_phrases_from_facts(merged)
    return merged.strip()


def _strip_operator_phrases_from_facts(text: str) -> str:
    out_lines: list[str] = []
    drop_markers = (
        "use the live booking system",
        "your name is",
        "you are maya",
        "you are ",
        "internal playbook",
        "knowledge base",
        "as an ai",
    )
    for line in re.split(r"[\n]+", text):
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if any(m in low for m in drop_markers):
            continue
        out_lines.append(s)
    return "\n".join(out_lines)


def persona_from_brief(brief: str) -> dict[str, str]:
    from app.services.voice.employee_playbook import agent_name_from_brief
    from app.services.voice.sarvam import business_name_from_context

    inst, _ = split_brief_instructions_and_facts(brief)
    name = agent_name_from_brief(brief) or "Maya"
    biz = business_name_from_context(brief=brief, website_knowledge="") or "the business"
    return {"name": name, "business": biz, "instructions": inst}