"""Actuation hysteresis state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class ThresholdConfig:
    actuate: int = 128
    release: int = 96

    def __post_init__(self) -> None:
        if not 0 <= self.release < self.actuate <= 255:
            raise ValueError(
                f"require 0 <= release < actuate <= 255, got "
                f"release={self.release} actuate={self.actuate}"
            )


class ThresholdEngine:
    """Per-key press/release with hysteresis."""

    def __init__(self, config: ThresholdConfig | None = None) -> None:
        self.config = config or ThresholdConfig()
        self._down: Dict[int, bool] = {}

    def update(self, key_id: int, depth: int) -> bool | None:
        """
        Feed a depth sample.

        Returns True on press edge, False on release edge, None if unchanged.
        """
        was = self._down.get(key_id, False)
        if depth < self.config.release:
            self._down[key_id] = False
            if was:
                return False
            return None
        if depth > self.config.actuate:
            self._down[key_id] = True
            if not was:
                return True
            return None
        return None

    def is_down(self, key_id: int) -> bool:
        return self._down.get(key_id, False)

    def reset(self) -> None:
        self._down.clear()
