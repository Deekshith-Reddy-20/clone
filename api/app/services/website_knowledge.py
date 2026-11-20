from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.config import Settings, get_settings
from app.services.voice.gemini import gemini_configured
from app.services.voice.sarvam import generate_agent_reply, sarvam_configured

logger = logging.getLogger(__name__)

MAX_FETCH_BYTES = 250_000
MAX_TEXT_CHARS = 12_000
_FETCHED_AT: dict[str, str] = {}


def noted_website_fetch(url: str | None) -> str:
    if not url:
        return ""
    return _FETCHED_AT.get(url, "")


def _remember_fetch(url: str) -> None:
    _FETCHED_AT[url] = datetime.now(UTC).isoformat()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r" {2,}", " ", raw)
        return raw.strip()


def normalize_website_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise ValueError("Website URL is required")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("Enter a valid website URL (e.g. https://yourhotel.com)")
    return url


def fetch_page_text(url: str) -> str:
    headers = {
        "User-Agent": "KaryukBot/1.0 (+https://karyuk.wayfinderops.com)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        _remember_fetch(url)
        body = r.content[:MAX_FETCH_BYTES]
    parser = _TextExtractor()
    parser.feed(body.decode("utf-8", errors="ignore"))
    text = parser.text()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n…"
    if len(text) < 80:
        raise ValueError("Could not extract enough text from this page. Try another URL.")
    return text


def _summarize_with_gemini(page_text: str, url: str, settings: Settings) -> str:
    model = settings.gemini_model.strip() or "gemini-2.5-flash"
    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={settings.gemini_api_key.strip()}"
    )
    prompt = (
        "You prepare facts for a human phone agent who answers live calls about this business.\n"
        f"Website URL: {url}\n\n"
        "From the page text below, write a concise knowledge base (max 900 words) covering:\n"
        "- Business type (hotel, clinic, dealership, etc.)\n"
        "- Services, rooms/products, hours, location\n"
        "- Availability, booking, reservation, or test-drive process\n"
        "- Prices or policies ONLY if explicitly stated on the page\n"
        "- 2–3 USPs / benefits callers care about\n"
        "- Common price objections and how the business answers (offers, packages, visit invites)\n"
        "- Reception phone, hours, location, callback policy\n"
        "- What to say when info is missing (offer to note request / callback)\n"
        "Use bullet sections. No marketing fluff. Facts only.\n\n"
        f"PAGE TEXT:\n{page_text[:10000]}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    with httpx.Client(timeout=60.0) as client:
        res = client.post(api_url, json=payload)
        res.raise_for_status()
        data = res.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no summary")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = " ".join(p.get("text", "") for p in parts).strip()
        if len(text) < 80:
            raise ValueError("Summary too short")
        return text[:6000]


def _summarize_with_sarvam(page_text: str, url: str) -> str:
    stub = (
        "Summarize this website for a phone agent: business facts, booking/availability, "
        "services, policies stated on site."
    )
    combined = f"{stub}\n\nURL: {url}\n\n{page_text[:6000]}"
    reply = generate_agent_reply(
        employee_brief="You extract structured website facts for call center agents.",
        caller_text=combined,
        history=[],
        reply_language="en-IN",
    )
    if len(reply) < 80:
        raise ValueError("Could not analyze website with Sarvam")
    return reply[:6000]


def analyze_website(url: str, settings: Settings | None = None) -> tuple[str, str]:
    """Returns (normalized_url, knowledge_text)."""
    s = settings or get_settings()
    normalized = normalize_website_url(url)
    page_text = fetch_page_text(normalized)
    if gemini_configured(s):
        knowledge = _summarize_with_gemini(page_text, normalized, s)
    elif sarvam_configured(s):
        knowledge = _summarize_with_sarvam(page_text, normalized)
    else:
        knowledge = f"Website: {normalized}\n\n{page_text[:3500]}"
    logger.info("Website analyzed %s (%d chars knowledge)", normalized, len(knowledge))
    return normalized, knowledge