"""Threshold engine unit tests."""

import pytest

from razer_analog_linux.threshold import ThresholdConfig, ThresholdEngine


def test_hysteresis_press_release():
    eng = ThresholdEngine(ThresholdConfig(actuate=128, release=96))
    assert eng.update(1, 50) is None
    assert eng.update(1, 130) is True
    assert eng.update(1, 140) is None
    assert eng.update(1, 100) is None  # inside deadband while down
    assert eng.is_down(1)
    assert eng.update(1, 90) is False
    assert not eng.is_down(1)


def test_invalid_config():
    with pytest.raises(ValueError):
        ThresholdConfig(actuate=50, release=60)
