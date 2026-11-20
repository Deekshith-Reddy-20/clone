"""Extract plain text from uploaded PDFs for workspace knowledge."""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

MAX_PDF_BYTES = 5_000_000
MAX_PDF_TEXT_CHARS = 24_000


def extract_pdf_text(data: bytes, *, filename: str = "upload.pdf") -> str:
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF is too large (max 5 MB).")
    if not data.startswith(b"%PDF"):
        raise ValueError("File does not look like a PDF.")
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) == 0:
        raise ValueError("PDF has no pages.")
    if len(reader.pages) > 80:
        raise ValueError("PDF has too many pages (max 80).")
    parts: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = t.strip()
        if t:
            parts.append(t)
    raw = "\n\n".join(parts)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = re.sub(r" {2,}", " ", raw)
    if len(raw) < 40:
        raise ValueError(
            "Could not read enough text from this PDF. Try a text-based PDF or paste content manually."
        )
    if len(raw) > MAX_PDF_TEXT_CHARS:
        raw = raw[:MAX_PDF_TEXT_CHARS] + "\n…"
    title_hint = (filename or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return f"### PDF: {title_hint}\n{raw}"