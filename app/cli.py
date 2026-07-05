"""CLI M0 — xương sống engine. Web UI đến ở M3+.

  import <ep>            SCRIPT.md -> project.json
  gen    <ep> --frame N  sinh take cho fragment của line N (TTS thật, cần .[engine])
  merge  <ep> --frame N  ghép take đã chọn -> line wav + words
  export <ep>            voices[] -> audio_meta.json
  script <ep>            export lại SCRIPT.md từ project.json
  smoke  [--full]        tự kiểm chứng end-to-end (mặc định offline: Fake TTS/align)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import config, pipeline, script_io, store


def _resolve_engines(full: bool):
    """(tts, aligner) — Fake cho offline, Real (vieneu/whisper) cho --full/gen."""
    if full:
        from .engine.tts import RealTTS
        from .engine.align import RealAligner
        cfg = config.load_config()
        return RealTTS(), RealAligner(cfg["whisper_model"])
    from .engine.tts import FakeTTS
    from .engine.align import FakeAligner
    return FakeTTS(), FakeAligner()


# ---------- commands ----------

def cmd_import(args) -> None:
    ep = Path(args.ep).resolve()
    if store.exists(ep) and not args.force:
        sys.exit(f"project.json đã tồn tại ở {ep} — dùng --force để ghi đè (re-import M5)")
    project = script_io.import_script(ep)
    store.save(ep, project)
    config.remember_project(str(ep))
    n_frag = sum(len(l.fragments) for l in project.lines)
    print(f"import: {store.project_path(ep)}")
    print(f"  {len(project.lines)} line, {n_frag} fragment")


def cmd_gen(args) -> None:
    ep = Path(args.ep).resolve()
    project = store.load(ep)
    cfg = config.load_config()
    line = project.line(args.frame)
    if not line:
        sys.exit(f"không có line frame {args.frame}")
    tts, aligner = _resolve_engines(full=True)
    for frag in line.active_fragments():
        take = pipeline.generate_take(project, ep, frag, tts, aligner, cfg)
        store.save(ep, project)  # lưu từng fragment: crash không mất tiến độ
        print(f"  {frag.id}: take {take.id} ({take.duration_s}s, {len(take.words)} words)")
    print(f"gen xong line {args.frame}. Tiếp: merge --frame {args.frame}")


def cmd_merge(args) -> None:
    ep = Path(args.ep).resolve()
    project = store.load(ep)
    cfg = config.load_config()
    line = project.line(args.frame)
    if not line:
        sys.exit(f"không có line frame {args.frame}")
    merged = pipeline.merge_line(project, ep, line, cfg)
    store.save(ep, project)
    print(f"merge line {args.frame} -> {merged.wav} "
          f"({merged.duration_s}s, {len(merged.words)} words)")


def cmd_export(args) -> None:
    ep = Path(args.ep).resolve()
    project = store.load(ep)
    meta_path, skipped = pipeline.export_audio_meta(project, ep)
    print(f"export: {meta_path}")
    if skipped:
        print(f"  bỏ qua (chưa merge): frame {skipped}")


def cmd_script(args) -> None:
    ep = Path(args.ep).resolve()
    project = store.load(ep)
    text = script_io.export_script(project)
    (ep / "SCRIPT.md").write_text(text, encoding="utf-8")
    print(f"export SCRIPT.md: {ep / 'SCRIPT.md'}")


_SMOKE_SCRIPT = """# SCRIPT — smoke

**Voice direction:** Chuyên nghiệp, rõ ràng.

---

## Line 1 — Hook (Frame 1)

**Time:** 0.0 – 6.0s
**Delivery:** Chậm rãi.

    Ba đến bốn tháng. Đó là thời gian đội phát triển bỏ ra cho mỗi dự án mới.

## Line 2 — Chốt (Frame 2)

**Time:** 6.0 – 10.0s
**Delivery:** Dứt khoát.

    Vấn đề có tên: dùng chung ứng dụng.
"""


def cmd_smoke(args) -> None:
    root = Path(__file__).resolve().parent.parent
    ep = root / ".smoke"
    if ep.exists():
        shutil.rmtree(ep)
    ep.mkdir(parents=True)
    (ep / "SCRIPT.md").write_text(_SMOKE_SCRIPT, encoding="utf-8")

    cfg = config.load_config()
    tts, aligner = _resolve_engines(full=args.full)
    mode = "FULL (vieneu + whisper)" if args.full else "OFFLINE (fake TTS/align)"
    print(f"[smoke] {mode}  dir={ep}")

    # 1. import
    project = script_io.import_script(ep)
    store.save(ep, project)
    n_frag = sum(len(l.fragments) for l in project.lines)
    _check(len(project.lines) == 2, f"2 line (được {len(project.lines)})")
    # line1: 2 câu; line2: tách ở dấu ':' -> 2 => tổng 4 (auto-split baseline)
    _check(n_frag == 4, f"4 fragment tổng (được {n_frag})")

    # 2. export SCRIPT.md round-trip (nội dung line phải giữ nguyên)
    rebuilt = script_io.export_script(project)
    _check("dùng chung ứng dụng" in rebuilt, "export SCRIPT.md giữ nội dung")

    # 3. gen + align từng fragment, 4. merge từng line
    for line in project.lines:
        for frag in line.active_fragments():
            take = pipeline.generate_take(project, ep, frag, tts, aligner, cfg)
            _check((ep / take.wav).exists(), f"{frag.id} có wav")
            _check(len(take.words) == len(frag.text.replace('—', ' ').split())
                   or len(take.words) > 0, f"{frag.id} có words")
        merged = pipeline.merge_line(project, ep, line, cfg)
        _check((ep / merged.wav).exists(), f"line {line.frame} có wav ghép")
        _check(len(merged.words) > 0, f"line {line.frame} có words offset")
        # offset phải tăng dần và không âm
        starts = [w.start for w in merged.words]
        _check(starts == sorted(starts) and starts[0] >= 0,
               f"line {line.frame} word start tăng dần")
    store.save(ep, project)

    # 5. take history: gen lần 2, lần 3 cho 1 fragment -> tối đa 2 take
    frag = project.lines[0].active_fragments()[0]
    pipeline.generate_take(project, ep, frag, tts, aligner, cfg)
    pipeline.generate_take(project, ep, frag, tts, aligner, cfg)
    _check(len(frag.takes) == 2, f"giữ tối đa 2 take (được {len(frag.takes)})")
    _check(frag.selected_take_id == frag.takes[-1].id, "auto-select bản mới nhất")

    # 6. export audio_meta.json — hợp đồng đầu ra
    meta_path, skipped = pipeline.export_audio_meta(project, ep)
    import json
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    _check(skipped == [], "mọi line đã merge")
    _check(len(meta["voices"]) == 2, "2 voices trong audio_meta")
    v = meta["voices"][0]
    _check(set(v) >= {"frame", "path", "duration_s", "words"}, "voices đúng schema")
    _check(set(v["words"][0]) == {"id", "text", "start", "end"}, "words đúng schema")
    _check("bgm" in meta and "sfx" in meta, "giữ bgm/sfx trong audio_meta")

    print(f"\n[smoke] PASS — {_PASS} kiểm tra. Xem output ở {ep}")


_PASS = 0


def _check(cond: bool, label: str) -> None:
    global _PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    _PASS += 1
    print(f"  ok: {label}")


def main() -> None:
    # Console Windows mặc định cp1252 -> ép UTF-8 để in tiếng Việt/emoji.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="vo-studio", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import"); p.add_argument("ep")
    p.add_argument("--force", action="store_true")
    for name in ("gen", "merge"):
        p = sub.add_parser(name); p.add_argument("ep")
        p.add_argument("--frame", type=int, required=True)
    for name in ("export", "script"):
        sub.add_parser(name).add_argument("ep")
    p = sub.add_parser("smoke"); p.add_argument("--full", action="store_true")

    args = ap.parse_args()
    {"import": cmd_import, "gen": cmd_gen, "merge": cmd_merge,
     "export": cmd_export, "script": cmd_script, "smoke": cmd_smoke}[args.cmd](args)


if __name__ == "__main__":
    main()
