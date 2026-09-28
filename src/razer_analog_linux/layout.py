"""Layout loading: Razer key id → Linux KEY_*."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import evdev


def _key_code(name: str) -> int:
    full = name if name.startswith("KEY_") else f"KEY_{name}"
    if full not in evdev.ecodes.ecodes:
        raise KeyError(f"unknown key name: {name}")
    return int(evdev.ecodes.ecodes[full])


def load_layout_file(path: Path) -> Dict[str, Dict[int, int]]:
    """Load layout JSON into {layer: {razer_id: KEY code}}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    result: Dict[str, Dict[int, int]] = {"plain": {}, "fn": {}, "fn_fn": {}}
    for layer in ("plain", "fn", "fn_fn"):
        for razer_key, evdev_key in (data.get(layer) or {}).items():
            if str(razer_key).startswith("_"):
                continue
            result[layer][int(razer_key)] = _key_code(str(evdev_key))
    return result


def unmapped_targets(path: Path) -> List[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("_unmapped_targets") or [])


_EXTRA_KEYS = (
    "ESC",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "GRAVE",
    "INSERT", "DELETE", "HOME", "END", "PAGEUP", "PAGEDOWN",
    "UP", "DOWN", "LEFT", "RIGHT",
    "NUMLOCK", "KPSLASH", "KPASTERISK", "KPMINUS", "KPPLUS", "KPENTER", "KPDOT",
    "KP0", "KP1", "KP2", "KP3", "KP4", "KP5", "KP6", "KP7", "KP8", "KP9",
    "SYSRQ", "SCROLLLOCK", "PAUSE",
    "MUTE", "VOLUMEUP", "VOLUMEDOWN",
    "PREVIOUSSONG", "PLAYPAUSE", "NEXTSONG", "STOPCD",
    "FN", "LEFTMETA", "RIGHTMETA", "COMPOSE",
)


def all_key_codes(layout: Dict[str, Dict[int, int]]) -> List[int]:
    codes: Set[int] = set()
    for layer in layout.values():
        codes.update(layer.values())
    for name in _EXTRA_KEYS:
        full = f"KEY_{name}"
        if full in evdev.ecodes.ecodes:
            codes.add(int(evdev.ecodes.ecodes[full]))
    return sorted(codes)


def get_active_layer(
    layout: Dict[str, Dict[int, int]],
    fn_pressed: bool,
    meta_as_fn: bool,
    meta_pressed: bool,
) -> Dict[int, int]:
    use_fn = fn_pressed or (meta_as_fn and meta_pressed)
    if fn_pressed and meta_as_fn and meta_pressed and layout.get("fn_fn"):
        return layout["fn_fn"]
    if use_fn and layout.get("fn"):
        # Merge plain under fn for unmapped passthrough of modifiers.
        merged = dict(layout["plain"])
        merged.update(layout["fn"])
        return merged
    return layout["plain"]


def save_plain_mapping(path: Path, razer_id: int, key_name: str) -> None:
    """Write/overwrite one plain-layer mapping and remove from _unmapped_targets."""
    data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    plain = data.setdefault("plain", {})
    plain[str(razer_id)] = key_name.removeprefix("KEY_")
    name = key_name.removeprefix("KEY_")
    targets: List[str] = list(data.get("_unmapped_targets") or [])
    data["_unmapped_targets"] = [t for t in targets if t != name]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def skip_unmapped_target(path: Path, key_name: str, *, reason: str) -> None:
    """Remove a target from _unmapped_targets and record it under _skipped."""
    data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    name = key_name.removeprefix("KEY_")
    targets: List[str] = list(data.get("_unmapped_targets") or [])
    data["_unmapped_targets"] = [t for t in targets if t != name]
    skipped = data.setdefault("_skipped", {})
    if not isinstance(skipped, dict):
        skipped = {}
        data["_skipped"] = skipped
    skipped[name] = reason
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def mapped_razer_ids(layout: Dict[str, Dict[int, int]]) -> Set[int]:
    ids: Set[int] = set()
    for layer in layout.values():
        ids.update(layer.keys())
    return ids


def invert_plain(layout: Dict[str, Dict[int, int]]) -> Dict[int, str]:
    """Map KEY code → name for logging."""
    out: Dict[int, str] = {}
    for razer_id, code in layout.get("plain", {}).items():
        name = evdev.ecodes.KEY.get(code, str(code))
        out[razer_id] = name if isinstance(name, str) else str(name)
    return out
