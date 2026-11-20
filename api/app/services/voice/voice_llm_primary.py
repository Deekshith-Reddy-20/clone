"""Which LLM provider is primary for inbound turns."""

from __future__ import annotations

import os


def llm_primary_provider() -> str:
    v = (os.getenv("KARYUK_LLM_PRIMARY") or "sarvam").strip().lower()
    if v in ("gemini", "google"):
        return "gemini"
    if v == "openai":
        return "openai"
    return "sarvam"


def llm_failover_chain() -> list[str]:
    """Primary first, then KARYUK_LLM_FAILOVER (comma-separated), deduped."""
    chain = [llm_primary_provider()]
    raw = (os.getenv("KARYUK_LLM_FAILOVER") or "openai").strip()
    for part in raw.split(","):
        p = part.strip().lower()
        if p in ("google",):
            p = "gemini"
        if p and p not in chain:
            chain.append(p)
    return chain


def judge_provider_name() -> str:
    return (os.getenv("KARYUK_JUDGE_PROVIDER") or "openai").strip().lower()


def _provider_configured(name: str) -> bool:
    if name == "sarvam":
        from app.services.voice.sarvam import sarvam_configured

        return sarvam_configured()
    if name == "gemini":
        from app.services.voice.gemini import gemini_configured

        return gemini_configured()
    if name == "openai":
        from app.services.voice.voice_openai_chat import openai_configured

        return openai_configured()
    return False


def judge_provider_for_run() -> str:
    """Judge must not use the same provider as primary for this run."""
    primary = llm_primary_provider()
    preferred = judge_provider_name()
    candidates: list[str] = []
    if preferred != primary:
        candidates.append(preferred)
    for p in llm_failover_chain():
        if p != primary and p not in candidates:
            candidates.append(p)
    for p in ("openai", "gemini", "sarvam"):
        if p != primary and p not in candidates:
            candidates.append(p)
    for p in candidates:
        if _provider_configured(p):
            return p
    return candidates[0] if candidates else preferred


def use_sarvam_llm_primary() -> bool:
    return llm_primary_provider() == "sarvam"


def use_gemini_llm_primary() -> bool:
    return llm_primary_provider() == "gemini"


def use_openai_llm_primary() -> bool:
    return llm_primary_provider() == "openai"