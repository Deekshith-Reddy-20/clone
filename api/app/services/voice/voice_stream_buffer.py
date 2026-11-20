"""Strip LLM tool tags before TTS — buffer until <tool_call> closes."""

from __future__ import annotations

import re

_OPEN = re.compile(r"<tool_call>", re.I)
_CLOSE = re.compile(r"</tool_call>", re.I)


class SpeechStreamSanitizer:
    def __init__(self) -> None:
        self._buf = ""
        self._in_tool = False

    def feed(self, delta: str) -> str:
        """Returns text safe to speak (tool blocks withheld)."""
        self._buf += delta or ""
        out_parts: list[str] = []
        while self._buf:
            if self._in_tool:
                m = _CLOSE.search(self._buf)
                if not m:
                    return "".join(out_parts)
                self._buf = self._buf[m.end() :]
                self._in_tool = False
                continue
            m = _OPEN.search(self._buf)
            if not m:
                out_parts.append(self._buf)
                self._buf = ""
                break
            out_parts.append(self._buf[: m.start()])
            self._buf = self._buf[m.end() :]
            self._in_tool = True
        return "".join(out_parts)