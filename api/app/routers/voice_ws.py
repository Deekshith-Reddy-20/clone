import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket

from app.services.voice.exotel_voicebot_session import ExotelVoicebotSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-ws"])


@router.websocket("/v1/ws/exotel/voice/{call_id}")
async def exotel_voicebot_ws(websocket: WebSocket, call_id: UUID) -> None:
    await websocket.accept()
    session = ExotelVoicebotSession(websocket, call_id)
    await session.run()