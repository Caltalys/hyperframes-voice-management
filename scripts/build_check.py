"""Kiểm lệnh build + parser strict + Take.voice/engine_version. Offline (FakeTTS).

Nghiệm thu theo đặc tả v3:
- build hai lần liên tiếp: lần hai không sinh take mới;
- sửa một câu: chỉ fragment của câu đó sinh lại, chỉ line đó merge lại;
- take đã chọn tay (không stale) không bị ghi đè;
- đổi voice: mọi fragment sinh lại; đổi phiên bản engine: chỉ cảnh báo;
- một fragment lỗi không dừng build, line đó không lọt vào audio_meta;
- parser strict báo đúng dòng cho trường lạ / lời giảng thụt sai / nội dung trước
  Line đầu / Pause after sai; parser lenient giữ hành vi cũ;
- cue: loại khỏi text/TTS, phân giải ở mức line (kể cả cue ở biên hai fragment), hash
  không tính cue (dời cue không sinh lại audio), export_script chèn lại cue, lỗi
  strict (trùng id, cue cuối line, id sai dạng, cú pháp {{...}} sai);
- build --dry-run chỉ liệt kê, không ghi file;
- project.json cũ (thiếu matched/voice/engine_version/pause_after_s/cues) vẫn đọc được.

Chạy: python scripts/build_check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import build, pipeline, script_io, store
from app.engine.align import FakeAligner
from app.engine.tts import FakeTTS
from app.script_io import ScriptError

_P = 0


def check(cond: bool, label: str) -> None:
    global _P
    if not cond:
        print("  FAIL:", label)
        sys.exit(1)
    _P += 1
    print("  ok:", label)


SCRIPT = """# SCRIPT - Hóa 11, Chương 1, Bài 1

**Voice direction:** Chậm rãi, rõ ràng.

---

## Line 1 - Mở đầu

**Time:** 0.0 - 6.0s
**Delivery:** Chậm rãi.
**Pause after:** 0.8s

    Hai bình khí có cùng một màu. Khi làm nóng, màu sẽ thay đổi.

## Line 2 - Quan sát

**Delivery:** Dứt khoát.

    Khi làm lạnh bình thì màu nhạt đi. Phản ứng chuyển dịch theo chiều thuận.
"""

CFG = {"voice": "Minh Đức", "default_gap_s": 0.4}


class FailingTTS(FakeTTS):
    """Fake TTS lỗi khi gặp từ khóa BOOM — để thử build không dừng khi có lỗi."""

    def generate(self, tts_text, voice, gap_s, out_wav, tmp_dir):
        if "BOOM" in tts_text:
            raise RuntimeError("tts hỏng giả lập")
        return super().generate(tts_text, voice, gap_s, out_wav, tmp_dir)


def run(ep: Path, cfg=CFG, tts=None):
    logs: list[str] = []
    r = build.build(ep, cfg, tts or FakeTTS(), FakeAligner(), log=logs.append)
    return r, logs


def meta(ep: Path) -> dict:
    return json.loads((ep / "audio_meta.json").read_text(encoding="utf-8"))


def write_script(ep: Path, text: str) -> None:
    (ep / "SCRIPT.md").write_text(text, encoding="utf-8")


def test_build_flow(root: Path) -> None:
    print("\n[build] chạy lần đầu / lặp lại / sửa một câu")
    ep = root / "bai"
    ep.mkdir()
    write_script(ep, SCRIPT)

    r, _ = run(ep)
    project = store.load(ep)
    n_frag = sum(len(l.fragments) for l in project.lines)
    check(r.created and len(r.generated) == n_frag and n_frag == 4,
          f"build lần đầu sinh đủ {n_frag} fragment")
    check(r.merged == [1, 2] and r.ok, "merge cả 2 line, build ok")
    m = meta(ep)
    check([v["frame"] for v in m["voices"]] == [1, 2], "audio_meta có 2 voices")
    check(all("matched" in w for v in m["voices"] for w in v["words"]),
          "mọi từ có matched trong audio_meta")
    check(m["voices"][0].get("pause_after_s") == 0.8, "pause_after_s=0.8 xuất ra voices[0]")
    check("pause_after_s" not in m["voices"][1], "line không khai báo pause thì không có key")
    t = project.lines[0].fragments[0].selected_take()
    check(t.voice == "Minh Đức" and t.engine_version == "fake", "take ghi voice + engine_version")

    before = {f.id: f.selected_take_id for l in project.lines for f in l.fragments}
    r2, _ = run(ep)
    check(r2.generated == [] and r2.merged == [] and not r2.created,
          "build lần 2 không sinh take, không merge lại")
    after = {f.id: f.selected_take_id
             for l in store.load(ep).lines for f in l.fragments}
    check(before == after, "take đã chọn không đổi sau build lần 2")

    # sửa đúng một câu của line 2 (câu thứ hai)
    write_script(ep, SCRIPT.replace("theo chiều thuận", "theo chiều nghịch"))
    r3, _ = run(ep)
    check(r3.generated == ["f-2-2"] or len(r3.generated) == 1,
          f"sửa một câu chỉ sinh lại 1 fragment (được {r3.generated})")
    check(r3.merged == [2], f"chỉ line 2 merge lại (được {r3.merged})")
    p3 = store.load(ep)
    old_ids = {fid: tid for fid, tid in before.items() if fid != r3.generated[0]}
    same = all(p3.fragment(fid).selected_take_id == tid for fid, tid in old_ids.items())
    check(same, "các fragment khác giữ nguyên take")
    check(any("chiều nghịch" in f.text for l in p3.lines for f in l.active_fragments()),
          "text mới đã vào project")
    check(any(f.orphan for f in p3.line(2).fragments), "câu cũ thành orphan (khôi phục được)")


def test_selection_preserved(root: Path) -> None:
    print("\n[build] giữ take người nghe đã chọn")
    ep = root / "chon"
    ep.mkdir()
    write_script(ep, SCRIPT)
    run(ep)
    project = store.load(ep)
    frag = project.lines[0].active_fragments()[0]
    first_take = frag.selected_take_id
    pipeline.generate_take(project, ep, frag, FakeTTS(), FakeAligner(), CFG)  # take #2, tự chọn
    frag.selected_take_id = first_take  # người nghe quay lại chọn take đầu
    store.save(ep, project)
    r, _ = run(ep)
    check(r.generated == [], "build không sinh lại khi take đã chọn không stale")
    check(store.load(ep).fragment(frag.id).selected_take_id == first_take,
          "take chọn tay vẫn được giữ")


def test_voice_and_version(root: Path) -> None:
    print("\n[build] đổi voice / đổi phiên bản engine")
    ep = root / "voice"
    ep.mkdir()
    write_script(ep, SCRIPT)
    run(ep)
    r, _ = run(ep, cfg={**CFG, "voice": "Giọng khác"})
    check(len(r.generated) == 4, f"đổi voice -> sinh lại cả 4 fragment (được {len(r.generated)})")
    p = store.load(ep)
    check(all(f.selected_take().voice == "Giọng khác"
              for l in p.lines for f in l.active_fragments()), "take mới ghi voice mới")

    # giả lập take sinh bằng phiên bản vieneu cũ
    for l in p.lines:
        for f in l.active_fragments():
            f.selected_take().engine_version = "3.0.12"
    store.save(ep, p)
    r2, logs = run(ep, cfg={**CFG, "voice": "Giọng khác"})
    check(r2.generated == [], "khác phiên bản engine: không sinh lại")
    check(len(r2.version_mismatch) == 4 and any("CẢNH BÁO" in x for x in logs),
          "khác phiên bản engine: có cảnh báo")


def test_failure_isolated(root: Path) -> None:
    print("\n[build] một fragment lỗi không dừng build")
    ep = root / "loi"
    ep.mkdir()
    write_script(ep, SCRIPT)
    run(ep)
    write_script(ep, SCRIPT.replace("Khi làm lạnh bình thì màu nhạt đi.", "BOOM nhạt đi.")
                 .replace("Hai bình khí", "Hai bình khí mới"))
    r, _ = run(ep, tts=FailingTTS())
    check(len(r.failed) == 1 and "BOOM" in store.load(ep).fragment(r.failed[0][0]).text,
          "ghi nhận đúng fragment lỗi")
    check(len(r.generated) == 1, "fragment khác (line 1) vẫn được sinh")
    check(r.unmerged == [2] and not r.ok, "line 2 không merge được, build báo không ok")
    frames = [v["frame"] for v in meta(ep)["voices"]]
    check(frames == [1], f"line lỗi không nằm trong audio_meta (được {frames})")
    r2, _ = run(ep)  # TTS ổn lại: fragment lỗi được sinh ở lần build sau
    check(r2.failed == [] and r2.ok and r2.merged == [2], "build sau đó (TTS ổn) hoàn tất, merge line 2")


def test_removed_line(root: Path) -> None:
    print("\n[build] line bị bỏ khỏi script")
    ep = root / "bo"
    ep.mkdir()
    write_script(ep, SCRIPT)
    run(ep)
    only1 = SCRIPT.split("## Line 2")[0]
    write_script(ep, only1)
    r, _ = run(ep)
    check(r.removed == [2] and r.ok, "line 2 báo đã bỏ, build ok")
    check([v["frame"] for v in meta(ep)["voices"]] == [1], "audio_meta chỉ còn line 1")


def test_strict_parser(root: Path) -> None:
    print("\n[parser] strict báo đúng dòng, lenient giữ hành vi cũ")
    ep = root / "parse"
    ep.mkdir()

    def issues(text: str) -> list[str]:
        write_script(ep, text)
        try:
            script_io.import_script(ep, strict=True)
        except ScriptError as exc:
            return exc.issues
        return []

    check(issues(SCRIPT) == [], "kịch bản mẫu hợp lệ")

    bad = SCRIPT.replace("**Delivery:** Chậm rãi.", "**Cue:** lanh-mau-nhat")
    got = issues(bad)
    check(len(got) == 1 and "dòng 10" in got[0] and "**Cue:**" in got[0],
          f"trường lạ -> báo dòng 10 ({got})")

    bad = SCRIPT.replace("    Hai bình khí", "  Hai bình khí")
    got = issues(bad)
    check(any("dòng 13" in g and "4 khoảng trắng" in g for g in got),
          f"thụt sai -> báo dòng 13 ({got})")

    bad = SCRIPT.replace("    Khi làm lạnh", "Khi làm lạnh")
    check(any("dòng 19" in g for g in issues(bad)), "lời giảng không thụt -> báo dòng 19")

    bad = SCRIPT.replace("    Hai bình khí", "\tHai bình khí")
    check(any("tab" in g for g in issues(bad)), "tab -> báo lỗi thụt")

    bad = "Ghi chú tạm\n\n" + SCRIPT
    got = issues(bad)
    check(len(got) == 1 and "dòng 1" in got[0] and "trước '## Line'" in got[0],
          f"nội dung trước Line đầu -> báo dòng 1 ({got})")

    bad = SCRIPT.replace("0.8s", "nhanh")
    check(any("Pause after" in g for g in issues(bad)), "Pause after sai giá trị -> báo lỗi")

    bad = SCRIPT.replace("## Line 2 - Quan sát", "## Line 1 - Trùng")
    check(any("trùng" in g for g in issues(bad)), "Line trùng số -> báo lỗi")

    bad = SCRIPT.replace("**Delivery:** Dứt khoát.\n\n    Khi làm lạnh bình thì màu nhạt đi. Phản ứng chuyển dịch theo chiều thuận.\n", "")
    check(any("không có lời giảng" in g for g in issues(bad)), "line trống -> báo lỗi")

    bad = SCRIPT.replace("**Delivery:** Dứt khoát.", "**Voice direction:** lạc chỗ")
    check(any("Voice direction" in g and "trước" in g for g in issues(bad)),
          "Voice direction trong line -> báo lỗi")

    write_script(ep, SCRIPT.replace("**Delivery:** Chậm rãi.", "**Cue:** x"))
    proj = script_io.import_script(ep)  # lenient mặc định
    check(len(proj.lines) == 2, "lenient vẫn bỏ qua trường lạ như trước")

    write_script(ep, SCRIPT)
    rebuilt = script_io.export_script(script_io.import_script(ep))
    check("**Pause after:** 0.8s" in rebuilt, "export_script giữ Pause after")
    (ep / "SCRIPT.md").write_text(rebuilt, encoding="utf-8")
    check(script_io.import_script(ep, strict=True).lines[0].pause_after_s == 0.8,
          "script export lại vẫn qua strict")


CUE_SCRIPT = """# SCRIPT - cue

---

## Line 1 - Cue

**Pause after:** 0.5s

    Đun nóng thuốc tím, ta thu được khí oxi. {{cue:phuong-trinh}} Trong điều kiện đó, các chất không kết hợp lại. Khi làm lạnh bình {{cue:lanh-nhat}} thì màu nhạt đi.

## Line 2 - Hai

    {{cue:dau-line}} Câu đầu của line hai.
"""


class NoBraceTTS(FakeTTS):
    """Fake TTS khẳng định cue không lọt vào văn bản đưa cho TTS."""

    def generate(self, tts_text, voice, gap_s, out_wav, tmp_dir):
        assert "{{" not in tts_text and "}}" not in tts_text, tts_text
        return super().generate(tts_text, voice, gap_s, out_wav, tmp_dir)


def test_cues(root: Path) -> None:
    print("\n[cue] loại khỏi text/TTS, phân giải ở mức line, hash không tính cue")
    ep = root / "cue"
    ep.mkdir()
    write_script(ep, CUE_SCRIPT)
    r, logs = run(ep, tts=NoBraceTTS())
    check(r.ok and r.cues_total == 3, f"3 cue qua build (được {r.cues_total})")
    p = store.load(ep)
    texts = [f.text for l in p.lines for f in l.fragments]
    check(not any("{{" in t for t in texts), "text fragment không còn cue")
    m = meta(ep)
    cues = {c["id"]: c for v in m["voices"] for c in v.get("cues", [])}
    words1 = m["voices"][0]["words"]
    check(words1[cues["phuong-trinh"]["word_index"]]["text"] == "Trong",
          "cue ở biên hai fragment neo vào từ 'Trong' (phân giải mức line)")
    check(words1[cues["lanh-nhat"]["word_index"]]["text"] == "thì", "cue giữa câu neo vào 'thì'")
    check(m["voices"][1]["words"][cues["dau-line"]["word_index"]]["text"] == "Câu",
          "cue đầu line neo vào từ đầu tiên")
    check(cues["phuong-trinh"]["time_s"] == words1[cues["phuong-trinh"]["word_index"]]["start"],
          "time_s = start của từ neo")
    check(any("CẢNH BÁO cue" in x for x in logs) and r.cue_warnings,
          "cue neo vào từ matched=false -> cảnh báo (aligner giả)")

    ids_before = {f.id: f.selected_take_id for l in p.lines for f in l.fragments}
    # sửa chữ TRƯỚC cue phuong-trinh: chỉ fragment đó sinh lại, cue vẫn neo vào 'Trong'
    write_script(ep, CUE_SCRIPT.replace("ta thu được khí oxi", "ta thu được một ít khí oxi"))
    r2, _ = run(ep, tts=NoBraceTTS())
    check(len(r2.generated) == 1, f"sửa chữ quanh cue chỉ sinh lại 1 fragment (được {r2.generated})")
    m2 = meta(ep)
    c2 = {c["id"]: c for v in m2["voices"] for c in v.get("cues", [])}
    w2 = m2["voices"][0]["words"]
    check(w2[c2["phuong-trinh"]["word_index"]]["text"] == "Trong"
          and c2["phuong-trinh"]["word_index"] == cues["phuong-trinh"]["word_index"] + 2,
          "thêm 2 từ trước cue: chỉ số dịch +2, vẫn neo vào 'Trong'")

    # chỉ dời cue (không đổi chữ): không sinh lại audio, nhưng vị trí cue cập nhật
    moved = CUE_SCRIPT.replace("ta thu được khí oxi", "ta thu được một ít khí oxi") \
        .replace("Khi làm lạnh bình {{cue:lanh-nhat}} thì", "Khi làm lạnh {{cue:lanh-nhat}} bình thì")
    write_script(ep, moved)
    r3, _ = run(ep, tts=NoBraceTTS())
    check(r3.generated == [] and r3.merged == [], "chỉ dời cue: không sinh lại, không merge lại")
    m3 = meta(ep)
    c3 = {c["id"]: c for v in m3["voices"] for c in v.get("cues", [])}
    check(c3["lanh-nhat"]["word_index"] == c2["lanh-nhat"]["word_index"] - 1,
          "cue dời 1 từ: word_index giảm 1 trong audio_meta")

    # đổi id cue: audio giữ nguyên, id mới xuất hiện
    write_script(ep, moved.replace("lanh-nhat", "lanh-mau-nhat"))
    r4, _ = run(ep, tts=NoBraceTTS())
    ids = {c["id"] for v in meta(ep)["voices"] for c in v.get("cues", [])}
    check(r4.generated == [] and "lanh-mau-nhat" in ids and "lanh-nhat" not in ids,
          "đổi id cue: không sinh lại, audio_meta có id mới")

    # export_script giữ cue
    back = script_io.export_script(store.load(ep))
    check("{{cue:phuong-trinh}} Trong" in back and "{{cue:dau-line}} Câu" in back,
          "export_script chèn lại cue đúng vị trí")

    print("[cue] lỗi parser strict")
    def issues(text: str) -> list[str]:
        write_script(ep, text)
        try:
            script_io.import_script(ep, strict=True)
        except ScriptError as exc:
            return exc.issues
        return []
    check(any("trùng" in g and "phuong-trinh" in g
              for g in issues(CUE_SCRIPT.replace("dau-line", "phuong-trinh"))), "cue trùng id -> lỗi")
    check(any("không có từ đi kèm" in g
              for g in issues(CUE_SCRIPT.replace("màu nhạt đi.", "màu nhạt đi. {{cue:cuoi}}"))),
          "cue cuối line -> lỗi")
    check(any("không hợp lệ" in g and "Viet_Hoa" in g
              for g in issues(CUE_SCRIPT.replace("dau-line", "Viet_Hoa"))), "id sai dạng -> lỗi")
    got = issues(CUE_SCRIPT.replace("{{cue:dau-line}}", "{{cuu:x}}"))
    check(any("{{" in g for g in got), f"cú pháp {{{{...}}}} sai -> lỗi ({got})")


def test_dry_run(root: Path) -> None:
    print("\n[dry-run] chỉ liệt kê, không ghi gì")
    ep = root / "dry"
    ep.mkdir()
    write_script(ep, SCRIPT)
    r, _ = run_dry(ep)
    check(len(r.planned) == 4 and r.dry_run, f"dry-run bài mới liệt kê 4 fragment (được {len(r.planned)})")
    check(not (ep / "assets").exists() and not (ep / "audio_meta.json").exists(),
          "dry-run không tạo file nào")
    run(ep)
    snap = store.project_path(ep).read_text(encoding="utf-8")
    r2, _ = run_dry(ep)
    check(r2.planned == [], "build xong rồi: dry-run không còn gì để sinh")
    r3, _ = run_dry(ep, cfg={**CFG, "voice": "Giọng khác"})
    check(len(r3.planned) == 4, "đổi voice: dry-run liệt kê đúng 4 fragment dùng giọng cũ")
    write_script(ep, SCRIPT.replace("theo chiều thuận", "theo chiều nghịch"))
    r4, _ = run_dry(ep)
    check(len(r4.planned) == 1, "sửa một câu: dry-run liệt kê đúng 1 fragment")
    check(store.project_path(ep).read_text(encoding="utf-8") == snap,
          "dry-run không đổi project.json (kể cả khi script đã sửa)")


def run_dry(ep: Path, cfg=CFG):
    logs: list[str] = []
    r = build.build(ep, cfg, FakeTTS(), FakeAligner(), log=logs.append, dry_run=True)
    return r, logs


def test_legacy_project(root: Path) -> None:
    print("\n[tương thích] project.json cũ")
    ep = root / "cu"
    ep.mkdir()
    write_script(ep, SCRIPT)
    run(ep)
    path = store.project_path(ep)
    data = json.loads(path.read_text(encoding="utf-8"))

    def strip(node):
        if isinstance(node, dict):
            for k in ("matched", "voice", "engine_version", "pause_after_s"):
                node.pop(k, None)
            for v in node.values():
                strip(v)
        elif isinstance(node, list):
            for v in node:
                strip(v)
    # cấu hình voice nằm trong cfg, không phải project: chỉ gỡ các key mới của take/word/line
    strip(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p = store.load(ep)
    w = p.lines[0].merged.words[0]
    t = p.lines[0].fragments[0].selected_take()
    check(w.matched is True and t.voice is None and t.engine_version is None,
          "thiếu matched/voice/engine_version -> mặc định")
    check(not p.lines[0].fragments[0].is_stale(0.4, "Giọng bất kỳ"),
          "take cũ không ghi voice thì không bị coi là stale vì voice")
    r, _ = run(ep)
    check(r.generated == [], "build trên project cũ không sinh lại")


def test_cli(root: Path) -> None:
    print("\n[cli] vo-studio build")
    ep = root / "cli"
    ep.mkdir()
    write_script(ep, SCRIPT)
    home = root / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "VO_STUDIO_ENGINE": "fake", "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, "-m", "app.cli", "build", str(ep)]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    check(r.returncode == 0 and "sinh 4 fragment" in r.stdout, f"build exit 0 ({r.returncode})")
    check((ep / "audio_meta.json").exists(), "CLI ghi audio_meta.json")
    write_script(ep, SCRIPT.replace("**Delivery:** Dứt khoát.", "**Cue:** x"))
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    check(r.returncode == 2 and "dòng" in r.stderr, f"script lỗi -> exit 2 + liệt kê dòng ({r.returncode})")


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        test_build_flow(root)
        test_selection_preserved(root)
        test_voice_and_version(root)
        test_failure_isolated(root)
        test_removed_line(root)
        test_strict_parser(root)
        test_cues(root)
        test_dry_run(root)
        test_legacy_project(root)
        test_cli(root)
    print(f"\n[build_check] PASS — {_P} kiểm tra")


if __name__ == "__main__":
    main()
