"""Shared tool schemas for Gemini native tools and Sarvam OpenAI-style tools."""

from __future__ import annotations

OPENAI_TOOLS = [
    {
        "name": "save_lead",
        "description": "Note callback when fact is missing or caller needs follow-up.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "check_availability",
        "description": "Check dates when PMS is configured.",
        "parameters": {"type": "object", "properties": {"dates": {"type": "string"}}},
    },
    {
        "name": "create_booking",
        "description": "File booking REQUEST after verbal confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "confirmed_verbal": {"type": "boolean"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "guests": {"type": "integer"},
            },
            "required": ["confirmed_verbal"],
        },
    },
    {
        "name": "transfer_to_human",
        "description": "Caller wants a manager/human.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "send_whatsapp_details",
        "description": "Send location or details on WhatsApp.",
        "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}},
    },
    {
        "name": "end_call",
        "description": "Caller is done.",
        "parameters": {"type": "object", "properties": {}},
    },
]

GEMINI_TOOL_DECLARATIONS = [
    {
        "name": t["name"],
        "description": t["description"],
        "parameters": t["parameters"],
    }
    for t in OPENAI_TOOLS
]