"""Razer HID feature-report protocol helpers."""

from __future__ import annotations

import struct

from razer_analog_linux.hidraw import HIDRaw

# Known analog keyboards
PRODUCT_HUNTSMAN_MINI_ANALOG = 0x0282
PRODUCT_HUNTSMAN_V2_ANALOG = 0x0266
VENDOR_RAZER = 0x1532

SUPPORTED_PRODUCTS = frozenset(
    {PRODUCT_HUNTSMAN_MINI_ANALOG, PRODUCT_HUNTSMAN_V2_ANALOG}
)

# Control-interface HID report descriptor (identical on Mini + V2 Analog)
CONTROL_DESCRIPTOR = bytes(
    [5, 12, 9, 1, 161, 1, 6, 0, 255, 9, 2, 21, 0, 37, 1, 117, 8, 149, 90, 177, 1, 192]
)

# Keyboard + analog input descriptor (identical on Mini + V2 Analog)
ANALOG_KEYBOARD_DESCRIPTOR = bytes(
    [
        5,
        1,
        9,
        6,
        161,
        1,
        133,
        1,
        5,
        7,
        5,
        7,
        25,
        224,
        41,
        231,
        21,
        0,
        37,
        1,
        117,
        1,
        149,
        8,
        129,
        2,
        25,
        0,
        41,
        160,
        21,
        0,
        37,
        1,
        117,
        1,
        149,
        160,
        129,
        2,
        117,
        8,
        149,
        2,
        129,
        1,
        5,
        8,
        25,
        1,
        41,
        3,
        21,
        0,
        37,
        1,
        117,
        1,
        149,
        3,
        145,
        2,
        149,
        5,
        145,
        1,
        192,
        5,
        12,
        9,
        1,
        161,
        1,
        133,
        2,
        25,
        0,
        42,
        60,
        2,
        21,
        0,
        38,
        60,
        2,
        149,
        1,
        117,
        16,
        129,
        0,
        117,
        8,
        149,
        21,
        129,
        1,
        192,
        5,
        1,
        9,
        128,
        161,
        1,
        133,
        3,
        25,
        129,
        41,
        131,
        21,
        0,
        37,
        1,
        117,
        1,
        149,
        3,
        129,
        2,
        149,
        5,
        129,
        1,
        117,
        8,
        149,
        22,
        129,
        1,
        192,
        5,
        1,
        9,
        0,
        161,
        1,
        133,
        4,
        9,
        3,
        21,
        0,
        38,
        255,
        0,
        53,
        0,
        70,
        255,
        0,
        117,
        8,
        149,
        23,
        129,
        0,
        192,
        5,
        1,
        9,
        0,
        161,
        1,
        133,
        5,
        9,
        3,
        21,
        0,
        38,
        255,
        0,
        53,
        0,
        70,
        255,
        0,
        117,
        8,
        149,
        23,
        129,
        0,
        192,
        5,
        1,
        9,
        0,
        161,
        1,
        133,
        7,
        9,
        3,
        21,
        0,
        38,
        255,
        0,
        53,
        0,
        70,
        255,
        0,
        117,
        8,
        149,
        23,
        129,
        0,
        192,
    ]
)

DEVICE_MODE_DRIVER = 3
DEVICE_MODE_NORMAL = 0


def razer_crc(buf: bytes) -> int:
    """XOR of bytes 2..85 (Razer 90-byte report)."""
    result = 0
    for i in range(2, 86):
        result ^= buf[i]
    return result


def build_feature_report(data: bytes, transaction_id: int = 0x1F) -> bytes:
    """Build a 90-byte Razer feature report (without report-id byte)."""
    send_report = struct.pack(
        ">BBHBB",
        0x00,  # status
        transaction_id,
        0x00,  # remaining_packets
        0x00,  # protocol_type
        len(data) - 2,  # size
    )
    send_report += data
    send_report += b"\x00" * (82 - len(data))
    send_report += bytes([razer_crc(send_report)])
    send_report += b"\x00"
    return send_report


def razer_command(hidraw: HIDRaw, data: bytes, transaction_id: int = 0x1F) -> bytes:
    """Send a Razer command and return the feature-report reply."""
    send_report = build_feature_report(data, transaction_id=transaction_id)
    hidraw.sendFeatureReport(send_report)
    received = hidraw.getFeatureReport(0, 90)
    if received[1] != 0x02:  # SUCCESS status in reply layout used by prior art
        # Note: reply[0] is report id; status often at [1] in this stack's convention.
        pass
    return bytes(received)


def set_device_mode_payload(mode: int) -> bytes:
    return b"\x00\x04" + bytes((mode & 0xFF, 0x00))
