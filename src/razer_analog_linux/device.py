"""USB / hidraw discovery and device-mode control."""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

import pyudev

from razer_analog_linux import protocol
from razer_analog_linux.hidraw import HIDRaw
from razer_analog_linux.parser import chunk_hid_reads, parse_analog_payload, with_implicit_releases


def find_keyboard_sysfs(
    product_ids: Set[int] | None = None,
) -> Optional[str]:
    """Return sysfs path of the first matching Razer USB device."""
    products = product_ids or set(protocol.SUPPORTED_PRODUCTS)
    context = pyudev.Context()
    for device in context.list_devices(subsystem="usb", DEVTYPE="usb_device"):
        try:
            vendor = int(device.get("ID_VENDOR_ID") or "0", 16)
            product = int(device.get("ID_MODEL_ID") or "0", 16)
        except ValueError:
            continue
        if vendor == protocol.VENDOR_RAZER and product in products:
            return device.sys_path
    return None


def find_openrazer_device_mode(sysfs_usb: str) -> Optional[Path]:
    """Locate OpenRazer device_mode sysfs under this USB device, if present."""
    root = Path(sysfs_usb)
    matches = list(root.glob("*/0003:1532:*/device_mode"))
    if not matches:
        matches = list(root.glob("*/*/0003:1532:*/device_mode"))
    return matches[0] if matches else None


def openrazer_daemon_running() -> bool:
    """Best-effort check for openrazer-daemon process."""
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().decode(errors="ignore")
            except OSError:
                continue
            if "openrazer-daemon" in cmdline:
                return True
    except OSError:
        pass
    return False


class AnalogKeyboard:
    """Hidraw-backed Razer analog keyboard."""

    def __init__(
        self,
        parent_sysfs: str,
        product_ids: Set[int] | None = None,
        sync_openrazer_sysfs: bool = True,
    ) -> None:
        self.product_ids = product_ids or set(protocol.SUPPORTED_PRODUCTS)
        self.sync_openrazer_sysfs = sync_openrazer_sysfs
        self.report_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.devices: List[io.BufferedReader] = []
        self.context = pyudev.Context()
        self.parent = pyudev.Devices.from_path(self.context, parent_sysfs)
        self.parent_sysfs = parent_sysfs
        self._control: Optional[HIDRaw] = None
        self.open()

    def open(self) -> None:
        self.devices = []
        loop = asyncio.get_event_loop()
        for udev in self.context.list_devices(parent=self.parent, subsystem="hidraw"):
            handle = open(udev.device_node, "rb")
            os.set_blocking(handle.fileno(), False)
            hidraw = HIDRaw(handle)
            info = hidraw.getInfo()
            if info.vendor != protocol.VENDOR_RAZER or info.product not in self.product_ids:
                handle.close()
                continue
            self.devices.append(handle)
            loop.add_reader(handle.fileno(), self._on_readable, handle)
            desc = bytes(hidraw.getRawReportDescriptor())
            if desc == protocol.CONTROL_DESCRIPTOR:
                self.devices[0], self.devices[-1] = self.devices[-1], self.devices[0]
                self._control = HIDRaw(self.devices[0])
        if self.devices and self._control is None:
            self._control = HIDRaw(self.devices[0])

    def close(self) -> None:
        loop = asyncio.get_event_loop()
        for device in self.devices:
            try:
                loop.remove_reader(device.fileno())
            except Exception:
                pass
            device.close()
        self.devices = []
        self._control = None

    def _on_readable(self, device_handle: io.BufferedReader) -> None:
        try:
            buf = device_handle.read(2048)
        except OSError:
            print("hidraw read failed; exiting", file=sys.stderr)
            self.close()
            sys.exit(1)
        if not buf:
            return
        for chunk in chunk_hid_reads(buf):
            if not chunk:
                continue
            rid = chunk[0]
            if rid == 0x04:
                continue
            if rid == 0x07:
                self.report_queue.put_nowait(chunk[1:23])
            # Ignore other report IDs quietly (boot keyboard noise, etc.)

    def razer_command(self, data: bytes) -> bytes:
        if not self._control:
            print("cannot send command, no control interface", file=sys.stderr)
            return b""
        return protocol.razer_command(self._control, data)

    def set_device_mode(self, mode: int) -> None:
        data = protocol.set_device_mode_payload(mode)
        reply = self.razer_command(data)
        if reply and reply[7:11] != data:
            print(f"set_device_mode mismatch want={data!r} got={reply[7:11]!r}", file=sys.stderr)
        if self.sync_openrazer_sysfs:
            path = find_openrazer_device_mode(self.parent_sysfs)
            if path and path.exists():
                try:
                    path.write_bytes(bytes((mode & 0xFF, 0x00)))
                except OSError as exc:
                    print(f"openrazer device_mode sync failed: {exc}", file=sys.stderr)

    async def pressed_stream(
        self, sink: asyncio.Queue[Dict[int, int]]
    ) -> None:
        """Parse analog reports into {key_id: depth} including implicit releases."""
        previous: Set[int] = set()
        while True:
            report = await self.report_queue.get()
            pressed = parse_analog_payload(report)
            pressed, previous = with_implicit_releases(pressed, previous)
            await sink.put(pressed)
