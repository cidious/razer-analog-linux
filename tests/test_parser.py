"""Parser unit tests."""

from razer_analog_linux.parser import parse_analog_payload, with_implicit_releases


def test_parse_pairs():
    payload = bytes([10, 200, 11, 50, 0, 0, 0, 0])
    assert parse_analog_payload(payload) == {10: 200, 11: 50}


def test_implicit_release():
    pressed, prev = with_implicit_releases({1: 10}, {1, 2})
    assert pressed[2] == 0
    assert prev == {1}
