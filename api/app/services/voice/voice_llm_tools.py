"""Shared OpenAI-format tool schemas for Sarvam / OpenAI chat."""

from __future__ import annotations

from typing import Any

from app.services.voice.voice_tool_definitions import OPENAI_TOOLS


def openai_tools_payload() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in OPENAI_TOOLS
    ]


def parse_accumulated_tool_calls(tool_acc: dict[int, dict]) -> list[dict]:
    import json

    tools_out: list[dict] = []
    for slot in tool_acc.values():
        name = slot.get("name", "")
        raw_args = slot.get("args", "{}")
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}
        if name:
            tools_out.append({"name": name, "args": args})
    return tools_out