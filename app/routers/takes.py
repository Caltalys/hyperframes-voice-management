"""Generate take (async job), chọn take, nghe wav."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import config, store
from ..jobs import ep_lock, manager
from .projects import resolve_ep

router = APIRouter(prefix="/api", tags=["takes"])


class GenerateBody(BaseModel):
    ep: str
    fragment_ids: list[str] | None = None
    frame: int | None = None   # nếu cho frame: gen mọi fragment active của line


@router.post("/takes/generate")
def generate(body: GenerateBody) -> dict:
    ep = resolve_ep(body.ep)
    project = store.load(ep)

    fids = list(body.fragment_ids or [])
    if body.frame is not None:
        line = project.line(body.frame)
        if not line:
            raise HTTPException(404, f"không có line frame {body.frame}")
        fids = [f.id for f in line.active_fragments()]
    if not fids:
        raise HTTPException(400, "cần fragment_ids hoặc frame")
    for fid in fids:
        if project.fragment(fid) is None:
            raise HTTPException(404, f"fragment không tồn tại: {fid}")

    job = manager.submit(ep, fids)
    return {"job_id": job.id, "total": job.total, "fragment_ids": fids}


class SelectBody(BaseModel):
    ep: str
    fragment_id: str
    take_id: str


@router.post("/takes/select")
async def select(body: SelectBody) -> dict:
    ep = resolve_ep(body.ep)
    async with ep_lock(ep):
        project = store.load(ep)
        frag = project.fragment(body.fragment_id)
        if frag is None:
            raise HTTPException(404, f"fragment không tồn tại: {body.fragment_id}")
        if not any(t.id == body.take_id for t in frag.takes):
            raise HTTPException(404, f"take không tồn tại: {body.take_id}")
        frag.selected_take_id = body.take_id
        store.save(ep, project)
    return {"fragment_id": body.fragment_id, "selected_take_id": body.take_id}


@router.get("/takes/audio")
def audio(ep: str, take_wav: str) -> FileResponse:
    """Stream wav để nghe/waveform. take_wav là đường dẫn tương đối trong project."""
    ep_path = resolve_ep(ep)
    wav = (ep_path / take_wav).resolve()
    # chặn path traversal: phải nằm trong assets/vo của ep
    vo_root = (ep_path / "assets" / "vo").resolve()
    if vo_root not in wav.parents or not wav.exists():
        raise HTTPException(404, f"wav không hợp lệ: {take_wav}")
    return FileResponse(str(wav), media_type="audio/wav")
