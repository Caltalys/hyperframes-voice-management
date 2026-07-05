"""Kiểm M4: split/merge fragment. Server chạy VO_STUDIO_ENGINE=fake.
Xác minh: split tách text + VỨT take (xóa wav) + xóa line.merged; merge-next gộp
text + vứt take; id mới không đụng id cũ."""
from __future__ import annotations
import json, shutil, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
EP = Path(__file__).resolve().parent.parent / ".m4test"
SCRIPT = """# SCRIPT — m4test

**Voice direction:** Rõ.

---

## Line 1 — Test (Frame 1)

    Ba đến bốn tháng rồi.
"""
_P = 0
def check(c, label):
    global _P
    if not c: print("  FAIL:", label); sys.exit(1)
    _P += 1; print("  ok:", label)
def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE+path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp: return json.loads(resp.read())
def get(path):
    with urllib.request.urlopen(BASE+path, timeout=30) as resp: return json.loads(resp.read())
def state():
    return get("/api/projects/state?ep=" + urllib.parse.quote(str(EP), safe=""))

def main():
    if EP.exists(): shutil.rmtree(EP)
    EP.mkdir(parents=True); (EP/"SCRIPT.md").write_text(SCRIPT, encoding="utf-8")
    r = req("POST", "/api/projects/import", {"ep": str(EP)})
    check(r["fragments"] == 1, f"import 1 fragment ({r})")

    # generate + merge line -> có take + line.merged
    g = req("POST", "/api/takes/generate", {"ep": str(EP), "frame": 1})
    for _ in range(100):
        if get(f"/api/jobs/{g['job_id']}")["status"] in ("done","error"): break
        time.sleep(0.1)
    req("POST", "/api/lines/merge", {"ep": str(EP), "frame": 1})
    st = state()["project"]["lines"][0]
    take_wav = EP / st["fragments"][0]["takes"][0]["wav"]
    check(take_wav.exists(), "take wav tồn tại trước split")
    check(st["merged"] is not None, "line.merged có trước split")

    # split "Ba đến bốn tháng rồi." tại 'tháng'
    text = st["fragments"][0]["text"]
    idx = text.index("tháng")
    s = req("POST", "/api/fragments/split",
            {"ep": str(EP), "fragment_id": "f-1-0", "char_index": idx})
    check(s["texts"] == ["Ba đến bốn", "tháng rồi."], f"tách đúng text ({s['texts']})")
    check(s["fragments"][1] != "f-1-0", f"id mới khác id cũ ({s['fragments']})")
    check(not take_wav.exists(), "take wav bị XÓA sau split (phương án a)")
    st2 = state()["project"]["lines"][0]
    check(len(st2["fragments"]) == 2, "2 fragment sau split")
    check(all(len(f["takes"]) == 0 for f in st2["fragments"]), "cả 2 fragment không còn take")
    check(st2["merged"] is None, "line.merged bị xóa sau thay đổi cấu trúc")

    # split biên -> lỗi 400
    try:
        req("POST", "/api/fragments/split", {"ep": str(EP), "fragment_id": "f-1-0", "char_index": 0})
        check(False, "split ở biên phải lỗi")
    except urllib.error.HTTPError as e:
        check(e.code == 400, "split ở biên -> 400")

    # merge-next gộp lại
    m = req("POST", "/api/fragments/merge-next", {"ep": str(EP), "fragment_id": "f-1-0"})
    check(m["text"] == "Ba đến bốn tháng rồi.", f"gộp đúng text ({m['text']})")
    st3 = state()["project"]["lines"][0]
    check(len(st3["fragments"]) == 1, "1 fragment sau merge-next")

    # merge-next ở fragment cuối -> lỗi
    try:
        req("POST", "/api/fragments/merge-next", {"ep": str(EP), "fragment_id": "f-1-0"})
        check(False, "merge-next fragment cuối phải lỗi")
    except urllib.error.HTTPError as e:
        check(e.code == 400, "merge-next cuối -> 400")

    print(f"\n[m4_check] PASS — {_P} kiểm tra")
    shutil.rmtree(EP)

if __name__ == "__main__":
    main()
