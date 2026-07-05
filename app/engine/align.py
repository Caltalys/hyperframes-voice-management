"""Force-align — timing cho từng từ trên wav của MỘT fragment (đoạn ngắn ->
whisper chính xác hơn nhiều so với align cả line dài).

RealAligner: port force_align từ vo.py. Whisper CHỈ cho timing; text hiển thị
lấy nguyên văn fragment.text (whisper hay sai chính tả tiếng Việt). Các run chưa
khớp được nội suy tuyến tính theo độ dài ký tự.

FakeAligner: chia đều thời lượng theo số từ — smoke offline.

Kết quả: list[Word] với start/end tính từ 0 (đầu wav fragment).
"""

from __future__ import annotations

import difflib
from pathlib import Path

from ..models import Word, norm_token
from . import audio


def _words_from_text(text: str) -> list[str]:
    # gạch ngang dùng riêng để ngắt nhịp, không hiển thị thành caption
    return [t for t in text.split() if t not in ("—", "–")]


class Aligner:
    def align(self, text: str, wav: Path) -> list[Word]:
        raise NotImplementedError


class RealAligner:
    def __init__(self, model_size: str = "small") -> None:
        self._model = None
        self._size = model_size

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._size, device="cpu", compute_type="int8")
        return self._model

    def align(self, text: str, wav: Path) -> list[Word]:
        model = self._load()
        segs, _ = model.transcribe(str(wav), language="vi", word_timestamps=True)
        ww = [w for s in segs for w in s.words]
        st = _words_from_text(text)
        sm = difflib.SequenceMatcher(
            a=[norm_token(w.word) for w in ww],
            b=[norm_token(t) for t in st],
            autojunk=False,
        )
        times: list = [None] * len(st)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                w = ww[blk.a + k]
                times[blk.b + k] = [w.start, w.end]
        total = audio.wav_duration(wav)
        # nội suy các run chưa match, trọng số theo độ dài ký tự
        i = 0
        while i < len(st):
            if times[i] is not None:
                i += 1
                continue
            j = i
            while j < len(st) and times[j] is None:
                j += 1
            t0 = times[i - 1][1] if i > 0 else 0.0
            t1 = times[j][0] if j < len(st) else total
            weights = [max(1, len(norm_token(st[k]))) for k in range(i, j)]
            span, acc = max(t1 - t0, 0.01 * len(weights)), 0.0
            for k, wgt in zip(range(i, j), weights):
                frac = wgt / sum(weights)
                times[k] = [t0 + acc * span, t0 + (acc + frac) * span]
                acc += frac
            i = j
        return [
            Word(id=f"w{i}", text=st[i],
                 start=round(times[i][0], 2), end=round(times[i][1], 2))
            for i in range(len(st))
        ]


class FakeAligner:
    """Chia đều thời lượng wav theo số từ — smoke offline."""

    def align(self, text: str, wav: Path) -> list[Word]:
        st = _words_from_text(text)
        total = audio.wav_duration(wav)
        if not st:
            return []
        step = total / len(st)
        return [
            Word(id=f"w{i}", text=st[i],
                 start=round(i * step, 2), end=round((i + 1) * step, 2))
            for i in range(len(st))
        ]
