"""Forward keyboard lock LEDs to the physical Razer input LED sysfs nodes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, Optional

import evdev

# Linux LED codes → sysfs suffix under /sys/class/leds/inputN::SUFFIX
_LED_SUFFIX = {
    evdev.ecodes.LED_NUML: "numlock",
    evdev.ecodes.LED_CAPSL: "capslock",
    evdev.ecodes.LED_SCROLLL: "scrolllock",
}


def find_physical_led_paths(usb_sysfs: str) -> Dict[int, Path]:
    """
    Map LED_* code → brightness path for the first keyboard interface
    under this USB device that exposes the standard lock LEDs.
    """
    root = Path(usb_sysfs)
    # Prefer interface 1.0 boot keyboard (usually has LED=7).
    candidates = sorted(root.glob("*/0003:1532:*/input/input*"))
    by_name: Dict[str, Path] = {}
    for inp in candidates:
        for suffix in ("numlock", "capslock", "scrolllock"):
            led = Path("/sys/class/leds") / f"{inp.name}::{suffix}"
            bright = led / "brightness"
            if bright.exists() and suffix not in by_name:
                by_name[suffix] = bright
        if len(by_name) == 3:
            break
    out: Dict[int, Path] = {}
    for code, suffix in _LED_SUFFIX.items():
        if suffix in by_name:
            out[code] = by_name[suffix]
    return out


def set_led_brightness(path: Path, on: bool) -> None:
    try:
        path.write_text("1" if on else "0", encoding="ascii")
    except OSError as exc:
        print(f"LED write failed {path}: {exc}", flush=True)


def resolve_uinput_device(user_input: evdev.UInput) -> Optional[evdev.InputDevice]:
    """Return the event InputDevice for a UInput instance (needs read access)."""
    device = getattr(user_input, "device", None)
    if device is not None:
        return device
    name = getattr(user_input, "name", None)
    if not name:
        return None
    # Fallback when UI_GET_SYSNAME / permissions left .device unset.
    try:
        paths = evdev.list_devices()
    except Exception:
        return None
    matches: list[tuple[int, evdev.InputDevice]] = []
    for path in paths:
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.name == name:
            # Prefer highest eventN number (newest).
            try:
                n = int(path.rsplit("event", 1)[-1])
            except ValueError:
                n = -1
            matches.append((n, d))
    if not matches:
        return None
    matches.sort(key=lambda t: t[0], reverse=True)
    return matches[0][1]


async def forward_uinput_leds(
    user_input: evdev.UInput,
    led_paths: Dict[int, Path],
) -> None:
    """
    Read EV_LED events the kernel sends to our uinput device (layout indicator,
    Caps/Num lock, etc.) and mirror them onto the physical keyboard LEDs.
    """
    if not led_paths:
        print("warning: no physical lock LED sysfs nodes found to forward", flush=True)
        return

    device = resolve_uinput_device(user_input)
    if device is None:
        print(
            "warning: cannot open uinput event node for LED read "
            "(need root / input group); Scroll Lock layout LED will not sync",
            flush=True,
        )
        return

    print(
        "LED forward: "
        + ", ".join(
            f"{_LED_SUFFIX[c]}→{p.parent.name}" for c, p in sorted(led_paths.items())
        ),
        flush=True,
    )

    try:
        async for event in device.async_read_loop():
            if event.type != evdev.ecodes.EV_LED:
                continue
            path = led_paths.get(event.code)
            if path is None:
                continue
            set_led_brightness(path, bool(event.value))
    except asyncio.CancelledError:
        raise
