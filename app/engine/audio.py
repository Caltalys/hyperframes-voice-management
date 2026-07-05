"""Xử lý wav — port concat_wavs/wav_duration từ vo.py.

Hai chế độ concat:
  trim=True  : ghép các CHUNK CÂU trong 1 fragment — trim lặng thừa đầu/cuối mỗi
               chunk để khoảng nghỉ = đúng gap_s (như vo.py). Dùng khi sinh take.
  trim=False : ghép các TAKE đã sạch thành 1 line — KHÔNG trim, để word-timing đã
               align trên từng take khớp chính xác vị trí trong line. Dùng khi merge.
"""

from __future__ import annotations

import wave
from pathlib import Path


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return round(w.getnframes() / w.getframerate(), 3)


def concat_wavs(paths: list[Path], out: Path, gap_s: float, trim: bool = True) -> float:
    """Ghép wav, chèn khoảng lặng gap_s giữa các phần. Trả duration của file ghép.

    trim=True: cắt lặng thừa hai đầu mỗi phần (dựa biên độ) trước khi ghép."""
    import numpy as np  # dependency của vieneu; cần cho smoke -> numpy ở lõi

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(paths[0])) as w0:
        params = w0.getparams()
    silence = b"\x00" * (
        int(params.framerate * gap_s) * params.sampwidth * params.nchannels
    )
    pad = int(params.framerate * 0.05)  # giữ 50ms đệm hai đầu khi trim
    with wave.open(str(out), "wb") as wo:
        wo.setparams(params)
        for i, p in enumerate(paths):
            if i:
                wo.writeframes(silence)
            with wave.open(str(p)) as wi:
                frames = wi.readframes(wi.getnframes())
            if trim:
                x = np.frombuffer(frames, dtype=np.int16)
                if x.size:
                    peak = np.abs(x).max()
                    loud = np.flatnonzero(np.abs(x) > 0.01 * peak) if peak else []
                    if len(loud):
                        lo = max(
                            0,
                            (int(loud[0]) - pad) // params.nchannels * params.nchannels,
                        )
                        hi = min(len(x), int(loud[-1]) + pad)
                        frames = x[lo:hi].tobytes()
            wo.writeframes(frames)
    return wav_duration(out)


def concat_segments(paths: list[Path], gaps_between: list[float], out: Path,
                    trim: bool = False) -> float:
    """Ghép các take thành 1 line. gaps_between[k] = khoảng lặng chèn GIỮA
    paths[k] và paths[k+1] (len = len(paths) - 1). trim=False để giữ nguyên
    word-timing đã align trên từng take. Trả duration file ghép."""
    assert len(gaps_between) == max(0, len(paths) - 1), "gaps_between phải = n-1"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(paths[0])) as w0:
        params = w0.getparams()

    def silence(sec: float) -> bytes:
        return b"\x00" * (
            int(params.framerate * sec) * params.sampwidth * params.nchannels
        )

    with wave.open(str(out), "wb") as wo:
        wo.setparams(params)
        for i, p in enumerate(paths):
            if i:
                wo.writeframes(silence(gaps_between[i - 1]))
            with wave.open(str(p)) as wi:
                wo.writeframes(wi.readframes(wi.getnframes()))
    return wav_duration(out)


def write_sine(path: Path, seconds: float, freq: float = 220.0,
               framerate: int = 22050) -> None:
    """Sinh wav sine đơn giản — chỉ dùng cho smoke offline (giả giọng đọc)."""
    import math
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * framerate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        frames = bytearray()
        for i in range(n):
            val = int(12000 * math.sin(2 * math.pi * freq * i / framerate))
            frames += struct.pack("<h", val)
        w.writeframes(bytes(frames))
