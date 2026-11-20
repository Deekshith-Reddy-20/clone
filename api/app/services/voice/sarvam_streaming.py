"""Sarvam realtime WS: Saaras v4 STT + Bulbul v4 Flash TTS (telephony 8 kHz)."""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import tempfile
import time
from typing import Any

from app.config import get_settings
from app.services.voice.pcm_audio import pcm_to_wav_bytes
from app.services.voice.sarvam import (
    STT_MODEL,
    TTS_MODEL,
    _normalize_detected_lang,
    _quota_error,
    _wav_b64_to_pcm,
    mark_sarvam_quota_exhausted,
    sarvam_configured,
)

logger = logging.getLogger(__name__)

_STT_RECV_S = 10.0
_TTS_RECV_S = 45.0


def _mp3_to_pcm8k(mp3: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not mp3:
        return b""
    fd, path = tempfile.mkstemp(suffix=".mp3")
    try:
        import os

        os.write(fd, mp3)
        os.close(fd)
        proc = subprocess.run(
            [ffmpeg, "-loglevel", "error", "-i", path, "-f", "s16le", "-ar", "8000", "-ac", "1", "-"],
            capture_output=True,
            timeout=45,
        )
        return proc.stdout if proc.returncode == 0 else b""
    finally:
        try:
            import os

            os.unlink(path)
        except OSError:
            pass


def _sarvam_client():
    from sarvamai import SarvamAI

    key = get_settings().sarvam_api_key.strip()
    return SarvamAI(api_subscription_key=key)


def transcribe_pcm_streaming(
    pcm: bytes,
    *,
    hint_language: str = "en-IN",
) -> tuple[str, str]:
    fallback = _normalize_detected_lang(hint_language, "en-IN")
    if not sarvam_configured() or len(pcm) < 1600:
        return "", fallback
    wav_b64 = base64.b64encode(pcm_to_wav_bytes(pcm)).decode("ascii")
    lang_hint = fallback if fallback in ("te-IN", "hi-IN", "en-IN") else "unknown"
    try:
        client = _sarvam_client()
        with client.speech_to_text_streaming.connect(
            language_code=lang_hint,
            model=STT_MODEL,
            mode="codemix",
            sample_rate="8000",
            flush_signal="true",
        ) as ws:
            ws.transcribe(wav_b64, encoding="audio/wav", sample_rate=8000)
            ws.flush()
            transcript = ""
            detected = fallback
            deadline = time.monotonic() + _STT_RECV_S
            while time.monotonic() < deadline:
                try:
                    msg = ws.recv()
                except Exception:
                    break
                if msg.type == "error":
                    data = msg.data
                    code = ""
                    if data is not None:
                        code = str(
                            getattr(data, "code", None)
                            or getattr(data, "error", None)
                            or getattr(data, "message", None)
                            or data
                        )[:120]
                    logger.warning(
                        "Sarvam STT WS rejected code=%s",
                        code or "unknown",
                    )
                    break
                if msg.type != "data" or not msg.data:
                    continue
                data = msg.data
                if hasattr(data, "transcript"):
                    piece = (getattr(data, "transcript", "") or "").strip()
                    if piece:
                        logger.debug("stt_partial len=%d text=%s", len(piece), piece[:80])
                        transcript = piece
                    lc = getattr(data, "language_code", None)
                    if lc:
                        detected = _normalize_detected_lang(str(lc), fallback)
                metrics = getattr(data, "metrics", None)
                if metrics and getattr(metrics, "is_final", None) is True:
                    break
            return transcript, detected
    except Exception as exc:
        if _quota_error(exc):
            mark_sarvam_quota_exhausted()
        code = ""
        if hasattr(exc, "status_code"):
            code = f"http_{exc.status_code}"
        logger.warning("Sarvam STT WS connect_failed code=%s err=%s", code or "n/a", type(exc).__name__)
        return "", fallback


def tts_pcm_8k_streaming(
    text: str,
    language_code: str,
    *,
    speaker: str | None = None,
) -> bytes:
    snippet = (text or "").strip()[:1500]
    if not snippet or not sarvam_configured():
        return b""
    lang = _normalize_detected_lang(language_code, "en-IN")
    from app.services.voice.voice_catalog import resolve_bulbul_speaker_for_lang

    spk = resolve_bulbul_speaker_for_lang(speaker, lang, tts_model=TTS_MODEL)
    audio_chunks: list[bytes] = []
    try:
        client = _sarvam_client()
        with client.text_to_speech_streaming.connect(
            model=TTS_MODEL,
            send_completion_event="true",
        ) as ws:
            ws.configure(
                target_language_code=lang,
                speaker=spk,
                pace=1.05,
                speech_sample_rate=8000,
                output_audio_codec="wav",
                enable_preprocessing=True,
            )
            ws.convert(snippet)
            ws.flush()
            deadline = time.monotonic() + _TTS_RECV_S
            while time.monotonic() < deadline:
                try:
                    msg: Any = ws.recv()
                except Exception:
                    break
                if getattr(msg, "type", None) == "error":
                    break
                if getattr(msg, "type", None) == "audio" and getattr(msg, "data", None):
                    raw = base64.b64decode(msg.data.audio)
                    ctype = str(getattr(msg.data, "content_type", "") or "")
                    if raw[:4] == b"RIFF":
                        audio_chunks.append(_wav_b64_to_pcm(raw))
                    elif "mp3" in ctype or raw[:3] == b"ID3" or raw[:2] == b"\xff\xfb":
                        pcm = _mp3_to_pcm8k(raw)
                        if pcm:
                            audio_chunks.append(pcm)
                if getattr(msg, "type", None) == "event":
                    name = getattr(getattr(msg, "data", None), "event_type", "") or ""
                    if str(name).lower() in ("completion", "completed", "done"):
                        break
        return b"".join(audio_chunks)
    except Exception as exc:
        if _quota_error(exc):
            mark_sarvam_quota_exhausted()
        logger.warning("Sarvam TTS WS failed: %s", exc)
        return b""


class BulbulTtsSession:
    """One Bulbul TTS WebSocket per voice call (reuse across sentences)."""

    def __init__(self, *, speaker: str | None = None) -> None:
        self._speaker = speaker
        self._ws: Any = None
        self._client: Any = None
        self._ctx: Any = None
        self._connected = False
        self.connect_count = 0
        self.sentence_count = 0
        self.first_sentence_ttfb_ms: float | None = None
        self.second_sentence_ttfb_ms: float | None = None

    def close(self) -> None:
        if self._ctx is not None:
            try:
                self._ctx.__exit__(None, None, None)
            except Exception:
                pass
        elif self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None
        self._ctx = None
        self._connected = False

    def _ensure(self) -> bool:
        if self._connected and self._ws is not None:
            return True
        if not sarvam_configured():
            return False
        try:
            self._client = _sarvam_client()
            self._ctx = self._client.text_to_speech_streaming.connect(
                model=TTS_MODEL,
                send_completion_event="true",
            )
            self._ws = self._ctx.__enter__()
            self._connected = True
            self.connect_count += 1
            logger.info("BulbulTtsSession connect n=%d", self.connect_count)
            return True
        except Exception as exc:
            logger.warning("Bulbul TTS session connect failed: %s", exc)
            self.close()
            return False

    def synthesize_pcm8k(self, text: str, language_code: str) -> bytes:
        snippet = (text or "").strip()[:1500]
        if not snippet:
            return b""
        if not self._ensure():
            return b""
        t0 = time.monotonic()
        lang = _normalize_detected_lang(language_code, "en-IN")
        from app.services.voice.voice_catalog import resolve_bulbul_speaker_for_lang

        spk = resolve_bulbul_speaker_for_lang(self._speaker, lang, tts_model=TTS_MODEL)
        audio_chunks: list[bytes] = []
        try:
            assert self._ws is not None
            self._ws.configure(
                target_language_code=lang,
                speaker=spk,
                pace=1.05,
                speech_sample_rate=8000,
                output_audio_codec="wav",
                enable_preprocessing=True,
            )
            self._ws.convert(snippet)
            self._ws.flush()
            deadline = time.monotonic() + _TTS_RECV_S
            while time.monotonic() < deadline:
                try:
                    msg: Any = self._ws.recv()
                except Exception:
                    break
                if getattr(msg, "type", None) == "error":
                    break
                if getattr(msg, "type", None) == "audio" and getattr(msg, "data", None):
                    raw = base64.b64decode(msg.data.audio)
                    ctype = str(getattr(msg.data, "content_type", "") or "")
                    if raw[:4] == b"RIFF":
                        audio_chunks.append(_wav_b64_to_pcm(raw))
                    elif "mp3" in ctype or raw[:3] == b"ID3" or raw[:2] == b"\xff\xfb":
                        pcm = _mp3_to_pcm8k(raw)
                        if pcm:
                            audio_chunks.append(pcm)
                if getattr(msg, "type", None) == "event":
                    name = getattr(getattr(msg, "data", None), "event_type", "") or ""
                    if str(name).lower() in ("completion", "completed", "done"):
                        break
            pcm_out = b"".join(audio_chunks)
            ttfb = (time.monotonic() - t0) * 1000.0
            self.sentence_count += 1
            if self.sentence_count == 1:
                self.first_sentence_ttfb_ms = ttfb
            elif self.sentence_count == 2:
                self.second_sentence_ttfb_ms = ttfb
            return pcm_out
        except Exception as exc:
            logger.warning("Bulbul TTS session sentence failed: %s", exc)
            self.close()
            return b""