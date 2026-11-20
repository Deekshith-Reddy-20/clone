"""When safety-net tool triggers must NOT fire (informational / past tense)."""

from __future__ import annotations


def safety_net_blocked(caller_text: str) -> bool:
    t = (caller_text or "").strip()
    low = t.lower()
    if any(
        p in low or p in t
        for p in (
            "ఎలా చేయాలి",
            "ఎలా book",
            "how to book",
            "how do i book",
            "last time i booked",
            "last time i",
            "ముందు book",
            "booking process",
            "booking ఎలా",
        )
    ):
        return True
    if ("manager" in low or "మానేజర్" in t) and any(
        w in low or w in t for w in ("who", "ఎవరు", "పేరు", "name", "ఏమిటి")
    ):
        return True
    if ("visit" in low or "విజిట్" in t) and any(
        w in low for w in ("how", "ఎలా", "policy", "rules")
    ):
        return True
    if low.startswith("what is") or low.startswith("who is") or "అంటే ఏమిటి" in t:
        return True
    return False


def manager_callback_intent(caller_text: str) -> bool:
    t = (caller_text or "").strip()
    low = t.lower()
    if safety_net_blocked(t):
        return False
    wants = any(
        k in low or k in t
        for k in (
            "talk to manager",
            "speak to manager",
            "manager please",
            "human agent",
            "మానేజర్ తో",
            "మానేజర్ కావాలి",
            "మాట్లాడాలి",
        )
    )
    if "మానేజర్" in t and "ఎవరు" not in t and "పేరు" not in t:
        if any(k in t for k in ("కావాలి", "మాట్లాడ", "తో")):
            return True
    return wants


def availability_action_intent(caller_text: str) -> bool:
    if safety_net_blocked(caller_text):
        return False
    low = (caller_text or "").lower()
    return any(
        p in low or p in (caller_text or "")
        for p in (
            "check-in",
            "check in",
            "availability",
            "available",
            "అవుతుందా",
            "వస్తుందా",
            "బాగుందా",
            "శనివారం",
            "this weekend",
            "next weekend",
        )
    )


def visit_action_intent(caller_text: str) -> bool:
    if safety_net_blocked(caller_text):
        return False
    low = (caller_text or "").lower()
    return any(
        p in low or p in (caller_text or "")
        for p in (
            "site visit",
            "campus visit",
            "visit కావాలి",
            "visit ఇవ్వండి",
            "visit ఇవ్వ",
            "visit చేయండి",
            "schedule a visit",
            "book a visit",
        )
    )


def booking_create_intent(caller_text: str, fields: dict) -> bool:
    from app.services.voice.booking_state import load_booking

    if safety_net_blocked(caller_text):
        return False
    low = (caller_text or "").lower()
    if not any(
        k in low or k in (caller_text or "")
        for k in (
            "confirm booking",
            "book it",
            "yes confirm",
            "confirm చే",
            "book చేయండి",
            "book చేసి",
        )
    ):
        return False
    st = load_booking(fields)
    return bool(st.check_in or st.check_out or "november" in low or "తేదీ" in caller_text)