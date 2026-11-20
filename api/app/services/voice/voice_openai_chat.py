"""OpenAI chat completions: stream + native tools (same assembly as Sarvam)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.voice.voice_llm_tools import openai_tools_payload, parse_accumulated_tool_calls

logger = logging.getLogger(__name__)

TTFT_BUDGET_MS = 2500.0


def openai_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool((s.openai_api_key or "").strip())


def _api_key(settings: Settings) -> str:
    return (settings.openai_api_key or "").strip()


def _model(settings: Settings) -> str:
    import os

    return (os.getenv("OPENAI_MODEL") or settings.openai_model or "gpt-4o-mini").strip()


def stream_chat_completion(
    *,
    messages: list[dict[str, str]],
    tool_choice: str = "auto",
    settings: Settings | None = None,
) -> Iterator[tuple[str, list[dict]]]:
    s = settings or get_settings()
    if not openai_configured(s):
        return
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_api_key(s)}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _model(s),
        "messages": messages,
        "tools": openai_tools_payload(),
        "tool_choice": tool_choice,
        "stream": True,
        "temperature": 0.45,
        "max_tokens": 180,
    }
    tool_acc: dict[int, dict] = {}
    t0 = time.perf_counter()
    first_ms: float | None = None
    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    logger.warning("openai_stream http_%s %s", resp.status_code, resp.read()[:200])
                    return
                for raw_line in resp.iter_lines():
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    data = raw_line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    piece = str(delta.get("content") or "")
                    if first_ms is None and (piece or delta.get("tool_calls")):
                        first_ms = (time.perf_counter() - t0) * 1000.0
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index") or 0)
                        slot = tool_acc.setdefault(idx, {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        nm = str(fn.get("name") or "")
                        if nm and not slot["name"]:
                            slot["name"] = nm
                        slot["args"] += str(fn.get("arguments") or "")
                    if piece:
                        yield piece, []
    except Exception as exc:
        logger.warning("openai_stream err=%s", exc)
        return
    tools_out = parse_accumulated_tool_calls(tool_acc)
    yield "", tools_out
    if first_ms is not None:
        logger.info("openai_stream ttft_ms=%.1f tools=%d", first_ms, len(tools_out))


def chat_completion_sync(
    *,
    messages: list[dict[str, str]],
    settings: Settings | None = None,
) -> tuple[str, float, list[dict]]:
    """Streaming first-token TTFT with 2.5s budget; returns empty on slow/error."""
    s = settings or get_settings()
    if not openai_configured(s):
        return "", 0.0, []
    text_parts: list[str] = []
    tools: list[dict] = []
    ttft = 0.0
    t0 = time.perf_counter()
    for piece, tcs in stream_chat_completion(messages=messages, settings=s):
        if tcs:
            tools = tcs
        if piece:
            if not text_parts:
                ttft = (time.perf_counter() - t0) * 1000.0
                if ttft > TTFT_BUDGET_MS:
                    return "", ttft, []
            text_parts.append(piece)
    if not text_parts and not tools:
        ttft = (time.perf_counter() - t0) * 1000.0
    return "".join(text_parts).strip(), ttft, tools


def chat_completion_ping(settings: Settings | None = None) -> tuple[bool, str]:
    s = settings or get_settings()
    if not openai_configured(s):
        return False, "OPENAI_API_KEY missing"
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_api_key(s)}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _model(s),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                return False, f"http_{r.status_code}"
        return True, "chat ok"
    except Exception as exc:
        return False, type(exc).__name__


def judge_completion(prompt: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if not openai_configured(s):
        return ""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {_api_key(s)}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _model(s),
        "messages": [{"role": "user", "content": prompt[:12000]}],
        "max_tokens": 400,
        "temperature": 0.2,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=45.0) as client:
            r = client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                return ""
            data = r.json()
            return str(
                data.get("choices", [{}])[0].get("message", {}).get("content") or ""
            ).strip()
    except Exception as exc:
        logger.warning("openai_judge err=%s", exc)
        return ""