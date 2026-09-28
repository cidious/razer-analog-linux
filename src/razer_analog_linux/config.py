"""Configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from razer_analog_linux.protocol import PRODUCT_HUNTSMAN_V2_ANALOG
from razer_analog_linux.threshold import ThresholdConfig

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


@dataclass
class AppConfig:
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)
    repeat_delay_ms: int = 200
    repeat_rate_ms: int = 30
    sysfs_path: str = ""
    product_ids: Set[int] = field(default_factory=lambda: {PRODUCT_HUNTSMAN_V2_ANALOG})
    sync_openrazer_sysfs: bool = True
    require_daemon_stopped: bool = False
    layout_file: str = "config/layouts/huntsman_v2_analog.json"
    meta_as_fn: bool = False


def _repo_root() -> Path:
    # src/razer_analog_linux/config.py → repo root
    return Path(__file__).resolve().parents[2]


def resolve_path(path: str | Path, base: Optional[Path] = None) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    root = base or _repo_root()
    return (root / p).resolve()


def load_config(path: Optional[str | Path] = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        candidate = _repo_root() / "config" / "default.toml"
        if not candidate.exists():
            return cfg
        path = candidate
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))

    th = data.get("threshold") or {}
    cfg.threshold = ThresholdConfig(
        actuate=int(th.get("actuate", cfg.threshold.actuate)),
        release=int(th.get("release", cfg.threshold.release)),
    )
    cfg.repeat_delay_ms = int(th.get("repeat_delay_ms", cfg.repeat_delay_ms))
    cfg.repeat_rate_ms = int(th.get("repeat_rate_ms", cfg.repeat_rate_ms))

    dev = data.get("device") or {}
    cfg.sysfs_path = str(dev.get("sysfs_path") or "")
    if "product_ids" in dev:
        cfg.product_ids = {int(x) for x in dev["product_ids"]}

    ora = data.get("openrazer") or {}
    cfg.sync_openrazer_sysfs = bool(ora.get("sync_sysfs", True))
    cfg.require_daemon_stopped = bool(ora.get("require_daemon_stopped", False))

    lay = data.get("layout") or {}
    cfg.layout_file = str(lay.get("file", cfg.layout_file))
    cfg.meta_as_fn = bool(lay.get("meta_as_fn", False))
    return cfg
