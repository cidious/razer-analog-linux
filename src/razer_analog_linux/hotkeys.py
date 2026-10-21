"""Optional key bindings that run shell commands (bypass compositor shortcuts)."""

from __future__ import annotations

import os
import pwd
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

import evdev


@dataclass(frozen=True)
class HotkeyBinding:
    """Run ``command`` when ``key`` actuates (optionally with Shift held)."""

    key: str
    command: str
    shift: bool = False
    consume: bool = True  # if True, do not emit the trigger key via uinput

    def key_code(self) -> int:
        name = self.key if self.key.startswith("KEY_") else f"KEY_{self.key}"
        if name not in evdev.ecodes.ecodes:
            raise KeyError(f"unknown hotkey key: {self.key}")
        return int(evdev.ecodes.ecodes[name])


_MODIFIER_NAMES = (
    "LEFTSHIFT",
    "RIGHTSHIFT",
    "LEFTCTRL",
    "RIGHTCTRL",
    "LEFTALT",
    "RIGHTALT",
    "LEFTMETA",
    "RIGHTMETA",
    "CAPSLOCK",
)


def modifier_key_codes() -> Set[int]:
    codes: Set[int] = set()
    for name in _MODIFIER_NAMES:
        full = f"KEY_{name}"
        if full in evdev.ecodes.ecodes:
            codes.add(int(evdev.ecodes.ecodes[full]))
    return codes


def no_repeat_key_codes() -> Set[int]:
    """Keys that should not auto-repeat (modifiers, locks, Pause, media, …)."""
    names = (
        *_MODIFIER_NAMES,
        "PAUSE",
        "BREAK",
        "SYSRQ",
        "SCROLLLOCK",
        "NUMLOCK",
        "COMPOSE",
        "FN",
        "MUTE",
        "VOLUMEUP",
        "VOLUMEDOWN",
        "PREVIOUSSONG",
        "PLAYPAUSE",
        "NEXTSONG",
        "STOPCD",
    )
    codes: Set[int] = set()
    for name in names:
        full = f"KEY_{name}"
        if full in evdev.ecodes.ecodes:
            codes.add(int(evdev.ecodes.ecodes[full]))
    return codes


def match_hotkey(
    bindings: Sequence[HotkeyBinding],
    key_code: int,
    *,
    shift_down: bool,
) -> Optional[HotkeyBinding]:
    """Return the best matching binding for a key press, or None."""
    # Prefer the more specific Shift+Key binding when Shift is held.
    candidates = [b for b in bindings if b.key_code() == key_code]
    if not candidates:
        return None
    if shift_down:
        for b in candidates:
            if b.shift:
                return b
        return None
    for b in candidates:
        if not b.shift:
            return b
    return None


def _session_env() -> dict:
    env = os.environ.copy()
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        try:
            pw = pwd.getpwnam(sudo_user)
        except KeyError:
            pw = None
        if pw is not None:
            env.setdefault("HOME", pw.pw_dir)
            env.setdefault("USER", sudo_user)
            env.setdefault("LOGNAME", sudo_user)
            xa = Path(pw.pw_dir) / ".Xauthority"
            if xa.is_file():
                env["XAUTHORITY"] = str(xa)
    env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    return env


def run_user_command(command: str) -> None:
    """
    Spawn ``command`` in the graphical session user's environment.

    When the daemon runs under sudo, drop to ``SUDO_USER`` so xdotool/xsel work.
    """
    env = _session_env()
    sudo_user = os.environ.get("SUDO_USER")
    try:
        if os.geteuid() == 0 and sudo_user and sudo_user != "root":
            subprocess.Popen(
                ["sudo", "-u", sudo_user, "-E", "bash", "-lc", command],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            subprocess.Popen(
                ["bash", "-lc", command],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        print(f"hotkey command failed to start: {command!r}: {exc}", flush=True)


def expand_command_path(command: str) -> str:
    """Expand ~ / $HOME, preferring SUDO_USER's home when running under sudo."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            home = pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            home = None
        if home:
            command = command.replace("${HOME}", home).replace("$HOME", home)
    return os.path.expanduser(os.path.expandvars(command))


def parse_hotkeys(entries: Iterable[dict]) -> List[HotkeyBinding]:
    out: List[HotkeyBinding] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        command = str(raw.get("command") or "").strip()
        if not key or not command:
            continue
        binding = HotkeyBinding(
            key=key.removeprefix("KEY_"),
            command=expand_command_path(command),
            shift=bool(raw.get("shift", False)),
            consume=bool(raw.get("consume", True)),
        )
        # Validate key name early.
        binding.key_code()
        out.append(binding)
    return out
