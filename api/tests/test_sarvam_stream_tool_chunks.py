"""Sarvam stream: tool_call arguments split across chunks assemble once."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.voice.voice_sarvam_chat import stream_chat_completion


def _fake_chunks():
    chunks = []
    for piece in ['{"question":', '"where is",', ' "reason":', '"location"}']:
        delta = MagicMock()
        delta.content = ""
        fn = MagicMock()
        fn.name = "save_lead" if piece.startswith("{") else ""
        fn.arguments = piece
        tc = MagicMock()
        tc.index = 0
        tc.function = fn
        delta.tool_calls = [tc]
        ch = MagicMock()
        ch.choices = [MagicMock(delta=delta)]
        chunks.append(ch)
    final = MagicMock()
    final.choices = [MagicMock(delta=MagicMock(content="", tool_calls=[]))]
    chunks.append(final)
    return chunks


class SarvamStreamToolChunksTests(unittest.TestCase):
    def test_tool_arguments_reassembled(self) -> None:
        tools: list[dict] = []
        with patch("app.services.voice.voice_sarvam_chat.sarvam_configured", return_value=True):
            with patch("app.services.voice.voice_sarvam_chat._client") as mock_client:
                mock_client.return_value.chat.completions.return_value = iter(_fake_chunks())
                for piece, tcs in stream_chat_completion(messages=[{"role": "user", "content": "hi"}]):
                    if tcs:
                        tools = tcs
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "save_lead")
        args = tools[0]["args"]
        self.assertEqual(args.get("question"), "where is")
        self.assertEqual(args.get("reason"), "location")

    def test_execute_tool_once(self) -> None:
        from app.services.voice.inbound_pstn_stream import run_pstn_stream_turn
        from unittest.mock import AsyncMock

        tools = [{"name": "save_lead", "args": {"question": "loc", "reason": "location"}}]
        events = [("ttft", 120.0, "sarvam"), ("tools", tools)]

        async def _fake_stream(**_kwargs):
            for ev in events:
                yield ev

        db = MagicMock()
        call = MagicMock()
        call.workspace_id = None
        call.captured_fields = {"inbound_chat": {"turns": []}, "employee_brief": "test"}
        executed = []

        def _exec(db, call, fields, name, args, **kwargs):
            executed.append(name)
            return "", fields, False

        async def _run():
            with (
                patch("app.services.voice.inbound_pstn_stream.iter_inbound_llm_stream", side_effect=_fake_stream),
                patch("app.services.voice.inbound_pstn_stream.execute_tool", side_effect=_exec),
                patch("app.services.voice.inbound_pstn_stream.is_emergency_utterance", return_value=False),
                patch("app.services.voice.inbound_pstn_stream.is_spurious_stt_snippet", return_value=False),
                patch("app.services.voice.inbound_pstn_stream.refresh_call_grounding", return_value=call.captured_fields),
            ):
                await run_pstn_stream_turn(
                    db,
                    call,
                    caller_text="where is the resort",
                    stt_language="te-IN",
                    on_sentence=AsyncMock(),
                )

        import asyncio

        asyncio.run(_run())
        self.assertEqual(executed.count("save_lead"), 1)