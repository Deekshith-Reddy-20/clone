"""Chunk sanitized LLM text into speakable sentences for telephony TTS."""

from __future__ import annotations

import re
import time

_END = re.compile(r"(?<=[.?!।])\s+")
_MIN_WORDS = 6
_MAX_FLUSH_S = 2.5


class SentenceChunker:
    def __init__(
        self,
        *,
        min_words: int = _MIN_WORDS,
        max_flush_s: float = _MAX_FLUSH_S,
        max_sentences: int = 2,
    ) -> None:
        self._buf = ""
        self._min_words = min_words
        self._max_flush_s = max_flush_s
        self._max_sentences = max(1, max_sentences)
        self._emitted = 0
        self._last_emit = time.monotonic()

    def feed(self, text: str) -> list[str]:
        self._buf += text or ""
        return self._drain(force=False)

    def flush(self) -> list[str]:
        return self._drain(force=True)

    def _word_count(self, s: str) -> int:
        return len(re.findall(r"\S+", s))

    def _drain(self, *, force: bool) -> list[str]:
        out: list[str] = []
        if self._emitted >= self._max_sentences:
            self._buf = ""
            return out
        while self._buf:
            m = _END.search(self._buf)
            if m:
                chunk = self._buf[: m.start()].strip()
                self._buf = self._buf[m.end() :]
                if chunk and (force or self._word_count(chunk) >= self._min_words):
                    if self._emitted >= self._max_sentences:
                        self._buf = ""
                        break
                    out.append(chunk)
                    self._emitted += 1
                    self._last_emit = time.monotonic()
                elif chunk:
                    self._buf = f"{chunk} {self._buf}".strip()
                continue
            age = time.monotonic() - self._last_emit
            if force:
                if self._buf.strip():
                    out.append(self._buf.strip())
                    self._buf = ""
                break
            if age >= self._max_flush_s and self._word_count(self._buf) >= self._min_words:
                out.append(self._buf.strip())
                self._buf = ""
                self._last_emit = time.monotonic()
            break
        return out