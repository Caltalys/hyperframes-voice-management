"""Import (bootstrap), re-import và export SCRIPT.md.

Nguồn sự thật là project.json — SCRIPT.md import để khởi tạo, re-import khi sửa
script bên ngoài, và là artifact EXPORT. Parser đọc đủ metadata (title/Time/
Delivery/Pause after/Voice direction) để export dựng lại đúng định dạng.

Định dạng (mọi quy tắc dưới đây được parse_script kiểm tra):
- Trước '## Line' đầu tiên chỉ có: dòng trống, '# tiêu đề', '---',
  '**Voice direction:**'.
- Mỗi line bắt đầu bằng '## Line N' (phần sau N là tiêu đề, '(Frame M)' tùy chọn).
- Trong line: '**Time:**', '**Delivery:**', '**Pause after:** <số>s', '---', dòng
  trống, và lời giảng thụt ĐÚNG 4 khoảng trắng.
- Lời giảng có thể chứa cue '{{cue:id}}' (id dạng [a-z0-9-]+, duy nhất trong bài, phải
  có từ ngay sau). Cue bị bỏ khỏi text/tts_text và lưu ở Line.cues (chỉ số token).
import_script mặc định bỏ qua lặng lẽ dòng không nhận diện (tương thích kịch bản
hyperframes cũ); strict=True báo lỗi kèm số dòng — lệnh build dùng chế độ này.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import (CUE_ID_RE, Cue, Fragment, Line, Project, display_tokens,
                     insert_cues, split_sentences, strip_cues)

_LINE_RE = re.compile(r"^##\s*Line\s+(\d+)\s*(.*)$")
_FRAME_TAIL_RE = re.compile(r"\s*\(Frame\s+\d+\)\s*$")
_TIME_RE = re.compile(r"^\*\*Time:\*\*\s*(.*)$")
_DELIVERY_RE = re.compile(r"^\*\*Delivery:\*\*\s*(.*)$")
_VOICE_DIR_RE = re.compile(r"^\*\*Voice direction:\*\*\s*(.*)$")
_PAUSE_RE = re.compile(r"^\*\*Pause after:\*\*\s*(.*)$")
_PAUSE_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*s?$")
_KEY_RE = re.compile(r"^\*\*([^*:]+):\*\*")
_HR_RE = re.compile(r"^-{3,}\s*$")
_H1_RE = re.compile(r"^#\s+\S")
_BODY_RE = re.compile(r"^    \S")  # đoạn thoại thụt đúng 4 space

_LINE_KEYS = "Time, Delivery, Pause after"


class ScriptError(ValueError):
    """SCRIPT.md không hợp lệ (strict). issues = danh sách lỗi kèm số dòng."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("SCRIPT.md không hợp lệ:\n"
                         + "\n".join(f"  - {i}" for i in issues))


def _title_from_header(tail: str) -> str | None:
    """'— Hook: 3-4 tháng (Frame 1)' -> 'Hook: 3-4 tháng'."""
    tail = _FRAME_TAIL_RE.sub("", tail).strip()
    tail = re.sub(r"^[—–-]\s*", "", tail).strip()
    return tail or None


def parse_script(ep: Path) -> tuple[Project, list[str]]:
    """Parse SCRIPT.md -> (Project, issues). Mỗi line auto-split thành fragment theo
    câu. issues = lỗi kèm số dòng (dòng không nhận diện, trường lạ, lời giảng
    thụt sai, Line trùng, Pause after sai giá trị, line không có lời giảng)."""
    src = (ep / "SCRIPT.md").read_text(encoding="utf-8")
    project = Project(ep_dir=ep.name, title=ep.name)
    issues: list[str] = []

    cur: Line | None = None
    cur_at = 0                       # số dòng của '## Line' hiện tại
    cur_mark = 0                     # len(issues) lúc bắt đầu line hiện tại
    text_buf: list[str] = []
    buf_at: list[int] = []           # số dòng tương ứng từng phần tử text_buf
    seen: dict[int, int] = {}        # frame -> số dòng khai báo
    cue_seen: dict[str, int] = {}    # cue id -> số dòng khai báo (duy nhất trong bài)

    def cue_line(cue_id: str) -> int:
        tag = "{{cue:%s}}" % cue_id
        return next((at for at, t in zip(buf_at, text_buf) if tag in t), cur_at)

    def flush() -> None:
        if cur is None:
            return
        paragraph = " ".join(text_buf).strip()
        clean, cues = strip_cues(paragraph)
        total = len(display_tokens(clean))
        for cid, idx in cues:
            at = cue_line(cid)
            if not CUE_ID_RE.match(cid):
                issues.append(f"dòng {at}: cue id {cid!r} không hợp lệ (chỉ a-z, 0-9, '-')")
            elif cid in cue_seen:
                issues.append(f"dòng {at}: cue {cid!r} trùng (đã khai báo ở dòng {cue_seen[cid]})")
            else:
                cue_seen[cid] = at
            if idx >= total:
                issues.append(f"dòng {at}: cue {cid!r} không có từ đi kèm (đứng cuối line)")
            cur.cues.append(Cue(id=cid, token_index=idx))
        if "{{" in clean or "}}" in clean:
            issues.append(f"dòng {buf_at[0] if buf_at else cur_at}: cú pháp '{{{{...}}}}' "
                          "không hợp lệ, chỉ hỗ trợ {{cue:id}}")
        if clean:
            for seq, sent in enumerate(split_sentences(clean)):
                cur.fragments.append(
                    Fragment(id=f"f-{cur.frame}-{seq}", text=sent)
                )
        elif len(issues) == cur_mark:  # đã có lỗi khác trong line thì khỏi báo thừa
            issues.append(f"dòng {cur_at}: Line {cur.frame} không có lời giảng "
                          "(cần đoạn thụt đúng 4 khoảng trắng)")
        project.lines.append(cur)

    for n, raw in enumerate(src.splitlines(), 1):
        m = _LINE_RE.match(raw)
        if m:
            flush()
            frame = int(m.group(1))
            if frame in seen:
                issues.append(f"dòng {n}: Line {frame} trùng (đã khai báo ở dòng {seen[frame]})")
            seen.setdefault(frame, n)
            cur = Line(frame=frame, title=_title_from_header(m.group(2)))
            cur_at = n
            cur_mark = len(issues)
            text_buf, buf_at = [], []
            continue

        blank = not raw.strip()
        if cur is None:
            mv = _VOICE_DIR_RE.match(raw)
            if mv:
                project.voice_direction = mv.group(1).strip()
            elif not (blank or _HR_RE.match(raw) or _H1_RE.match(raw)):
                issues.append(f"dòng {n}: nội dung không nhận diện trước '## Line' "
                              f"đầu tiên: {raw.strip()[:50]!r}")
            continue

        mt = _TIME_RE.match(raw)
        if mt:
            cur.time_range = mt.group(1).strip()
            continue
        md = _DELIVERY_RE.match(raw)
        if md:
            cur.delivery = md.group(1).strip()
            continue
        mp = _PAUSE_RE.match(raw)
        if mp:
            mv = _PAUSE_VALUE_RE.match(mp.group(1).strip())
            if mv:
                cur.pause_after_s = float(mv.group(1))
            else:
                issues.append(f"dòng {n}: **Pause after:** cần số giây, ví dụ "
                              f"'0.8s' (được {mp.group(1).strip()!r})")
            continue
        if _BODY_RE.match(raw):
            text_buf.append(raw.strip())
            buf_at.append(n)
            continue
        if blank or _HR_RE.match(raw):
            continue

        mk = _KEY_RE.match(raw)
        if mk and mk.group(1).strip() == "Voice direction":
            issues.append(f"dòng {n}: **Voice direction:** chỉ đặt được trước "
                          "'## Line' đầu tiên")
        elif mk:
            issues.append(f"dòng {n}: trường không nhận diện **{mk.group(1)}:** "
                          f"(trong line chỉ có: {_LINE_KEYS})")
        elif raw[0].isspace():
            issues.append(f"dòng {n}: lời giảng phải thụt đúng 4 khoảng trắng "
                          f"(không dùng tab hay thụt sâu hơn): {raw.strip()[:50]!r}")
        else:
            issues.append(f"dòng {n}: dòng không nhận diện, lời giảng phải thụt "
                          f"đúng 4 khoảng trắng: {raw.strip()[:50]!r}")

    flush()
    if not project.lines:
        raise ValueError(
            f"Không tìm thấy line nào trong {ep/'SCRIPT.md'} "
            "(cần '## Line N' + đoạn thụt 4 space)"
        )
    return project, issues


def import_script(ep: Path, strict: bool = False) -> Project:
    """Parse SCRIPT.md -> Project. strict=True: có lỗi cú pháp thì raise
    ScriptError (liệt kê mọi lỗi); mặc định bỏ qua lặng lẽ như trước."""
    project, issues = parse_script(ep)
    if strict and issues:
        raise ScriptError(issues)
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
        meta_changed = (old.title, old.time_range, old.delivery, old.pause_after_s,
                        old.cues) != (inc.title, inc.time_range, inc.delivery,
                                      inc.pause_after_s, inc.cues)
        old.title, old.time_range, old.delivery = inc.title, inc.time_range, inc.delivery
        old.pause_after_s = inc.pause_after_s
        old.cues = inc.cues  # chỉ ảnh hưởng export, không làm line wav cũ mất hiệu lực
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
        if line.pause_after_s is not None:
            out.append(f"**Pause after:** {line.pause_after_s:g}s")
        if line.time_range or line.delivery or line.pause_after_s is not None:
            out.append("")
        paragraph = " ".join(f.text for f in line.active_fragments()).strip()
        out.append(f"    {insert_cues(paragraph, line.cues)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
