"""Tests for hotkey matching / parsing."""

from __future__ import annotations

import evdev

from razer_analog_linux.hotkeys import HotkeyBinding, match_hotkey, parse_hotkeys


def test_match_prefers_shift_binding_when_shift_down() -> None:
    pause = HotkeyBinding(key="PAUSE", command="a")
    shift_pause = HotkeyBinding(key="PAUSE", command="b", shift=True)
    code = int(evdev.ecodes.KEY_PAUSE)
    assert match_hotkey([pause, shift_pause], code, shift_down=True) is shift_pause
    assert match_hotkey([pause, shift_pause], code, shift_down=False) is pause


def test_match_none_when_shift_required_but_missing() -> None:
    shift_pause = HotkeyBinding(key="PAUSE", command="b", shift=True)
    code = int(evdev.ecodes.KEY_PAUSE)
    assert match_hotkey([shift_pause], code, shift_down=False) is None


def test_parse_hotkeys_expands_and_validates() -> None:
    bindings = parse_hotkeys(
        [
            {"key": "PAUSE", "command": "$HOME/bin/layout_changing_previous.sh"},
            {
                "key": "KEY_PAUSE",
                "shift": True,
                "command": "$HOME/bin/layout_changing_selected.sh",
            },
            {"key": "PAUSE", "command": ""},  # skipped
        ]
    )
    assert len(bindings) == 2
    assert bindings[0].key == "PAUSE"
    assert bindings[0].shift is False
    assert bindings[1].shift is True
    assert bindings[0].command.endswith("layout_changing_previous.sh")
