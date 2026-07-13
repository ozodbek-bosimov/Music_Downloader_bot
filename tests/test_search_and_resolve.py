"""Unit tests for YouTube Music search mapping and the download strategy.

These need no network: the ytmusicapi client, the SoundCloud fallback, the
``_download`` primitive and the YouTube oEmbed helper are all monkeypatched at
the module boundary.

Runnable under pytest (``env/bin/pytest``) or standalone
(``env/bin/python tests/test_search_and_resolve.py``).
"""

from __future__ import annotations

from musicbot import metrics
from musicbot.downloader import client
from musicbot.downloader.exceptions import DownloadBlockedError, DownloadError

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


class _FakeYTMusic:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = results

    def search(
        self, query: str, filter: str | None = None, limit: int = 0
    ) -> list[dict[str, Any]]:
        return self._results


@contextmanager
def _patch(name: str, value: Any) -> Iterator[None]:
    original = getattr(client, name)
    setattr(client, name, value)
    try:
        yield
    finally:
        setattr(client, name, original)


class _DownloadRecorder:
    """Stands in for ``client._download``, recording targets and simulating
    per-target success/failure."""

    def __init__(self, behavior: Callable[[str], list[tuple[Any, Any]]]) -> None:
        self.calls: list[str] = []
        self._behavior = behavior

    def __call__(
        self, target: str, label: Any = None, cover_url: Any = None
    ) -> list[tuple[Any, Any]]:
        self.calls.append(target)
        return self._behavior(target)


# --- YouTube Music search mapping ------------------------------------------


def test_youtube_music_mapping_skips_and_dedups() -> None:
    raw = [
        {
            'title': 'Song A',
            'artists': [{'name': 'Art1'}, {'name': 'Art2'}],
            'duration_seconds': 200,
            'videoId': 'aaa',
        },
        {'title': 'No Id', 'artists': [{'name': 'X'}]},  # skipped: no videoId
        {'title': 'Dup', 'artists': [{'name': 'Y'}], 'videoId': 'aaa'},  # dedup
        {'title': None, 'artists': [], 'duration_seconds': None, 'videoId': 'ddd'},
    ]
    with _patch('_get_ytmusic', lambda: _FakeYTMusic(raw)):
        results = client._search_youtube_music('anything', 10)

    assert [r['id'] for r in results] == ['aaa', 'ddd']
    first = results[0]
    assert first['title'] == 'Song A'
    assert first['artist'] == 'Art1, Art2'
    assert first['duration'] == 200
    assert first['url'] == 'https://music.youtube.com/watch?v=aaa'
    # Missing title/artist/duration degrade to safe defaults.
    assert results[1]['title'] == 'Unknown'
    assert results[1]['artist'] == 'Unknown'
    assert results[1]['duration'] == 0


def test_search_tracks_falls_back_to_soundcloud() -> None:
    sentinel = [{'id': 'sc1', 'title': 'T', 'artist': 'A', 'duration': 1, 'url': 'u'}]
    # Both YouTube tiers empty -> SoundCloud is used.
    with _patch('_search_youtube_music', lambda q, limit: []), _patch(
        '_search_youtube_ytdlp', lambda q, limit: []
    ), _patch('_search_soundcloud', lambda q, limit: sentinel):
        assert client._search_tracks('q', 5) == sentinel


def test_search_tracks_uses_ytdlp_when_music_empty() -> None:
    sentinel = [{'id': 'v', 'title': 't', 'artist': 'a', 'duration': 1, 'url': 'yt'}]

    def _boom(query: str, limit: int) -> list[dict[str, Any]]:
        raise AssertionError('SoundCloud must not run when yt-dlp search has hits')

    with _patch('_search_youtube_music', lambda q, limit: []), _patch(
        '_search_youtube_ytdlp', lambda q, limit: sentinel
    ), _patch('_search_soundcloud', _boom):
        assert client._search_tracks('q', 5) == sentinel


def test_search_tracks_prefers_youtube_music() -> None:
    yt_results = [
        {'id': 'v', 'title': 't', 'artist': 'a', 'duration': 1, 'url': 'yt'}
    ]

    def _boom(query: str, limit: int) -> list[dict[str, Any]]:
        raise AssertionError('SoundCloud should not be queried when YT Music has hits')

    with _patch('_search_youtube_music', lambda q, limit: yt_results), _patch(
        '_search_soundcloud', _boom
    ):
        assert client._search_tracks('q', 5) == yt_results


# --- Download strategy (YouTube first, SoundCloud fallback) ----------------


def test_resolve_youtube_success_no_fallback() -> None:
    url = 'https://music.youtube.com/watch?v=abc'
    rec = _DownloadRecorder(lambda target: [('song', 'path')])
    with _patch('_download', rec):
        result = client._resolve_and_download(url)

    assert result == [('song', 'path')]
    assert rec.calls == [url]  # SoundCloud never attempted


def test_resolve_youtube_falls_back_to_soundcloud() -> None:
    url = 'https://music.youtube.com/watch?v=abc'

    def behavior(target: str) -> list[tuple[Any, Any]]:
        if target == url:
            raise DownloadBlockedError
        return [('sc-song', 'sc-path')]

    rec = _DownloadRecorder(behavior)
    with _patch('_download', rec), _patch(
        '_youtube_search_query', lambda u: 'Title Artist'
    ):
        result = client._resolve_and_download(url)

    assert result == [('sc-song', 'sc-path')]
    assert rec.calls == [url, 'scsearch1:Title Artist']


def test_resolve_plaintext_ytsearch_then_scsearch() -> None:
    def behavior(target: str) -> list[tuple[Any, Any]]:
        if target.startswith('ytsearch1:'):
            raise DownloadError
        return [('sc-song', 'sc-path')]

    rec = _DownloadRecorder(behavior)
    with _patch('_download', rec):
        result = client._resolve_and_download('hello world')

    assert result == [('sc-song', 'sc-path')]
    assert rec.calls == ['ytsearch1:hello world', 'scsearch1:hello world']


# --- Source metrics (observability) ----------------------------------------


def test_resolve_records_youtube_metric() -> None:
    url = 'https://music.youtube.com/watch?v=abc'
    before = metrics.snapshot().get(metrics.YOUTUBE, 0)
    with _patch('_download', _DownloadRecorder(lambda target: [('s', 'p')])):
        client._resolve_and_download(url)
    assert metrics.snapshot().get(metrics.YOUTUBE, 0) == before + 1


def test_resolve_records_soundcloud_metric_on_fallback() -> None:
    url = 'https://music.youtube.com/watch?v=abc'

    def behavior(target: str) -> list[tuple[Any, Any]]:
        if target == url:
            raise DownloadBlockedError
        return [('s', 'p')]

    before = metrics.snapshot().get(metrics.SOUNDCLOUD, 0)
    with _patch('_download', _DownloadRecorder(behavior)), _patch(
        '_youtube_search_query', lambda u: 'Title Artist'
    ):
        client._resolve_and_download(url)
    assert metrics.snapshot().get(metrics.SOUNDCLOUD, 0) == before + 1


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
