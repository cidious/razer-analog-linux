"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from razer_analog_linux import __version__
from razer_analog_linux.config import load_config, resolve_path
from razer_analog_linux.daemon import calibrate_keys, dump_keys, run_daemon
from razer_analog_linux.device import find_keyboard_sysfs
from razer_analog_linux.threshold import ThresholdConfig


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config",
        default=None,
        help="Path to config TOML (default: config/default.toml)",
    )
    p.add_argument(
        "--device",
        default=None,
        help="USB device sysfs path (parent of hidraw interfaces)",
    )
    p.add_argument("--actuate", type=int, default=None, help="Override actuate threshold 0-255")
    p.add_argument("--release", type=int, default=None, help="Override release threshold 0-255")


def _resolve(args: argparse.Namespace):
    cfg = load_config(args.config)
    sysfs = args.device or cfg.sysfs_path or find_keyboard_sysfs(cfg.product_ids)
    if not sysfs:
        raise SystemExit(
            "No device specified and auto-detect failed. Pass --device /sys/devices/.../usbX/Y-Z"
        )
    if args.actuate is not None:
        cfg.threshold.actuate = args.actuate
    if args.release is not None:
        cfg.threshold.release = args.release
    cfg.threshold = ThresholdConfig(cfg.threshold.actuate, cfg.threshold.release)
    return cfg, sysfs


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="razer-analog-linux",
        description="Razer Huntsman V2 Analog — driver mode + tunable actuation",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Enter driver mode and inject keypresses")
    _add_common(run_p)

    dump_p = sub.add_parser("dump", help="Print raw key_id/depth (no key injection)")
    _add_common(dump_p)

    cal = sub.add_parser("calibrate", help="Interactively map missing keys into layout JSON")
    _add_common(cal)
    cal.add_argument(
        "--layout",
        default=None,
        help="Layout JSON to update (default from config)",
    )
    cal.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Only calibrate these KEY names (e.g. F1 F2 LEFT)",
    )

    find_p = sub.add_parser("find-device", help="Print auto-detected USB sysfs path")
    find_p.add_argument("--config", default=None, help="Path to config TOML")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.cmd == "find-device":
        cfg = load_config(args.config)
        path = find_keyboard_sysfs(cfg.product_ids)
        if not path:
            print("not found", file=sys.stderr)
            sys.exit(1)
        print(path)
        return

    cfg, sysfs = _resolve(args)

    if args.cmd == "run":
        print(f"device={sysfs} actuate={cfg.threshold.actuate} release={cfg.threshold.release}")
        asyncio.run(run_daemon(cfg, sysfs))
    elif args.cmd == "dump":
        asyncio.run(dump_keys(cfg, sysfs))
    elif args.cmd == "calibrate":
        layout = resolve_path(args.layout or cfg.layout_file)
        asyncio.run(calibrate_keys(cfg, sysfs, Path(layout), targets=args.only))
    else:
        raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    main()
