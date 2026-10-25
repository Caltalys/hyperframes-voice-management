"""Kiểm trường Word.matched, không cần tải model.

RealAligner được dựng với model whisper giả trả về kết quả nhận dạng thiếu một
từ: từ đó phải được nội suy (matched=False), các từ còn lại matched=True.
FakeAligner phải đánh dấu mọi từ matched=False. File cũ thiếu trường -> True.

Chạy: python scripts/matched_check.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import audio
from app.engine.align import FakeAligner, RealAligner
from app.models import Word

_P = 0


def check(cond: bool, label: str) -> None:
    global _P
    if not cond:
        print("  FAIL:", label)
        sys.exit(1)
    _P += 1
    print("  ok:", label)


class _StubModel:
    """Nhận dạng được 'Ba', 'bốn', 'tháng' nhưng bỏ sót 'đến'."""

    def transcribe(self, path, language, word_timestamps):
        words = [SimpleNamespace(word="Ba", start=0.0, end=0.3),
                 SimpleNamespace(word="bốn", start=0.8, end=1.1),
                 SimpleNamespace(word="tháng", start=1.1, end=1.6)]
        return [SimpleNamespace(words=words)], None


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        audio.write_sine(wav, 2.0)
        text = "Ba đến bốn tháng"

        real = RealAligner()
        real._model = _StubModel()
        words = real.align(text, wav)
        flags = [w.matched for w in words]
        check([w.text for w in words] == ["Ba", "đến", "bốn", "tháng"], "đủ 4 từ theo text")
        check(flags == [True, False, True, True], f"chỉ từ 'đến' nội suy (được {flags})")
        gap = words[1]
        check(words[0].end <= gap.start <= gap.end <= words[2].start,
              "từ nội suy nằm giữa hai từ khớp")

        fake = FakeAligner().align(text, wav)
        check(len(fake) == 4 and not any(w.matched for w in fake), "FakeAligner: mọi từ matched=False")

    old = Word.model_validate({"id": "w0", "text": "Ba", "start": 0.0, "end": 0.3})
    check(old.matched is True, "file cũ thiếu matched -> True")
    check("matched" in old.model_dump(), "model_dump có matched")
    print(f"\n[matched_check] PASS — {_P} kiểm tra")


if __name__ == "__main__":
    main()
