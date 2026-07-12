"""Unit tests for the audio seek/metadata fix.

These focus on pure logic (`_accurate_duration`) and the `_ydl_options()`
format string, so they need neither network access nor a real ffmpeg install:
`_probe_duration` is stubbed out and the `REMUX_FOR_SEEK` toggle is patched
directly on the module.

Runnable under pytest (``env/bin/pytest``) or standalone
(``env/bin/python tests/test_seek_metadata_fix.py``).
"""

from __future__ import annotations

from musicbot.downloader import client

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _patched(*, probed: int | None, remux: bool = True) -> Iterator[None]:
    """Temporarily stub `_probe_duration` and the `REMUX_FOR_SEEK` toggle."""
    original_probe = client._probe_duration
    original_toggle = client.REMUX_FOR_SEEK
    client._probe_duration = lambda _path: probed  # type: ignore[assignment]
    client.REMUX_FOR_SEEK = remux
    try:
        yield
    finally:
        client._probe_duration = original_probe  # type: ignore[assignment]
        client.REMUX_FOR_SEEK = original_toggle


_FIXTURE_PATH = Path('/tmp/does-not-need-to-exist.m4a')


def test_returns_probed_when_extractor_is_zero() -> None:
    with _patched(probed=37):
        assert client._accurate_duration(0, _FIXTURE_PATH) == 37


def test_returns_probed_when_off_by_more_than_tolerance() -> None:
    # Default DURATION_TOLERANCE_SECONDS is 2; a 100 vs 37 gap must correct.
    with _patched(probed=37):
        assert client._accurate_duration(100, _FIXTURE_PATH) == 37


def test_returns_extractor_when_within_tolerance() -> None:
    # 36 vs 37 is within tolerance, so the extractor value is preserved.
    with _patched(probed=37):
        assert client._accurate_duration(36, _FIXTURE_PATH) == 36


def test_returns_extractor_when_path_is_none() -> None:
    with _patched(probed=37):
        assert client._accurate_duration(123, None) == 123


def test_returns_extractor_when_remux_disabled() -> None:
    # When the toggle is off, no probe happens and the extractor value stands.
    with _patched(probed=37, remux=False):
        assert client._accurate_duration(123, _FIXTURE_PATH) == 123


def test_returns_extractor_when_probe_fails() -> None:
    with _patched(probed=None):
        assert client._accurate_duration(50, _FIXTURE_PATH) == 50


def test_ydl_format_contains_new_hls_last_resort_tier() -> None:
    fmt = client._ydl_options()['format']
    assert 'protocol!*=m3u8' in fmt


def test_ydl_format_keeps_original_tiers_in_order() -> None:
    fmt = client._ydl_options()['format']
    tiers = fmt.split('/')
    expected_order = [
        'bestaudio[protocol=http][ext=mp3]',
        'bestaudio[protocol=http]',
        'bestaudio[ext=m4a]',
        'bestaudio[protocol!*=m3u8]',
        'bestaudio',
        'best',
    ]
    assert tiers == expected_order


if __name__ == '__main__':
    import sys
    import traceback

    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith('test_') and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception:  # noqa: BLE001 - standalone runner reports all
            failures += 1
            sys.stdout.write(f'FAIL: {test.__name__}\n')
            traceback.print_exc()
        else:
            sys.stdout.write(f'PASS: {test.__name__}\n')
    sys.stdout.write(f'\n{len(tests) - failures}/{len(tests)} passed\n')
    raise SystemExit(1 if failures else 0)
