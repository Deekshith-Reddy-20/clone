"""
LiveKit voice worker for Karyuk inbound/outbound calls.
Run: .\\scripts\\run-voice-agent.ps1
Requires LIVEKIT_* in repo .env; add OPENAI_API_KEY for real back-and-forth conversation.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("karyuk-voice")


def _brief_from_room(ctx: JobContext) -> str:
    meta = (ctx.room.metadata or "").strip()
    if not meta:
        return "You are a friendly phone agent for Karyuk. Greet the caller and help briefly."
    try:
        payload = json.loads(meta)
        if isinstance(payload, dict) and payload.get("brief"):
            return str(payload["brief"])
    except json.JSONDecodeError:
        pass
    return meta


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    brief = _brief_from_room(ctx)
    instructions = (
        f"{brief}\n\n"
        "You are on a live phone call. Speak in short, natural sentences. "
        "Ask one question at a time. Be warm and professional."
    )

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    vad = silero.VAD.load()
    session: AgentSession

    if openai_key:
        session = AgentSession(
            vad=vad,
            stt=openai.STT(),
            llm=openai.LLM(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
            tts=openai.TTS(voice=os.getenv("OPENAI_TTS_VOICE", "alloy")),
        )
    else:
        session = AgentSession(
            vad=vad,
            tts=silero.TTS.load(),
        )

    agent = Agent(instructions=instructions)
    await session.start(agent=agent, room=ctx.room)

    if openai_key:
        await session.say(
            "Hi, thanks for calling Karyuk. How can I help you today?",
            allow_interruptions=True,
        )
    else:
        await session.say(
            f"Hi, thanks for calling Karyuk. {brief[:200]}",
            allow_interruptions=False,
        )
        await session.say(
            "Add OPENAI_API_KEY to your environment for full two-way conversation.",
            allow_interruptions=False,
        )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=os.getenv("LIVEKIT_AGENT_NAME", "karyuk-voice"),
        )
    )