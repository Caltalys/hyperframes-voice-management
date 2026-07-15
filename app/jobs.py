"""Job queue async + SSE — TTS ~5x chậm realtime nên generate KHÔNG thể đồng bộ.

In-process, 1 worker serialize (không load model 2 lần song song). Generate chạy
trong thread (asyncio.to_thread) để không chẹn event loop -> SSE vẫn realtime.
Ghi project.json dưới lock per-ep để worker và API không tranh chấp.

Engine mặc định lấy từ config["engine"] (registry ở engine/tts.py); env
VO_STUDIO_ENGINE override (fake dùng test async không cần tải model).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, pipeline, store

# ---------- lock per-ep (đồng bộ đọc-sửa-ghi project.json) ----------

_locks: dict[str, asyncio.Lock] = {}


def ep_lock(ep: Path) -> asyncio.Lock:
    key = str(ep)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


# ---------- engine factory ----------

_engines: tuple | None = None


def get_engines() -> tuple:
    """(tts, aligner) singleton — lazy, giữ model nạp 1 lần trong tiến trình."""
    global _engines
    if _engines is None:
        from .engine.tts import make_tts
        cfg = config.load_config()
        # env override > config["engine"]; "real" = alias cho backend thật.
        name = (os.environ.get("VO_STUDIO_ENGINE") or cfg["engine"]).lower()
        if name == "real":
            name = cfg["engine"]
        tts = make_tts(name)
        if name == "fake":
            from .engine.align import FakeAligner
            _engines = (tts, FakeAligner())
        else:
            from .engine.align import RealAligner
            _engines = (tts, RealAligner(cfg["whisper_model"]))
    return _engines


# ---------- job model ----------

@dataclass
class Job:
    id: str
    ep: str
    fragment_ids: list[str]
    status: str = "queued"           # queued | running | done | error | canceled
    index: int = 0                   # fragment đang xử lý (1-based)
    total: int = 0
    error: str | None = None
    results: list[dict] = field(default_factory=list)  # {fragment_id, take_id}
    cancel_requested: bool = False   # worker kiểm giữa các fragment (không cắt giữa TTS)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "ep": self.ep, "status": self.status,
            "index": self.index, "total": self.total,
            "error": self.error, "results": self.results,
        }


class JobManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.jobs: dict[str, Job] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker = None

    # --- submit ---
    def submit(self, ep: Path, fragment_ids: list[str]) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], ep=str(ep),
                  fragment_ids=fragment_ids, total=len(fragment_ids))
        self.jobs[job.id] = job
        self.queue.put_nowait(job.id)
        self._emit({"type": "queued", **job.public()})
        return job

    # --- cancel ---
    def cancel(self, job_id: str) -> Job | None:
        """Yêu cầu hủy job. queued -> hủy ngay; running -> hủy ở ranh giới fragment
        kế tiếp (fragment đang TTS chạy nốt). Job đã kết thúc -> trả nguyên trạng."""
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if job.status in ("done", "error", "canceled"):
            return job
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "canceled"
            self._emit({"type": "canceled", **job.public()})
        return job

    # --- SSE pub/sub ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _emit(self, event: dict) -> None:
        for q in list(self._subscribers):
            q.put_nowait(event)

    # --- worker loop ---
    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs[job_id]
            try:
                if job.status != "canceled":  # hủy khi còn queued -> bỏ qua
                    await self._run_job(job)
            except Exception as exc:  # noqa: BLE001 — báo lỗi job, không sập worker
                job.status = "error"
                job.error = str(exc)
                self._emit({"type": "error", **job.public()})
            finally:
                self.queue.task_done()

    async def _run_job(self, job: Job) -> None:
        ep = Path(job.ep)
        tts, aligner = get_engines()
        cfg = config.load_config()
        job.status = "running"
        self._emit({"type": "start", **job.public()})

        for i, fid in enumerate(job.fragment_ids, 1):
            if job.cancel_requested:
                job.status = "canceled"
                self._emit({"type": "canceled", **job.public()})
                return
            job.index = i
            self._emit({"type": "fragment_start", "job_id": job.id,
                        "fragment_id": fid, "index": i, "total": job.total})

            async with ep_lock(ep):
                project = store.load(ep)
                frag = project.fragment(fid)
                if frag is None:
                    raise ValueError(f"fragment không tồn tại: {fid}")
                # generate_take là blocking (TTS/whisper) -> chạy trong thread
                take = await asyncio.to_thread(
                    pipeline.generate_take, project, ep, frag, tts, aligner, cfg
                )
                store.save(ep, project)  # lưu từng fragment

            job.results.append({"fragment_id": fid, "take_id": take.id})
            self._emit({"type": "fragment_done", "job_id": job.id,
                        "fragment_id": fid, "take_id": take.id,
                        "duration_s": take.duration_s,
                        "index": i, "total": job.total})

        job.status = "done"
        self._emit({"type": "done", **job.public()})


# singleton toàn tiến trình
manager = JobManager()
