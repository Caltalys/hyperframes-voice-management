"""Lệnh build — SCRIPT.md -> audio_meta.json trọn bài, không cần duyệt tay.

Mỗi lần chạy (idempotent):
  1. Parse SCRIPT.md ở chế độ strict (lỗi cú pháp -> ScriptError, chưa đụng gì).
  2. Có project.json thì reimport_project (áp sửa script, fragment không đổi giữ
     nguyên take); chưa có thì dùng project mới parse.
  3. Sinh take cho fragment active chưa có take được chọn hoặc take đã stale
     (text/tts/gap đổi, hoặc take sinh bằng voice khác). KHÔNG ghi đè take đã
     chọn mà không stale — kết quả người nghe duyệt được giữ.
  4. Merge lại line có fragment vừa sinh hoặc chưa có line wav.
  5. Export audio_meta.json.

Lỗi một fragment không dừng build: ghi nhận, chạy tiếp, báo cuối (exit != 0).
Phiên bản engine khác chỉ cảnh báo, không sinh lại.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import pipeline, script_io, store


@dataclass
class BuildReport:
    meta_path: Path | None = None
    created: bool = False                      # project.json mới tạo lần này
    diff: dict | None = None                   # kết quả reimport (nếu có)
    generated: list[str] = field(default_factory=list)       # fragment id
    failed: list[tuple[str, str]] = field(default_factory=list)  # (fragment id, lỗi)
    merged: list[int] = field(default_factory=list)          # frame vừa merge
    unmerged: list[int] = field(default_factory=list)        # có lời giảng nhưng chưa merge được
    removed: list[int] = field(default_factory=list)         # line đã bỏ khỏi script
    version_mismatch: list[str] = field(default_factory=list)  # fragment id
    engine_version: str | None = None
    words_total: int = 0
    words_unmatched: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed and not self.unmerged


def build(ep: Path, cfg: dict, tts, aligner,
          log: Callable[[str], None] = print) -> BuildReport:
    report = BuildReport(engine_version=tts.version())
    default_gap, voice = cfg["default_gap_s"], cfg["voice"]

    incoming = script_io.import_script(ep, strict=True)
    if store.exists(ep):
        project = store.load(ep)
        report.diff = script_io.reimport_project(project, incoming, apply=True)
        for ch in report.diff["lines_changed"]:
            log(f"  script: line {ch['frame']} đổi "
                f"(thêm {len(ch['added'])}, bỏ {len(ch['orphaned'])}, "
                f"khôi phục {ch['restored']})")
        for frame in report.diff["lines_added"]:
            log(f"  script: thêm line {frame}")
        for frame in report.diff["lines_removed"]:
            log(f"  script: line {frame} đã bỏ khỏi script")
    else:
        project = incoming
        report.created = True
    store.save(ep, project)

    # --- sinh take ---
    todo = [(line, frag) for line in project.lines
            for frag in line.active_fragments()
            if frag.needs_generation(default_gap, voice)]
    log(f"  sinh {len(todo)} fragment "
        f"(engine {report.engine_version or '?'}, voice {voice})")
    touched: set[int] = set()
    for line, frag in todo:
        touched.add(line.frame)
        try:
            take = pipeline.generate_take(project, ep, frag, tts, aligner, cfg)
        except Exception as exc:  # noqa: BLE001 — một fragment lỗi không dừng cả bài
            report.failed.append((frag.id, f"{type(exc).__name__}: {exc}"))
            log(f"  LỖI {frag.id}: {exc}")
            continue
        store.save(ep, project)  # lưu từng fragment: crash không mất tiến độ
        report.generated.append(frag.id)
        log(f"  {frag.id}: take {take.id} ({take.duration_s}s)")

    # --- phiên bản engine lệch: chỉ cảnh báo ---
    if report.engine_version:
        for line in project.lines:
            for frag in line.active_fragments():
                t = frag.selected_take()
                if t and t.engine_version and t.engine_version != report.engine_version:
                    report.version_mismatch.append(frag.id)
        if report.version_mismatch:
            log(f"  CẢNH BÁO: {len(report.version_mismatch)} fragment có take sinh bằng "
                f"phiên bản engine khác {report.engine_version} (không sinh lại)")

    # --- merge ---
    for line in project.lines:
        if not line.active_fragments():
            line.merged = None
            report.removed.append(line.frame)
            continue
        if line.frame in touched:
            line.merged = None  # take đổi (hoặc lỗi) -> line wav cũ không còn đúng
        if line.merged is not None:
            continue
        if line.ready_to_merge():
            pipeline.merge_line(project, ep, line, cfg)
            report.merged.append(line.frame)
        else:
            report.unmerged.append(line.frame)
    store.save(ep, project)

    # --- export ---
    report.meta_path, _skipped = pipeline.export_audio_meta(project, ep)
    for line in project.lines:
        if line.merged:
            report.words_total += len(line.merged.words)
            report.words_unmatched += sum(1 for w in line.merged.words if not w.matched)
    return report
