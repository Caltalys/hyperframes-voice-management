"""Kiểm endpoint M3 mới: PUT /api/fragments/text (+stale), PUT /api/lines/meta.
Server chạy với VO_STUDIO_ENGINE=fake."""
from __future__ import annotations
import json, shutil, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
EP = Path(__file__).resolve().parent.parent / ".uitest"
SCRIPT = """# SCRIPT — uitest

**Voice direction:** Rõ ràng.

---

## Line 1 — Hook (Frame 1)

**Time:** 0.0 – 5.0s

    Ba đến bốn tháng.
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

def main():
    if EP.exists(): shutil.rmtree(EP)
    EP.mkdir(parents=True); (EP/"SCRIPT.md").write_text(SCRIPT, encoding="utf-8")
    r = req("POST", "/api/projects/import", {"ep": str(EP)})
    check(r["fragments"] == 1, f"import 1 fragment ({r})")

    # generate rồi mới sửa text -> phải thành stale
    g = req("POST", "/api/takes/generate", {"ep": str(EP), "frame": 1})
    for _ in range(100):
        if get(f"/api/jobs/{g['job_id']}")["status"] in ("done", "error"): break
        time.sleep(0.1)
    fid = "f-1-0"
    e = req("PUT", "/api/fragments/text", {"ep": str(EP), "fragment_id": fid, "text": "Năm đến sáu tháng."})
    check(e["text"] == "Năm đến sáu tháng.", "sửa text nhận giá trị mới")
    check(e["stale"] is True, "take cũ -> stale sau sửa text")

    # sửa gap
    e2 = req("PUT", "/api/fragments/text", {"ep": str(EP), "fragment_id": fid, "gap_s": 0.8})
    check(e2["gap_s"] == 0.8, "sửa gap nhận giá trị")
    e3 = req("PUT", "/api/fragments/text", {"ep": str(EP), "fragment_id": fid, "clear_gap": True})
    check(e3["gap_s"] is None, "clear_gap -> None (dùng default global)")

    # sửa meta line
    m = req("PUT", "/api/lines/meta", {"ep": str(EP), "frame": 1, "title": "Mở đầu mới"})
    check(m["title"] == "Mở đầu mới", "sửa title line")

    # state phản ánh stale + has_selected
    st = get("/api/projects/state?ep=" + urllib.parse.quote(str(EP), safe=""))
    f = st["project"]["lines"][0]["fragments"][0]
    check(f["stale"] is True and f["has_selected"] is True, "state có cờ stale + has_selected")

    print(f"\n[ui_check] PASS — {_P} kiểm tra")
    shutil.rmtree(EP)

if __name__ == "__main__":
    main()
