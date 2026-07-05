"""Merge line -> line wav, export audio_meta.json / SCRIPT.md."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, pipeline, script_io, store
from ..jobs import ep_lock
from .projects import resolve_ep

router = APIRouter(prefix="/api", tags=["export"])


class MergeBody(BaseModel):
    ep: str
    frame: int


@router.post("/lines/merge")
async def merge_line(body: MergeBody) -> dict:
    ep = resolve_ep(body.ep)
    cfg = config.load_config()
    async with ep_lock(ep):
        project = store.load(ep)
        line = project.line(body.frame)
        if not line:
            raise HTTPException(404, f"không có line frame {body.frame}")
        try:
            merged = pipeline.merge_line(project, ep, line, cfg)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        store.save(ep, project)
    return {"frame": body.frame, "wav": merged.wav,
            "duration_s": merged.duration_s, "words": len(merged.words)}


class EpBody(BaseModel):
    ep: str


@router.post("/export/audio-meta")
def export_audio_meta(body: EpBody) -> dict:
    ep = resolve_ep(body.ep)
    project = store.load(ep)
    meta_path, skipped = pipeline.export_audio_meta(project, ep)
    return {"path": str(meta_path), "voices": len(project.lines) - len(skipped),
            "skipped_frames": skipped}


@router.post("/export/script")
def export_script(body: EpBody) -> dict:
    ep = resolve_ep(body.ep)
    project = store.load(ep)
    (ep / "SCRIPT.md").write_text(script_io.export_script(project), encoding="utf-8")
    return {"path": str(ep / "SCRIPT.md")}
