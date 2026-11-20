"""Per-turn latency metrics on call.captured_fields (Phase E)."""

from __future__ import annotations

from typing import Any


def append_turn_metrics(fields: dict, metric: dict[str, Any]) -> dict:
    rows = list(fields.get("voice_turn_metrics") or [])
    rows.append(metric)
    fields["voice_turn_metrics"] = rows[-40:]
    return fields


def summarize_turn_metrics(fields: dict) -> dict[str, float]:
    rows = fields.get("voice_turn_metrics") or []
    def pct(key: str, p: float) -> float:
        vals = sorted(float(r[key]) for r in rows if r.get(key) is not None)
        if not vals:
            return 0.0
        i = int(round((len(vals) - 1) * p))
        return vals[i]

    return {
        "e2e_p50_ms": pct("e2e_ms", 0.5),
        "e2e_p95_ms": pct("e2e_ms", 0.95),
        "stt_p50_ms": pct("stt_final_ms", 0.5),
        "llm_p50_ms": pct("llm_ttft_ms", 0.5),
        "tts_p50_ms": pct("tts_ttfb_ms", 0.5),
        "barge_in_total": float(sum(int(r.get("barge_in") or 0) for r in rows)),
    }