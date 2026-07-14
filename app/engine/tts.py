"""TTS engine — sinh wav cho 1 fragment.

Fragment.effective_tts() -> tách câu (tts_chunks) -> infer từng câu -> concat
(trim=True, gap giữa câu) thành wav của fragment. Đây là cùng cách vo.py sinh
audio, chỉ đổi đơn vị line -> fragment.

RealTTS lazy-load vieneu 1 lần (nặng). FakeTTS sinh sine wav để smoke offline.
"""

from __future__ import annotations

from pathlib import Path

from ..models import tts_chunks
from . import audio


class TTSEngine:
    """Interface: generate(tts_text, voice, gap_s, out_wav, tmp_dir) -> duration_s."""

    def generate(self, tts_text: str, voice: str, gap_s: float,
                 out_wav: Path, tmp_dir: Path) -> float:
        raise NotImplementedError


class RealTTS(TTSEngine):
    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from vieneu import Vieneu  # nặng — chỉ import khi thật sự dùng
            self._model = Vieneu()
        return self._model

    def generate(self, tts_text: str, voice: str, gap_s: float,
                 out_wav: Path, tmp_dir: Path) -> float:
        tts = self._load()
        chunks = tts_chunks(tts_text)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i, c in enumerate(chunks):
            p = tmp_dir / f"chunk-{i}.wav"
            out = tts.infer(c, voice=voice)
            tts.save(out, str(p))
            paths.append(p)
        dur = audio.concat_wavs(paths, out_wav, gap_s, trim=True)
        for p in paths:
            p.unlink(missing_ok=True)
        return dur


class FakeTTS(TTSEngine):
    """Sine wav ~0.5s mỗi câu — smoke offline, không tải model."""

    def generate(self, tts_text: str, voice: str, gap_s: float,
                 out_wav: Path, tmp_dir: Path) -> float:
        import os
        import time
        # giả lập TTS chậm (test cancel job giữa batch) — mặc định 0, không delay
        delay = float(os.environ.get("VO_STUDIO_FAKE_DELAY_S", "0"))
        if delay > 0:
            time.sleep(delay)
        chunks = tts_chunks(tts_text) or [tts_text]
        tmp_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for i, c in enumerate(chunks):
            p = tmp_dir / f"chunk-{i}.wav"
            # thời lượng ~ số từ, để merge/offset có gì đó thực tế
            secs = max(0.4, 0.12 * len(c.split()))
            audio.write_sine(p, secs, freq=180 + 40 * (i % 3))
            paths.append(p)
        dur = audio.concat_wavs(paths, out_wav, gap_s, trim=False)
        for p in paths:
            p.unlink(missing_ok=True)
        return dur
