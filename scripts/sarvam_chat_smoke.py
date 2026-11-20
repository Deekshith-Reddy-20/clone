"""One-shot Sarvam chat completion (sarvam-105b-conversations)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def _load_env_file() -> None:
    if not ENV_FILE.is_file():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()


def main() -> int:
    _load_env_file()
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        print("SARVAM_API_KEY is missing. Add it to .env in the project root.", file=sys.stderr)
        return 1

    from sarvamai import SarvamAI

    client = SarvamAI(api_subscription_key=key)
    response = client.chat.completions(
        model="sarvam-105b-conversations",
        messages=[{"role": "user", "content": "Say hello in one short sentence."}],
    )
    text = response.choices[0].message.content
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())