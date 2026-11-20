"""BulbulTtsSession: one WebSocket per call."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.voice.sarvam_streaming import BulbulTtsSession


class BulbulSessionReuseTests(unittest.TestCase):
    def test_single_connect_two_sentences(self) -> None:
        ws = MagicMock()
        ws.configure = MagicMock()
        ws.convert = MagicMock()
        ws.flush = MagicMock()

        class _Evt:
            type = "event"
            data = MagicMock(event_type="completed")

        ws.recv = MagicMock(side_effect=[_Evt()])

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ws)
        ctx.__exit__ = MagicMock(return_value=False)

        client = MagicMock()
        client.text_to_speech_streaming.connect.return_value = ctx

        with (
            patch("app.services.voice.sarvam_streaming.sarvam_configured", return_value=True),
            patch("app.services.voice.sarvam_streaming._sarvam_client", return_value=client),
            patch("app.services.voice.sarvam_streaming._wav_b64_to_pcm", return_value=b"\x00\x01" * 100),
        ):
            sess = BulbulTtsSession()
            sess.synthesize_pcm8k("Hello there friend.", "en-IN")
            sess.synthesize_pcm8k("Second sentence now.", "en-IN")
            sess.close()

        self.assertEqual(sess.connect_count, 1)
        self.assertEqual(sess.sentence_count, 2)
        self.assertEqual(client.text_to_speech_streaming.connect.call_count, 1)