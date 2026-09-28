"""Analog report parsing."""

from __future__ import annotations

from typing import Dict, Iterable, Set, Tuple


def parse_analog_payload(report: bytes) -> Dict[int, int]:
    """Parse report-id-0x07 payload (up to 11 key/depth pairs) into {key_id: depth}."""
    pressed: Dict[int, int] = {}
    for i in range(0, len(report), 2):
        if i + 1 >= len(report):
            break
        if report[i] == 0 and report[i + 1] == 0:
            break
        key, value = report[i], report[i + 1]
        pressed[key] = value
    return pressed


def with_implicit_releases(
    pressed: Dict[int, int], previous_keys: Set[int]
) -> Tuple[Dict[int, int], Set[int]]:
    """Add depth=0 for keys that disappeared from the active set."""
    out = dict(pressed)
    for key_up in previous_keys - set(pressed.keys()):
        out[key_up] = 0
    return out, set(pressed.keys())


def chunk_hid_reads(buf: bytes, chunk_size: int = 24) -> Iterable[bytes]:
    """Split a hidraw read into fixed-size report chunks (device quirk)."""
    while buf:
        yield buf[:chunk_size]
        buf = buf[chunk_size:]
