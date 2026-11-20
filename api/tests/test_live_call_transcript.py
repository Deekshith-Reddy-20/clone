"""Live Telugu stay transcript: answer what was asked, then one next step.

The call is dummy data through process_inbound_speech — the same handler
the Exotel worker uses. No second pipeline.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.services.voice.booking_dialogue import is_booking_status_question
from app.services.voice.booking_state import extract_guest_count, load_booking
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.sarvam import avoid_repeat_reply
from tests.legacy_fastpath import skip_unless_legacy

_BAD_RECAP = "ఇంకా ఆ తేదీలు మరియు మంది సరిపోతాయా?"

TRANSCRIPT = [
    "నాకు మీ V-Forms-లో 22వ తారీఖు booking ఉందా లేదా చూసి చెప్తావా?",
    "ఆ అవును, 22 తారీఖున checking చేయాలనుకుంటున్నాను.",
    "24వ తేదీ.",
    "ఈ నెలలో, November-లో.",
    "book చేసుకున్నావా?",
    "సరిపోతాయి.",
    "చెప్పా కదా 35 మంది అని.",
    "సరే చూసి చెప్తారుగా.",
    "book చేశారా?",
    "అవసరం లేదు కానీ మూసుకొని book చెయ్ అతి చేయకుండా.",
    "ఇందాక చెప్పా కదా 60079913.",
    "సరిపోతాయిరా సరిపోతాయిరా స్వామి బుక్కేరా అన్నం పెడతా.",
    "అంతే చాలు thank you",
]


class _DB:
    def commit(self) -> None:
        pass

    def refresh(self, _c) -> None:
        pass


def _call(brief: str, know: str, *, language: str = "Telugu") -> SimpleNamespace:
    return SimpleNamespace(
        captured_fields={
            "employee_brief": brief,
            "employee_language": language,
            "employee_website_knowledge": know,
            "employee_website_url": "https://example.test/stay",
            "knowledge_state": "published",
            "employee_snapshot_revision": "1",
            "conversation_language": "te-IN",
            "inbound_chat": {"turns": []},
        },
        transcript="",
        summary="",
        outcome=None,
        finalized_at=None,
        duration_seconds=0,
    )


@skip_unless_legacy
class LiveCallTranscriptTests(unittest.TestCase):
    KNOW = "V-Farms resort cottages near Medchal. Pool 8:30 AM to 10 PM. Large groups welcome."

    def test_status_phrases_include_roman_book(self) -> None:
        for line in (
            "book చేశారా?",
            "book చేసుకున్నావా?",
            "బుక్ చేశారా?",
            "చూశారా?",
            "చూసి చెప్తారుగా",
        ):
            self.assertTrue(is_booking_status_question(line), line)

    def test_repeat_keeps_real_state(self) -> None:
        same = "ఇంకా బుక్ కాలేదండి. ఎంత మంది వస్తారు?"
        out = avoid_repeat_reply(same, same, booking_active=True)
        self.assertNotIn(_BAD_RECAP, out)
        self.assertIn("ఇంకా బుక్ కాలేదండి", out)
        self.assertNotEqual(out, same)

    def test_spoken_thirty_five(self) -> None:
        self.assertEqual(extract_guest_count("ముప్పై అయిదు మంది"), 35)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_transcript_turn_by_turn(self, _sarvam) -> None:
        call = _call("Your name is Maya for V Farms Resort.", self.KNOW)
        db = _DB()
        created: list[str] = []
        real = uuid.uuid4

        def _uuid():
            value = real()
            created.append(value.hex)
            return value

        def turn(q: str) -> str:
            reply, _hang = process_inbound_speech(db, call, caller_text=q, stt_language="te-IN")
            self.assertNotIn(_BAD_RECAP, reply)
            self.assertNotIn("22న చెక్-ఇన్ చేయాలనుకుంటున్నారా?", reply)
            self.assertFalse(reply.endswith("కని"), reply)
            return reply

        with (
            patch(
                "app.services.voice.inbound_conversation.refresh_call_grounding",
                side_effect=lambda _db, c: dict(c.captured_fields),
            ),
            patch("app.services.voice.inbound_booking.uuid.uuid4", side_effect=_uuid),
        ):
            r1 = turn(TRANSCRIPT[0])
            self.assertIn("ఇంకా బుక్ కాలేదండి", r1)
            self.assertEqual(load_booking(call.captured_fields).check_in_day, 22)

            r2 = turn(TRANSCRIPT[1])
            self.assertIn("చెక్-ఔట్", r2)
            self.assertNotIn("చెక్-ఇన్ చేయాలనుకుంటున్నారా", r2)
            self.assertEqual(load_booking(call.captured_fields).check_in_day, 22)

            r3 = turn(TRANSCRIPT[2])
            self.assertIn("నెల", r3)
            self.assertEqual(load_booking(call.captured_fields).check_out_day, 24)

            r4 = turn(TRANSCRIPT[3])
            self.assertIn("మంది", r4)
            st = load_booking(call.captured_fields)
            self.assertEqual(st.check_in, "2026-11-22")
            self.assertEqual(st.check_out, "2026-11-24")
            self.assertTrue(st.month_confirmed)

            r5 = turn(TRANSCRIPT[4])
            self.assertIn("ఇంకా బుక్ కాలేదండి", r5)
            self.assertIn("మంది", r5)
            self.assertNotIn(_BAD_RECAP, r5)

            r6 = turn(TRANSCRIPT[5])
            self.assertIn("మంది", r6)
            self.assertNotIn("22న వచ్చి", r6)

            r7 = turn(TRANSCRIPT[6])
            self.assertIn("అవకాశం ఉందండి", r7)
            self.assertIn("బుక్ చేయనా", r7)
            self.assertTrue(r7.endswith((".", "?", "!", "।")))
            self.assertNotIn("కని", r7)
            self.assertEqual(load_booking(call.captured_fields).guest_count, 35)

            r8 = turn(TRANSCRIPT[7])
            self.assertIn("ఇంకా బుక్ కాలేదండి", r8)
            self.assertIn("బుక్ చేయనా", r8)
            self.assertNotIn("మొబైల్", r8)
            self.assertNotIn("నంబర్", r8)

            r9 = turn(TRANSCRIPT[8])
            self.assertIn("ఇంకా బుక్ కాలేదండి", r9)
            self.assertNotIn(_BAD_RECAP, r9)

            r10 = turn(TRANSCRIPT[9])
            self.assertIn("కన్ఫర్మ్", r10)
            self.assertNotIn("మొబైల్", r10)
            self.assertNotIn("నంబర్", r10)
            ref = load_booking(call.captured_fields).booking_ref
            self.assertTrue(ref and ref.startswith("VF-"))
            self.assertEqual(len(created), 1)

            r11 = turn(TRANSCRIPT[10])
            self.assertNotIn("అంకెలు", r11)
            self.assertNotIn("మొబైల్ నంబర్ చెప్ప", r11)
            st = load_booking(call.captured_fields)
            self.assertEqual(st.partial_phone, "60079913")
            self.assertEqual(st.check_out_day, 24)
            self.assertEqual(st.booking_ref, ref)
            self.assertEqual(len(created), 1)

            r12 = turn(TRANSCRIPT[11])
            self.assertIn("కన్ఫర్మ్", r12)
            self.assertNotIn("మొబైల్", r12)
            self.assertEqual(load_booking(call.captured_fields).booking_ref, ref)
            self.assertEqual(len(created), 1)

            for _ in range(8, 12):
                st = load_booking(call.captured_fields)
                self.assertEqual(st.check_in, "2026-11-22")
                self.assertEqual(st.check_out, "2026-11-24")
                self.assertEqual(st.guest_count, 35)

            bye, hang = process_inbound_speech(
                db, call, caller_text=TRANSCRIPT[12], stt_language="te-IN"
            )
            self.assertTrue(hang)
            self.assertIn("థ్యాంక్యూ", bye)
            self.assertEqual(load_booking(call.captured_fields).booking_ref, ref)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_partial_phone_asks_only_missing_digits(self, _sarvam) -> None:
        call = _call("Your name is Maya for V Farms Resort.", self.KNOW)
        call.captured_fields["employee_requires_callback"] = True
        db = _DB()
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            for line in (
                "నవంబర్ 22 నుంచి 24, 35 మంది",
                "book చేయండి",
                "60079913",
            ):
                reply, _ = process_inbound_speech(db, call, caller_text=line, stt_language="te-IN")
        st = load_booking(call.captured_fields)
        self.assertEqual(st.partial_phone, "60079913")
        self.assertIsNone(st.booking_ref)
        self.assertIn("60079913 వినిపించింది", reply)
        self.assertIn("రెండు అంకెలు", reply)
        self.assertNotIn(_BAD_RECAP, reply)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_hospital_telugu_then_hindi_is_not_a_resort(self, _sarvam) -> None:
        call = _call(
            "Ananya, receptionist for Karyuk Demo Hospital Hyderabad.",
            "OPD 9 AM to 5 PM. Cardiology department. Location Hyderabad Gachibowli.",
        )
        db = _DB()
        lodging = ("చెక్-ఇన్", "చెక్-ఔట్", "check-in", "check-out", "checkout", "గది", "rooms")
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            te, _ = process_inbound_speech(
                db,
                call,
                caller_text="డాక్టర్ కలవాలి appointment కావాలి",
                stt_language="te-IN",
            )
            hi, _ = process_inbound_speech(
                db,
                call,
                caller_text="मुझे हिंदी में बात करनी है। कल कार्डियोलॉजी अपॉइंटमेंट चाहिए।",
                stt_language="hi-IN",
            )
        for reply in (te, hi):
            low = reply.lower()
            for word in lodging:
                self.assertNotIn(word, reply)
                self.assertNotIn(word, low)
        self.assertFalse(load_booking(call.captured_fields).check_in)
        self.assertIn("अपॉइंटमेंट", hi)

    @patch("app.services.voice.inbound_conversation.use_sarvam_inbound_voice", return_value=True)
    def test_second_employee_uses_only_its_published_site(self, _sarvam) -> None:
        from app.services.employee_knowledge import refresh_call_grounding

        farm_id = uuid.uuid4()
        shop_id = uuid.uuid4()
        farm_ver = uuid.uuid4()
        shop_ver = uuid.uuid4()
        ws = uuid.uuid4()
        versions = {
            farm_ver: {
                "brief": "Maya for V Farms Resort stays.",
                "language": "Telugu",
                "website_url": "https://vfarms.example/stay",
                "website_knowledge": "Dragonfruit sunrise package costs 6400 rupees on weekends.",
                "website_fetched_at": "2026-11-20T06:00:00+00:00",
                "revision": 3,
                "version_number": 2,
                "workspace_knowledge": "",
            },
            shop_ver: {
                "brief": "Front desk for City Books shop.",
                "language": "Telugu",
                "website_url": "https://citybooks.example",
                "website_knowledge": "City Books opens 10 AM. Landmark is tank bund.",
                "website_fetched_at": "2026-11-20T06:05:00+00:00",
                "revision": 1,
                "version_number": 1,
                "workspace_knowledge": "",
            },
        }
        active = {farm_id: farm_ver, shop_id: shop_ver}

        class _Emp:
            def __init__(self, vid):
                self.active_version_id = vid

        db = _DB()

        def _get(_model, key):
            if key in versions:
                return SimpleNamespace(snapshot=dict(versions[key]))
            if key in active:
                return _Emp(active[key])
            return None

        db.get = _get  # type: ignore[attr-defined]
        db.scalars = lambda *_a, **_k: SimpleNamespace(all=lambda: [])  # type: ignore[attr-defined]

        def session(eid, stale: str) -> SimpleNamespace:
            call = _call("stale", stale)
            call.employee_id = eid
            call.workspace_id = ws
            call.captured_fields["browser_preview"] = False
            call.captured_fields["employee_website_knowledge"] = stale
            return call

        question = "dragonfruit sunrise package price చెప్పండి"
        farm = session(farm_id, "old stale text")
        refresh_call_grounding(db, farm)  # type: ignore[arg-type]
        self.assertIn("6400", farm.captured_fields["employee_website_knowledge"])
        self.assertEqual(
            farm.captured_fields["knowledge_source_url"],
            "https://vfarms.example/stay",
        )
        self.assertTrue(farm.captured_fields["knowledge_fetched_at"])
        self.assertTrue(farm.captured_fields["knowledge_content_version"])
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            farm_reply, _ = process_inbound_speech(db, farm, caller_text=question, stt_language="te-IN")
        self.assertIn("6400", farm_reply)

        shop = session(shop_id, "City Books opens 10 AM. Landmark is tank bund.")
        refresh_call_grounding(db, shop)  # type: ignore[arg-type]
        with (
            patch(
                "app.services.voice.inbound_conversation.refresh_call_grounding",
                side_effect=lambda _db, c: dict(c.captured_fields),
            ),
            patch(
                "app.services.voice.inbound_conversation.generate_agent_reply_sarvam",
                return_value="ఆ వివరాలు నా దగ్గర లేవండి.",
            ),
        ):
            shop_reply, _ = process_inbound_speech(db, shop, caller_text=question, stt_language="te-IN")
        self.assertNotIn("6400", shop_reply)
        self.assertNotIn("dragonfruit", shop_reply.lower())

        versions[farm_ver]["website_knowledge"] = (
            "Dragonfruit sunrise package costs 8800 rupees on weekends."
        )
        versions[farm_ver]["revision"] = 4
        nxt = session(farm_id, "Dragonfruit sunrise package costs 6400 rupees on weekends.")
        refresh_call_grounding(db, nxt)  # type: ignore[arg-type]
        self.assertIn("8800", nxt.captured_fields["employee_website_knowledge"])
        self.assertNotIn("6400", nxt.captured_fields["employee_website_knowledge"])
        with patch(
            "app.services.voice.inbound_conversation.refresh_call_grounding",
            side_effect=lambda _db, c: dict(c.captured_fields),
        ):
            new_reply, _ = process_inbound_speech(db, nxt, caller_text=question, stt_language="te-IN")
        self.assertIn("8800", new_reply)
        self.assertNotIn("6400", new_reply)


if __name__ == "__main__":
    unittest.main()
