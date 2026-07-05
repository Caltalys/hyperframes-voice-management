"""Schema dữ liệu — nguồn sự thật là project.json trong <ep-dir>/assets/vo/.

Cây: Project -> Line (theo frame) -> Fragment -> Take. Fragment là entity hạng
nhất: có text/tts_text/gap riêng, review + regenerate độc lập, giữ tối đa
MAX_TAKES bản gần nhất, rồi merge (thủ công) thành line wav.

Voice KHÔNG nằm ở đây — là hằng số toàn cục (config), không tham gia hash.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional

from pydantic import BaseModel, Field

MAX_TAKES = 2  # giữ 2 take gần nhất mỗi fragment (quyết định thiết kế)
SCHEMA_VERSION = 1


# ---------- text utilities (port từ vo.py) ----------

def to_tts(text: str) -> str:
    """Text đưa vào TTS: gạch ngang câu -> dấu chấm để giọng nghỉ đúng chỗ."""
    return text.replace(" — ", ". ").replace("—", ",")


def tts_chunks(tts_text: str) -> list[str]:
    """Tách theo câu — mỗi chunk infer riêng rồi ghép với khoảng lặng cố định,
    để điểm ngắt luôn đúng và nhất quán."""
    parts = re.split(r"(?<=[.?!…;:])\s+", tts_text)
    return [p.strip() for p in parts if p.strip()]


def split_sentences(paragraph: str) -> list[str]:
    """Auto-split đoạn văn thành câu — dùng khi import để tạo fragment ban đầu."""
    return tts_chunks(paragraph)


def norm_token(tok: str) -> str:
    """Chuẩn hoá token để so khớp alignment (bỏ dấu câu, lowercase, NFC)."""
    t = unicodedata.normalize("NFC", tok.lower())
    return re.sub(r"[\W_]+", "", t, flags=re.UNICODE)


def content_hash(text: str, tts_text: Optional[str], gap_s: float) -> str:
    """Hash nội dung fragment (KHÔNG gồm voice). Dùng để phát hiện lệch giữa
    text hiện tại và take đã sinh — chỉ để badge cảnh báo, không auto-invalidate."""
    key = f"{text}|{tts_text or ''}|{gap_s:.3f}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


# ---------- models ----------

class Word(BaseModel):
    id: str
    text: str
    start: float
    end: float


class Take(BaseModel):
    id: str
    wav: str                       # đường dẫn tương đối tới <ep-dir>
    duration_s: float
    words: list[Word] = Field(default_factory=list)
    content_hash: str              # hash lúc sinh — so với fragment để biết lệch
    created_at: str


class Fragment(BaseModel):
    id: str                        # ổn định: f-{frame}-{seq}
    text: str
    tts_text: Optional[str] = None
    gap_s: Optional[float] = None  # None -> dùng config.default_gap_s
    selected_take_id: Optional[str] = None
    takes: list[Take] = Field(default_factory=list)
    orphan: bool = False           # từng có nhưng biến mất sau re-import

    # --- dẫn xuất ---
    def effective_tts(self) -> str:
        return self.tts_text or to_tts(self.text)

    def effective_gap(self, default_gap: float) -> float:
        return self.gap_s if self.gap_s is not None else default_gap

    def current_hash(self, default_gap: float) -> str:
        return content_hash(self.text, self.tts_text, self.effective_gap(default_gap))

    def selected_take(self) -> Optional[Take]:
        if not self.selected_take_id:
            return None
        return next((t for t in self.takes if t.id == self.selected_take_id), None)

    def is_stale(self, default_gap: float) -> bool:
        """True nếu take đang chọn được sinh từ text/tts/gap khác hiện tại."""
        t = self.selected_take()
        return bool(t and t.content_hash != self.current_hash(default_gap))


class Merged(BaseModel):
    wav: str
    duration_s: float
    words: list[Word] = Field(default_factory=list)
    merged_at: str


class Line(BaseModel):
    frame: int
    title: Optional[str] = None
    time_range: Optional[str] = None
    delivery: Optional[str] = None
    merged: Optional[Merged] = None
    fragments: list[Fragment] = Field(default_factory=list)

    def active_fragments(self) -> list[Fragment]:
        return [f for f in self.fragments if not f.orphan]

    def ready_to_merge(self) -> bool:
        frags = self.active_fragments()
        return bool(frags) and all(f.selected_take() for f in frags)


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    ep_dir: str = ""
    title: str = ""
    voice_direction: Optional[str] = None
    lines: list[Line] = Field(default_factory=list)

    def line(self, frame: int) -> Optional[Line]:
        return next((l for l in self.lines if l.frame == frame), None)

    def fragment(self, fragment_id: str) -> Optional[Fragment]:
        for l in self.lines:
            for f in l.fragments:
                if f.id == fragment_id:
                    return f
        return None
