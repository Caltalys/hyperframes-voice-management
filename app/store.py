"""Đọc/ghi project.json — atomic write (ghi .tmp rồi rename) để crash giữa
chừng không làm hỏng nguồn sự thật."""

from __future__ import annotations

import os
from pathlib import Path

from .models import Project


def vo_dir(ep: Path) -> Path:
    return ep / "assets" / "vo"


def project_path(ep: Path) -> Path:
    return vo_dir(ep) / "project.json"


def exists(ep: Path) -> bool:
    return project_path(ep).exists()


def load(ep: Path) -> Project:
    p = project_path(ep)
    if not p.exists():
        raise FileNotFoundError(
            f"project.json chưa tồn tại: {p} — chạy `import {ep}` trước"
        )
    return Project.model_validate_json(p.read_text(encoding="utf-8"))


def save(ep: Path, project: Project) -> None:
    p = project_path(ep)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        project.model_dump_json(indent=2, exclude_none=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, p)  # atomic trên cùng ổ đĩa
