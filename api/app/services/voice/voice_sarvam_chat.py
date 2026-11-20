"""Sarvam chat completions: sarvam-105b-conversations, stream + native tools."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from app.config import get_settings
from app.services.voice.sarvam import SARVAM_CHAT_MODEL, _client, sarvam_configured
from app.services.voice.voice_llm_tools import openai_tools_payload, parse_accumulated_tool_calls

logger = logging.getLogger(__name__)


def stream_chat_completion(
    *,
    messages: list[dict[str, str]],
    tool_choice: str = "auto",
) -> Iterator[tuple[str, list[dict]]]:
    """
    Yields (delta_text, tool_calls_so_far). Final yield may have empty text + complete tools.
    """
    if not sarvam_configured():
        return
    client = _client()
    tool_acc: dict[int, dict] = {}
    t0 = time.perf_counter()
    stream = client.chat.completions(
        model=SARVAM_CHAT_MODEL,
        messages=messages,
        tools=openai_tools_payload(),
        tool_choice=tool_choice,
        stream=True,
        temperature=0.45,
        max_tokens=120,
    )
    first_ms: float | None = None
    for chunk in stream:
        if first_ms is None:
            first_ms = (time.perf_counter() - t0) * 1000.0
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        if not delta:
            continue
        piece = str(getattr(delta, "content", "") or "")
        tcs = getattr(delta, "tool_calls", None) or []
        for tc in tcs:
            idx = int(getattr(tc, "index", 0) or 0)
            slot = tool_acc.setdefault(idx, {"name": "", "args": ""})
            fn = getattr(tc, "function", None)
            if fn:
                nm = str(getattr(fn, "name", "") or "")
                if nm and not slot["name"]:
                    slot["name"] = nm
                slot["args"] += str(getattr(fn, "arguments", "") or "")
        if piece:
            yield piece, []
    tools_out = parse_accumulated_tool_calls(tool_acc)
    yield "", tools_out
    if first_ms is not None:
        logger.info("sarvam_stream ttft_ms=%.1f tools=%d", first_ms, len(tools_out))


def chat_completion_sync(
    *,
    messages: list[dict[str, str]],
) -> tuple[str, float, list[dict]]:
    if not sarvam_configured():
        return "", 0.0, []
    t0 = time.perf_counter()
    resp = _client().chat.completions(
        model=SARVAM_CHAT_MODEL,
        messages=messages,
        tools=openai_tools_payload(),
        tool_choice="auto",
        stream=False,
        temperature=0.45,
        max_tokens=120,
    )
    ttft = (time.perf_counter() - t0) * 1000.0
    msg = resp.choices[0].message
    text = str(getattr(msg, "content", "") or "").strip()
    tools: list[dict] = []
    for tc in getattr(msg, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        if not fn:
            continue
        try:
            args = json.loads(getattr(fn, "arguments", "") or "{}")
        except json.JSONDecodeError:
            args = {}
        tools.append({"name": getattr(fn, "name", ""), "args": args})
    return text, ttft, tools