"""Global config (voice bất biến cho MỌI tập) — ~/.hyperframes-vo/config.json.

Voice là hằng số toàn cục nên nằm ở đây, KHÔNG lặp trong từng project.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".hyperframes-vo"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "voice": "Đức Trí",
    "engine": "vieneu",
    "whisper_model": "small",
    "default_gap_s": 0.40,
    "recent_projects": [],
}


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def remember_project(ep_dir: str) -> None:
    """Đưa project lên đầu danh sách gần đây (khử trùng lặp)."""
    cfg = load_config()
    recent = [p for p in cfg.get("recent_projects", []) if p != ep_dir]
    recent.insert(0, ep_dir)
    cfg["recent_projects"] = recent[:20]
    save_config(cfg)
