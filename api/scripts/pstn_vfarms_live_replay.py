#!/usr/bin/env python3
"""Live LLM replay of V Farms PSTN booking path (frozen 2026-11-20)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas.business_profile import BusinessProfile
from app.services.business_profile_render import render_profile_facts
from app.models.booking_request import VoiceBookingRequest
from app.services.voice.booking_state import load_booking
from app.services.voice.inbound_conversation import process_inbound_speech

CASE = ROOT / "tests" / "conversations" / "pstn_vfarms_20261120.json"
FIXTURES = ROOT / "tests" / "fixtures"

FLOWS = {
    "default": [
        "Checking date వచ్చేసి నేను ఎల్లుండి వద్దామనుకుంటున్నాను.",
        "4 వస్తారు.",
        "2 nights.",
        "అవును, ఇలాగే పెట్టండి.",
    ],
    "nights_first": [
        "2 nights, ఎల్లుండి రావాలి.",
        "4 వస్తారు.",
        "అవును book చేయండి.",
    ],
    "date_correct": [
        "ఎల్లుండి check-in.",
        "లేదు, వచ్చే ఆదివారం అండి.",
        "4 వస్తారు.",
        "1 night.",
        "సరే confirm.",
    ],
    "pool_mid": [
        "ఎల్లుండి రావాలి.",
        "pool ఉందా?",
        "4 వస్తారు.",
        "2 nights.",
        "అవును.",
    ],
    "no_pool_mid": [
        "ఎల్లుండి రావాలి.",
        "pool ఉందా?",
        "2 nights.",
        "4 వస్తారు.",
        "అవును.",
    ],
    "price_before_confirm": [
        "ఎల్లుండి check-in.",
        "4 వస్తారు.",
        "2 nights.",
        "price ఎంత?",
        "సరే పెట్టండి.",
    ],
    "reject_nights": [
        "ఎల్లుండి check-in.",
        "4 వస్తారు.",
        "2 nights.",
        "వద్దు, 3 nights.",
        "అవును.",
    ],
}


FLOW_PROFILE = {
    "no_pool_mid": "vfarms_no_pool_profile.json",
}


def _neg_checks(reply: str, failed: list[str]) -> None:
    data = json.loads(CASE.read_text(encoding="utf-8"))
    for bad in data["expectations"]["forbid_agent_substrings"]:
        if bad in (reply or ""):
            failed.append(f"forbid {bad!r}")
    for bad in (
        "rooms available",
        "December",
        "11th December",
        "Dec 11",
        "30th November",
        "November 30",
    ):
        if bad.lower() in (reply or "").lower():
            failed.append(f"ungrounded {bad!r}")


def _judge(transcript: str, scenario: str) -> dict | None:
    from app.services.voice.gemini import gemini_configured, generate_agent_reply
    from app.services.voice.voice_llm_primary import judge_provider_for_run
    from app.services.voice.voice_openai_chat import judge_completion, openai_configured

    jp = judge_provider_for_run()
    rubric = (
        "You are a strict QA judge. Score 1-5 with a one-sentence reason per dimension.\n"
        "task_success: slot order, one create_booking after yes, outcome.\n"
        "naturalness: Telugu/codemix, varied acks, one slot question per collecting turn.\n"
        "correctness: dates/guests; no amenity claims absent from FACTS; full weekday/month; "
        "no pre-confirm commitment (బుక్ చేస్తాం).\n"
    )
    prompt = (
        f"{rubric}Scenario={scenario}. Output ONLY JSON:\n"
        '{"task_success":N,"task_success_reason":"...",'
        '"naturalness":N,"naturalness_reason":"...",'
        '"correctness":N,"correctness_reason":"..."}\n\n'
        f"{transcript}"
    )
    raw = ""
    if jp == "openai" and openai_configured():
        raw = judge_completion(prompt).strip()
    elif jp == "gemini" and gemini_configured():
        raw = generate_agent_reply(
            employee_brief="Output only valid JSON.",
            caller_text=prompt,
            history=[],
        ).strip()
    elif jp == "sarvam":
        from app.services.voice.sarvam import sarvam_configured
        from app.services.voice.voice_sarvam_chat import chat_completion_sync

        if sarvam_configured():
            raw, _, _ = chat_completion_sync(
                messages=[
                    {"role": "system", "content": "Output only valid JSON."},
                    {"role": "user", "content": prompt},
                ]
            )
            raw = (raw or "").strip()
        else:
            return None
    else:
        return None
    if not raw:
        return None
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(m.group(0) if m else raw)
        for k in (
            "task_success",
            "naturalness",
            "correctness",
            "task_success_reason",
            "naturalness_reason",
            "correctness_reason",
        ):
            data.setdefault(k, "")
        data["judge_provider"] = jp
        return data
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None


def run_flow(flow_key: str) -> tuple[int, str]:
    if os.getenv("KARYUK_RUN_LIVE_LLM") != "1":
        print("Set KARYUK_RUN_LIVE_LLM=1")
        return 2, ""

    os.environ["KARYUK_CALL_DATE"] = "2026-11-20"
    os.environ.setdefault("KARYUK_VOICE_LLM_FIRST", "1")

    data = json.loads(CASE.read_text(encoding="utf-8"))
    prof_name = FLOW_PROFILE.get(flow_key, data["meta"]["profile_fixture"])
    prof = json.loads((FIXTURES / prof_name).read_text(encoding="utf-8"))
    facts = render_profile_facts(BusinessProfile.from_snapshot(prof))
    db = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    booking_rows: list = []

    def _add(obj):
        if isinstance(obj, VoiceBookingRequest):
            booking_rows.append(obj)

    db.add = _add

    call = MagicMock()
    call.workspace_id = "00000000-0000-0000-0000-000000000001"
    call.id = "00000000-0000-0000-0000-000000000010"
    call.captured_fields = {
        "employee_brief": data["meta"]["employee_brief"],
        "employee_language": "Telugu",
        "employee_spoken_facts": facts,
        "employee_business_profile": prof,
        "employee_natural_spoken": True,
        "conversation_language": "te-IN",
        "caller_e164": "+919876543210",
        "inbound_chat": {"turns": []},
    }

    flow = FLOWS[flow_key]
    failed: list[str] = []
    lines: list[str] = [f"=== LIVE REPLAY ({flow_key}, frozen 2026-11-20) ===\n"]
    readback_seen = False
    create_count_at_readback = 0

    for i, caller in enumerate(flow):
        before_tools = [
            t.get("name")
            for t in (call.captured_fields or {}).get("tool_log") or []
        ]
        reply, _ = process_inbound_speech(db, call, caller_text=caller, stt_language="te-IN")
        lines.append(f"Caller: {caller}")
        lines.append(f"Agent:  {reply}\n")
        _neg_checks(reply or "", failed)

        if flow_key == "no_pool_mid" and "pool" in caller.lower():
            low = (reply or "").lower()
            if re.search(r"(pool\s+ఉంది|swimming\s+pool\s+ఉంది|మాకు\s+.+pool)", reply or "", re.I):
                failed.append("no_pool: agent claimed pool ఉంది")
            if "pool ఉంది" in (reply or ""):
                failed.append("no_pool: must not assert pool")

        if i == 1 and flow_key == "default" and "4 వస్తారు" in caller:
            if not re.search(r"(ఎన్ని\s*nights|nights)", reply or "", re.I):
                failed.append("after 4 వస్తారు agent must ask nights")

        if re.search(r"(పెట్టమంటారా|nights.*guests)", reply or "", re.I):
            readback_seen = True
            create_count_at_readback = before_tools.count("create_booking")

        if flow_key == "reject_nights" and "వద్దు" in caller:
            if not re.search(r"3\s*nights", reply or "", re.I):
                failed.append("reject_nights: read-back should show 3 nights")
            if "పెట్టమంటారా" not in (reply or ""):
                failed.append("reject_nights: code read-back required after correction")
            tools_now = [
                t.get("name")
                for t in (call.captured_fields or {}).get("tool_log") or []
            ]
            if "create_booking" in tools_now:
                failed.append("reject_nights: create_booking before yes after correction")

    st = load_booking(call.captured_fields)
    exp = data["expectations"]
    if flow_key == "default":
        if st.check_in != exp["check_in"]:
            failed.append(f"check_in {st.check_in} != {exp['check_in']}")
        if st.guest_count != exp["guest_count"]:
            failed.append(f"guests {st.guest_count} != {exp['guest_count']}")
        if not readback_seen:
            failed.append("read-back with date/nights/guests before create")
        if create_count_at_readback > 0:
            failed.append("create_booking before read-back confirm")
        tools = [t.get("name") for t in (call.captured_fields or {}).get("tool_log") or []]
        if tools.count("create_booking") != 1:
            failed.append(f"create_booking count {tools.count('create_booking')} != 1")
        if len(booking_rows) != 1:
            failed.append(f"booking request rows {len(booking_rows)} != 1")

    if flow_key == "reject_nights":
        if st.nights != 3:
            failed.append(f"expected 3 nights after correction, got {st.nights}")
        tools = [t.get("name") for t in (call.captured_fields or {}).get("tool_log") or []]
        if tools.count("create_booking") != 1:
            failed.append(f"reject_nights: create_booking count {tools.count('create_booking')}")

    transcript = "\n".join(lines)
    judge = _judge(transcript, flow_key)
    lines.append("=== SUMMARY ===")
    lines.append(f"check_in={st.check_in} guests={st.guest_count} nights={st.nights}")
    lines.append(f"tools={[t.get('name') for t in (call.captured_fields or {}).get('tool_log') or []]}")
    for f in failed:
        lines.append(f"FAIL: {f}")
    if judge is None:
        lines.append("judge: unavailable")
    else:
        lines.append(
            "JUDGE raw: "
            f"task_success={judge.get('task_success')} ({judge.get('task_success_reason')}) | "
            f"naturalness={judge.get('naturalness')} ({judge.get('naturalness_reason')}) | "
            f"correctness={judge.get('correctness')} ({judge.get('correctness_reason')})"
        )
        if int(judge.get("task_success", 0)) < 4:
            failed.append(f"task_success {judge.get('task_success')} < 4")

    print("\n".join(lines))
    return (1 if failed else 0), transcript


def main() -> int:
    variant = os.getenv("KARYUK_REPLAY_VARIANT", "default")
    if variant == "all":
        code = 0
        for k in FLOWS:
            c, _ = run_flow(k)
            code = max(code, c)
        return code
    c, _ = run_flow(variant)
    return c


if __name__ == "__main__":
    raise SystemExit(main())