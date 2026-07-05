"""Lõi nghiệp vụ — CLI (M0) và web API (M2+) đều gọi thẳng các hàm ở đây.

  generate_take   : sinh 1 take cho fragment (TTS -> align), append + prune 2 bản,
                    auto-select bản mới nhất.
  merge_line      : ghép take đã chọn của mọi fragment -> line wav, cộng dồn offset
                    để có words[] cấp line (chính xác vì ta tự ghép).
  export_audio_meta: ghi voices[] vào audio_meta.json (GIỮ bgm/sfx).

Không phụ thuộc engine cụ thể — nhận TTSEngine/Aligner qua tham số nên smoke
truyền Fake*, còn CLI thật truyền Real*.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import MAX_TAKES, Line, Merged, Project, Take, Word


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_take_id(fragment) -> str:
    """t{k} tăng đơn điệu theo take hiện có (không đụng lại id đã prune)."""
    nums = []
    for t in fragment.takes:
        m = t.id.rsplit("t", 1)
        if len(m) == 2 and m[1].isdigit():
            nums.append(int(m[1]))
    return f"t{(max(nums) + 1) if nums else 1}"


def generate_take(project: Project, ep: Path, fragment, tts, aligner,
                  cfg: dict) -> Take:
    """Sinh take cho fragment, align, prune còn MAX_TAKES, auto-select."""
    default_gap = cfg["default_gap_s"]
    gap = fragment.effective_gap(default_gap)
    tid = _next_take_id(fragment)
    wav_rel = f"assets/vo/.takes/{fragment.id}/{tid}.wav"
    wav_abs = ep / wav_rel
    tmp = ep / "assets" / "vo" / ".tmp" / fragment.id

    dur = tts.generate(fragment.effective_tts(), cfg["voice"], gap, wav_abs, tmp)
    words = aligner.align(fragment.text, wav_abs)

    take = Take(
        id=tid, wav=wav_rel, duration_s=dur, words=words,
        content_hash=fragment.current_hash(default_gap), created_at=_now(),
    )
    fragment.takes.append(take)
    _prune_takes(ep, fragment)
    fragment.selected_take_id = take.id
    return take


def _prune_takes(ep: Path, fragment) -> None:
    """Giữ MAX_TAKES bản mới nhất; xóa file wav của bản bị loại."""
    while len(fragment.takes) > MAX_TAKES:
        dropped = fragment.takes.pop(0)
        (ep / dropped.wav).unlink(missing_ok=True)
        if fragment.selected_take_id == dropped.id:
            fragment.selected_take_id = (
                fragment.takes[-1].id if fragment.takes else None
            )


def merge_line(project: Project, ep: Path, line: Line, cfg: dict) -> Merged:
    """Ghép take đã chọn -> line wav, words[] cộng offset. Yêu cầu mọi fragment
    active đã có take chọn."""
    from .engine import audio

    frags = line.active_fragments()
    if not line.ready_to_merge():
        missing = [f.id for f in frags if not f.selected_take()]
        raise ValueError(f"Line {line.frame} chưa đủ take để merge: {missing}")

    default_gap = cfg["default_gap_s"]
    takes = [f.selected_take() for f in frags]
    paths = [ep / t.wav for t in takes]
    gaps_between = [f.effective_gap(default_gap) for f in frags[:-1]]

    merged_rel = f"assets/vo/{line.frame:02d}.wav"
    dur = audio.concat_segments(paths, gaps_between, ep / merged_rel, trim=False)

    words: list[Word] = []
    offset = 0.0
    n = len(frags)
    for idx, (frag, take) in enumerate(zip(frags, takes)):
        for w in take.words:
            words.append(Word(id=f"w{len(words)}", text=w.text,
                              start=round(w.start + offset, 2),
                              end=round(w.end + offset, 2)))
        offset += take.duration_s
        if idx < n - 1:
            offset += frag.effective_gap(default_gap)

    line.merged = Merged(wav=merged_rel, duration_s=dur, words=words,
                         merged_at=_now())
    return line.merged


def export_audio_meta(project: Project, ep: Path) -> tuple[Path, list[int]]:
    """Ghi voices[] vào <ep>/audio_meta.json, GIỮ nguyên bgm/sfx.
    Trả (đường dẫn, danh sách frame CHƯA merge bị bỏ qua)."""
    meta_path = ep / "audio_meta.json"
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists() else {"bgm": None, "voices": [], "sfx": []})

    voices, skipped = [], []
    for line in project.lines:
        if not line.merged:
            skipped.append(line.frame)
            continue
        voices.append({
            "frame": line.frame,
            "path": line.merged.wav,
            "duration_s": line.merged.duration_s,
            "words": [w.model_dump() for w in line.merged.words],
        })
    meta["voices"] = voices
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta_path, skipped
