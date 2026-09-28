"""Async daemon orchestration."""

from __future__ import annotations

import asyncio
import atexit
import signal
import sys
from pathlib import Path
from typing import Dict, Optional

from razer_analog_linux.config import AppConfig, resolve_path
from razer_analog_linux.device import AnalogKeyboard, find_openrazer_device_mode, openrazer_daemon_running
from razer_analog_linux.layout import all_key_codes, load_layout_file
from razer_analog_linux.leds import find_physical_led_paths, forward_uinput_leds
from razer_analog_linux.protocol import DEVICE_MODE_DRIVER, DEVICE_MODE_NORMAL
from razer_analog_linux.threshold import ThresholdEngine
from razer_analog_linux.uinput_kb import create_uinput, virtual_keyboard, write_events

# ESC / SPACE on Huntsman Mini/V2 analog reports (seeded layout).
EXIT_KEY_ID = 110
SKIP_KEY_ID = 61  # SPACE — skip current calibrate target (media keys have no analog ID)


def _warn_driver_mode_no_ctrl_c(*, exit_hint: str) -> None:
    print(
        "NOTE: keyboard is entering DRIVER MODE — normal HID (including Ctrl+C from\n"
        "      this keyboard) will NOT reach the terminal until mode is restored.\n"
        f"      {exit_hint}\n"
        "      Or send SIGINT/SIGTERM from another keyboard/terminal "
        "(e.g. kill the process).",
        file=sys.stderr,
        flush=True,
    )


def _read_device_mode_sysfs(sysfs_usb: str) -> Optional[bytes]:
    path = find_openrazer_device_mode(sysfs_usb)
    if path is None or not path.exists():
        return None
    try:
        return path.read_bytes()[:2]
    except OSError:
        return None


def _confirm_driver_mode(kb: AnalogKeyboard) -> None:
    """Explicitly verify / report driver mode after switch."""
    mode = _read_device_mode_sysfs(kb.parent_sysfs)
    if mode is None:
        print(
            "driver mode command sent (OpenRazer device_mode sysfs not readable to confirm)",
            flush=True,
        )
        return
    if mode[0] == DEVICE_MODE_DRIVER:
        print(f"confirmed driver mode via sysfs: {mode.hex()}", flush=True)
    else:
        print(
            f"WARNING: expected device_mode 0x{DEVICE_MODE_DRIVER:02x}, sysfs shows {mode.hex()}",
            file=sys.stderr,
            flush=True,
        )


def _install_stop_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _stop() -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())


def _hotkey_actuated(
    pressed: Dict[int, int],
    engine: ThresholdEngine,
    key_id: int,
) -> bool:
    """Return True if key_id just crossed actuate."""
    if key_id not in pressed:
        return False
    return engine.update(key_id, pressed[key_id]) is True


def _exit_key_actuated(
    pressed: Dict[int, int],
    engine: ThresholdEngine,
    exit_key_id: int = EXIT_KEY_ID,
) -> bool:
    return _hotkey_actuated(pressed, engine, exit_key_id)


def _skip_key_actuated(
    pressed: Dict[int, int],
    engine: ThresholdEngine,
    skip_key_id: int = SKIP_KEY_ID,
) -> bool:
    return _hotkey_actuated(pressed, engine, skip_key_id)


async def run_daemon(cfg: AppConfig, device_sysfs: str) -> None:
    if cfg.require_daemon_stopped and openrazer_daemon_running():
        raise SystemExit(
            "openrazer-daemon is running and require_daemon_stopped=true; "
            "stop it or set openrazer.require_daemon_stopped=false"
        )

    layout_path = resolve_path(cfg.layout_file)
    layout = load_layout_file(layout_path)
    threshold = ThresholdEngine(cfg.threshold)

    pressed_queue: asyncio.Queue[Dict[int, int]] = asyncio.Queue()
    out_queue: asyncio.Queue = asyncio.Queue()

    kb = AnalogKeyboard(
        device_sysfs,
        product_ids=cfg.product_ids,
        sync_openrazer_sysfs=cfg.sync_openrazer_sysfs,
    )
    if not kb.devices:
        kb.close()
        raise SystemExit(f"No matching hidraw interfaces under {device_sysfs}")

    uinput = create_uinput(all_key_codes(layout))
    led_paths = find_physical_led_paths(device_sysfs)

    def shutdown() -> None:
        try:
            kb.set_device_mode(DEVICE_MODE_NORMAL)
        except Exception:
            pass
        try:
            kb.close()
        except Exception:
            pass
        try:
            uinput.close()
        except Exception:
            pass

    atexit.register(shutdown)
    kb.set_device_mode(DEVICE_MODE_DRIVER)
    _confirm_driver_mode(kb)
    if openrazer_daemon_running():
        print("note: openrazer-daemon is running (RGB OK; input owned by this process)")

    # In run mode, keys are injected via uinput so Ctrl+C from this keyboard works again.
    stop = asyncio.Event()
    _install_stop_signals(stop)

    worker_tasks = [
        asyncio.create_task(kb.pressed_stream(pressed_queue), name="pressed_stream"),
        asyncio.create_task(
            virtual_keyboard(
                pressed_queue,
                out_queue,
                layout,
                threshold,
                meta_as_fn=cfg.meta_as_fn,
                repeat_delay_ms=cfg.repeat_delay_ms,
                repeat_rate_ms=cfg.repeat_rate_ms,
            ),
            name="virtual_keyboard",
        ),
        asyncio.create_task(write_events(uinput, out_queue), name="write_events"),
        asyncio.create_task(forward_uinput_leds(uinput, led_paths), name="led_forward"),
    ]
    stop_task = asyncio.create_task(stop.wait(), name="stop")

    try:
        done, pending = await asyncio.wait(
            {*worker_tasks, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        # If a worker crashed, surface the error.
        for t in done:
            if t is stop_task:
                continue
            exc = t.exception()
            if exc is not None:
                raise exc
    except asyncio.CancelledError:
        pass
    finally:
        stop.set()
        for t in (*worker_tasks, stop_task):
            t.cancel()
        await asyncio.gather(*worker_tasks, stop_task, return_exceptions=True)
        shutdown()
        atexit.unregister(shutdown)


async def dump_keys(
    cfg: AppConfig,
    device_sysfs: str,
    *,
    min_depth: int = 1,
) -> None:
    """Print razer key_id + depth until ESC (analog) or external SIGINT/SIGTERM."""
    kb = AnalogKeyboard(
        device_sysfs,
        product_ids=cfg.product_ids,
        sync_openrazer_sysfs=cfg.sync_openrazer_sysfs,
    )
    if not kb.devices:
        kb.close()
        raise SystemExit(f"No matching hidraw interfaces under {device_sysfs}")

    pressed_queue: asyncio.Queue[Dict[int, int]] = asyncio.Queue()
    exit_engine = ThresholdEngine(cfg.threshold)

    def shutdown() -> None:
        try:
            kb.set_device_mode(DEVICE_MODE_NORMAL)
        except Exception:
            pass
        try:
            kb.close()
        except Exception:
            pass

    atexit.register(shutdown)
    _warn_driver_mode_no_ctrl_c(
        exit_hint=f"Press ESC (razer key_id={EXIT_KEY_ID}) past the actuate "
        f"threshold ({cfg.threshold.actuate}) to quit and restore device mode."
    )
    kb.set_device_mode(DEVICE_MODE_DRIVER)
    _confirm_driver_mode(kb)
    print(
        f"dump mode: key_id=N depth=D  |  quit: ESC (id {EXIT_KEY_ID}) or SIGTERM",
        flush=True,
    )

    stop = asyncio.Event()
    _install_stop_signals(stop)
    stream = asyncio.create_task(kb.pressed_stream(pressed_queue))

    try:
        last: Dict[int, int] = {}
        while not stop.is_set():
            get_task = asyncio.create_task(pressed_queue.get())
            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                {get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            if stop_task in done:
                print("\nstopped by signal — restoring device mode", flush=True)
                break
            pressed = get_task.result()
            if _exit_key_actuated(pressed, exit_engine):
                print(
                    f"\nESC (key_id={EXIT_KEY_ID}) actuated — restoring device mode",
                    flush=True,
                )
                break
            for key_id, depth in sorted(pressed.items()):
                if depth < min_depth and last.get(key_id, 0) < min_depth:
                    continue
                if last.get(key_id) == depth:
                    continue
                print(f"key_id={key_id:3d} depth={depth:3d}", flush=True)
                last[key_id] = depth
    finally:
        stream.cancel()
        try:
            await stream
        except asyncio.CancelledError:
            pass
        shutdown()
        atexit.unregister(shutdown)
        mode = _read_device_mode_sysfs(kb.parent_sysfs)
        if mode is not None and mode[0] != DEVICE_MODE_NORMAL:
            print(
                f"WARNING: device_mode still {mode.hex()} after restore attempt",
                file=sys.stderr,
                flush=True,
            )
        elif mode is not None:
            print(f"confirmed device mode restored: {mode.hex()}", flush=True)


async def calibrate_keys(
    cfg: AppConfig,
    device_sysfs: str,
    layout_path: Path,
    targets: Optional[list[str]] = None,
) -> None:
    """Interactively map unmapped KEY names to Razer key IDs."""
    from razer_analog_linux.layout import (
        load_layout_file,
        mapped_razer_ids,
        save_plain_mapping,
        skip_unmapped_target,
        unmapped_targets,
    )

    kb = AnalogKeyboard(
        device_sysfs,
        product_ids=cfg.product_ids,
        sync_openrazer_sysfs=cfg.sync_openrazer_sysfs,
    )
    if not kb.devices:
        kb.close()
        raise SystemExit(f"No matching hidraw interfaces under {device_sysfs}")

    engine = ThresholdEngine(cfg.threshold)
    exit_engine = ThresholdEngine(cfg.threshold)
    skip_engine = ThresholdEngine(cfg.threshold)
    wanted = targets if targets is not None else unmapped_targets(layout_path)
    if not wanted:
        print("nothing to calibrate — _unmapped_targets is empty")
        kb.close()
        return

    pressed_queue: asyncio.Queue[Dict[int, int]] = asyncio.Queue()

    def shutdown() -> None:
        try:
            kb.set_device_mode(DEVICE_MODE_NORMAL)
        except Exception:
            pass
        try:
            kb.close()
        except Exception:
            pass

    atexit.register(shutdown)
    _warn_driver_mode_no_ctrl_c(
        exit_hint=(
            f"SPACE (key_id={SKIP_KEY_ID}) skips the current target; "
            f"ESC (key_id={EXIT_KEY_ID}) aborts and restores device mode."
        )
    )
    kb.set_device_mode(DEVICE_MODE_DRIVER)
    _confirm_driver_mode(kb)
    stream = asyncio.create_task(kb.pressed_stream(pressed_queue))
    stop = asyncio.Event()
    _install_stop_signals(stop)

    print(
        f"calibrate: actuate>{cfg.threshold.actuate} release<{cfg.threshold.release}\n"
        f"writing to {layout_path}\n"
        f"controls: SPACE=skip current  ESC=abort  (or SIGTERM)\n"
        f"note: dedicated media keys / volume dial are NOT analog optical switches;\n"
        f"      they do not appear on report 0x07 — use SPACE to skip MUTE/VOLUME/…",
        flush=True,
    )

    aborted = False
    try:
        for name in wanted:
            if stop.is_set():
                aborted = True
                break
            layout = load_layout_file(layout_path)
            known = mapped_razer_ids(layout)
            print(
                f"\n>>> Press and fully hold the physical key for KEY_{name} …\n"
                f"    SPACE=skip (no analog event expected for media/dial)  ESC=abort",
                flush=True,
            )
            assigned = None
            skipped = False
            while assigned is None and not skipped and not stop.is_set():
                get_task = asyncio.create_task(pressed_queue.get())
                stop_task = asyncio.create_task(stop.wait())
                done, pending = await asyncio.wait(
                    {get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
                if stop_task in done:
                    aborted = True
                    break
                pressed = get_task.result()

                if _exit_key_actuated(pressed, exit_engine):
                    print(
                        f"\nESC (key_id={EXIT_KEY_ID}) — aborting calibration",
                        flush=True,
                    )
                    aborted = True
                    break

                if _skip_key_actuated(pressed, skip_engine):
                    skip_unmapped_target(
                        layout_path,
                        name,
                        reason=(
                            "skipped during calibrate (no analog report — "
                            "typical for dedicated media keys / dial)"
                        ),
                    )
                    print(
                        f"  skipped KEY_{name} (SPACE) — removed from _unmapped_targets",
                        flush=True,
                    )
                    skipped = True
                    # Wait for SPACE release so it doesn't skip the next target too.
                    while skip_engine.is_down(SKIP_KEY_ID) and not stop.is_set():
                        pressed = await pressed_queue.get()
                        if _exit_key_actuated(pressed, exit_engine):
                            aborted = True
                            break
                        for key_id, depth in pressed.items():
                            skip_engine.update(key_id, depth)
                            engine.update(key_id, depth)
                    break

                for key_id, depth in pressed.items():
                    if key_id in (EXIT_KEY_ID, SKIP_KEY_ID):
                        continue
                    edge = engine.update(key_id, depth)
                    if edge is True and key_id not in known:
                        assigned = key_id
                        break
                    if edge is True and key_id in known:
                        print(
                            f"  (key_id={key_id} already mapped — "
                            f"use a different key, SPACE to skip, or edit JSON)",
                            flush=True,
                        )

            if aborted or stop.is_set():
                break
            if skipped:
                continue
            if assigned is None:
                break

            save_plain_mapping(layout_path, assigned, name)
            print(f"  saved key_id={assigned} → KEY_{name}", flush=True)
            while engine.is_down(assigned) and not stop.is_set():
                get_task = asyncio.create_task(pressed_queue.get())
                stop_task = asyncio.create_task(stop.wait())
                done, pending = await asyncio.wait(
                    {get_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
                if stop_task in done:
                    aborted = True
                    break
                pressed = get_task.result()
                if _exit_key_actuated(pressed, exit_engine):
                    aborted = True
                    break
                for key_id, depth in pressed.items():
                    engine.update(key_id, depth)
                    skip_engine.update(key_id, depth)

        if aborted:
            print("\ncalibration aborted — partial mappings kept", flush=True)
        else:
            print("\ncalibration complete", flush=True)
    finally:
        stream.cancel()
        try:
            await stream
        except asyncio.CancelledError:
            pass
        shutdown()
        atexit.unregister(shutdown)
        mode = _read_device_mode_sysfs(kb.parent_sysfs)
        if mode is not None and mode[0] != DEVICE_MODE_NORMAL:
            print(
                f"WARNING: device_mode still {mode.hex()} after restore attempt",
                file=sys.stderr,
                flush=True,
            )
        elif mode is not None:
            print(f"confirmed device mode restored: {mode.hex()}", flush=True)
