"""Virtual keyboard via uinput."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Iterable, List, Tuple

import evdev

from razer_analog_linux.layout import all_key_codes, get_active_layer
from razer_analog_linux.threshold import ThresholdEngine


def create_uinput(
    key_codes: Iterable[int],
    name: str = "Razer Huntsman V2 Analog (linux-analog)",
) -> evdev.UInput:
    """Create a virtual keyboard that also accepts lock-LED updates from the compositor."""
    codes = list(key_codes)
    led_codes = [
        evdev.ecodes.LED_NUML,
        evdev.ecodes.LED_CAPSL,
        evdev.ecodes.LED_SCROLLL,
    ]
    return evdev.UInput(
        {
            evdev.ecodes.EV_KEY: codes,
            evdev.ecodes.EV_LED: led_codes,
        },
        name=name,
    )


async def write_events(
    user_input: evdev.UInput,
    queue: asyncio.Queue[Tuple[int, int, int]],
) -> None:
    while True:
        etype, code, value = await queue.get()
        user_input.write(etype, code, value)
        user_input.syn()


async def virtual_keyboard(
    pressed_queue: asyncio.Queue[Dict[int, int]],
    out_queue: asyncio.Queue[Tuple[int, int, int]],
    layout: Dict[str, Dict[int, int]],
    threshold: ThresholdEngine,
    *,
    meta_as_fn: bool = False,
    repeat_delay_ms: int = 200,
    repeat_rate_ms: int = 30,
    log_unmapped: bool = True,
) -> None:
    """Convert analog depths into EV_KEY press/release/repeat."""
    repeat_until: Dict[int, float] = {}
    logged_unmapped: set[int] = set()
    fn_id = None
    meta_id = None
    fn_code = evdev.ecodes.ecodes.get("KEY_FN")
    meta_code = evdev.ecodes.ecodes.get("KEY_LEFTMETA")
    for rid, code in layout.get("plain", {}).items():
        if fn_code is not None and code == fn_code:
            fn_id = rid
        if meta_code is not None and code == meta_code:
            meta_id = rid

    while True:
        try:
            pressed = pressed_queue.get_nowait()
        except asyncio.QueueEmpty:
            await asyncio.sleep(repeat_rate_ms / 1000.0)
            now = time.monotonic()
            for code, until in list(repeat_until.items()):
                if now > until:
                    await out_queue.put((evdev.ecodes.EV_KEY, code, 2))
                    repeat_until[code] = now + (repeat_rate_ms / 1000.0)
            continue

        fn_pressed = bool(fn_id is not None and threshold.is_down(fn_id))
        meta_pressed = bool(meta_id is not None and threshold.is_down(meta_id))
        # Update threshold state first so modifier detection is current.
        edges: List[Tuple[int, bool | None, int]] = []
        for key_id, depth in pressed.items():
            edge = threshold.update(key_id, depth)
            edges.append((key_id, edge, depth))

        fn_pressed = bool(fn_id is not None and threshold.is_down(fn_id))
        meta_pressed = bool(meta_id is not None and threshold.is_down(meta_id))
        active = get_active_layer(layout, fn_pressed, meta_as_fn, meta_pressed)

        for key_id, edge, depth in edges:
            if key_id not in active:
                if log_unmapped and depth > 0 and key_id not in logged_unmapped:
                    print(f"unmapped razer key_id={key_id} depth={depth}")
                    logged_unmapped.add(key_id)
                continue
            code = active[key_id]
            if edge is True:
                if code not in repeat_until:
                    repeat_until[code] = time.monotonic() + (repeat_delay_ms / 1000.0)
                    await out_queue.put((evdev.ecodes.EV_KEY, code, 1))
            elif edge is False:
                if code in repeat_until:
                    del repeat_until[code]
                    await out_queue.put((evdev.ecodes.EV_KEY, code, 0))
