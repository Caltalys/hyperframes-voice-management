"""Kiểm M5: re-import diff/orphan/restore + cancel job.
Server chạy: VO_STUDIO_ENGINE=fake VO_STUDIO_FAKE_DELAY_S=0.2 uvicorn app.main:app"""
from __future__ import annotations
import json, shutil, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
EP = Path(__file__).resolve().parent.parent / ".m5test"
SCRIPT_V1 = """# SCRIPT — m5test

**Voice direction:** Rõ ràng.

---

## Line 1 — Hook (Frame 1)

**Time:** 0.0 – 5.0s

    Ba đến bốn tháng. Đó là thời gian trung bình.

## Line 2 — Bỏ đi (Frame 2)

    Line này sẽ biến mất.
"""
# v2: line 1 giữ câu 1, thay câu 2, thêm câu 3; line 2 biến mất; line 3 mới (4 câu — test cancel)
SCRIPT_V2 = """# SCRIPT — m5test

**Voice direction:** Rõ ràng.

---

## Line 1 — Hook mới (Frame 1)

**Time:** 0.0 – 5.0s

    Ba đến bốn tháng. Một con số khác hẳn. Thêm câu mới nữa.

## Line 3 — Mới (Frame 3)

    Câu một. Câu hai. Câu ba. Câu bốn.
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
    with urllib.request.urlopen(r, timeout=60) as resp: return json.loads(resp.read())
def get(path):
    with urllib.request.urlopen(BASE+path, timeout=60) as resp: return json.loads(resp.read())
def wait_job(job_id, timeout=30):
    for _ in range(int(timeout*10)):
        j = get(f"/api/jobs/{job_id}")
        if j["status"] in ("done", "error", "canceled"): return j
        time.sleep(0.1)
    raise TimeoutError(job_id)
def state_line(st, frame):
    return next(l for l in st["project"]["lines"] if l["frame"] == frame)

def main():
    if EP.exists(): shutil.rmtree(EP)
    EP.mkdir(parents=True); (EP/"SCRIPT.md").write_text(SCRIPT_V1, encoding="utf-8")
    ep = str(EP); epq = urllib.parse.quote(ep, safe="")

    r = req("POST", "/api/projects/import", {"ep": ep})
    check(r["lines"] == 2 and r["fragments"] == 3, f"import v1: 2 line, 3 fragment ({r})")
    g = req("POST", "/api/takes/generate", {"ep": ep, "frame": 1})
    check(wait_job(g["job_id"])["status"] == "done", "gen line 1 xong")

    # --- re-import ---
    (EP/"SCRIPT.md").write_text(SCRIPT_V2, encoding="utf-8")
    r = req("POST", "/api/projects/reimport", {"ep": ep, "confirm": False})
    d = r["diff"]
    check(r["applied"] is False and d["changed"] is True, "preview không áp dụng, changed=true")
    check(d["lines_added"] == [3] and d["lines_removed"] == [2], f"diff line +3 −2 ({d})")
    lc = next(x for x in d["lines_changed"] if x["frame"] == 1)
    check(lc["kept"] == 1 and len(lc["added"]) == 2 and len(lc["orphaned"]) == 1,
          f"diff line 1: giữ 1, thêm 2, orphan 1 ({lc})")
    st = get(f"/api/projects/state?ep={epq}")
    check(len([f for f in state_line(st, 1)["fragments"] if not f["orphan"]]) == 2,
          "preview xong project trên đĩa chưa đổi")

    r = req("POST", "/api/projects/reimport", {"ep": ep, "confirm": True})
    check(r["applied"] is True, "confirm=true áp dụng")
    st = get(f"/api/projects/state?ep={epq}")
    l1 = state_line(st, 1)
    active1 = [f for f in l1["fragments"] if not f["orphan"]]
    check(len(active1) == 3, "line 1 có 3 fragment active")
    kept = next(f for f in active1 if f["text"] == "Ba đến bốn tháng.")
    check(kept["id"] == "f-1-0" and kept["has_selected"], "fragment khớp text giữ nguyên id + take")
    check(all(not f["has_selected"] for f in active1 if f["id"] != "f-1-0"),
          "fragment mới là fragment trống")
    orphan1 = next(f for f in l1["fragments"] if f["orphan"])
    check(orphan1["text"] == "Đó là thời gian trung bình." and orphan1["takes"],
          "fragment biến mất -> orphan, take không bị xóa")
    check((EP / orphan1["takes"][0]["wav"]).exists(), "wav của take orphan còn trên đĩa")
    check(l1["title"] == "Hook mới", "meta line cập nhật theo script")
    l2 = state_line(st, 2)
    check(all(f["orphan"] for f in l2["fragments"]), "line biến mất -> mọi fragment orphan")
    check(len(state_line(st, 3)["fragments"]) == 4, "line mới xuất hiện với 4 fragment")

    # --- restore orphan ---
    r = req("POST", "/api/fragments/restore", {"ep": ep, "fragment_id": orphan1["id"]})
    check(r["orphan"] is False, "restore orphan")
    st = get(f"/api/projects/state?ep={epq}")
    back = next(f for f in state_line(st, 1)["fragments"] if f["id"] == orphan1["id"])
    check(not back["orphan"] and back["has_selected"], "fragment khôi phục vẫn giữ take")

    # script không đổi nhưng project vừa restore lệch script -> preview phải báo đổi
    d2 = req("POST", "/api/projects/reimport", {"ep": ep, "confirm": False})["diff"]
    check(any(x["frame"] == 1 for x in d2["lines_changed"]), "restore lệch script -> preview báo đổi")

    # --- cancel: job đang chạy (fake delay 0.2s/fragment) ---
    g = req("POST", "/api/takes/generate", {"ep": ep, "frame": 3})   # 4 fragment
    time.sleep(0.1)
    c = req("POST", f"/api/jobs/{g['job_id']}/cancel")
    check(c["status"] in ("running", "canceled", "queued"), f"cancel nhận ({c['status']})")
    j = wait_job(g["job_id"])
    check(j["status"] == "canceled", f"job running -> canceled ở ranh giới fragment ({j['status']})")
    check(len(j["results"]) < j["total"], f"hủy giữa chừng: {len(j['results'])}/{j['total']} fragment")

    # --- cancel: job còn queued (job 1 chạy, job 2 xếp hàng) ---
    g1 = req("POST", "/api/takes/generate", {"ep": ep, "frame": 3})
    g2 = req("POST", "/api/takes/generate", {"ep": ep, "frame": 1})
    c2 = req("POST", f"/api/jobs/{g2['job_id']}/cancel")
    check(c2["status"] == "canceled" and c2["index"] == 0, "job queued hủy ngay, chưa chạy fragment nào")
    wait_job(g1["job_id"])
    check(get(f"/api/jobs/{g2['job_id']}")["status"] == "canceled", "job hủy không bị worker chạy lại")

    print(f"\n[m5_check] PASS — {_P} kiểm tra")
    shutil.rmtree(EP)

if __name__ == "__main__":
    main()
