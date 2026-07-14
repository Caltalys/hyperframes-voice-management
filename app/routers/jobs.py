"""Trạng thái job + SSE stream tiến độ generate."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..jobs import manager

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/stream")
async def jobs_stream(request: Request) -> StreamingResponse:
    """SSE — đẩy event tiến độ realtime (queued/start/fragment_*/done/error)."""
    q = manager.subscribe()

    async def gen():
        try:
            # comment mở đầu để client biết đã kết nối
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # giữ kết nối sống
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            manager.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = manager.jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"job không tồn tại: {job_id}")
    return job.public()


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    """Hủy job: queued hủy ngay, running hủy ở ranh giới fragment kế tiếp
    (fragment đang TTS chạy nốt, take của nó vẫn được lưu)."""
    job = manager.cancel(job_id)
    if job is None:
        raise HTTPException(404, f"job không tồn tại: {job_id}")
    return job.public()
