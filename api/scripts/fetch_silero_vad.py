"""Download Silero VAD onnx into app/services/voice/data/ (production image)."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
OUT = Path(__file__).resolve().parents[1] / "app" / "services" / "voice" / "data" / "silero_vad.onnx"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.is_file() and OUT.stat().st_size > 10_000:
        print(f"silero model exists {OUT}")
        return 0
    print(f"fetching {URL} -> {OUT}")
    urllib.request.urlretrieve(URL, OUT)
    print("done", OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())