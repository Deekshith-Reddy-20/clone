"""Lightweight same-site crawler for business profile extraction."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from app.services.website_knowledge import MAX_FETCH_BYTES, _TextExtractor, normalize_website_url

MAX_PAGES = 24
MAX_CRAWL_CHARS = 48_000


class _LinkExtractor(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__()
        self.base = base
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        href = ""
        for k, v in attrs:
            if k == "href":
                href = v or ""
                break
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return
        self.links.append(urljoin(self.base, href))


def _same_site(seed: str, url: str) -> bool:
    a = urlparse(seed).netloc.lower()
    b = urlparse(url).netloc.lower()
    return a == b


def crawl_site_text(url: str) -> tuple[str, list[dict[str, str]]]:
    """Returns merged text and per-page source records."""
    seed = normalize_website_url(url)
    headers = {
        "User-Agent": "KaryukBot/1.0 (+https://karyuk.wayfinderops.com)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    seen: set[str] = set()
    queue: list[str] = [seed]
    chunks: list[str] = []
    sources: list[dict[str, str]] = []
    total = 0

    with httpx.Client(follow_redirects=True, timeout=25.0) as client:
        while queue and len(seen) < MAX_PAGES and total < MAX_CRAWL_CHARS:
            page_url = queue.pop(0)
            if page_url in seen or not _same_site(seed, page_url):
                continue
            seen.add(page_url)
            try:
                r = client.get(page_url, headers=headers)
                r.raise_for_status()
            except Exception:
                continue
            body = r.content[:MAX_FETCH_BYTES]
            html = body.decode("utf-8", errors="ignore")
            parser = _TextExtractor()
            parser.feed(html)
            text = parser.text()
            if len(text) < 40:
                continue
            link_parser = _LinkExtractor(page_url)
            link_parser.feed(html)
            for link in link_parser.links:
                if link not in seen and link not in queue:
                    queue.append(link)
            snippet = text[:6000]
            chunks.append(f"--- PAGE: {page_url} ---\n{snippet}")
            sources.append({"url": page_url, "page": page_url, "field": "crawl"})
            total += len(snippet)

    merged = "\n\n".join(chunks)
    if len(merged) > MAX_CRAWL_CHARS:
        merged = merged[:MAX_CRAWL_CHARS] + "\n…"
    return merged, sources


def slug_hint(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else "home"