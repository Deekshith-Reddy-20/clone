#!/usr/bin/env python3
"""Verify inbound AI employee chain: DB → dispatch → public webhooks → WS (optional Sarvam)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import websockets

from app.config import get_settings
from app.database import SessionLocal
from app.models import Employee
from app.services.calls import _employee_snapshot, resolve_inbound_employee
from app.services.telephony import telephony_status_payload
from app.services.voice.session_trace import _build_sha


def _check(name: str, ok: bool, detail: object) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


async def _ws_handshake(wss_url: str) -> dict:
    import ssl

    try:
        ssl_ctx = ssl.create_default_context()
        async with websockets.connect(wss_url, open_timeout=12, ssl=ssl_ctx) as ws:
            await ws.send(json.dumps({"event": "connected"}))
            await ws.send(
                json.dumps(
                    {
                        "event": "start",
                        "stream_sid": "e2e-probe",
                        "start": {"mediaFormat": {"encoding": "audio/l16", "sampleRate": 8000}},
                    }
                )
            )
            deadline = asyncio.get_event_loop().time() + 45
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                except asyncio.TimeoutError:
                    continue
                if any(k in raw for k in ('"event": "media"', '"event": "mark"', '"event": "transcript"')):
                    return {"connected": True, "first_event": raw[:220]}
            return {"connected": True, "first_event": None, "note": "session up; greeting TTS may be blocked (Sarvam quota)"}
    except Exception as e:
        return {"error": str(e)[:200] or type(e).__name__}


async def run(*, ws_probe: bool, sarvam_ping: bool) -> int:
    settings = get_settings()
    base_local = "http://127.0.0.1:8010"
    base_public = settings.public_api_base_url.rstrip("/")
    checks: list[dict] = []

    tel = telephony_status_payload(settings)
    to_raw = (settings.exotel_caller_id or "").strip() or "0404590002"
    db = SessionLocal()
    try:
        route = resolve_inbound_employee(db, to_raw=to_raw, settings=settings)
        if route:
            emp = db.get(Employee, route[1])
            snap = _employee_snapshot(db, emp) if emp else {}
            route_detail = {
                "exophone": to_raw,
                "employee_id": str(route[1]),
                "published": bool(emp and emp.active_version_id),
                "speaker": snap.get("tts_speaker"),
                "revision": snap.get("revision"),
                "call_mode": snap.get("mode"),
            }
        else:
            route_detail = {"error": "no_employee_for_exophone", "exophone": to_raw}
        checks.append(_check("db_inbound_route", bool(route), route_detail))
    finally:
        db.close()

    checks.append(
        _check(
            "worker_build",
            True,
            {"sha": _build_sha(), "inbound_voice_mode": tel.get("inbound_voice_mode")},
        )
    )

    for label, base in (("health_local", base_local), ("health_public", base_public)):
        try:
            r = httpx.get(f"{base}/health", timeout=8)
            checks.append(_check(label, r.status_code == 200 and r.json().get("status") == "ok", r.json()))
        except Exception as e:
            checks.append(_check(label, False, str(e)[:160]))

    try:
        r = httpx.get(f"{base_local}/v1/ops/status", timeout=8)
        checks.append(_check("ops_telephony", r.status_code == 200, r.json().get("telephony", {})))
    except Exception as e:
        checks.append(_check("ops_telephony", False, str(e)[:160]))

    voicebot_url = tel.get("exotel_voicebot_resolve_url") or f"{base_public}/v1/webhooks/exotel/voicebot"
    try:
        r = httpx.post(
            voicebot_url,
            data={
                "From": "+919988776655",
                "To": to_raw,
                "CallSid": f"e2e-{uuid.uuid4().hex[:12]}",
            },
            timeout=15,
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        wss = body.get("url") or ""
        ok = r.status_code == 200 and wss.startswith("wss://") and "/v1/ws/exotel/voice/" in wss
        checks.append(_check("voicebot_resolve_public", ok, {"status": r.status_code, "url": wss}))
    except Exception as e:
        checks.append(_check("voicebot_resolve_public", False, str(e)[:160]))
        wss = ""

    if ws_probe and wss:
        hs = await _ws_handshake(wss)
        checks.append(_check("voicebot_wss_connect", "error" not in hs, hs))

    try:
        r = httpx.get("https://127.0.0.1:5174/health", verify=False, timeout=5)
        checks.append(_check("vite_https_proxy_health", r.status_code == 200, {"status": r.status_code}))
    except Exception as e:
        checks.append(_check("vite_https_proxy_health", False, str(e)[:160]))

    if sarvam_ping:
        from app.services.voice.sarvam import sarvam_media_ready

        sarvam_ok, sarvam_reason = sarvam_media_ready(probe=True)
        checks.append(
            _check("sarvam_media", sarvam_ok, {"ready": sarvam_ok, "reason": sarvam_reason})
        )

    critical = {c["name"] for c in checks if c["name"] != "sarvam_media"}
    report = {
        "ok": all(c["ok"] for c in checks if c["name"] in critical),
        "sarvam_ok": all(c["ok"] for c in checks if c["name"] == "sarvam_media") if sarvam_ping else None,
        "flow": [
            "PSTN → Exotel Voicebot applet → POST " + voicebot_url,
            "→ JSON wss URL → /v1/ws/exotel/voice/{call_id}",
            "→ ExotelVoicebotSession + Sarvam STT/TTS + published employee",
            "Browser: https://<host>:5174 → Team voice preview (same WS path)",
        ],
        "exotel_applet_voicebot_url": voicebot_url,
        "exotel_xml_url_note": (
            "/v1/webhooks/exotel/inbound is Say+Gather (Exotel speech), not Sarvam media WS. "
            "Use Voicebot URL above for Telugu/Sarvam."
        ),
        "checks": checks,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ws", action="store_true", help="Open a short WSS handshake after voicebot resolve")
    p.add_argument("--sarvam", action="store_true", help="Ping Sarvam TTS (uses quota)")
    args = p.parse_args()
    return asyncio.run(run(ws_probe=args.ws, sarvam_ping=args.sarvam))


if __name__ == "__main__":
    raise SystemExit(main())