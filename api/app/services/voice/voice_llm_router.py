"""Inbound LLM with configurable primary + failover (2.5s TTFT budget)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.config import get_settings
from app.services.voice.gemini import gemini_configured
from app.services.voice.gemini import generate_agent_reply as generate_gemini
from app.services.voice.gemini import generate_agent_reply_with_tools
from app.services.voice.sarvam import sarvam_configured
from app.services.voice.voice_llm_primary import llm_failover_chain, llm_primary_provider
from app.services.voice.voice_openai_chat import (
    chat_completion_sync as openai_chat_completion_sync,
    openai_configured,
    stream_chat_completion as openai_stream_chat_completion,
)
from app.services.voice.voice_sarvam_chat import chat_completion_sync, stream_chat_completion

logger = logging.getLogger(__name__)

SARVAM_TTFT_BUDGET_MS = 2500.0


@dataclass
class LlmTurnResult:
    text: str
    ttft_ms: float
    provider: str
    failover_from: str | None = None
    failover_reason: str | None = None
    tool_calls: list[dict] | None = None


def _build_messages(
    *,
    system_prompt: str,
    employee_brief: str,
    caller_text: str,
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    sys_content = f"{system_prompt}\n\n{employee_brief}".strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": sys_content[:12000]}]
    for turn in history[-10:]:
        role = turn.get("role")
        if role == "user":
            messages.append({"role": "user", "content": turn.get("text", "")[:500]})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": turn.get("text", "")[:500]})
    messages.append({"role": "user", "content": (caller_text or "Hello")[:800]})
    return messages


def _provider_ready(name: str) -> bool:
    if name == "sarvam":
        return sarvam_configured()
    if name == "gemini":
        return gemini_configured()
    if name == "openai":
        return openai_configured()
    return False


def _try_sarvam(messages: list[dict[str, str]]) -> tuple[str, float, list[dict], str]:
    t0 = time.perf_counter()
    try:
        raw, ttft, tools = chat_completion_sync(messages=messages)
        if raw.strip() or tools:
            return raw, ttft or (time.perf_counter() - t0) * 1000, tools, "ok"
        if ttft > SARVAM_TTFT_BUDGET_MS:
            return "", ttft, [], "sarvam_ttft_timeout"
        return "", ttft, [], "sarvam_empty"
    except Exception as exc:
        return "", (time.perf_counter() - t0) * 1000, [], f"sarvam_error:{type(exc).__name__}"


def _try_openai(messages: list[dict[str, str]]) -> tuple[str, float, list[dict], str]:
    t0 = time.perf_counter()
    try:
        raw, ttft, tools = openai_chat_completion_sync(messages=messages)
        if raw.strip() or tools:
            return raw, ttft or (time.perf_counter() - t0) * 1000, tools, "ok"
        if ttft > SARVAM_TTFT_BUDGET_MS:
            return "", ttft, [], "openai_ttft_timeout"
        return "", ttft, [], "openai_empty"
    except Exception as exc:
        return "", (time.perf_counter() - t0) * 1000, [], f"openai_error:{type(exc).__name__}"


def _try_gemini(
    *,
    system_prompt: str,
    employee_brief: str,
    caller_text: str,
    history: list[dict[str, str]],
) -> tuple[str, float, list[dict], str]:
    t0 = time.perf_counter()
    try:
        gtxt, gtools = generate_agent_reply_with_tools(
            system_prompt=f"{system_prompt}\n\n{employee_brief}",
            caller_text=caller_text,
            history=history,
        )
        if not gtxt and not gtools:
            gtxt = generate_gemini(
                employee_brief=f"{system_prompt}\n\n{employee_brief}",
                caller_text=caller_text,
                history=history,
            )
        ttft = (time.perf_counter() - t0) * 1000.0
        if gtxt.strip() or gtools:
            return gtxt, ttft, gtools, "ok"
        return "", ttft, [], "gemini_empty"
    except Exception as exc:
        return "", (time.perf_counter() - t0) * 1000, [], f"gemini_error:{type(exc).__name__}"


def generate_inbound_llm_turn(
    *,
    system_prompt: str,
    employee_brief: str,
    spoken_facts: str,
    caller_text: str,
    history: list[dict[str, str]],
    bcp47: str,
    vertical: str,
    website_url: str | None,
    natural_spoken: bool,
) -> LlmTurnResult:
    del spoken_facts, bcp47, vertical, website_url, natural_spoken
    messages = _build_messages(
        system_prompt=system_prompt,
        employee_brief=employee_brief,
        caller_text=caller_text,
        history=history,
    )
    chain = llm_failover_chain()
    primary = chain[0] if chain else llm_primary_provider()
    last_reason = "primary_skipped"
    last_ttft = 0.0

    for i, prov in enumerate(chain):
        if not _provider_ready(prov):
            last_reason = f"{prov}_not_configured"
            continue
        if prov == "sarvam":
            raw, ttft, tools, reason = _try_sarvam(messages)
        elif prov == "openai":
            raw, ttft, tools, reason = _try_openai(messages)
        elif prov == "gemini":
            raw, ttft, tools, reason = _try_gemini(
                system_prompt=system_prompt,
                employee_brief=employee_brief,
                caller_text=caller_text,
                history=history,
            )
        else:
            last_reason = f"unknown_provider:{prov}"
            continue
        last_ttft = ttft
        if reason == "ok" and (raw.strip() or tools):
            fo = primary if i > 0 else None
            logger.info(
                "llm_turn provider=%s ttft_ms=%.1f reason=ok tools=%d failover_from=%s",
                prov,
                ttft,
                len(tools),
                fo,
            )
            return LlmTurnResult(
                raw.strip(),
                ttft,
                prov,
                failover_from=fo,
                failover_reason=last_reason if i > 0 else None,
                tool_calls=tools,
            )
        last_reason = reason

    get_settings()
    return LlmTurnResult("", last_ttft, primary, failover_reason=last_reason, tool_calls=[])


async def iter_inbound_llm_stream(
    *,
    system_prompt: str,
    employee_brief: str,
    spoken_facts: str,
    caller_text: str,
    history: list[dict[str, str]],
    bcp47: str,
    vertical: str,
    website_url: str | None,
    natural_spoken: bool,
) -> AsyncIterator[tuple]:
    del spoken_facts, bcp47, vertical, website_url, natural_spoken
    messages = _build_messages(
        system_prompt=system_prompt,
        employee_brief=employee_brief,
        caller_text=caller_text,
        history=history,
    )
    chain = llm_failover_chain()
    reason = "not_configured"

    def _stream_provider(prov: str) -> list[tuple]:
        events: list[tuple] = []
        t0 = time.perf_counter()
        first = True
        tools: list[dict] = []
        stream_fn = stream_chat_completion if prov == "sarvam" else openai_stream_chat_completion
        try:
            for piece, tcs in stream_fn(messages=messages):
                if first and (piece or tcs):
                    events.append(("ttft", (time.perf_counter() - t0) * 1000.0, prov))
                    first = False
                if tcs:
                    tools = tcs
                if piece:
                    if first:
                        events.append(("ttft", (time.perf_counter() - t0) * 1000.0, prov))
                        first = False
                    events.append(("token", piece))
            if first:
                events.append(("ttft", (time.perf_counter() - t0) * 1000.0, prov))
            events.append(("tools", tools))
            return events
        except Exception as exc:
            events.append(("stream_error", str(exc)))
            return events

    loop = asyncio.get_running_loop()
    for prov in chain:
        if prov not in ("sarvam", "openai") or not _provider_ready(prov):
            reason = f"{prov}_not_configured"
            continue
        try:
            events = await asyncio.wait_for(
                loop.run_in_executor(None, lambda p=prov: _stream_provider(p)),
                timeout=SARVAM_TTFT_BUDGET_MS / 1000 + 8.0,
            )
        except asyncio.TimeoutError:
            reason = f"{prov}_ttft_timeout"
            continue
        if events and events[0][0] == "ttft" and events[0][1] > SARVAM_TTFT_BUDGET_MS:
            reason = f"{prov}_ttft_timeout"
            continue
        if any(e[0] == "stream_error" for e in events):
            reason = f"{prov}_error"
            continue
        if events:
            if prov != chain[0]:
                yield ("failover", reason, prov)
            for ev in events:
                yield ev
            return
        reason = f"{prov}_empty"

    if gemini_configured():
        t1 = time.perf_counter()
        gtxt, gtools = await loop.run_in_executor(
            None,
            lambda: generate_agent_reply_with_tools(
                system_prompt=f"{system_prompt}\n\n{employee_brief}",
                caller_text=caller_text,
                history=history,
            ),
        )
        ttft = (time.perf_counter() - t1) * 1000.0
        yield ("failover", reason, "gemini")
        yield ("ttft", ttft, "gemini")
        for i in range(0, len(gtxt), 12):
            yield ("token", gtxt[i : i + 12])
        yield ("tools", gtools)
        return

    yield ("failover", reason, "none")
    yield ("ttft", 0.0, "none")
    yield ("tools", [])