"""Published employee playbook: brief, website, hire template — used on every inbound turn."""

from __future__ import annotations

import re
from app.services.voice.booking_state import load_booking


def is_pool_timing_question(text: str) -> bool:
    low = (text or "").lower()
    te = text or ""
    markers = (
        "pool",
        "swimming",
        "పూల్",
        "पूल",
        "timings",
        "timing",
        "open",
        "close",
        "hours",
        "గంటల",
        "తెరుస్తారు",
        "తెరుచు",
    )
    return any(m in low or m in te for m in markers)


_POOL_TIME_RE = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))",
    re.I,
)


def _pool_hours_from_corpus(corpus: str) -> tuple[str | None, str | None]:
    low_corpus = corpus.lower()
    if not any(k in low_corpus for k in ("pool", "swimming")) and "పూల్" not in corpus:
        return None, None
    pool_blob = corpus
    if not pool_blob.strip():
        return None, None
    times = [t.upper().replace(" ", "") for t in _POOL_TIME_RE.findall(pool_blob)]
    low = pool_blob.lower()
    if len(times) >= 2:
        return times[0], times[-1]
    if len(times) == 1:
        if "close" in low:
            return None, times[0]
        return times[0], None
    return None, None


def try_pool_timing_reply(
    caller_text: str,
    *,
    website_knowledge: str | None,
    brief: str,
    lang: str,
) -> str | None:
    if not is_pool_timing_question(caller_text):
        return None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    open_t, close_t = _pool_hours_from_corpus(corpus)
    has_pool = any(
        k in corpus.lower() or k in corpus
        for k in ("pool", "swimming", "పూల్")
    )
    if lang == "te-IN":
        if open_t and close_t:
            return f"పూల్ {open_t} నుంచి {close_t} వరకు తెరిచి ఉంటుంది."
        if open_t:
            return f"పూల్ {open_t} నుంచి తెరుస్తారు."
        return (
            "పూల్ ఉంది. కానీ ఎన్ని గంటల నుంచి ఎన్ని గంటల వరకు తెరిచి ఉంటుందో "
            "ప్రచురిత నాలెడ్జ్‌లో లేదు."
        )
    if lang == "hi-IN":
        if open_t and close_t:
            return f"पूल {open_t} से {close_t} तक खुला रहता है।"
        if has_pool:
            return "पूल है, लेकिन घंटों का विवरण यहाँ नहीं है।"
        return None
    if open_t and close_t:
        return f"The pool is open {open_t} to {close_t}."
    return "We have a pool, but opening hours are not in our published knowledge."


_AGENT_NAME_PATTERNS = (
    re.compile(r"(?:your name is|i am|i'm|call me|this is)\s+([A-Za-z][a-z]{1,20})", re.I),
    re.compile(r"(?:నా పేరు|నేను)\s+([A-Za-z][a-z]{1,20})", re.I),
    re.compile(r"(?:me|mai|i am)\s+([A-Za-z][a-z]{1,20})", re.I),
)


def agent_name_from_brief(brief: str) -> str | None:
    text = (brief or "").strip()
    if not text:
        return None
    for pat in _AGENT_NAME_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip().title()
    m = re.search(r"\bfor\s+([A-Z][a-z]{2,16})\b", text)
    if m:
        return m.group(1).strip()
    return None


def is_caller_identity_question(text: str) -> bool:
    te = text or ""
    low = te.lower()
    if is_resort_name_question(text) or is_location_question(text):
        return False
    if any(p in te for p in ("మీ resort", "resort పేరు", "hotel పేరు", "property name")):
        return False
    return any(
        p in te or p in low
        for p in (
            "నీ పేరు",
            "నీవు ఎవరు",
            "మీ పేరు",
            "your name",
            "who are you",
            "what is your name",
            "పేరేం",
            "పేరేం పేరు",
            "పేరు ఏంటి",
            "ఎవరు మాట్లాడ",
        )
    )


def is_resort_name_question(text: str) -> bool:
    te = text or ""
    low = te.lower()
    if any(p in te or p in low for p in ("booking", "బుక్", "ఉందా", "availability", "అవైలబిలిటీ", "check in", "తారీఖు")):
        return False
    explicit_name = "పేరు" in te or "name" in low or "ఏం పేర" in te or "ఏం పేరు" in te
    if not explicit_name:
        return False
    return any(
        p in te or p in low
        for p in (
            "resort పేరు",
            "hotel పేరు",
            "property name",
            "business name",
            "మీ resort",
            "రిసార్ట్ పేరు",
            "resort name",
        )
    ) or ("resort" in low or "రిసార్ట్" in te or "ఫార్మ" in te or "v farm" in low or "v-form" in low)


def _sanitize_location_phrase(fact: str) -> str:
    s = (fact or "").strip()
    s = re.sub(
        r"^(hello[,!]?\s*)?(welcome to\s+[^,.\n]+[,!]?\s*)",
        "",
        s,
        flags=re.I,
    ).strip()
    s = re.sub(r"^(hi[,!]?\s*)", "", s, flags=re.I).strip()
    if len(s) > 110:
        s = s[:107].rstrip() + "…"
    return s or fact.strip()


def is_location_confirm_question(text: str) -> bool:
    te = text or ""
    low = te.lower()
    return bool(
        re.search(r"(మొత్తం|पूरा|full|complete|entire).{0,24}(location|లోకేషన్|address|చిరునామా)", te + low, re.I)
        or re.search(r"location-?\s*ఆ|location\s*aa\b", low + te, re.I)
        or ("అదేనా" in te and "లోకేషన్" in te)
    )


def is_business_contact_question(text: str) -> bool:
    """Public office / reception / property phone — not the agent's private mobile."""
    te = (text or "").strip()
    if len(te) < 6:
        return False
    low = te.lower()
    if re.search(r"(personal|private|వ్యక్తిగత|నిజి).{0,20}(number|phone|mobile)", low + te, re.I):
        return False
    office_markers = (
        "office number",
        "office phone",
        "reception number",
        "reception phone",
        "contact number",
        "business number",
        "hotel number",
        "resort number",
        "property number",
        "call this number",
        "ఆఫీస్ నంబర్",
        "ఆఫీస్ ఫోన్",
        "రిసెప్షన్ నంబర్",
        "కాంటాక్ట్ నంబర్",
        "ఫోన్ నంబర్ చెప్ప",
        "నంబర్ ఇవ్వ",
        "number ఇవ్వ",
        "number చెప్ప",
        "number తో",
        "నంబర్ తో",
    )
    if any(m in te or m in low for m in office_markers):
        return True
    if re.search(r"(office|reception|resort|hotel|property|ఆఫీస్|రిసెప్షన్).{0,32}(number|phone|నంబర్|ఫోన్)", te + low, re.I):
        return True
    if re.search(r"(నంబర్|number).{0,40}(ఇవ్వ|చెప్ప|తెలుసు|దీయ)", te + low, re.I) and re.search(
        r"(office|reception|call|contact|ఆఫీస్|డైల్|మర్చిపోయాను)", te + low, re.I
    ):
        return True
    return False


def extract_business_phones(corpus: str) -> list[str]:
    hits: list[str] = []
    seen: set[str] = set()
    blob = corpus or ""
    patterns = (
        r"(?:\+91[\s-]?)?[6-9]\d{9}",
        r"\b0\d{9,11}\b",
        r"\b0\d{2,4}[\s-]?\d{7,8}\b",
        r"\b[6-9]\d{2}[\s-]?\d{3}[\s-]?\d{4}\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, blob):
            raw = m.group(0)
            digits = re.sub(r"\D", "", raw)
            if len(digits) < 10:
                continue
            if digits.startswith("0") and len(digits) <= 12:
                norm = digits
            else:
                norm = digits[-10:]
            if norm not in seen:
                seen.add(norm)
                hits.append(norm)
    for line in re.split(r"[\n.]+", blob):
        if re.search(r"phone|contact|call us|tel|mobile|whatsapp|dial", line, re.I):
            for m in re.finditer(r"[6-9]\d{9}", re.sub(r"\D", " ", line)):
                norm = m.group(0)
                if norm not in seen:
                    seen.add(norm)
                    hits.append(norm)
    return hits[:3]


def try_business_contact_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
    fields: dict | None = None,
) -> str | None:
    te = caller_text or ""
    if is_private_or_personal_request(te) and not is_business_contact_question(te):
        return None
    wants_number = is_business_contact_question(te)
    if not wants_number and fields:
        st = load_booking(fields)
        if st.booking_ref and re.search(r"(నంబర్|number).{0,36}(ఇవ్వ|చెప్ప|కావాల)", te, re.I):
            wants_number = True
    if not wants_number:
        return None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    phones = extract_business_phones(corpus)
    if phones:
        line = phones[0]
        if lang == "te-IN":
            return f"మా ఆఫీస్ / రిసెప్షన్ నంబర్ {line} అండి."
        if lang == "hi-IN":
            return f"हमारा ऑफिस/रिसेप्शन नंबर {line} है जी।"
        return f"Our office line is {line}."
    return polite_not_in_knowledge_reply(lang, honorific=caller_honorific(caller_text, lang))


def is_caller_compliment(text: str) -> bool:
    te = text or ""
    return bool(
        re.search(r"(వయసు|voice|స్వరం|మాట).{0,24}(బాగుంది|బాగా|nice|sweet)", te, re.I)
        or re.search(r"(మీ|your).{0,16}(voice|స్వరం).{0,16}(nice|మంచి)", te, re.I)
    )


def try_compliment_reply(caller_text: str, lang: str) -> str | None:
    if not is_caller_compliment(caller_text):
        return None
    if lang == "te-IN":
        return "ధన్యవాదాలు అండి, మీకు సహాయం చేయడానికి ఉన్నాను."
    if lang == "hi-IN":
        return "धन्यवाद जी, मैं आपकी मदद के लिए यहीं हूँ।"
    return "Thank you — happy to help."


def is_location_question(text: str) -> bool:
    if is_location_confirm_question(text):
        return True
    te = text or ""
    low = te.lower()
    return any(
        p in te or p in low
        for p in (
            "ఎక్కడ",
            "లోకేషన్",
            "location",
            "current location",
            "address",
            "where are you",
            "where is",
            "దగ్గర",
            "చిరునామా",
            "map",
            "దారి",
        )
    )


def is_post_booking_side_question(text: str) -> bool:
    """Facts about the agent, property, or site — not another booking step."""
    if is_business_contact_question(text):
        return True
    if is_caller_identity_question(text) or is_resort_name_question(text) or is_location_question(text):
        return True
    if is_pool_timing_question(text):
        return True
    te = text or ""
    low = te.lower()
    if any(p in te for p in ("సహాయం", "మరేమైనా", "anything else")):
        return True
    if "compliment" in low or "voice" in low and "nice" in low:
        return True
    if re.search(r"^(okay|ok|అవును|సరే)\s*[,.]?\s*$", low):
        return True
    return False


def try_reception_smalltalk_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
    fields: dict | None = None,
) -> str | None:
    """Name, property, location — from published brief and website only."""
    from app.services.voice.sarvam import business_name_from_context

    text = (caller_text or "").strip()
    if not text:
        return None
    if is_caller_identity_question(text):
        who = agent_name_from_brief(brief)
        biz = business_name_from_context(brief=brief, website_knowledge=website_knowledge or "")
        if lang == "te-IN":
            if who and biz:
                return f"నేను {who} అండి, {biz} నుంచి మాట్లాడుతున్నాను."
            if who:
                return f"నేను {who} అండి."
            if biz:
                return f"{biz} నుంచి మాట్లాడుతున్నాను అండి."
        if who:
            return f"I'm {who}."
        return None

    if is_resort_name_question(text):
        biz = business_name_from_context(brief=brief, website_knowledge=website_knowledge or "")
        if not biz:
            snippet = try_brand_knowledge_reply(text, brief=brief, website_knowledge=website_knowledge, lang=lang)
            if snippet:
                return snippet
            return {
                "te-IN": "ఆ పేరు వివరం నా దగ్గర స్పష్టంగా లేదండి.",
                "hi-IN": "वह जानकारी दस्तावेज़ में साफ़ नहीं है।",
                "en-IN": "I don't have the property name clearly on file.",
            }.get(lang, "I don't have the property name on file.")
        if lang == "te-IN":
            return f"మా resort పేరు {biz} అండి."
        return f"This is {biz}."

    if is_business_contact_question(text):
        hit = try_business_contact_reply(
            text,
            brief=brief,
            website_knowledge=website_knowledge,
            lang=lang,
            fields=fields,
        )
        if hit:
            return hit

    if is_location_question(text):
        corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
        low_corpus = corpus.lower()
        place = ""
        for line in _lines_knowledge(corpus):
            ll = line.lower()
            if any(k in ll or k in line for k in ("medchal", "location", "address", "near", "highway", "hyderabad", "లోకేషన్", "దగ్గర", "మెద్చల్", "telangana")):
                place = _sanitize_location_phrase(line.strip())
                break
        if not place and "medchal" in low_corpus:
            place = "V-Farms, మెద్చల్ దగ్గర, తెలంగాణ"
        if place:
            if is_location_confirm_question(text):
                if lang == "te-IN":
                    return f"అవును అండి, అదే మా property లోకేషన్ — {place}."
                return f"Yes — that's our location: {place}."
            if lang == "te-IN":
                return f"మా property ఇక్కడ ఉందండి — {place}."
            return place
        return {
            "te-IN": "ఆ లోకేషన్ వివరం ప్రచురిత సైట్‌లో లేదండి.",
            "hi-IN": "लोकेशन का विवरण साइट पर नहीं मिला।",
            "en-IN": "That location detail is not on the published site.",
        }.get(lang, "Location not in published knowledge.")

    return None


def booking_intent(text: str) -> bool:
    if is_business_contact_question(text):
        return False
    if is_location_confirm_question(text):
        return False
    if is_post_booking_side_question(text):
        return False
    low = (text or "").lower()
    te = text or ""
    return any(
        p in low or p in te
        for p in (
            "availability",
            "available",
            "book",
            "booking",
            "reservation",
            "check in",
            "check-in",
            "checkout",
            "check out",
            "weekend",
            "వీకెండ్",
            "అవైలబిలిటీ",
            "బుక్",
            "గది",
            "room",
            "rooms",
            "resort",
            "resort-",
            "స్టే",
            "stay",
            "చెక్",
            "తేదీ",
            "తారీకు",
            "తారీక",
            "ఎల్లుండి",
            "guests",
            "mandi",
            "మంది",
            "कमरा",
            "वीकेंड",
            "बुक",
            "बुकिंग",
            "चेक",
            "तारीख",
            "मेहमान",
            "लोग",
            "पंद्रह",
        )
    )


def booking_flow_active(fields: dict) -> bool:
    """Caller is mid stay booking — not just finished or asking general facts."""
    st = load_booking(fields)
    if st.booking_ref:
        return False
    if st.last_prompt or st.pending_confirm_field or st.awaiting_confirmation or st.lookup_in_progress:
        return True
    if st.check_in_day or st.check_out_day or st.guest_count:
        return True
    return bool(st.check_in or st.check_out or st.availability_summary)


def is_factual_business_question(text: str) -> bool:
    """Doubt, price, hours, services — answer from published facts, not a form restart."""
    te = (text or "").strip()
    if is_business_contact_question(te):
        return True
    if len(te) < 6:
        return False
    digits = re.sub(r"\D", "", te)
    if len(digits) >= 8 and digits[0] in "6789":
        return False
    if "నంబర్" in te or "number" in te.lower():
        if len(digits) >= 6:
            return False
    if is_post_booking_side_question(text):
        return True
    from app.services.voice.booking_dialogue import is_book_command, is_booking_status_question

    if is_booking_status_question(text) or is_book_command(text):
        return False
    low = te.lower()
    if booking_intent(text):
        if re.search(r"\d{1,2}\s*(?:వ|th|తేదీ|నుంచి)", te):
            return False
        stay_ask = (
            "availability",
            "available",
            "rooms",
            "room",
            "stay",
            "book",
            "booking",
            "అవైలబిలిటీ",
            "గది",
            "బుక్",
            "ఉందా",
            "తారీఖు",
        )
        if any(p in low or p in te for p in stay_ask):
            return False
    markers = (
        "?",
        "ఏమి",
        "ఎలా",
        "ఎంత",
        "ఎప్పుడు",
        "ఎక్కడ",
        "ఎవరు",
        "ఏం",
        "చెప్పండి",
        "తెలుసా",
        "అర్థం",
        "డౌట్",
        "సందేహం",
        "clarify",
        "doubt",
        "what",
        "how",
        "when",
        "where",
        "which",
        "tell me",
        "explain",
        "about",
        "fee",
        "fees",
        "price",
        "cost",
        "timing",
        "hours",
        "offer",
        "discount",
        "doctor",
        "department",
        "menu",
        "course",
        "batch",
        "test drive",
        "ఫీజు",
        "రేటు",
        "డాక్టర్",
        "గంటల",
        "సమయం",
        "వివర",
        "గురించి",
        "services",
        "facility",
    )
    return any(m in te or m in low for m in markers)


def should_prefer_reception_llm(text: str, fields: dict) -> bool:
    """Use Sarvam chat reception when the turn is Q&A, not lodging data collection."""
    te = (text or "").strip()
    digits = re.sub(r"\D", "", te)
    if len(digits) >= 6:
        return False
    if booking_flow_active(fields):
        return False
    if is_factual_business_question(text):
        if booking_intent(text):
            return False
        return True
    if booking_intent(text):
        return False
    know = str(fields.get("employee_website_knowledge") or "").strip()
    if len(know) >= 48 and len(te) >= 8:
        return True
    return len(te) >= 12


def office_attendant_prompt(
    lang: str,
    *,
    brief: str = "",
    website_knowledge: str | None = None,
) -> str:
    """Human desk line when no script matched — not a generic bot."""
    from app.services.voice.sarvam import business_name_from_context

    biz = business_name_from_context(brief=brief, website_knowledge=website_knowledge or "")
    who = agent_name_from_brief(brief)
    if lang == "te-IN":
        if who and biz:
            return (
                f"చెప్పండి అండి, {biz} reception నుంచి {who} — "
                "లోకేషన్, టైమింగ్స్, రేట్లు, బుకింగ్ — ఏమైనా అడగండి."
            )
        if biz:
            return f"చెప్పండి అండి, {biz} office నుంచి — ఏం కావాలో చెప్తారా?"
        return "చెప్పండి అండి, మేము office నుంచే మాట్లాడుతున్నాం — ఏ సహాయం కావాలి?"
    if lang == "hi-IN":
        place = biz or "हमारे office"
        return f"जी बताइए, {place} से — location, timing, booking — क्या जानना है?"
    place = biz or "our office"
    return f"Sure — {place} desk. Ask me about location, hours, prices, or booking."


def try_grounded_employee_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
    vertical: str = "general",
    fields: dict | None = None,
) -> str | None:
    """Fast answers from published brief + website before LLM or booking."""
    thanks = try_compliment_reply(caller_text, lang)
    if thanks:
        return thanks
    personal = try_personal_boundary_reply(caller_text, lang)
    if personal:
        return personal
    if vertical == "hospital":
        return None
    if booking_intent(caller_text) and not is_factual_business_question(caller_text):
        return None
    hit = try_reception_smalltalk_reply(
        caller_text,
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
        fields=fields,
    )
    if hit:
        return hit
    if is_pool_timing_question(caller_text):
        pool = try_pool_timing_reply(
            caller_text,
            website_knowledge=website_knowledge,
            brief=brief,
            lang=lang,
        )
        if pool:
            return pool
    brand = try_brand_knowledge_reply(
        caller_text,
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
    )
    if brand:
        return brand
    if is_factual_business_question(caller_text) or len((caller_text or "").strip()) >= 10:
        snippet = try_knowledge_snippet_reply(
            caller_text,
            brief=brief,
            website_knowledge=website_knowledge,
            lang=lang,
        )
        if snippet:
            return snippet
    missing = try_knowledge_missing_reply(
        caller_text,
        website_knowledge=website_knowledge,
        brief=brief,
        lang=lang,
    )
    if missing:
        return missing
    return try_knowledge_snippet_reply(
        caller_text,
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
    )


def _utterance_has_phone_fragment(text: str) -> bool:
    digits = re.sub(r"\D", "", text or "")
    return len(digits) >= 6 and digits[0] in "6789"


def should_run_booking_flow(fields: dict, caller_text: str) -> bool:
    from app.services.voice.booking_dialogue import is_book_command, is_booking_status_question
    from app.services.voice.booking_state import confirmation_yes
    from app.services.voice.inbound_vertical import inbound_vertical

    if is_business_contact_question(caller_text):
        return False
    if inbound_vertical(fields) != "lodging":
        return False
    if is_post_booking_side_question(caller_text):
        return False
    st = load_booking(fields)
    if st.booking_ref:
        if _utterance_has_phone_fragment(caller_text):
            return True
        if is_booking_status_question(caller_text) or is_book_command(caller_text):
            return True
        yn = confirmation_yes(caller_text)
        if yn is not None and len((caller_text or "").strip()) < 96:
            return True
        return False
    if is_factual_business_question(caller_text) and not booking_flow_active(fields):
        return False
    if booking_flow_active(fields):
        return True
    return booking_intent(caller_text)


def employee_snapshot_from_fields(fields: dict) -> dict:
    return {
        "brief": str(fields.get("employee_brief") or "").strip(),
        "language": str(fields.get("employee_language") or "English"),
        "website_knowledge": str(fields.get("employee_website_knowledge") or "").strip(),
        "website_url": str(fields.get("employee_website_url") or "").strip(),
        "natural_spoken": bool(fields.get("employee_natural_spoken", True)),
        "mode": str(fields.get("employee_mode") or ""),
    }


_STOP = frozenset(
    "a an the and or to for of in on at is are am was be with you we i me my your our this that it".split()
)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9\u0c00-\u0c7f\u0900-\u097f][\w\-]{2,}", (text or "").lower())
    return {w for w in words if w not in _STOP}


_BRAND_MARKERS = (
    "v-form",
    "v-forms",
    "vform",
    "vforms",
    "v farms",
    "vfarms",
    "v-farm",
    "v farms",
    "vfarm resort",
    "resort",
    "వి ఫార్మ",
    "వి-ఫారం",
    "వీ ఫార్మ",
)


def _caller_asks_brand(text: str) -> bool:
    low = (text or "").lower()
    te = text or ""
    if any(m in low or m in te for m in _BRAND_MARKERS):
        return True
    return bool(re.search(r"\bv\s*[- ]?forms?\b", low, re.I))


def _line_matches_brand(line: str, *, number_hint: str | None = None) -> bool:
    low = line.lower()
    if any(m in low for m in ("v farm", "v-form", "vform", "vfarms", "resort")):
        return True
    if number_hint and number_hint in line:
        return True
    return False


def _has_latin_hours(line: str) -> bool:
    return bool(_POOL_TIME_RE.search(line))


def _lines_knowledge(blob: str) -> list[str]:
    lines: list[str] = []
    for block in re.split(r"\n+", blob):
        for piece in re.split(r"(?<=[.!?])\s+", block.strip()):
            s = piece.strip().lstrip("-•* ")
            if len(s) >= 24:
                lines.append(s)
    return lines[:80]


def caller_honorific(caller_text: str, lang: str) -> str:
    """Sir/madam tone when the caller uses it; default polite address."""
    te = caller_text or ""
    low = te.lower()
    if any(p in low or p in te for p in ("madam", "ma'am", "maam", "మేడం", "mem", "मैडम")):
        return "madam"
    if any(p in low or p in te for p in ("sir", "సార్", "సర్", "சார்", "سर", "सर")):
        return "sir"
    if lang in ("te-IN", "hi-IN"):
        return "sir"
    return "sir or madam"


def polite_not_in_knowledge_reply(lang: str, *, honorific: str | None = None) -> str:
    h = honorific or ("sir or madam" if lang == "en-IN" else "sir")
    if lang == "te-IN":
        return "క్షమించండి అండి, ఆ వివరాలు నా దగ్గర లేవండి."
    if lang == "hi-IN":
        hey = "मैडम" if h == "madam" else "सर"
        return f"माफ़ कीजिए {hey} जी, वो जानकारी हमारे पास मौजूद नहीं है।"
    label = h if h in ("sir", "madam") else "sir or madam"
    return f"Sorry {label}, I don't have that information with me."


def is_private_or_personal_request(text: str) -> bool:
    """Agent personal life / private numbers — not public business contact from the site."""
    te = (text or "").strip()
    if len(te) < 5:
        return False
    if is_caller_compliment(te):
        return False
    if is_business_contact_question(te):
        return False
    low = te.lower()
    business_contact = re.search(
        r"(resort|hotel|office|reception|property|company|business|branch|"
        r"రిసార్ట్|ఆఫీస్|రిసెప్షన్|ऑफिस|होटल).{0,40}(phone|contact|number|call|mobile|whatsapp)",
        low + te,
        re.I,
    )
    if business_contact:
        return False
    personal_markers = (
        r"\b(your|you)\s+(phone|mobile|number|whatsapp|address|salary|income|age|home)\b",
        r"(where do you live|how old are you|are you married|your husband|your wife)",
        r"(personal number|private number|personal phone|personal life)",
        r"(నీ|మీ)\s*(మొబైల్|ఫోన్|ఇంటి|జీతం)",
        r"(నీ|మీ)\s+number\b",
        r"(personal details about you|about you personally)",
        r"(tell me your number|give me your number|what is your number)",
        r"(మీ\s*personal|పర్సనల్\s*(నంబర్|విషయం|ఫోన్))",
        r"(आपका\s*नंबर|आपकी\s*सैलरी|तुम्हारा\s*नंबर|निजी\s*नंबर)",
    )
    return any(re.search(p, te, re.I) or re.search(p, low, re.I) for p in personal_markers)


def try_personal_boundary_reply(caller_text: str, lang: str) -> str | None:
    if not is_private_or_personal_request(caller_text):
        return None
    h = caller_honorific(caller_text, lang)
    if lang == "te-IN":
        return "క్షమించండి అండి, అలాంటి పర్సనల్ విషయాలు మనం షేర్ చేయం. ఆఫీస్ / బిజినెస్ వివరాలు చెప్తాను."
    if lang == "hi-IN":
        hey = "मैडम" if h == "madam" else "सर"
        return f"माफ़ कीजिए {hey} जी, निजी जानकारी मैं शेयर नहीं कर सकती। बिज़नेस डिटेल बताती हूँ।"
    label = h if h in ("sir", "madam") else "sir or madam"
    return f"Sorry {label}, I can't share personal details like that. I can help with business information."


def _looks_like_specific_fact_ask(text: str) -> bool:
    te = text or ""
    low = te.lower()
    return bool(
        re.search(
            r"(how much|what.*price|cost|fee|rate|charge|timing|hours|open|close|"
            r"where|location|address|when|available|availability|heated|wifi|parking|"
            r"ఎంత|ధర|ఎక్కడ|లోకేషన్|ఎప్పుడు|టైమ్|అవైలబిల్|"
            r"कितना|कीमत|कहाँ|कब|समय|उपलब्ध)",
            low + te,
            re.I,
        )
        or "?" in te
        or "ా?" in te
    )


def _corpus_fact_score(corpus: str, question: str) -> int:
    q = _tokens(question)
    if len(q) < 2:
        return 0
    best = 0
    for line in _lines_knowledge(corpus):
        best = max(best, len(q & _tokens(line)))
    return best


def try_knowledge_gap_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
) -> str | None:
    """Polite 'not on file' when the caller asks a concrete fact absent from website/PDF/FAQ."""
    if booking_intent(caller_text) and not is_pool_timing_question(caller_text):
        from app.services.voice.booking_dialogue import is_booking_status_question

        if not is_booking_status_question(caller_text):
            return None
    if not is_factual_business_question(caller_text) and not _looks_like_specific_fact_ask(caller_text):
        return None
    if is_private_or_personal_request(caller_text):
        return None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    honorific = caller_honorific(caller_text, lang)
    if try_knowledge_snippet_reply(
        caller_text,
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
    ):
        return None
    if _corpus_fact_score(corpus, caller_text) >= 3:
        return None
    if len(corpus.strip()) < 24:
        return polite_not_in_knowledge_reply(lang, honorific=honorific)
    if not _looks_like_specific_fact_ask(caller_text):
        return None
    return polite_not_in_knowledge_reply(lang, honorific=honorific)


_NOT_IN_DOC = {
    "te-IN": "క్షమించండి అండి, ఆ వివరాలు నా దగ్గర లేవండి.",
    "hi-IN": "माफ़ कीजिए सर जी, वो जानकारी हमारे पास मौजूद नहीं है।",
    "en-IN": "Sorry sir or madam, I don't have that information with me.",
}


def try_knowledge_missing_reply(
    caller_text: str,
    *,
    website_knowledge: str | None,
    brief: str = "",
    lang: str,
) -> str | None:
    """Answer when the caller asks for a fact that is absent from uploaded knowledge."""
    if booking_intent(caller_text):
        return None
    low = (caller_text or "").lower()
    te = caller_text or ""
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""])).lower()
    heated_markers = (
        "heated",
        "heat",
        "হীট",
        "హీటెడ్",
        "హీట్",
        "गरम",
        "गर्म",
        "temperature",
    )
    asks_heated = any(m in low or m in te for m in heated_markers)
    corpus_has_heated = any(m in corpus for m in ("heated", "heat", "गरम"))
    if asks_heated and not corpus_has_heated:
        return polite_not_in_knowledge_reply(lang, honorific=caller_honorific(caller_text, lang))
    return None


def try_brand_knowledge_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
) -> str | None:
    if not _caller_asks_brand(caller_text):
        return None
    nums = re.findall(r"\b(\d{2,4})\b", caller_text or "")
    number_hint = nums[0] if nums else None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    hits: list[str] = []
    for line in _lines_knowledge(corpus):
        if _line_matches_brand(line, number_hint=number_hint):
            hits.append(line.strip())
    if not hits and corpus:
        for block in corpus.split("\n"):
            bl = block.strip()
            if bl and _line_matches_brand(bl, number_hint=number_hint):
                hits.append(bl[:200])
    if not hits:
        return None
    fact = hits[0][:120]
    if lang == "te-IN":
        return f"V Farms / V-Form గురించి: {fact}"
    return f"About V Farms / V-Form: {fact}"


def try_knowledge_snippet_reply(
    caller_text: str,
    *,
    brief: str,
    website_knowledge: str | None,
    lang: str,
) -> str | None:
    """
    Fast answer from website/brief bullets when the question clearly matches a fact line.
  Falls through to LLM when no confident match.
    """
    pool = try_pool_timing_reply(
        caller_text,
        website_knowledge=website_knowledge,
        brief=brief,
        lang=lang,
    )
    if pool:
        return pool
    brand = try_brand_knowledge_reply(
        caller_text,
        brief=brief,
        website_knowledge=website_knowledge,
        lang=lang,
    )
    if brand:
        return brand
    if booking_intent(caller_text):
        return None
    q_tokens = _tokens(caller_text)
    if len(q_tokens) < 2:
        return None
    corpus = "\n".join(filter(None, [brief, website_knowledge or ""]))
    best_score = 0
    best_line = ""
    for line in _lines_knowledge(corpus):
        lt = _tokens(line)
        score = len(q_tokens & lt)
        if score > best_score:
            best_score = score
            best_line = line
    strong = any(len(t) >= 4 and t in _tokens(best_line) for t in q_tokens)
    if is_pool_timing_question(caller_text):
        return None
    if not best_line or (best_score < 2 and not strong):
        return None
    snippet = best_line.strip()
    if len(snippet) > 100:
        snippet = snippet[:97].rstrip() + "…"
    if lang == "te-IN":
        if _has_latin_hours(snippet):
            return try_pool_timing_reply(
                caller_text,
                website_knowledge=website_knowledge,
                brief=brief,
                lang=lang,
            )
        return snippet
    if lang == "hi-IN":
        return snippet
    return snippet