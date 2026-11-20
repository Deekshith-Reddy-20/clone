from __future__ import annotations

from uuid import UUID

from app.config import get_settings


def xml_escape_text(text: str) -> str:
    return (
        text.replace("&", "and")
        .replace("<", " ")
        .replace(">", " ")
        .replace('"', "'")
    )


def exotel_gemini_open_xml(call_id: UUID | str, *, greeting: str) -> str:
    settings = get_settings()
    base = settings.public_api_base_url.rstrip("/")
    action = f"{base}/v1/webhooks/exotel/inbound/conversation/{call_id}"
    say_line = xml_escape_text(greeting)[:400]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{say_line}</Say>
  <Gather action="{action}" method="POST" input="speech" timeout="10" speechTimeout="auto" language="en-IN">
    <Say voice="woman">Please tell me how I can help.</Say>
  </Gather>
  <Redirect method="POST">{action}</Redirect>
</Response>"""


def exotel_gemini_turn_xml(
    call_id: UUID | str,
    *,
    agent_say: str,
    hangup: bool = False,
) -> str:
    settings = get_settings()
    base = settings.public_api_base_url.rstrip("/")
    action = f"{base}/v1/webhooks/exotel/inbound/conversation/{call_id}"
    say_line = xml_escape_text(agent_say)[:400]
    if hangup:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{say_line}</Say>
  <Hangup/>
</Response>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="woman">{say_line}</Say>
  <Gather action="{action}" method="POST" input="speech" timeout="12" speechTimeout="auto" language="en-IN">
    <Say voice="woman">Go ahead, I am listening.</Say>
  </Gather>
  <Say voice="woman">Thanks for calling. Goodbye.</Say>
  <Hangup/>
</Response>"""