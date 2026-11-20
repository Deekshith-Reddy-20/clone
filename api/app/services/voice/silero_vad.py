"""Silero VAD (onnx, CPU) with energy fallback when model unavailable."""

from __future__ import annotations

import audioop
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_MODEL = Path(__file__).resolve().parent / "data" / "silero_vad.onnx"

_SAMPLE_RATE = 8000
_WINDOW_SAMPLES = 256


@lru_cache(maxsize=1)
def _session():
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        return None
    try:
        if not _MODEL.is_file():
            return None
        sess = ort.InferenceSession(str(_MODEL), providers=["CPUExecutionProvider"])
        return sess, np
    except Exception as exc:
        logger.warning("silero_vad load failed: %s", exc)
        return None


def vad_engine_name() -> str:
    return "silero" if _session() is not None else "energy"


def speech_ms_in_pcm(pcm: bytes, *, sample_rate: int = _SAMPLE_RATE) -> float:
    """Milliseconds of speech detected in PCM16 mono buffer."""
    if len(pcm) < _WINDOW_SAMPLES * 2:
        return 0.0
    loaded = _session()
    if loaded is None:
        try:
            rms = audioop.rms(pcm, 2)
            return (len(pcm) / (sample_rate * 2)) * 1000.0 if rms >= 180 else 0.0
        except Exception:
            return 0.0
    sess, np = loaded
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate != 16000:
        import audioop as ap

        audio16 = ap.ratecv(pcm, 2, 1, sample_rate, 16000, None)[0]
        audio = np.frombuffer(audio16, dtype=np.int16).astype(np.float32) / 32768.0
    state = np.zeros((2, 1, 128), dtype=np.float32)
    sr = np.array(16000, dtype=np.int64)
    speech_frames = 0
    hop = 512
    for i in range(0, len(audio) - hop, hop):
        chunk = audio[i : i + hop]
        if len(chunk) < hop:
            break
        inp = chunk.reshape(1, -1)
        out, state = sess.run(None, {"input": inp, "state": state, "sr": sr})
        if float(out[0][0]) >= 0.5:
            speech_frames += 1
    return speech_frames * (hop / 16000.0) * 1000.0