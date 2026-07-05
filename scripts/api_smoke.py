"""Kiểm chứng M2 end-to-end qua HTTP thật (không cần model — chạy server với
VO_STUDIO_ENGINE=fake). Kiểm: import -> generate (async job) -> SSE nhận tiến độ
-> poll job done -> take xuất hiện trong state -> merge -> export audio_meta.

Dùng: khởi server `uvicorn app.main:app` (env fake), rồi `python scripts/api_smoke.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
EP = ROOT / ".apitest"

SCRIPT = """# SCRIPT — apitest

**Voice direction:** Rõ ràng.

---

## Line 1 — Hook (Frame 1)

**Time:** 0.0 – 5.0s
**Delivery:** Chậm.

    Ba đến bốn tháng. Đó là thời gian mỗi dự án mới.

## Line 2 — Chốt (Frame 2)

**Delivery:** Dứt khoát.

    Vấn đề có tên rõ ràng.
"""

_PASS = 0


def check(cond: bool, label: str) -> None:
    global _PASS
    if not cond:
        print(f"  FAIL: {label}")
        sys.exit(1)
    _PASS += 1
    print(f"  ok: {label}")


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def sse_collect(events: list, stop: threading.Event) -> None:
    with urllib.request.urlopen(BASE + "/api/jobs/stream", timeout=60) as r:
        for raw in r:
            if stop.is_set():
                return
            line = raw.decode("utf-8").strip()
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))


def main() -> None:
    check(get("/api/health")["ok"], "health")

    if EP.exists():
        shutil.rmtree(EP)
    EP.mkdir(parents=True)
    (EP / "SCRIPT.md").write_text(SCRIPT, encoding="utf-8")

    # SSE listener nền
    events: list = []
    stop = threading.Event()
    t = threading.Thread(target=sse_collect, args=(events, stop), daemon=True)
    t.start()
    time.sleep(0.5)  # để kết nối SSE sẵn sàng trước khi submit

    r = post("/api/projects/import", {"ep": str(EP)})
    check(r["lines"] == 2 and r["fragments"] == 3, f"import 2 line/3 frag ({r})")

    r = post("/api/takes/generate", {"ep": str(EP), "frame": 1})
    job_id = r["job_id"]
    check(r["total"] == 2, f"job nhận 2 fragment ({r})")

    # poll job done
    for _ in range(100):
        js = get(f"/api/jobs/{job_id}")
        if js["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    check(js["status"] == "done", f"job done ({js['status']}, err={js.get('error')})")
    check(len(js["results"]) == 2, "job có 2 kết quả take")

    time.sleep(0.3)  # để SSE flush nốt event
    stop.set()
    types = [e.get("type") for e in events]
    check("fragment_done" in types, f"SSE có fragment_done (types={types})")
    check("done" in types, "SSE có event done")

    # state: fragment line 1 có take
    st = get(f"/api/projects/state?ep={urllib_quote(str(EP))}")
    line1 = next(l for l in st["project"]["lines"] if l["frame"] == 1)
    check(all(len(f["takes"]) == 1 for f in line1["fragments"]),
          "mỗi fragment line 1 có 1 take")
    check(all(f["has_selected"] for f in line1["fragments"]),
          "take được auto-select")

    # gen line 2 rồi merge cả hai + export
    r = post("/api/takes/generate", {"ep": str(EP), "frame": 2})
    for _ in range(100):
        if get(f"/api/jobs/{r['job_id']}")["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    for fr in (1, 2):
        m = post("/api/lines/merge", {"ep": str(EP), "frame": fr})
        check(m["words"] > 0, f"merge line {fr} có words")
    ex = post("/api/export/audio-meta", {"ep": str(EP)})
    check(ex["voices"] == 2 and ex["skipped_frames"] == [], f"export 2 voices ({ex})")

    print(f"\n[api_smoke] PASS — {_PASS} kiểm tra")


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


if __name__ == "__main__":
    main()
