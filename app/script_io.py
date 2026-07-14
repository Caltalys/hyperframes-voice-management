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


def _next_seq(line: Line) -> int:
    """Seq kế tiếp chưa dùng trong line (tính cả orphan — id không tái đánh số)."""
    maxn = -1
    for f in line.fragments:
        tail = f.id.rsplit("-", 1)[-1]
        if tail.isdigit():
            maxn = max(maxn, int(tail))
    return maxn + 1


def reimport_project(existing: Project, incoming: Project, apply: bool) -> dict:
    """So khớp incoming (parse mới từ SCRIPT.md) với existing, map theo frame.

    Trong line: fragment text khớp -> giữ nguyên (take còn liên kết); text mới ->
    fragment trống; fragment cũ không còn -> orphan (không xóa, khôi phục được).
    Line biến mất khỏi script -> mọi fragment thành orphan, line giữ lại.
    Trả diff (preview); apply=True mới sửa existing tại chỗ (caller lo save).
    """
    diff: dict = {"changed": False, "lines_added": [], "lines_removed": [],
                  "lines_changed": []}
    new_lines: list[Line] = []

    for inc in incoming.lines:
        old = existing.line(inc.frame)
        if old is None:
            diff["lines_added"].append(inc.frame)
            new_lines.append(inc)
            continue

        # khớp text từng fragment mới với fragment cũ chưa dùng (ưu tiên active,
        # orphan khớp lại được khôi phục — take cũ vẫn còn)
        pool = sorted(old.fragments, key=lambda f: f.orphan)
        was_orphan = {f.id: f.orphan for f in pool}
        used: set[str] = set()
        matched: list[Fragment] = []
        added: list[str] = []
        seq = _next_seq(old)
        for nf in inc.fragments:
            hit = next((f for f in pool
                        if f.id not in used and f.text == nf.text), None)
            if hit is not None:
                used.add(hit.id)
                hit.orphan = False
                matched.append(hit)
            else:
                matched.append(Fragment(id=f"f-{old.frame}-{seq}", text=nf.text))
                seq += 1
                added.append(nf.text)
        orphaned = [f for f in pool if f.id not in used and not was_orphan[f.id]]
        for f in orphaned:
            f.orphan = True
        old_orphans = [f for f in pool if f.id not in used and was_orphan[f.id]]

        restored = [f for f in matched if was_orphan.get(f.id)]
        meta_changed = (old.title, old.time_range, old.delivery) != (
            inc.title, inc.time_range, inc.delivery)
        old.title, old.time_range, old.delivery = inc.title, inc.time_range, inc.delivery
        old.fragments = matched + orphaned + old_orphans
        if added or orphaned or restored:
            old.merged = None  # tập fragment active đã đổi -> line wav cũ không còn hợp lệ
        if added or orphaned or restored or meta_changed:
            diff["lines_changed"].append({
                "frame": old.frame, "kept": len(used),
                "added": added, "orphaned": [f.text for f in orphaned],
                "restored": len(restored), "meta_changed": meta_changed,
            })
        new_lines.append(old)

    # line không còn trong script -> giữ lại nhưng orphan toàn bộ fragment
    inc_frames = {l.frame for l in incoming.lines}
    for old in existing.lines:
        if old.frame not in inc_frames:
            diff["lines_removed"].append(old.frame)
            for f in old.fragments:
                f.orphan = True
            old.merged = None
            new_lines.append(old)

    diff["changed"] = bool(diff["lines_added"] or diff["lines_removed"]
                           or diff["lines_changed"])
    if apply and diff["changed"]:
        existing.voice_direction = incoming.voice_direction
        existing.lines = new_lines
    return diff


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
