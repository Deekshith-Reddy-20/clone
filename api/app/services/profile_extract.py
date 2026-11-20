"""LLM JSON extraction into BusinessProfile with source tracking."""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import Settings, get_settings
from app.schemas.business_profile import BusinessProfile, ProfileSource
from app.services.voice.gemini import gemini_configured
from app.services.voice.sarvam import generate_agent_reply, sarvam_configured
from app.services.website_crawler import crawl_site_text

logger = logging.getLogger(__name__)

_EXTRACT_SCHEMA_HINT = """
Return ONLY valid JSON matching this shape (no markdown):
{
  "business": {"name":"","type":"resort","one_line_pitch":""},
  "location": {"full_address":"","area":"","city":"","state":"","landmarks":[],"distance_from":[],"maps_link":""},
  "contact": {"reception_phone":"","whatsapp":"","email":"","hours":""},
  "offerings": [{"name":"","description":"","capacity":"","price_from":null,"price_unit":"","price_notes":""}],
  "amenities": [],
  "policies": {},
  "offers": [],
  "usps": [],
  "faqs": [{"q":"","a":""}],
  "objection_handling": [],
  "unknown_policy": "callback",
  "sources": []
}
Facts only — no marketing fluff. Include prices only when stated on pages.
"""


def _parse_profile_json(raw: str) -> BusinessProfile:
    text = (raw or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    data = json.loads(text)
    return BusinessProfile.model_validate(data)


def _extract_gemini(crawl_text: str, url: str, settings: Settings) -> BusinessProfile:
    model = settings.gemini_model.strip() or "gemini-2.5-flash"
    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.gemini_api_key.strip()}"
    )
    prompt = (
        "Extract a business profile for a phone receptionist from crawled website text.\n"
        f"Primary URL: {url}\n{_EXTRACT_SCHEMA_HINT}\n\nCRAWL:\n{crawl_text[:32000]}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    with httpx.Client(timeout=90.0) as client:
        res = client.post(api_url, json=payload)
        res.raise_for_status()
        data = res.json()
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = " ".join(p.get("text", "") for p in parts).strip()
    return _parse_profile_json(text)


def _extract_sarvam(crawl_text: str, url: str) -> BusinessProfile:
    reply = generate_agent_reply(
        employee_brief="Output JSON business profile only.",
        caller_text=f"{_EXTRACT_SCHEMA_HINT}\n\nURL:{url}\n\n{crawl_text[:12000]}",
        history=[],
        reply_language="en-IN",
    )
    return _parse_profile_json(reply)


def crawl_and_extract_profile(url: str, settings: Settings | None = None) -> tuple[BusinessProfile, str]:
    s = settings or get_settings()
    crawl_text, page_sources = crawl_site_text(url)
    if gemini_configured(s):
        profile = _extract_gemini(crawl_text, url, s)
    elif sarvam_configured(s):
        profile = _extract_sarvam(crawl_text, url)
    else:
        profile = BusinessProfile()
        profile.business.name = url
    merged_sources = [
        ProfileSource(url=ps.get("url", ""), page=ps.get("page", ""), field=ps.get("field", ""))
        for ps in page_sources
    ]
    profile.sources = merged_sources + list(profile.sources)
    return profile, crawl_text


def merge_profile_into_draft_fields(
    *,
    brief: str,
    profile: BusinessProfile,
    crawl_summary: str,
) -> tuple[str, str, dict, dict]:
    """Returns operator_instructions, legacy website_knowledge text, persona dict, profile dict."""
    inst = (brief or "").strip()
    if re.search(r"(?i)^(your name is|you are)", inst):
        operator_instructions = inst
        brief_out = inst
    else:
        operator_instructions = inst
        brief_out = inst
    persona = {
        "name": "Maya",
        "gender": "female",
        "voice": "warm",
        "languages": ["te-IN", "hi-IN", "en-IN"],
    }
    from app.services.voice.employee_playbook import agent_name_from_brief

    n = agent_name_from_brief(brief)
    if n:
        persona["name"] = n
    from app.services.business_profile_render import render_profile_facts

    knowledge = render_profile_facts(profile)
    if not knowledge and crawl_summary:
        knowledge = crawl_summary[:12000]
    return operator_instructions, brief_out, persona, profile.model_dump(mode="json")