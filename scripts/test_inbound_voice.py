"""Inbound Exotel+Gemini XML checks (no running server required)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "api"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def main() -> None:
    ops = client.get("/v1/ops/status")
    ops.raise_for_status()
    mode = ops.json()["telephony"]["inbound_voice_mode"]
    assert mode in ("exotel_gemini", "livekit", "sarvam"), mode

    sid = "pytest-inbound-001"
    r = client.get(
        f"/v1/webhooks/exotel/inbound?From=%2B916300729913&To=0404590002&CallSid={sid}"
    )
    r.raise_for_status()
    xml = r.text
    if mode in ("exotel_gemini", "sarvam"):
        assert "<Gather" in xml, "expected Gather in inbound XML"
        import re

        m = re.search(r"conversation/([a-f0-9-]{36})", xml)
        assert m, "missing conversation call id in Gather action"
        call_id = m.group(1)
        turn = client.post(
            f"/v1/webhooks/exotel/inbound/conversation/{call_id}",
            data={"SpeechResult": "I want to book a test drive"},
        )
        turn.raise_for_status()
        assert "<Say" in turn.text, "conversation must return Say"
    print("INBOUND_VOICE_OK", {"mode": mode})


if __name__ == "__main__":
    main()