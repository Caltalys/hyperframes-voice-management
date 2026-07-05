"""Mở / import / trạng thái project. Project định danh bằng đường dẫn ep tuyệt đối."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config, script_io, store

router = APIRouter(prefix="/api", tags=["projects"])


def resolve_ep(ep: str) -> Path:
    p = Path(ep).expanduser().resolve()
    if not p.exists():
        raise HTTPException(404, f"thư mục không tồn tại: {p}")
    return p


class EpBody(BaseModel):
    ep: str
    force: bool = False


@router.get("/config")
def get_config() -> dict:
    return config.load_config()


@router.get("/projects/recent")
def recent() -> dict:
    return {"recent_projects": config.load_config().get("recent_projects", [])}


@router.post("/projects/import")
def import_project(body: EpBody) -> dict:
    ep = resolve_ep(body.ep)
    if store.exists(ep) and not body.force:
        raise HTTPException(409, "project.json đã tồn tại — dùng force=true (re-import M5)")
    if not (ep / "SCRIPT.md").exists():
        raise HTTPException(400, f"không thấy SCRIPT.md trong {ep}")
    project = script_io.import_script(ep)
    store.save(ep, project)
    config.remember_project(str(ep))
    return {"ep": str(ep), "lines": len(project.lines),
            "fragments": sum(len(l.fragments) for l in project.lines)}


@router.post("/projects/open")
def open_project(body: EpBody) -> dict:
    ep = resolve_ep(body.ep)
    if not store.exists(ep):
        raise HTTPException(404, "chưa có project.json — import trước")
    config.remember_project(str(ep))
    return _state(ep)


@router.get("/projects/state")
def state(ep: str) -> dict:
    return _state(resolve_ep(ep))


def _state(ep: Path) -> dict:
    project = store.load(ep)
    default_gap = config.load_config()["default_gap_s"]
    # bổ sung trạng thái dẫn xuất cho UI (stale badge, sẵn sàng merge)
    data = project.model_dump()
    for line, ldata in zip(project.lines, data["lines"]):
        ldata["ready_to_merge"] = line.ready_to_merge()
        for frag, fdata in zip(line.fragments, ldata["fragments"]):
            fdata["stale"] = frag.is_stale(default_gap)
            fdata["has_selected"] = frag.selected_take() is not None
    return {"ep": str(ep), "project": data}
