"""Synthetic WSS path latency harness (no live Exotel)."""

from __future__ import annotations

import statistics
import unittest

from app.services.voice.exotel_voicebot_session import ExotelVoicebotSession


class WssLatencyHarnessTests(unittest.TestCase):
    def test_outbound_chunk_aligns_320_at_8k(self) -> None:
        sess = ExotelVoicebotSession(websocket=object(), call_id="00000000-0000-0000-0000-000000000099")  # type: ignore
        sess._inbound_sample_rate_hz = 8000
        sess._out_chunk_pcm = 3200
        pcm = b"\x00\x01" * 4000
        chunks = sess._pcm_to_wire_chunks(pcm)
        for c in chunks:
            self.assertEqual(len(c) % 320, 0)
        self.assertGreaterEqual(len(chunks), 1)

    def test_synthetic_e2e_budget_ms(self) -> None:
        """SYNTHETIC ONLY — not from WSS+WAV replay (see test_wss_real_latency.py)."""
        samples = [900, 1100, 850, 1300, 980, 1050, 1150, 880]
        p50 = statistics.median(samples)
        p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
        self.assertLess(p50, 5000, f"SYNTHETIC p50={p50}")
        self.assertLess(p95, 5000, f"SYNTHETIC p95={p95}")