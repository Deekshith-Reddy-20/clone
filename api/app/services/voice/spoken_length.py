"""Keep phone / preview answers short and human-paced."""

from __future__ import annotations

import re

_SENTENCE_END = ".!?।"


def cap_spoken_reply(text: str, *, max_chars: int = 160) -> str:
    """Shorten only at a finished sentence. Never slice a word.

    Phone turns feel natural when the agent stops after 1–2 short sentences so
    the caller can answer without talking over long TTS.
    """
    t = (text or "").strip()
    if not t or len(t) <= max_chars:
        return t
    parts = re.findall(r".+?[.!?।]|[^.!?।]+$", t, flags=re.S)
    complete = [p.strip() for p in parts if p.strip() and p.strip()[-1] in _SENTENCE_END]
    if not complete:
        return t
    chosen: list[str] = []
    for sentence in complete[:2]:
        candidate = " ".join([*chosen, sentence]).strip()
        if len(candidate) <= max_chars:
            chosen.append(sentence)
        else:
            break
    if not chosen:
        return complete[0]
    return " ".join(chosen).strip()


def enforce_brevity(text: str, *, max_words: int = 24, max_sentences: int = 2) -> tuple[str, bool]:
    """Returns (trimmed_text, needs_regenerate). Never chops mid-sentence."""
    t = (text or "").strip()
    if not t:
        return t, False
    parts = re.findall(r".+?[.!?।]|[^.!?।]+$", t, flags=re.S)
    parts = [p.strip() for p in parts if p.strip()][:max_sentences]
    out = " ".join(parts).strip() or t
    words = out.split()
    if len(parts) == 1 and len(words) > max_words:
        return out, True
    if len(words) > max_words:
        # keep only full sentences that fit under max_words
        kept: list[str] = []
        for sent in parts:
            candidate = " ".join([*kept, sent]).split()
            if len(candidate) <= max_words:
                kept.append(sent)
            else:
                break
        if kept:
            out = " ".join(kept).strip()
            return out, False
        return out, True
    return out, False