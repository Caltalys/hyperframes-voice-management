"""Sửa nội dung line/fragment. Tool là nguồn sự thật — text sửa ở đây, không sửa
SCRIPT.md trực tiếp (SCRIPT.md là artifact export).

Split/merge fragment (M4) sẽ thêm vào đây sau.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, store
from ..jobs import ep_lock
from .projects import resolve_ep

router = APIRouter(prefix="/api", tags=["lines"])


class FragmentEdit(BaseModel):
    ep: str
    fragment_id: str
    text: str | None = None
    tts_text: str | None = None
    gap_s: float | None = None
    clear_tts: bool = False   # đặt tts_text về None (dùng lại to_tts mặc định)
    clear_gap: bool = False   # đặt gap_s về None (dùng default_gap global)


@router.put("/fragments/text")
async def edit_fragment(body: FragmentEdit) -> dict:
    ep = resolve_ep(body.ep)
    default_gap = config.load_config()["default_gap_s"]
    async with ep_lock(ep):
        project = store.load(ep)
        frag = project.fragment(body.fragment_id)
        if frag is None:
            raise HTTPException(404, f"fragment không tồn tại: {body.fragment_id}")
        if body.text is not None:
            if not body.text.strip():
                raise HTTPException(400, "text rỗng")
            frag.text = body.text.strip()
        if body.clear_tts:
            frag.tts_text = None
        elif body.tts_text is not None:
            frag.tts_text = body.tts_text
        if body.clear_gap:
            frag.gap_s = None
        elif body.gap_s is not None:
            frag.gap_s = body.gap_s
        store.save(ep, project)
        # take cũ có thể lệch text mới -> badge stale (không tự xóa)
        return {"fragment_id": frag.id, "text": frag.text,
                "tts_text": frag.tts_text, "gap_s": frag.gap_s,
                "stale": frag.is_stale(default_gap)}


class LineMeta(BaseModel):
    ep: str
    frame: int
    title: str | None = None
    time_range: str | None = None
    delivery: str | None = None


@router.put("/lines/meta")
async def edit_line_meta(body: LineMeta) -> dict:
    ep = resolve_ep(body.ep)
    async with ep_lock(ep):
        project = store.load(ep)
        line = project.line(body.frame)
        if not line:
            raise HTTPException(404, f"không có line frame {body.frame}")
        if body.title is not None:
            line.title = body.title
        if body.time_range is not None:
            line.time_range = body.time_range
        if body.delivery is not None:
            line.delivery = body.delivery
        store.save(ep, project)
    return {"frame": body.frame, "title": line.title,
            "time_range": line.time_range, "delivery": line.delivery}
