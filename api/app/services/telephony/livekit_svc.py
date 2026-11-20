from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.config import Settings, get_settings


def livekit_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return all(
        [
            s.livekit_url.strip(),
            s.livekit_api_key.strip(),
            s.livekit_api_secret.strip(),
        ]
    )


def room_name_for_call(call_id: str) -> str:
    return f"karyuk-call-{call_id}"


def livekit_sip_dial_target(room_name: str, settings: Settings | None = None) -> str:
    """SIP URI Exotel dials — room name as the user part (LiveKit callee dispatch)."""
    s = settings or get_settings()
    host = s.livekit_sip_uri.strip().removeprefix("sip:").split(";")[0]
    if not host:
        return ""
    # Exotel → LiveKit: sip:{room}@{project}.sip.livekit.cloud
    return f"sip:{room_name}@{host};transport=tcp"


def create_agent_participant_token(
    *,
    room_name: str,
    identity: str = "karyuk-agent",
    metadata: dict | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Mint a LiveKit access token for the voice worker (not for browsers)."""
    s = settings or get_settings()
    if not livekit_configured(s):
        return None
    try:
        from livekit import api
    except ImportError:
        return None

    grants = api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
    token = (
        api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
        .with_identity(identity)
        .with_grants(grants)
        .with_ttl(timedelta(hours=2))
    )
    if metadata:
        token.with_metadata(json.dumps(metadata))
    return token.to_jwt()


def ensure_livekit_room(
    room_name: str,
    settings: Settings | None = None,
    *,
    metadata: dict | None = None,
) -> bool:
    """Create the room so SIP + agent can join before Exotel dials LiveKit."""
    s = settings or get_settings()
    if not livekit_configured(s):
        return False
    try:
        from livekit import api
    except ImportError:
        return False

    host = s.livekit_url.strip().replace("wss://", "https://").replace("ws://", "http://")

    agent_name = s.livekit_agent_name.strip() or "karyuk-voice"

    async def _run() -> None:
        async with api.LiveKitAPI(host, s.livekit_api_key, s.livekit_api_secret) as lk:
            meta = {**(metadata or {}), "room": room_name}
            meta_json = json.dumps(meta)
            agents = [
                api.RoomAgentDispatch(
                    agent_name=agent_name,
                    metadata=meta_json,
                )
            ]
            try:
                await lk.room.create_room(
                    api.CreateRoomRequest(
                        name=room_name,
                        empty_timeout=600,
                        metadata=meta_json,
                        agents=agents,
                    )
                )
            except Exception as exc:
                msg = str(exc).lower()
                if "already" in msg and "exist" in msg:
                    try:
                        await lk.room.update_room_metadata(
                            api.UpdateRoomMetadataRequest(
                                room=room_name,
                                metadata=meta_json,
                            )
                        )
                    except Exception:
                        pass
                    try:
                        await lk.agent_dispatch.create_dispatch(
                            api.CreateAgentDispatchRequest(
                                agent_name=agent_name,
                                room=room_name,
                                metadata=meta_json,
                            )
                        )
                    except Exception:
                        pass
                    return
                raise exc

    try:
        import asyncio

        asyncio.run(_run())
        return True
    except Exception:
        return False


def dispatch_voice_runtime(call_id: str, employee_snapshot: dict) -> dict:
    """Prepare LiveKit room metadata for an external agent worker to join."""
    s = get_settings()
    room = room_name_for_call(call_id)
    meta = {
        "call_id": call_id,
        "brief": employee_snapshot.get("brief", ""),
        "language": employee_snapshot.get("language", "en"),
        "dispatched_at": datetime.now(UTC).isoformat(),
    }
    agent_token = create_agent_participant_token(room_name=room, metadata=meta)
    ensure_livekit_room(room, s, metadata=meta)
    return {
        "room": room,
        "livekit_url": s.livekit_url if livekit_configured() else None,
        "agent_token_ready": bool(agent_token),
        "room_metadata": meta,
    }