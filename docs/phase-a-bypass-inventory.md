# Phase A — Caller-facing bypass inventory (pre-removal)

Every path that could produce **spoken text without Sarvam/Gemini chat** in the live employee pipeline (`process_inbound_speech` → Exotel TTS).

| File | Function / block | What it spoke |
|------|------------------|---------------|
| `inbound_conversation.py` | `emergency_reply` via `is_emergency_utterance` | 112 / emergency (keep: safety) |
| `inbound_conversation.py` | empty STT retries | "వినిపించలేదు" (keep: I/O) |
| `inbound_conversation.py` | `is_spurious_stt_snippet` | repeat request (keep: I/O) |
| `inbound_conversation.py` | hangup / thank-you phrases | goodbye (keep: action) |
| `inbound_conversation.py` | `m05_voice_enabled` → `generate_m05_reply` | separate M05 stack (**remove**) |
| `inbound_conversation.py` | `is_incomplete_caller_utterance` | "finish what you were saying" (**remove → LLM**) |
| `inbound_conversation.py` | `try_compliment_reply` | thanks (**remove → LLM**) |
| `inbound_conversation.py` | `is_human_transfer_request` → `transfer_reply` | transfer line (→ tool in Phase D; keep short action text) |
| `inbound_conversation.py` | `try_value_offer_snippet` | price objection script (**remove → LLM**) |
| `inbound_conversation.py` | `try_personal_boundary_reply` | personal refusal (**remove → LLM + guard**) |
| `inbound_conversation.py` | `try_hospital_turn` | hospital form lines (**→ LLM + tools Phase D**) |
| `inbound_conversation.py` | `try_pool_timing_reply` | pool hours snippet (**remove → LLM**) |
| `inbound_conversation.py` | `try_grounded_employee_reply` | name/location/brand/snippet/missing (**remove → LLM**) |
| `inbound_conversation.py` | `try_knowledge_gap_reply` | "లేవండి" template (**remove → LLM**) |
| `inbound_conversation.py` | `should_prefer_reception_llm` gate | blocked LLM on many turns (**remove gate**) |
| `inbound_conversation.py` | `try_booking_turn` | check-in/guests/confirm scripts (**remove speech → state sync only**) |
| `inbound_conversation.py` | `_SHORT_ACK` + `office_attendant_prompt` | desk/check-in canned (**remove → LLM**) |
| `inbound_conversation.py` | MAX_TURNS goodbye | goodbye (keep) |
| `inbound_conversation.py` | `try_knowledge_missing_reply` | heated-pool etc. (**remove → LLM**) |
| `inbound_conversation.py` | `try_brand_knowledge_reply` | **`V Farms / V-Form గురించి:` + brief line (F1)** (**remove**) |
| `inbound_conversation.py` | `try_knowledge_snippet_reply` | FAQ line match (**remove → LLM**) |
| `inbound_conversation.py` | LLM fail fallback | grounded/snippet/office (**remove → single hard fallback**) |
| `employee_playbook.py` | `try_reception_smalltalk_reply` | name, location template "**Telangana..**" (F3) |
| `employee_playbook.py` | `try_business_contact_reply` | office number from corpus |
| `employee_playbook.py` | `try_brand_knowledge_reply` | brand + brief prefix (F1) |
| `employee_playbook.py` | `try_knowledge_snippet_reply` | first matching knowledge line (F2 operator text risk) |
| `employee_playbook.py` | `try_knowledge_missing_reply` / `try_knowledge_gap_reply` | not-in-doc templates |
| `employee_playbook.py` | `try_pool_timing_reply` | pool time |
| `employee_playbook.py` | `office_attendant_prompt` | generic desk |
| `inbound_booking.py` | `try_booking_turn` / `_msg` bank | booking script (F5 price redirect text if in knowledge) |
| `inbound_hospital.py` | `try_hospital_turn` / `_msg` | appointment script |
| `voice_leads.py` | `transfer_reply`, `callback_promise_reply`, `try_value_offer_snippet` | canned |
| `sarvam.py` | `avoid_repeat_reply` | "**మళ్ళీ చెప్తాను**" + same truncated line (F4) |
| `sarvam.py` | `_clarify_more` | "మరోసారి చెప్పగలరా" on LLM fail |
| `sarvam.py` | `opening_greeting_for_employee` | opening greet (keep: one-shot template) |
| `spoken_output.py` | `filter_caller_facing_reply` | leak filter (keep + expand guard) |
| `m05_sarvam.py` | `generate_m05_reply` | M05 path |
| `exotel_gemini_xml.py` | XML Say paths | non-Voicebot (**out of scope for Voicebot**) |
| `webhooks.py` | Gather XML handler | legacy Gather (**out of scope**) |

**Known production defects mapped:** F1 brand/brief, F2 instruction in knowledge, F3 location truncation, F4 avoid_repeat, F5 price routing, F6 English instructions, F7 duration (no finalize on Exotel `stop` in `exotel_voicebot_session.py`).