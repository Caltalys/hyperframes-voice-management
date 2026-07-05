"""Import (bootstrap) và export SCRIPT.md.

Nguồn sự thật là project.json — SCRIPT.md chỉ IMPORT 1 lần để khởi tạo, sau đó
là artifact EXPORT. Parser đọc đủ metadata (title/Time/Delivery/Voice direction)
để export dựng lại đúng định dạng.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Fragment, Line, Project, split_sentences

_LINE_RE = re.compile(r"^##\s*Line\s+(\d+)\s*(.*)$")
_FRAME_TAIL_RE = re.compile(r"\s*\(Frame\s+\d+\)\s*$")
_TIME_RE = re.compile(r"^\*\*Time:\*\*\s*(.*)$")
_DELIVERY_RE = re.compile(r"^\*\*Delivery:\*\*\s*(.*)$")
_VOICE_DIR_RE = re.compile(r"^\*\*Voice direction:\*\*\s*(.*)$")


def _title_from_header(tail: str) -> str | None:
    """'— Hook: 3-4 tháng (Frame 1)' -> 'Hook: 3-4 tháng'."""
    tail = _FRAME_TAIL_RE.sub("", tail).strip()
    tail = re.sub(r"^[—–-]\s*", "", tail).strip()
    return tail or None


def import_script(ep: Path) -> Project:
    """Parse SCRIPT.md -> Project, auto-split mỗi line thành fragment theo câu."""
    src = (ep / "SCRIPT.md").read_text(encoding="utf-8")
    project = Project(ep_dir=ep.name, title=ep.name)

    cur: Line | None = None
    text_buf: list[str] = []

    def flush() -> None:
        if cur is None:
            return
        paragraph = " ".join(text_buf).strip()
        if paragraph:
            for seq, sent in enumerate(split_sentences(paragraph)):
                cur.fragments.append(
                    Fragment(id=f"f-{cur.frame}-{seq}", text=sent)
                )
        project.lines.append(cur)

    for raw in src.splitlines():
        m = _LINE_RE.match(raw)
        if m:
            flush()
            cur = Line(frame=int(m.group(1)), title=_title_from_header(m.group(2)))
            text_buf = []
            continue
        if cur is None:
            mv = _VOICE_DIR_RE.match(raw)
            if mv:
                project.voice_direction = mv.group(1).strip()
            continue
        mt = _TIME_RE.match(raw)
        if mt:
            cur.time_range = mt.group(1).strip()
            continue
        md = _DELIVERY_RE.match(raw)
        if md:
            cur.delivery = md.group(1).strip()
            continue
        if re.match(r"^    \S", raw):  # đoạn thoại thụt 4 space
            text_buf.append(raw.strip())

    flush()
    if not project.lines:
        raise ValueError(
            f"Không tìm thấy line nào trong {ep/'SCRIPT.md'} "
            "(cần '## Line N' + đoạn thụt 4 space)"
        )
    return project


def export_script(project: Project) -> str:
    """Dựng lại SCRIPT.md từ project.json (nội dung khớp để git diff sạch)."""
    out: list[str] = [f"# SCRIPT — {project.title}", ""]
    if project.voice_direction:
        out += [f"**Voice direction:** {project.voice_direction}", ""]
    out += ["---", ""]
    for line in project.lines:
        header = f"## Line {line.frame}"
        if line.title:
            header += f" — {line.title}"
        header += f" (Frame {line.frame})"
        out.append(header)
        out.append("")
        if line.time_range:
            out.append(f"**Time:** {line.time_range}")
        if line.delivery:
            out.append(f"**Delivery:** {line.delivery}")
        if line.time_range or line.delivery:
            out.append("")
        paragraph = " ".join(f.text for f in line.active_fragments()).strip()
        out.append(f"    {paragraph}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
