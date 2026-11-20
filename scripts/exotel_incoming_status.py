"""Print ExoPhone VoiceUrl from Exotel API vs .env PUBLIC_API_BASE_URL."""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    base = s.public_api_base_url.rstrip("/")
    want_inbound = f"{base}/v1/webhooks/exotel/inbound"
    want_voicebot = f"{base}/v1/webhooks/exotel/voicebot"
    from app.services.telephony.inbound_mode import resolved_inbound_voice_mode

    voice_mode = resolved_inbound_voice_mode(s)
    want = want_voicebot if voice_mode == "sarvam" else want_inbound
    root = s.exotel_api_base_url.rstrip("/")
    auth = base64.b64encode(f"{s.exotel_api_key}:{s.exotel_api_token}".encode()).decode()
    url = f"{root}/v1/Accounts/{s.exotel_account_sid}/IncomingPhoneNumbers.json"
    r = httpx.get(url, headers={"Authorization": f"Basic {auth}"}, timeout=25)
    r.raise_for_status()
    ipn = r.json().get("IncomingPhoneNumber", {})
    voice = ipn.get("VoiceUrl") or ""
    phone = ipn.get("PhoneNumber") or ""
    flow_applet = "start_voice" in voice or "exoml" in voice
    ok = want in voice or voice == want
    print(f"ExoPhone:   {phone}")
    print(f"VoiceUrl:   {voice}")
    print(f"Mode:       {voice_mode}")
    print(f"Karyuk URL: {want}")
    if voice_mode == "sarvam":
        print(f"Also OK:    Voicebot applet inside Exotel flow → {want_voicebot}")
    if ok:
        print("MATCH:      yes (ExoPhone points at Karyuk)")
        return 0
    if flow_applet:
        print("MATCH:      Exotel *flow* URL (normal) — open that flow in my.exotel.com and set:")
        if voice_mode == "sarvam":
            print(f"            Voicebot applet URL = {want_voicebot}")
            print("            Flow: Call Start → Voicebot (no Hangup after). Save & assign to ExoPhone.")
        else:
            print(f"            Passthru/HTTP URL = {want_inbound}  OR Voicebot = {want_voicebot}")
        return 1
    print("MATCH:      NO — calls may never hit Karyuk (fix flow in Exotel dashboard)")
    # Recent inbound
    calls = httpx.get(
        f"{root}/v1/Accounts/{s.exotel_account_sid}/Calls.json?PageSize=3&SortBy=DateCreated:desc",
        headers={"Authorization": f"Basic {auth}"},
        timeout=25,
    ).json().get("Calls", [])
    for c in calls[:3]:
        if (c.get("Direction") or "").lower() == "inbound":
            print(
                f"Recent IB: {c.get('StartTime')} duration={c.get('Duration')}s status={c.get('Status')}"
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())