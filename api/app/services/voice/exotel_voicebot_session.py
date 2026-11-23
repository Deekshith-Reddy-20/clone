from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from uuid import UUID

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.database import SessionLocal
from app.models import Call
from app.services.telephony.inbound_mode import use_sarvam_inbound_voice
from app.services.voice.inbound_conversation import process_inbound_speech
from app.services.voice.booking_state import booking_state_trace_summary, load_booking
from app.services.voice.session_trace import (
    emit_voice_session_trace,
    knowledge_revision_from_fields,
    log_pipeline_event,
    log_voice_turn,
)
from app.services.voice.call_turn_policy import (
    is_short_acknowledgment,
    reject_turn_reason,
    stt_language_for_reply,
)
from app.services.voice.speech_route import (
    apply_explicit_language_switch,
    employee_default_bcp47,
)
from app.services.voice.spoken_length import cap_spoken_reply
from app.config import get_settings
from app.services.voice.inbound_pstn_stream import run_pstn_stream_turn
from app.services.voice.sarvam_streaming import BulbulTtsSession
from app.services.voice.silero_vad import speech_ms_in_pcm
from app.services.voice.sarvam import (
    sarvam_media_ready,
    _clarify_more,
    _has_devanagari_script,
    clamp_voice_lang,
    detect_language_from_text,
    is_spurious_stt_snippet,
    language_bcp47_from_employee,
    opening_greeting_for_employee,
    transcribe_pcm as sarvam_transcribe_pcm,
    tts_pcm_8k as sarvam_tts_pcm_8k,
)

logger = logging.getLogger(__name__)

SILENCE_SECONDS = 0.48
BARGE_IN_MIN_MS = 300
BARGE_IN_PCM_BYTES = 4800  # 300 ms @ 8 kHz PCM16
SILENCE_SECONDS_LONG = 1.05  # caller spelling phone / dates with pauses
MIN_SPEECH_BYTES = 6_400  # ~0.4 s of 8 kHz mono PCM16
POST_SPEECH_COOLDOWN = 0.22
# Outbound frame size set from inbound media_format (100–200 ms, multiple of 320 @ 8 kHz)
CHUNK_PCM = 3200
TTS_CHUNK_PAUSE_S = 0.08
# Exotel still plays audio after we finish sending chunks — ignore mic until then (+echo tail).
PLAYBACK_TAIL_S = 0.16
MIN_STT_RMS = 55  # PSTN mobile mics are often quieter than browser mic
# Line noise on Exotel often sits above MIN_STT_RMS and was resetting the end-of-utterance
# timer forever (8s buffers). Only real voice should extend the turn.
SPEECH_CONTINUE_RMS = 80
MIN_STT_RMS_HARD_FLOOR = 22  # below this: line noise / echo only — discard, never STT
MIN_STT_RMS_BROWSER = 45
BROWSER_SILENCE_SECONDS = 0.85
# Keep early caller syllables that arrive during agent playback (greeting / TTS), not agent echo.
PRE_ROLL_MAX_BYTES = 32_000  # ~2 s @ 8 kHz PCM16
# Echo during agent TTS fills pre_roll; only keep the tail when listen opens.
PRE_ROLL_MERGE_TAIL_BYTES = 16_000  # ~1 s @ 8 kHz PCM16
# Cap one utterance (~4 s) so mid-phrase pauses still commit on PSTN.
MAX_UTTERANCE_PCM_BYTES = 64_000
MARK_GREETING_PLAYBACK = "karyuk-greeting-playback-done"
MARK_UTTERANCE_PLAYBACK = "karyuk-utterance-playback-done"
MARK_FALLBACK_CAP_S = 12.0


class ExotelVoicebotSession:
    def __init__(self, websocket: WebSocket, call_id: UUID) -> None:
        self.ws = websocket
        self.call_id = call_id
        self.stream_sid: str | None = None
        self.pcm_buffer = bytearray()
        self.speaking = False
        self.lang_code = "en-IN"
        self._caller_language_locked = False
        self._silence_task: asyncio.Task | None = None
        self._turn_lock = asyncio.Lock()
        self._ignore_input_until = 0.0
        # Inbound from PSTN often µ-law; Voicebot playback expects slin PCM16 out
        self._inbound_encoding = "linear16"
        self._inbound_sample_rate_hz = 8000
        self._media_chunks = 0
        self._greeting_task: asyncio.Task | None = None
        self._sequence_out = 0
        self._last_final_text = ""
        self._speak_generation = 0
        self._greeting_done = False
        self._listen_lang = "en-IN"
        self._turn_started_at = 0.0
        self._playback_until = 0.0
        self._stream_started_monotonic = 0.0
        self._speech_stack = "sarvam"
        self._employee_bcp47 = "te-IN"
        self._rejected_turns = 0
        self._pre_roll = bytearray()
        self._stt_miss_streak = 0
        self._tts_speaker: str | None = None
        self._browser_preview = False
        self._voice_turn_seq = 0
        self._ingress_task: asyncio.Task | None = None
        self._ingress_queue: asyncio.Queue | None = None
        self._exotel_events_seen: set[str] = set()
        self._skipped_outbound_frames = 0
        self._listen_gate_was_open = False
        self._utterance_end_deadline = 0.0
        self._last_buffer_growth_at = 0.0
        self._utterance_claim_active = False
        self._utterance_finalize_task: asyncio.Task | None = None
        self._mark_fallback_task: asyncio.Task | None = None
        self._pending_playback_mark: str | None = None
        self._barge_accum_bytes = 0
        self._barge_in_count = 0
        self._out_chunk_pcm = CHUNK_PCM
        self._caller_eos_at = 0.0
        self._marks_handled: set[str] = set()
        self._mark_sentence: dict[str, str] = {}
        self._confirmed_spoken: list[str] = []
        self._barge_pcm_window = bytearray()
        self._stt_partial_text = ""
        self._agent_audio_started_at = 0.0
        self._first_agent_media_at: float | None = None
        self._bulbul: BulbulTtsSession | None = None
        self._tts_ws_failed = False
        barge_env = os.getenv("VOICE_BARGE_IN", get_settings().voice_barge_in or "off")
        self._barge_in_enabled = str(barge_env).strip().lower() == "on"

    def _min_stt_rms(self) -> int:
        return MIN_STT_RMS_BROWSER if self._browser_preview else MIN_STT_RMS

    def _accepting_caller_audio(self) -> bool:
        if self.speaking:
            return False
        if time.monotonic() < self._ignore_input_until:
            return False
        if time.monotonic() < self._playback_until:
            return False
        return True

    def _merge_pre_roll_into_buffer(self, *, force: bool = False, full: bool = False) -> None:
        if not self._pre_roll:
            return
        if not force and not self._accepting_caller_audio():
            return
        if full or len(self._pre_roll) <= PRE_ROLL_MERGE_TAIL_BYTES:
            tail = bytes(self._pre_roll)
        else:
            tail = bytes(self._pre_roll[-PRE_ROLL_MERGE_TAIL_BYTES:])
        self._pre_roll.clear()
        if tail:
            self.pcm_buffer.extend(tail)

    def _buffer_meets_stt_energy(self, buf: bytes) -> bool:
        rms = self._pcm_rms(buf)
        if rms < MIN_STT_RMS_HARD_FLOOR:
            return False
        if self._browser_preview:
            return rms >= self._min_stt_rms()
        if len(buf) > 48_000:
            tail_rms = self._pcm_rms(buf[-32_000:])
            if tail_rms >= MIN_STT_RMS:
                return True
        return rms >= MIN_STT_RMS

    def _chunk_has_speech_energy(self, pcm: bytes) -> bool:
        """True only when this chunk should extend the current utterance.

        PSTN uses a higher floor than STT acceptance so idle line noise does not
        keep re-arming the silence timer (symptom: 5–8s buffers, late commits).
        """
        if len(pcm) < 320:
            return False
        try:
            floor = self._min_stt_rms() if self._browser_preview else SPEECH_CONTINUE_RMS
            return audioop.rms(pcm, 2) >= floor
        except Exception:
            return False

    def _discard_low_energy_buffer(self, *, reason: str) -> None:
        if len(self.pcm_buffer) < MIN_SPEECH_BYTES and not self._pre_roll:
            return
        buf = bytes(self.pcm_buffer) if self.pcm_buffer else bytes(self._pre_roll)
        if self._buffer_meets_stt_energy(buf):
            return
        log_pipeline_event(
            call_id=str(self.call_id),
            stage="stt_discarded_low_energy",
            reason=reason,
            buffer_bytes=len(self.pcm_buffer),
            pre_roll_bytes=len(self._pre_roll),
            rms=self._pcm_rms(buf),
            min_rms=MIN_STT_RMS if not self._browser_preview else self._min_stt_rms(),
            inbound_frames=self._media_chunks,
        )
        self.pcm_buffer.clear()
        self._pre_roll.clear()
        self._utterance_end_deadline = 0.0
        self._last_buffer_growth_at = 0.0

    def _trim_buffer_to_max_utterance(self) -> None:
        if len(self.pcm_buffer) <= MAX_UTTERANCE_PCM_BYTES:
            return
        drop = len(self.pcm_buffer) - MAX_UTTERANCE_PCM_BYTES
        del self.pcm_buffer[:drop]
        log_pipeline_event(
            call_id=str(self.call_id),
            stage="utterance_buffer_trim",
            dropped_bytes=drop,
            buffer_bytes=len(self.pcm_buffer),
            inbound_frames=self._media_chunks,
        )

    def _ingest_inbound_pcm(self, pcm: bytes) -> None:
        energetic = self._chunk_has_speech_energy(pcm)
        if self.speaking and energetic and self._barge_in_enabled:
            echo_ok = (
                self._agent_audio_started_at > 0
                and (time.monotonic() - self._agent_audio_started_at) * 1000.0 >= 400.0
            )
            if echo_ok:
                self._barge_pcm_window.extend(pcm)
                if len(self._barge_pcm_window) > 48_000:
                    self._barge_pcm_window = self._barge_pcm_window[-48_000:]
                silero_ms = speech_ms_in_pcm(bytes(self._barge_pcm_window))
                if silero_ms >= 300.0:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._barge_maybe_interrupt(bytes(self._barge_pcm_window)))
                    except RuntimeError:
                        pass
        elif self.speaking and energetic and not self._barge_in_enabled:
            pass
        if self._accepting_caller_audio():
            self._merge_pre_roll_into_buffer()
            self.pcm_buffer.extend(pcm)
            if energetic:
                self._last_buffer_growth_at = time.monotonic()
                self._utterance_end_deadline = 0.0
            self._trim_buffer_to_max_utterance()
            return
        self._pre_roll.extend(pcm)
        if energetic:
            self._last_buffer_growth_at = time.monotonic()
        if len(self._pre_roll) > PRE_ROLL_MAX_BYTES:
            drop = len(self._pre_roll) - PRE_ROLL_MAX_BYTES
            del self._pre_roll[:drop]

    @staticmethod
    def _ingress_from_media_format(mf: dict) -> tuple[str, int]:
        """Exotel Voicebot bidirectional default is slin PCM16 @ 8 kHz (payload base64)."""
        enc = str(mf.get("encoding") or mf.get("codec") or "").lower()
        rate_raw = mf.get("sampleRate") or mf.get("sample_rate") or mf.get("rate")
        try:
            rate = int(rate_raw) if rate_raw is not None else 8000
        except (TypeError, ValueError):
            rate = 8000
        if rate not in (8000, 16000):
            rate = 8000
        if "mulaw" in enc or "g.711" in enc or "g711" in enc:
            return "mulaw", rate
        if any(x in enc for x in ("l16", "pcm", "linear", "slin")):
            return "linear16", rate
        # Many live Exotel streams send encoding literally as "base64" — audio is still slin.
        return "linear16", rate

    async def _bootstrap_after_start(self) -> None:
        try:
            await self._play_greeting()
            await self._emit_call_trace()
        except Exception:
            logger.exception("Voicebot %s bootstrap failed", self.call_id)

    async def _ws_ingress_reader(self) -> None:
        """Always drain Exotel WebSocket — never block on greeting/STT/TTS."""
        assert self._ingress_queue is not None
        try:
            while True:
                raw = await self.ws.receive_text()
                await self._ingress_queue.put(("msg", raw))
        except WebSocketDisconnect as exc:
            await self._ingress_queue.put(("disconnect", exc))
        except Exception as exc:
            await self._ingress_queue.put(("error", exc))

    async def _handle_exotel_message(self, msg: dict) -> bool:
        """Returns False when the session should end (Exotel stop)."""
        event = msg.get("event")
        if event and event not in self._exotel_events_seen:
            self._exotel_events_seen.add(str(event))
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="exotel_event",
                event=event,
            )
        if event == "connected":
            return True
        if event == "start":
            start = msg.get("start") or {}
            self._stream_started_monotonic = time.monotonic()
            from app.services.voice.silero_vad import vad_engine_name

            self._vad_engine = vad_engine_name()
            logger.info("Voicebot %s vad_engine=%s", self.call_id, self._vad_engine)
            dbv = SessionLocal()
            try:
                call = dbv.get(Call, self.call_id)
                if call:
                    call.captured_fields = {
                        **(call.captured_fields or {}),
                        "vad_engine": self._vad_engine,
                        "voice_barge_in": "on" if self._barge_in_enabled else "off",
                    }
                    dbv.commit()
            finally:
                dbv.close()
            self.stream_sid = msg.get("stream_sid") or start.get("stream_sid") or start.get("streamSid")
            mf = start.get("mediaFormat") or start.get("media_format") or {}
            self._inbound_encoding, self._inbound_sample_rate_hz = self._ingress_from_media_format(mf)
            ms = 150
            rate = self._inbound_sample_rate_hz
            chunk = max(320, int(rate * (ms / 1000.0) * 2))
            self._out_chunk_pcm = chunk if chunk % 320 == 0 else chunk + (320 - chunk % 320)
            enc = str(mf.get("encoding") or mf.get("codec") or "")
            self.lang_code = "en-IN"
            self._caller_language_locked = False
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stream_start",
                encoding=self._inbound_encoding,
                ingress_hz=self._inbound_sample_rate_hz,
                format_hint=enc[:32] or "unknown",
                stream_sid_prefix=(self.stream_sid or "")[:8],
            )
            self._load_tts_speaker_from_db()
            if not self._greeting_task or self._greeting_task.done():
                self._greeting_task = asyncio.create_task(self._bootstrap_after_start())
            return True
        if event == "media":
            media = msg.get("media") or {}
            track = str(media.get("track") or "inbound").lower()
            if track in ("outbound", "output", "agent"):
                self._skipped_outbound_frames += 1
                return True
            payload = (media.get("payload") or "").strip()
            if not payload:
                return True
            pcm = self._decode_media_payload(payload)
            if not pcm:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="media_decode_empty",
                    encoding=self._inbound_encoding,
                    frame_bytes=0,
                )
                return True
            self._media_chunks += 1
            if self._media_chunks == 1:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="first_media_frame",
                    frame_bytes=len(pcm),
                    track=track or "inbound",
                    encoding=self._inbound_encoding,
                )
            elif self._media_chunks % 50 == 0:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="media_ingest",
                    inbound_frames=self._media_chunks,
                    listening=int(self._accepting_caller_audio()),
                    buffer_bytes=len(self.pcm_buffer),
                    pre_roll_bytes=len(self._pre_roll),
                )
            self._ingest_inbound_pcm(pcm)
            return True
        if event == "dtmf":
            digit = (msg.get("dtmf") or {}).get("digit")
            if digit:
                await self._handle_caller_text(f"pressed {digit}")
            return True
        if event == "stop":
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="exotel_stop",
                inbound_frames=self._media_chunks,
                skipped_outbound=self._skipped_outbound_frames,
                pre_roll_bytes=len(self._pre_roll),
                buffer_bytes=len(self.pcm_buffer),
                listening=int(self._accepting_caller_audio()),
            )
            await self._flush_utterance_on_stop()
            self._finalize_call_record_on_disconnect(source="exotel_stop")
            return False
        if event == "mark":
            mark = msg.get("mark") or {}
            name = str(mark.get("name") or "").strip()
            if name:
                await self._handle_playback_mark(name, source="exotel")
            return True
        if event:
            log_pipeline_event(call_id=str(self.call_id), stage="exotel_unhandled", event=event)
        return True

    async def run(self) -> None:
        self._silence_task = asyncio.create_task(self._silence_loop())
        self._ingress_queue = asyncio.Queue(maxsize=2048)
        self._ingress_task = asyncio.create_task(self._ws_ingress_reader())
        disconnect_code: int | None = None
        try:
            while True:
                kind, payload = await self._ingress_queue.get()
                if kind == "disconnect":
                    exc = payload
                    disconnect_code = getattr(exc, "code", None)
                    break
                if kind == "error":
                    raise payload
                try:
                    msg = json.loads(payload)
                except json.JSONDecodeError as exc:
                    log_pipeline_event(
                        call_id=str(self.call_id),
                        stage="ws_json_error",
                        error=str(exc)[:80],
                    )
                    continue
                cont = await self._handle_exotel_message(msg)
                if not cont:
                    break
        except Exception as exc:
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="session_error",
                error_type=type(exc).__name__,
                inbound_frames=self._media_chunks,
            )
            logger.info(
                "Voicebot session %s closed: %s media_chunks=%s",
                self.call_id,
                exc,
                self._media_chunks,
            )
        else:
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="session_end",
                disconnect_code=disconnect_code,
                inbound_frames=self._media_chunks,
                skipped_outbound=self._skipped_outbound_frames,
            )
            logger.info(
                "Voicebot session %s disconnected code=%s media_chunks=%s",
                self.call_id,
                disconnect_code,
                self._media_chunks,
            )
        finally:
            if self._bulbul is not None:
                self._bulbul.close()
                self._bulbul = None
            self._finalize_call_record_on_disconnect()
            if self._greeting_task and not self._greeting_task.done():
                self._greeting_task.cancel()
            if self._ingress_task and not self._ingress_task.done():
                self._ingress_task.cancel()
            if self._silence_task:
                self._silence_task.cancel()
            if self._utterance_finalize_task and not self._utterance_finalize_task.done():
                try:
                    await asyncio.wait_for(self._utterance_finalize_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
            if self._mark_fallback_task and not self._mark_fallback_task.done():
                self._mark_fallback_task.cancel()

    def _silence_deadline_for_speech(self) -> float:
        if self._last_buffer_growth_at <= 0:
            return 0.0
        return self._last_buffer_growth_at + self._silence_pause_seconds()

    def _try_claim_pcm_buffer(self) -> bytes | None:
        if self._utterance_claim_active:
            return None
        if len(self.pcm_buffer) < MIN_SPEECH_BYTES:
            return None
        buf = bytes(self.pcm_buffer)
        if not self._buffer_meets_stt_energy(buf):
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stt_discarded_low_energy",
                reason="claim",
                buffer_bytes=len(buf),
                rms=self._pcm_rms(buf),
                min_rms=MIN_STT_RMS if not self._browser_preview else self._min_stt_rms(),
                inbound_frames=self._media_chunks,
            )
            self.pcm_buffer.clear()
            return None
        self.pcm_buffer.clear()
        self._utterance_claim_active = True
        self._utterance_end_deadline = 0.0
        return buf

    def _finalize_call_record_on_disconnect(self, *, source: str = "exotel_wss_disconnect") -> None:
        from app.models.enums import CallOutcome
        from app.services.voice.call_finalize import finalize_call_idempotent

        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            started = self._stream_started_monotonic or 0.0
            duration = (
                max(1, int(time.monotonic() - started))
                if started > 0
                else max(int(call.duration_seconds or 0), 1)
            )
            finalize_call_idempotent(
                db,
                call,
                duration_seconds=duration,
                outcome=CallOutcome.completed,
                source=source,
            )
        except Exception:
            logger.exception("finalize_call_record failed call_id=%s", self.call_id)
        finally:
            db.close()

    async def _flush_utterance_on_stop(self) -> None:
        self._merge_pre_roll_into_buffer(force=True, full=True)
        if len(self.pcm_buffer) > MAX_UTTERANCE_PCM_BYTES:
            tail = bytes(self.pcm_buffer[-MAX_UTTERANCE_PCM_BYTES:])
            self.pcm_buffer.clear()
            self.pcm_buffer.extend(tail)
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="utterance_buffer_trim",
                dropped_bytes=-1,
                buffer_bytes=len(self.pcm_buffer),
                inbound_frames=self._media_chunks,
            )
        if self._utterance_finalize_task and not self._utterance_finalize_task.done():
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stt_skipped_on_stop",
                reason="finalize_in_flight",
                buffer_bytes=len(self.pcm_buffer),
                pre_roll_bytes=len(self._pre_roll),
            )
            try:
                await asyncio.wait_for(self._utterance_finalize_task, timeout=30.0)
            except asyncio.TimeoutError:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="stt_provider_error",
                    provider_code="stop_wait_timeout",
                )
            return
        buf = self._try_claim_pcm_buffer()
        if not buf:
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stt_skipped_on_stop",
                buffer_bytes=len(self.pcm_buffer),
                pre_roll_bytes=len(self._pre_roll),
                claimed=int(self._utterance_claim_active),
            )
            return
        await self._run_stt_pipeline(buf)

    async def _schedule_utterance_finalize(self) -> None:
        if self._utterance_finalize_task and not self._utterance_finalize_task.done():
            at_cap = len(self.pcm_buffer) >= MAX_UTTERANCE_PCM_BYTES
            buf = bytes(self.pcm_buffer)
            has_energy = len(buf) >= MIN_SPEECH_BYTES and self._buffer_meets_stt_energy(buf)
            if at_cap or has_energy:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="stt_cancel_stale",
                    buffer_bytes=len(self.pcm_buffer),
                    at_cap=int(at_cap),
                    inbound_frames=self._media_chunks,
                )
                self._utterance_finalize_task.cancel()
                try:
                    await self._utterance_finalize_task
                except asyncio.CancelledError:
                    pass
                self._utterance_claim_active = False
                self._utterance_finalize_task = None
            else:
                return
        if not self._accepting_caller_audio() and len(self.pcm_buffer) < MIN_SPEECH_BYTES:
            return
        self._merge_pre_roll_into_buffer()
        buf = self._try_claim_pcm_buffer()
        if not buf:
            return
        self._utterance_finalize_task = asyncio.create_task(self._run_stt_pipeline(buf))

    async def _evaluate_utterance_timer(self) -> None:
        self._merge_pre_roll_into_buffer(force=True, full=True)
        if len(self.pcm_buffer) < MIN_SPEECH_BYTES and len(self._pre_roll) < MIN_SPEECH_BYTES:
            self._utterance_end_deadline = 0.0
            return
        now = time.monotonic()
        deadline = self._silence_deadline_for_speech()
        if deadline <= 0:
            return
        if now >= deadline:
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="utterance_pause_elapsed",
                buffer_bytes=len(self.pcm_buffer),
                inbound_frames=self._media_chunks,
            )
            await self._schedule_utterance_finalize()
        else:
            self._utterance_end_deadline = deadline
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="utterance_pause_armed",
                buffer_bytes=len(self.pcm_buffer),
                pause_ms=int((deadline - now) * 1000),
                inbound_frames=self._media_chunks,
            )

    def _cancel_mark_fallback(self) -> None:
        if self._mark_fallback_task and not self._mark_fallback_task.done():
            self._mark_fallback_task.cancel()
        self._mark_fallback_task = None
        self._pending_playback_mark = None

    def _arm_mark_fallback(self, mark_name: str, wait_s: float) -> None:
        self._cancel_mark_fallback()
        self._pending_playback_mark = mark_name
        cap = min(max(wait_s, PLAYBACK_TAIL_S), MARK_FALLBACK_CAP_S)

        async def _fallback() -> None:
            try:
                await asyncio.sleep(cap)
                if self._pending_playback_mark == mark_name and mark_name not in self._marks_handled:
                    log_pipeline_event(
                        call_id=str(self.call_id),
                        stage="playback_mark_fallback",
                        mark=mark_name,
                        wait_ms=int(cap * 1000),
                    )
                    await self._handle_playback_mark(mark_name, source="fallback")
            except asyncio.CancelledError:
                pass

        self._mark_fallback_task = asyncio.create_task(_fallback())

    async def _handle_playback_mark(self, name: str, *, source: str) -> None:
        if name in self._marks_handled:
            return
        self._marks_handled.add(name)
        if self._pending_playback_mark == name:
            self._cancel_mark_fallback()
        log_pipeline_event(
            call_id=str(self.call_id),
            stage="playback_mark",
            mark=name,
            mark_source=source,
            inbound_frames=self._media_chunks,
        )
        self._playback_until = 0.0
        self.speaking = False
        self._ignore_input_until = time.monotonic() + POST_SPEECH_COOLDOWN
        self._listen_gate_was_open = False
        if name in self._mark_sentence:
            sent = self._mark_sentence.get(name, "").strip()
            if sent and (not self._confirmed_spoken or self._confirmed_spoken[-1] != sent):
                self._confirmed_spoken.append(sent)
        if name == MARK_GREETING_PLAYBACK:
            self._on_listen_gate_opened()
            self._discard_low_energy_buffer(reason="post_greeting_echo")
        elif name in (MARK_UTTERANCE_PLAYBACK, "utterance-complete"):
            self._merge_pre_roll_into_buffer(force=True, full=True)
        await self._evaluate_utterance_timer()

    def _decode_media_payload(self, payload_b64: str) -> bytes:
        try:
            raw = base64.b64decode(payload_b64)
        except Exception:
            return b""
        if self._inbound_encoding == "mulaw":
            try:
                pcm = audioop.ulaw2lin(raw, 2)
            except Exception:
                return b""
        else:
            pcm = raw
        if self._inbound_sample_rate_hz == 16000 and len(pcm) >= 4:
            try:
                samples = memoryview(pcm).cast("h")
                pcm = bytes(samples[i] for i in range(0, len(samples), 2))
            except Exception:
                return b""
        return pcm

    @staticmethod
    def _trim_pcm_leading_silence(pcm: bytes, window: int = 320) -> bytes:
        if len(pcm) < window * 2:
            return pcm
        mv = memoryview(pcm).cast("h")
        idx = 0
        for i in range(0, len(mv) - window, window):
            chunk = mv[i : i + window]
            if max(abs(s) for s in chunk) > 120:
                idx = i * 2
                break
        else:
            return pcm
        return pcm[idx:]

    def _pcm_to_wire_chunks(self, pcm_lin: bytes) -> list[bytes]:
        """Outbound: Exotel Voicebot expects raw slin PCM16 @ 8 kHz (base64)."""
        if not pcm_lin:
            return []
        if len(pcm_lin) % 2:
            pcm_lin += b"\x00"
        pad = (320 - (len(pcm_lin) % 320)) % 320
        if pad:
            pcm_lin += b"\x00" * pad
        step = self._out_chunk_pcm
        return [pcm_lin[i : i + step] for i in range(0, len(pcm_lin), step)]

    async def _send_wire_audio(self, wire_chunk: bytes) -> None:
        if not self.stream_sid or not wire_chunk:
            return
        self._sequence_out += 1
        await self.ws.send_json(
            {
                "event": "media",
                "stream_sid": self.stream_sid,
                "sequence_number": str(self._sequence_out),
                "media": {"payload": base64.b64encode(wire_chunk).decode("ascii")},
            }
        )

    @staticmethod
    def _pcm_rms(pcm: bytes) -> int:
        if len(pcm) < 320:
            return 0
        try:
            return audioop.rms(pcm, 2)
        except Exception:
            return 0

    @staticmethod
    def _playback_seconds(pcm: bytes) -> float:
        """8 kHz mono PCM16."""
        return len(pcm) / 16000.0 if pcm else 0.0

    def _playback_guard_seconds(self, play_s: float, wire_chunk_count: int) -> float:
        """How long after the last outbound chunk PSTN may still be playing agent audio."""
        if wire_chunk_count <= 0 or play_s <= 0:
            return PLAYBACK_TAIL_S
        send_wall_s = max(0.0, (wire_chunk_count - 1)) * TTS_CHUNK_PAUSE_S + (
            CHUNK_PCM / 16000.0
        )
        # Chunks are paced slightly faster than real time; keep the listen gate closed until playout ends.
        remaining = max(0.0, play_s - send_wall_s) + PLAYBACK_TAIL_S
        return remaining

    async def _finalize_buffered_utterance(self) -> None:
        if self._turn_lock.locked():
            return
        await self._schedule_utterance_finalize()
        if self._utterance_finalize_task and not self._utterance_finalize_task.done():
            await self._utterance_finalize_task

    async def _run_stt_pipeline(self, buf: bytes) -> None:
        try:
            await self._stt_and_handle_reply(buf)
        finally:
            self._utterance_claim_active = False
            self._utterance_finalize_task = None

    async def _stt_and_handle_reply(self, buf: bytes) -> None:
        if len(buf) < MIN_SPEECH_BYTES:
            return
        if self._turn_lock.locked():
            return
        async with self._turn_lock:
            t0 = time.monotonic()
            rms = self._pcm_rms(buf)
            min_rms = self._min_stt_rms()
            if rms < MIN_STT_RMS_HARD_FLOOR:
                logger.info(
                    "Voicebot %s echo/noise discarded rms=%d bytes=%d",
                    self.call_id,
                    rms,
                    len(buf),
                )
                return
            if rms < min_rms:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="stt_discarded_low_energy",
                    reason="pipeline",
                    buffer_bytes=len(buf),
                    rms=rms,
                    min_rms=min_rms,
                    inbound_frames=self._media_chunks,
                )
                return
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stt_request",
                pcm_bytes=len(buf),
                rms=rms,
                encoding=self._inbound_encoding,
                ingress_hz=self._inbound_sample_rate_hz,
            )
            detected = ""
            try:
                if use_sarvam_inbound_voice():
                    text, detected = await asyncio.wait_for(
                        asyncio.to_thread(
                            sarvam_transcribe_pcm, buf, hint_language=self._listen_lang
                        ),
                        timeout=12.0,
                    )
                else:
                    from app.services.voice.gemini import transcribe_pcm_wav

                    text = await asyncio.wait_for(
                        asyncio.to_thread(transcribe_pcm_wav, buf), timeout=22.0
                    )
                    detected = self.lang_code
            except asyncio.TimeoutError:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="stt_provider_error",
                    provider_code="timeout",
                    encoding=self._inbound_encoding,
                    ingress_hz=self._inbound_sample_rate_hz,
                    pcm_bytes=len(buf),
                )
                return
            except Exception as exc:
                log_pipeline_event(
                    call_id=str(self.call_id),
                    stage="stt_provider_error",
                    provider_code=type(exc).__name__[:40],
                    encoding=self._inbound_encoding,
                    ingress_hz=self._inbound_sample_rate_hz,
                    pcm_bytes=len(buf),
                )
                return
            text = (text or "").strip()
            log_pipeline_event(
                call_id=str(self.call_id),
                stage="stt_final" if text else "stt_empty",
                text_len=len(text),
                stt_lang=detected or self._listen_lang,
            )
            if not text:
                logger.info("Voicebot %s empty STT skipped bytes=%d", self.call_id, len(buf))
                self._stt_miss_streak += 1
                if not self._browser_preview and self._stt_miss_streak in (1, 3):
                    await self._speak(self._invite_caller_line())
                ready, why = sarvam_media_ready()
                if (
                    not ready
                    and why == "insufficient_quota"
                    and self._browser_preview
                    and self._stt_miss_streak == 1
                ):
                    await self._emit_browser_transcript(
                        "system",
                        "Sarvam STT/TTS quota exhausted — top up at docs.sarvam.ai, then restart the test.",
                    )
                    await self._speak(
                        "Sorry, voice recognition is temporarily unavailable. Please add Sarvam credits."
                    )
                else:
                    await self._maybe_prompt_missed_speech()
                return
            if text == self._last_final_text:
                logger.info("Voicebot %s duplicate STT skipped", self.call_id)
                return
            if is_spurious_stt_snippet(text) and not is_short_acknowledgment(text):
                logger.info("Voicebot %s spurious STT skipped text=%r", self.call_id, text[:40])
                self._stt_miss_streak += 1
                await self._maybe_prompt_missed_speech()
                return
            log_voice_turn(
                call_id=str(self.call_id),
                turn_index=self._voice_turn_seq + 1,
                inbound_media_chunks=self._media_chunks,
                greeting_done=self._greeting_done,
                listening=int(self._accepting_caller_audio()),
                stt_text_len=len(text),
                stt_lang=detected or self._listen_lang,
                conv_lang=self.lang_code,
                knowledge_revision="",
                drop_reason="",
                lookup=f"pre_stt:{self._inbound_encoding}:rms={rms}:bytes={len(buf)}",
            )
            db = SessionLocal()
            try:
                call_row = db.get(Call, self.call_id)
                fields = (call_row.captured_fields or {}) if call_row else {}
                emp_lang = str(fields.get("employee_language") or "Telugu")
                conv = str(fields.get("conversation_language") or self.lang_code)
            finally:
                db.close()
            reason = reject_turn_reason(
                text,
                employee_language=emp_lang,
                conversation_language=conv,
            )
            if reason:
                self._rejected_turns += 1
                self._voice_turn_seq += 1
                log_voice_turn(
                    call_id=str(self.call_id),
                    turn_index=self._voice_turn_seq,
                    inbound_media_chunks=self._media_chunks,
                    greeting_done=self._greeting_done,
                    listening=int(self._accepting_caller_audio()),
                    stt_text_len=len(text),
                    stt_lang=detected or self._listen_lang,
                    conv_lang=self.lang_code,
                    knowledge_revision=knowledge_revision_from_fields(fields),
                    reply_audio_sent=0,
                    drop_reason=reason,
                )
                logger.info(
                    "Voicebot %s turn_rejected reason=%s len=%d conv=%s",
                    self.call_id,
                    reason,
                    len(text),
                    self.lang_code,
                )
                if self._rejected_turns in (2, 5):
                    await self._speak(self._repeat_request_line())
                return
            self._rejected_turns = 0
            self._stt_miss_streak = 0
            self._voice_turn_seq += 1
            from_text = detect_language_from_text(text)
            if from_text:
                self._maybe_lock_caller_language(from_text, transcript=text)
            stt_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "Voicebot %s STT ms=%d bytes=%d lang=%s text_len=%d accepted=1",
                self.call_id,
                stt_ms,
                len(buf),
                self.lang_code,
                len(text),
            )
            self._last_final_text = text
            await self._emit_browser_transcript("caller", text, turn_id=self._voice_turn_seq)
            if self.speaking or time.monotonic() < self._playback_until:
                await self._interrupt_playback()
            stt_for_lang = stt_language_for_reply(
                text,
                detected,
                employee_language=emp_lang,
                conversation_language=conv,
            )
        stt_ms = int((time.monotonic() - t0) * 1000)
        await self._handle_caller_text(
            text,
            stt_language=stt_for_lang or detected,
            turn_started_at=t0,
            utterance_ms=stt_ms,
            stt_confidence=None,
        )

    def _silence_pause_seconds(self) -> float:
        if self._browser_preview:
            return BROWSER_SILENCE_SECONDS
        # Slightly longer pause only while the caller is already mid-utterance
        # (dates / phone digits), not from the first syllable.
        if len(self.pcm_buffer) > 48_000:
            return SILENCE_SECONDS_LONG
        return SILENCE_SECONDS

    def _on_listen_gate_opened(self) -> None:
        pre_before = len(self._pre_roll)
        # Agent audio has stopped — pre-roll is caller speech (already capped at PRE_ROLL_MAX_BYTES).
        self._merge_pre_roll_into_buffer(force=True, full=True)
        log_pipeline_event(
            call_id=str(self.call_id),
            stage="listen_gate_open",
            pre_roll_before=pre_before,
            buffer_bytes=len(self.pcm_buffer),
            inbound_frames=self._media_chunks,
            encoding=self._inbound_encoding,
            ingress_hz=self._inbound_sample_rate_hz,
        )

    async def _silence_loop(self) -> None:
        while True:
            await asyncio.sleep(0.12)
            accepting = self._accepting_caller_audio()
            if accepting and not self._listen_gate_was_open:
                self._on_listen_gate_opened()
                await self._evaluate_utterance_timer()
            self._listen_gate_was_open = accepting
            has_speech = len(self.pcm_buffer) >= MIN_SPEECH_BYTES or len(self._pre_roll) >= MIN_SPEECH_BYTES
            if not has_speech:
                self._utterance_end_deadline = 0.0
                continue
            # Never wipe pre_roll while the agent is still talking — that drops
            # early caller syllables captured during greeting/TTS.
            if accepting and len(self.pcm_buffer) >= MIN_SPEECH_BYTES:
                combined = bytes(self.pcm_buffer)
                if not self._buffer_meets_stt_energy(combined):
                    self._discard_low_energy_buffer(reason="silence_loop")
                    continue
            if accepting and self._pre_roll:
                self._merge_pre_roll_into_buffer()
            if accepting and len(self.pcm_buffer) >= MAX_UTTERANCE_PCM_BYTES:
                await self._schedule_utterance_finalize()
                continue
            now = time.monotonic()
            if self._utterance_end_deadline <= 0:
                deadline = self._silence_deadline_for_speech()
                if deadline > 0 and self._last_buffer_growth_at > 0:
                    self._utterance_end_deadline = deadline
                    if accepting and now >= deadline:
                        self._utterance_end_deadline = 0.0
                        await self._schedule_utterance_finalize()
                    elif accepting:
                        log_pipeline_event(
                            call_id=str(self.call_id),
                            stage="utterance_pause_armed",
                            buffer_bytes=len(self.pcm_buffer),
                            pause_ms=int(max(0.0, deadline - now) * 1000),
                            inbound_frames=self._media_chunks,
                        )
                continue
            if now < self._utterance_end_deadline:
                continue
            if not accepting:
                continue
            self._utterance_end_deadline = 0.0
            await self._schedule_utterance_finalize()

    def _maybe_lock_caller_language(self, bcp47: str, *, transcript: str = "") -> None:
        """Lock from transcript script / explicit switch — not STT metadata."""
        from app.services.voice.sarvam import is_hindi_ack_noise

        if bcp47 not in ("te-IN", "hi-IN", "en-IN"):
            return
        if transcript and (
            is_spurious_stt_snippet(transcript) or is_hindi_ack_noise(transcript)
        ):
            return
        if _has_telugu_in_transcript(transcript):
            bcp47 = "te-IN"
        if self._employee_bcp47 == "te-IN" and bcp47 == "hi-IN":
            from app.services.voice.speech_route import apply_explicit_language_switch

            if len((transcript or "").strip()) < 28:
                if apply_explicit_language_switch(transcript, "te-IN") != "hi-IN":
                    return
            elif not _has_devanagari_script(transcript):
                return
        if bcp47 in ("te-IN", "hi-IN"):
            self._caller_language_locked = True
            self.lang_code = bcp47
            self._listen_lang = bcp47
            self._persist_conversation_language(bcp47)
        elif not self._caller_language_locked:
            self.lang_code = "en-IN"
            self._listen_lang = "en-IN"

    def _persist_conversation_language(self, bcp47: str) -> None:
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            call.captured_fields = {
                **(call.captured_fields or {}),
                "conversation_language": bcp47,
            }
            db.commit()
        finally:
            db.close()

    def _load_tts_speaker_from_db(self) -> None:
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            fields = call.captured_fields or {}
            spk = str(fields.get("tts_speaker") or "").strip()
            if spk:
                self._tts_speaker = spk
            self._browser_preview = bool(fields.get("browser_preview"))
        finally:
            db.close()

    async def _emit_browser_transcript(
        self, role: str, text: str, *, turn_id: int | None = None
    ) -> None:
        if not self._browser_preview or not text.strip():
            return
        tid = turn_id if turn_id is not None else self._voice_turn_seq
        try:
            await self.ws.send_json(
                {
                    "event": "transcript",
                    "stream_sid": self.stream_sid,
                    "transcript": {
                        "role": role,
                        "text": text.strip()[:800],
                        "turn_id": tid,
                    },
                }
            )
        except Exception:
            pass

    async def _play_greeting(self) -> None:
        if self._greeting_done:
            return
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            fields = call.captured_fields or {}
            if fields.get("voice_greeting_played"):
                self._greeting_done = True
                return
            brief = str(fields.get("employee_brief") or "")
            web = str(fields.get("employee_website_knowledge") or "")
            emp_lang = str(fields.get("employee_language") or "English")
            if use_sarvam_inbound_voice():
                from app.services.voice.m05_sarvam import m05_voice_enabled, spoken_opening

                if m05_voice_enabled(call_fields=fields):
                    try:
                        greet = spoken_opening(emp_lang)
                        greet_lang = language_bcp47_from_employee(emp_lang)
                    except Exception:
                        logger.exception("m05_opening_failed")
                        greet, greet_lang = opening_greeting_for_employee(
                            employee_language=emp_lang,
                            brief=brief,
                            website_knowledge=web,
                            phone=not self._browser_preview,
                        )
                else:
                    greet, greet_lang = opening_greeting_for_employee(
                        employee_language=emp_lang,
                        brief=brief,
                        website_knowledge=web,
                        phone=not self._browser_preview,
                    )
                self.lang_code = greet_lang
                self._listen_lang = greet_lang
            elif brief:
                greet = f"Hello, thanks for calling. {str(brief)[:220]}"
            else:
                greet = "Hello, thanks for calling. How can I help you today?"
            await self._emit_browser_transcript("agent", greet, turn_id=0)
            await self._speak(
                greet,
                playback_mark=MARK_GREETING_PLAYBACK,
            )
            self._greeting_done = True
            if not self._browser_preview:
                if self._pcm_rms(bytes(self.pcm_buffer)) < MIN_STT_RMS_HARD_FLOOR:
                    self.pcm_buffer.clear()
                    self._pre_roll.clear()
            emp = language_bcp47_from_employee(emp_lang)
            self._employee_bcp47 = emp
            self._caller_language_locked = emp == "te-IN"
            call.captured_fields = {
                **(call.captured_fields or {}),
                "conversation_language": emp,
            }
            call.captured_fields = {
                **(call.captured_fields or {}),
                "voice_greeting_played": True,
            }
            db.commit()
            self._speech_stack = "sarvam"
        finally:
            db.close()

    async def _emit_call_trace(self) -> None:
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            fields = call.captured_fields or {}
            emp = str(fields.get("employee_language") or "English")
            bcp47 = employee_default_bcp47(emp)
            self._speech_stack = "sarvam"
            spk = (self._tts_speaker or fields.get("tts_speaker") or "shubh")
            models = {
                "stt_model_requested": "saaras:v4",
                "tts_voice_requested": f"bulbul:v4-flash/{spk}",
                "tts_voice_confirmed": f"bulbul:v4-flash/{spk}",
            }
            trace = emit_voice_session_trace(
                channel="exotel",
                call_id=str(self.call_id),
                locale_bcp47=bcp47,
                speech_stack=self._speech_stack,
                stt_model=models["stt_model_requested"],
                tts_voice_requested=models["tts_voice_requested"],
                tts_voice_confirmed=models.get("tts_voice_confirmed"),
                knowledge_revision=knowledge_revision_from_fields(fields),
                knowledge_state=str(fields.get("knowledge_state") or "employee_snapshot"),
                audio_flags={
                    "ingress_hz": 8000,
                    "playback_tail_s": PLAYBACK_TAIL_S,
                    "room_tone": False,
                },
            )
            import os

            build_sha = (os.getenv("KARYUK_VOICE_BUILD_SHA") or "unknown").strip()[:64]
            call.captured_fields = {
                **fields,
                "voice_trace_id": trace["trace_id"],
                "voice_build_sha": build_sha,
            }
            db.commit()
        finally:
            db.close()

    def _repeat_request_line(self) -> str:
        emp = self._employee_bcp47 if self._employee_bcp47 in ("te-IN", "hi-IN", "en-IN") else self.lang_code
        return {
            "te-IN": "చివరి మాట సరిగ్గా వినిపించలేదు. మీ ప్రశ్నను మళ్లీ చెప్తారా?",
            "hi-IN": "आख़िरी बात साफ़ नहीं सुनाई दी। कृपया अपना सवाल दोबारा बताइए।",
            "en-IN": "Sorry, I did not catch the last part. Please repeat your question.",
        }.get(emp, "Please say your question again.")

    def _invite_caller_line(self) -> str:
        emp = self._employee_bcp47 if self._employee_bcp47 in ("te-IN", "hi-IN", "en-IN") else self.lang_code
        return {
            "te-IN": "ఆలోచించి మీ ప్రశ్న లేదా అవసరం చెప్పండి.",
            "hi-IN": "अपना सवाल या ज़रूरत बताइए।",
            "en-IN": "Please tell me your question or what you need.",
        }.get(emp, "Please tell me what you need.")

    async def _maybe_prompt_missed_speech(self) -> None:
        if self._stt_miss_streak not in (2, 5) or self.speaking:
            return
        if time.monotonic() < self._playback_until:
            return
        await self._speak(self._repeat_request_line())

    async def _barge_maybe_interrupt(self, pcm: bytes) -> None:
        if not self.speaking or not self._barge_in_enabled:
            return
        if len(pcm) < 4800:
            return
        text, _ = await asyncio.to_thread(
            sarvam_transcribe_pcm, pcm, hint_language=self._listen_lang
        )
        self._stt_partial_text = (text or "").strip()
        if len(self._stt_partial_text.split()) < 1:
            return
        self._barge_pcm_window.clear()
        self._barge_in_count += 1
        await self._interrupt_playback()

    async def _interrupt_playback(self) -> None:
        self._speak_generation += 1
        self.speaking = False
        self._playback_until = 0.0
        self.pcm_buffer.clear()
        self._pre_roll.clear()
        self._trim_assistant_history_to_played()
        if self.stream_sid:
            try:
                await self.ws.send_json({"event": "clear", "stream_sid": self.stream_sid})
            except Exception:
                pass

    def _trim_assistant_history_to_played(self) -> None:
        played = " ".join(self._confirmed_spoken).strip()
        if not played:
            return
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            fields = dict(call.captured_fields or {})
            chat = fields.get("inbound_chat") or {}
            turns = list(chat.get("turns") or [])
            for i in range(len(turns) - 1, -1, -1):
                if turns[i].get("role") == "assistant":
                    turns[i]["text"] = played
                    break
            fields["inbound_chat"] = {"turns": turns}
            call.captured_fields = fields
            db.commit()
        finally:
            db.close()
        self._mark_sentence.clear()

    async def _speak_stream_sentence(self, sentence: str, mark: str) -> None:
        if not self.stream_sid or not sentence.strip():
            return
        self._mark_sentence[mark] = sentence
        gen = self._speak_generation + 1
        self._speak_generation = gen
        self.speaking = True
        if self._agent_audio_started_at <= 0:
            self._agent_audio_started_at = time.monotonic()
        tts_lang = self._tts_lang_for_text(sentence)
        tts_t0 = time.monotonic()
        # Always use REST TTS on PSTN. Bulbul streaming WS can hang on connect/recv
        # (same failure mode as Saaras WS STT) and leave the caller with silence.
        try:
            pcm = await asyncio.wait_for(
                asyncio.to_thread(
                    sarvam_tts_pcm_8k,
                    sentence,
                    tts_lang,
                    speaker=self._tts_speaker,
                    rest_only=True,
                ),
                timeout=12.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Voicebot %s REST TTS timeout for stream sentence", self.call_id)
            pcm = b""
        if not pcm:
            self.speaking = False
            return
        pcm = self._trim_pcm_leading_silence(pcm)
        play_s = self._playback_seconds(pcm)
        wire_chunks = self._pcm_to_wire_chunks(pcm)
        for wire in wire_chunks:
            if gen != self._speak_generation:
                return
            if self._first_agent_media_at is None:
                self._first_agent_media_at = time.monotonic()
            await self._send_wire_audio(wire)
        if gen == self._speak_generation:
            guard_s = self._playback_guard_seconds(play_s, len(wire_chunks))
            self._playback_until = time.monotonic() + guard_s
            await self.ws.send_json(
                {"event": "mark", "stream_sid": self.stream_sid, "mark": {"name": mark}}
            )
            self._arm_mark_fallback(mark, guard_s + PLAYBACK_TAIL_S)
        self.speaking = False
        ttfb = int((time.monotonic() - tts_t0) * 1000)
        if self._bulbul is not None and self._bulbul.connect_count == 1:
            if self._bulbul.sentence_count == 1:
                self._last_tts_ttfb_ms = ttfb

    async def _handle_caller_text(
        self,
        text: str,
        *,
        stt_language: str = "",
        turn_started_at: float = 0.0,
        utterance_ms: int = 0,
        stt_confidence: float | None = None,
    ) -> None:
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if not call:
                return
            fields_pre = dict(call.captured_fields or {})
            fields_pre["last_utterance_ms"] = utterance_ms
            fields_pre["last_stt_confidence"] = stt_confidence
            call.captured_fields = fields_pre
            db.commit()
            self._caller_eos_at = turn_started_at or time.monotonic()
            self._confirmed_spoken = []
            self._first_agent_media_at = None
            self._agent_audio_started_at = 0.0
            t1 = time.monotonic()
            stt_ms = int((t1 - turn_started_at) * 1000) if turn_started_at else 0
            # Default off: streaming LLM+TTS path was hanging after STT on live Exotel.
            use_stream = os.getenv("KARYUK_PSTN_STREAM", "0").strip() in ("1", "true", "on", "yes")
            if use_stream and not self._browser_preview:

                async def _on_sentence(sent: str, mark: str) -> None:
                    await self._speak_stream_sentence(sent, mark)

                hangup, fields, reply = await run_pstn_stream_turn(
                    db,
                    call,
                    caller_text=text,
                    stt_language=stt_language or None,
                    on_sentence=_on_sentence,
                )
            else:
                reply, hangup = process_inbound_speech(
                    db, call, caller_text=text, stt_language=stt_language or None
                )
                fields = call.captured_fields or {}
            think_ms = int((time.monotonic() - t1) * 1000)
            db.refresh(call)
            fields = call.captured_fields or {}
            conv = fields.get("conversation_language")
            emp_bcp = language_bcp47_from_employee(str(fields.get("employee_language") or ""))
            switched = apply_explicit_language_switch(text, str(conv) if conv else emp_bcp)
            if switched in ("te-IN", "hi-IN", "en-IN") and (
                len(text.strip()) >= 24 or switched != conv
            ):
                if emp_bcp == "te-IN" and switched == "hi-IN" and len(text.strip()) < 28:
                    switched = "te-IN"
                fields["conversation_language"] = switched
                call.captured_fields = fields
                db.commit()
                conv = switched
            if conv in ("te-IN", "hi-IN", "en-IN"):
                self.lang_code = str(conv)
                self._listen_lang = str(conv)
                self._speech_stack = "sarvam"
                if conv in ("te-IN", "hi-IN"):
                    self._caller_language_locked = True
            # Speak at most once. Stream path already played sentences via on_sentence.
            if reply and reply.strip() and use_stream and not self._browser_preview:
                from app.services.voice.spoken_output import filter_caller_facing_reply

                spoken = cap_spoken_reply(
                    filter_caller_facing_reply(reply, lang=self.lang_code),
                    max_chars=160,
                )
                await self._emit_browser_transcript("agent", spoken, turn_id=self._voice_turn_seq)
                tts_ttfb_ms = (
                    int((self._first_agent_media_at - self._caller_eos_at) * 1000)
                    if self._first_agent_media_at and self._caller_eos_at
                    else 0
                )
            elif reply and reply.strip():
                from app.services.voice.spoken_output import filter_caller_facing_reply

                spoken = cap_spoken_reply(
                    filter_caller_facing_reply(reply, lang=self.lang_code),
                    max_chars=160,
                )
                # Skip identical back-to-back agent lines (echo / tiny STT loops).
                if spoken == getattr(self, "_last_spoken_reply", ""):
                    logger.info("Voicebot %s duplicate reply skipped", self.call_id)
                    tts_ttfb_ms = 0
                else:
                    await self._emit_browser_transcript("agent", spoken, turn_id=self._voice_turn_seq)
                    tts_t0 = time.monotonic()
                    await self._speak(spoken)
                    self._last_spoken_reply = spoken
                    tts_ttfb_ms = int((time.monotonic() - tts_t0) * 1000)
            else:
                tts_ttfb_ms = 0
            if reply and reply.strip():
                total_ms = int((time.monotonic() - turn_started_at) * 1000) if turn_started_at else 0
                spoken_for_log = (reply or "")[:500]
                from app.services.voice.voice_turn_metrics import append_turn_metrics, summarize_turn_metrics

                fields = append_turn_metrics(
                    fields,
                    {
                        "turn": self._voice_turn_seq,
                        "stt_final_ms": stt_ms,
                        "llm_ttft_ms": fields.get("llm_last_ttft_ms"),
                        "tts_ttfb_ms": tts_ttfb_ms,
                        "e2e_ms": total_ms,
                        "barge_in": self._barge_in_count,
                        "provider": fields.get("llm_primary_provider"),
                    },
                )
                fields["voice_latency_summary"] = summarize_turn_metrics(fields)
                call.captured_fields = fields
                db.commit()
                log_voice_turn(
                    call_id=str(self.call_id),
                    turn_index=self._voice_turn_seq,
                    inbound_media_chunks=self._media_chunks,
                    greeting_done=self._greeting_done,
                    listening=int(self._accepting_caller_audio()),
                    stt_text_len=len(text),
                    stt_lang=stt_language or self._listen_lang,
                    conv_lang=str(conv or self.lang_code),
                    knowledge_revision=knowledge_revision_from_fields(fields),
                    reply_pcm_bytes=len(spoken_for_log) * 4,
                    reply_audio_sent=1,
                    lookup=f"conversation:{booking_state_trace_summary(load_booking(fields))}",
                    think_ms=think_ms,
                )
                logger.info(
                    "Voicebot %s turn think_ms=%d total_to_tts_ms=%d",
                    self.call_id,
                    think_ms,
                    total_ms,
                )
            if hangup:
                # Let farewell TTS finish on the PSTN leg, then close WSS so Exotel
                # advances past Voicebot (Hangup / next applet) and ends the call.
                await asyncio.sleep(1.2)
                try:
                    await self.ws.close()
                except Exception:
                    logger.info("Voicebot %s hangup close failed", self.call_id)
                return
        except Exception:
            logger.exception("Voicebot %s turn failed", self.call_id)
            from app.services.voice.voice_repair_policy import pick_repair_reply

            fields = (call.captured_fields or {}) if (call := db.get(Call, self.call_id)) else {}
            turns = list((fields.get("inbound_chat") or {}).get("turns") or [])
            last = next(
                (t.get("text") for t in reversed(turns) if t.get("role") == "assistant" and t.get("text")),
                None,
            )
            line = pick_repair_reply(
                lang=self.lang_code,
                caller_text=text,
                fields=fields,
                turns=turns,
                last_agent=last,
                reason="turn_exception",
                db=db,
                workspace_id=getattr(call, "workspace_id", None) if call else None,
            )
            await self._speak(line)
        finally:
            db.close()

    def _tts_lang_for_text(self, text: str) -> str:
        if _has_telugu_in_transcript(text):
            return "te-IN"
        if any("\u0900" <= ch <= "\u097f" for ch in text):
            return "hi-IN"
        return clamp_voice_lang(self.lang_code, "en-IN")

    async def _speak(
        self,
        text: str,
        *,
        playback_mark: str = MARK_UTTERANCE_PLAYBACK,
    ) -> None:
        if not self.stream_sid or not text.strip():
            return
        gen = self._speak_generation + 1
        self._speak_generation = gen
        self.speaking = True
        tts_t0 = time.monotonic()
        tts_lang = self._tts_lang_for_text(text)
        stack = "sarvam"
        try:
            if use_sarvam_inbound_voice():
                pcm = await asyncio.to_thread(
                    sarvam_tts_pcm_8k,
                    text,
                    tts_lang,
                    speaker=self._tts_speaker,
                    rest_only=not self._browser_preview,
                )
            else:
                pcm = await asyncio.to_thread(_tts_pcm_8k_edge, text)
            if not pcm:
                backend = "sarvam" if use_sarvam_inbound_voice() else "edge-tts"
                short = text.strip()[:180]
                if short and short != text.strip() and use_sarvam_inbound_voice():
                    pcm = await asyncio.to_thread(
                        sarvam_tts_pcm_8k,
                        short,
                        tts_lang,
                        speaker=self._tts_speaker,
                        rest_only=not self._browser_preview,
                    )
                if not pcm and use_sarvam_inbound_voice():
                    pcm = await asyncio.to_thread(_tts_pcm_8k_edge, text)
                    if pcm:
                        stack = "edge-tts-fallback"
                        logger.warning(
                            "Voicebot %s Sarvam TTS unavailable — edge-tts fallback len=%d",
                            self.call_id,
                            len(text),
                        )
                if not pcm:
                    logger.warning("Voicebot %s TTS failed (%s) len=%d", self.call_id, backend, len(text))
                    if self._browser_preview:
                        await self._emit_browser_transcript(
                            "system",
                            "Agent audio unavailable (check Sarvam API credits).",
                        )
                    return
            pcm = self._trim_pcm_leading_silence(pcm)
            play_s = self._playback_seconds(pcm)
            wire_chunks = self._pcm_to_wire_chunks(pcm)
            first_ms = int((time.monotonic() - tts_t0) * 1000)
            logger.info(
                "Voicebot %s TTS ok lang=%s stack=%s pcm=%d chunks=%d first_ms=%d",
                self.call_id,
                tts_lang,
                stack,
                len(pcm),
                len(wire_chunks),
                first_ms,
            )
            for wire in wire_chunks:
                if gen != self._speak_generation:
                    logger.info("Voicebot %s stale TTS discarded", self.call_id)
                    return
                await self._send_wire_audio(wire)
                await asyncio.sleep(TTS_CHUNK_PAUSE_S)
            if gen == self._speak_generation:
                guard_s = self._playback_guard_seconds(play_s, len(wire_chunks))
                self._playback_until = time.monotonic() + guard_s
            if self.stream_sid and gen == self._speak_generation and playback_mark:
                await self.ws.send_json(
                    {
                        "event": "mark",
                        "stream_sid": self.stream_sid,
                        "mark": {"name": playback_mark},
                    }
                )
                remain = max(0.0, self._playback_until - time.monotonic())
                self._arm_mark_fallback(playback_mark, remain + PLAYBACK_TAIL_S)
        finally:
            self.speaking = False
            if gen == self._speak_generation and self._playback_until <= time.monotonic():
                self._playback_until = time.monotonic() + PLAYBACK_TAIL_S
            self._ignore_input_until = max(
                self._playback_until,
                time.monotonic() + POST_SPEECH_COOLDOWN,
            )


def _has_telugu_in_transcript(text: str) -> bool:
    return any("\u0c00" <= ch <= "\u0c7f" for ch in (text or ""))


def _tts_pcm_8k_edge(text: str) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return b""
    try:
        import edge_tts
    except ImportError:
        return b""

    async def _mp3_file() -> str:
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        await edge_tts.Communicate(text[:600], "en-IN-NeerjaNeural").save(path)
        return path

    mp3_path = asyncio.run(_mp3_file())
    try:
        proc = subprocess.run(
            [ffmpeg, "-loglevel", "error", "-i", mp3_path, "-f", "s16le", "-ar", "8000", "-ac", "1", "-"],
            capture_output=True,
            timeout=45,
        )
        if proc.returncode != 0:
            return b""
        return proc.stdout
    finally:
        try:
            os.unlink(mp3_path)
        except OSError:
            pass