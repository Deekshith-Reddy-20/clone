#!/usr/bin/env python3
"""Run live suite + default replay for sarvam and openai primaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], env: dict) -> str:
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return (p.stdout or "") + (p.stderr or "")


def main() -> int:
    base = os.environ.copy()
    base["KARYUK_RUN_LIVE_LLM"] = "1"
    base.setdefault("KARYUK_CALL_DATE", "2026-11-20")
    base.setdefault("KARYUK_VOICE_LLM_FIRST", "1")
    base.setdefault("KARYUK_LLM_FAILOVER", "openai")
    base.setdefault("KARYUK_JUDGE_PROVIDER", "openai")

    py = str(ROOT / ".venv" / "bin" / "python")
    blocks: list[str] = []
    for primary in ("sarvam", "openai"):
        env = {**base, "KARYUK_LLM_PRIMARY": primary}
        blocks.append(f"\n######## PRIMARY={primary} ########\n")
        blocks.append(_run([py, "scripts/live_suite_report.py"], env))
        blocks.append(_run([py, "scripts/pstn_vfarms_live_replay.py"], {**env, "KARYUK_REPLAY_VARIANT": "default"}))
    out = "\n".join(blocks)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())