from __future__ import annotations

import yt_dlp

from musicbot import metrics
from musicbot.config import (
    CONVERT_TO_MP3,
    DURATION_TOLERANCE_SECONDS,
    FFMPEG_LOCATION,
    MAX_AUDIO_FILESIZE,
    MAX_PARALLEL_DOWNLOADS,
    POT_PROVIDER_BASE_URL,
    REMUX_FOR_SEEK,
    SOUNDCLOUD_FALLBACK,
    TRACKS_PATH,
    YTDLP_COOKIEFILE,
    YTDLP_PLAYER_CLIENTS,
)
from musicbot.downloader.exceptions import (
    DownloadBlockedError,
    DownloadError,
    DRMProtectedError,
    TrackTooLargeError,
    UnsupportedSpotifyLinkError,
    VideoUnavailableError,
)

from .models import Song

from asyncio import Semaphore
from contextlib import suppress
from html import unescape
from pathlib import Path
from typing import Any
import asyncio
import json
import logging
import os
import re
import socket
import subprocess
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_download_semaphore = Semaphore(MAX_PARALLEL_DOWNLOADS)

# Spotify serves server-rendered metadata (Open Graph tags) to simple,
# bot-like user agents, but a full browser UA gets a JavaScript app shell with
# no metadata. So we deliberately use a minimal user agent here.
_USER_AGENT = 'Mozilla/5.0'


def _ydl_options() -> dict[str, Any]:
    # Best available audio-only stream. Prefer m4a (no transcoding needed), but
    # fall back to any audio format — some videos don't offer m4a at all.
    options: dict[str, Any] = {
        # Prefer direct HTTP streams (proper seek support) over HLS (m3u8)
        # which lacks seek metadata and breaks fast-forward/rewind in players.
        'format': 'bestaudio[protocol=http][ext=mp3]/bestaudio[protocol=http]/bestaudio[ext=m4a]/bestaudio[protocol!*=m3u8]/bestaudio/best',
        'outtmpl': str(TRACKS_PATH / '%(title).200B.%(ext)s'),
        'restrictfilenames': True,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'noplaylist': True,
        'ignoreerrors': False,
        # Reject anything bigger than Telegram's upload limit.
        'max_filesize': MAX_AUDIO_FILESIZE,
    }

    if YTDLP_PLAYER_CLIENTS:
        options['extractor_args'] = {'youtube': {'player_client': YTDLP_PLAYER_CLIENTS}}

    if POT_PROVIDER_BASE_URL:
        # Point the bgutil PO-token plugin at a non-default provider URL. With
        # the default local server, no config is needed (the plugin finds it).
        extractor_args = options.setdefault('extractor_args', {})
        extractor_args['youtubepot-bgutil'] = {'base_url': POT_PROVIDER_BASE_URL}

    if CONVERT_TO_MP3:
        options['postprocessors'] = [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }
        ]

    if FFMPEG_LOCATION:
        options['ffmpeg_location'] = FFMPEG_LOCATION

    if YTDLP_COOKIEFILE:
        options['cookiefile'] = YTDLP_COOKIEFILE

    return options


# The bgutil plugin's default provider address when POT_PROVIDER_BASE_URL is unset.
_DEFAULT_POT_BASE_URL = 'http://127.0.0.1:4416'


def pot_provider_reachable() -> bool:
    """Best-effort TCP check that the PO-token provider is accepting connections.

    Used by /stats to reveal whether cookieless YouTube downloads can work; a
    down provider means the bot is degrading to the SoundCloud fallback.
    """
    base = POT_PROVIDER_BASE_URL or _DEFAULT_POT_BASE_URL
    parsed = urllib.parse.urlparse(base)
    host = parsed.hostname or '127.0.0.1'
    port = parsed.port or 4416
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


# MP4-family containers whose seekability depends on a leading 'moov' atom.
# Only these are worth remuxing for faststart; everything else is left alone.
_MP4_FAMILY_SUFFIXES = frozenset({'.m4a', '.mp4', '.mov', '.m4b'})

# Cache whether ffmpeg is usable so a missing binary isn't retried per file.
# None = not yet checked, True/False = last known result.
_ffmpeg_available: bool | None = None


def _ffmpeg_binary(name: str) -> str:
    """Resolve an ffmpeg tool ('ffmpeg'/'ffprobe') honouring FFMPEG_LOCATION.

    FFMPEG_LOCATION may be a directory holding the binaries or an explicit path
    to a binary; when unset we fall back to the bare name (resolved via PATH).
    """
    if FFMPEG_LOCATION:
        location = Path(FFMPEG_LOCATION)
        if location.is_dir():
            return str(location / name)
        # An explicit binary path: use its directory for the sibling tool
        # (e.g. FFMPEG_LOCATION points at .../ffmpeg, we want .../ffprobe too).
        if location.name in ('ffmpeg', 'ffprobe'):
            return str(location.parent / name)
        return str(location)
    return name


def _remux_for_faststart(path: Path) -> Path:
    """Rewrite an MP4-family file with its 'moov' atom first (+faststart).

    Best-effort and lossless (`-c copy`, no re-encode). Non-MP4-family files
    are returned immediately, untouched. Any failure (missing binary, non-zero
    exit, timeout, empty output) returns the original path so today's behaviour
    is preserved.
    """
    global _ffmpeg_available

    if path.suffix.lower() not in _MP4_FAMILY_SUFFIXES:
        return path

    if _ffmpeg_available is False:
        return path

    tmp_path = path.with_name(f'{path.stem}.faststart{path.suffix}')
    try:
        result = subprocess.run(
            [
                _ffmpeg_binary('ffmpeg'),
                '-y',
                '-loglevel', 'error',
                '-i', str(path),
                '-c', 'copy',
                '-map', '0:a',
                '-movflags', '+faststart',
                str(tmp_path),
            ],
            capture_output=True,
            timeout=60,
        )
    except FileNotFoundError:
        # ffmpeg isn't installed/reachable; don't retry on the next file.
        _ffmpeg_available = False
        return path
    except (subprocess.TimeoutExpired, OSError):
        _cleanup_temp(tmp_path)
        return path

    _ffmpeg_available = True

    if result.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
        _cleanup_temp(tmp_path)
        return path

    try:
        os.replace(tmp_path, path)
    except OSError:
        _cleanup_temp(tmp_path)
        return path

    return path


def _cleanup_temp(tmp_path: Path) -> None:
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _probe_duration(path: Path) -> int | None:
    """Measure a file's real duration (seconds) via ffprobe.

    Returns None on any failure (missing binary, non-zero exit, unparsable
    output, timeout).
    """
    global _ffmpeg_available

    if _ffmpeg_available is False:
        return None

    try:
        result = subprocess.run(
            [
                _ffmpeg_binary('ffprobe'),
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        _ffmpeg_available = False
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        return int(round(float(result.stdout.strip())))
    except (TypeError, ValueError):
        return None


def _accurate_duration(extractor_duration: int, path: Path | None) -> int:
    """Return the most trustworthy duration for a downloaded file.

    Keeps the extractor's value unless a probe of the real file disagrees:
    when the extractor value is missing/zero or off by more than
    DURATION_TOLERANCE_SECONDS, the probed value wins.
    """
    if path is None or not REMUX_FOR_SEEK:
        return extractor_duration

    probed = _probe_duration(path)
    if probed is None:
        return extractor_duration

    if extractor_duration <= 0 or abs(extractor_duration - probed) > DURATION_TOLERANCE_SECONDS:
        return probed

    return extractor_duration


def _http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode('utf-8', 'ignore')


def _meta_tag(html: str, prop: str) -> str | None:
    match = re.search(
        r'<meta[^>]*\bproperty=["\']'
        + re.escape(prop)
        + r'["\'][^>]*\bcontent=["\']([^"\']*)["\']',
        html,
    )
    return unescape(match.group(1)) if match else None


def _spotify_track(url: str) -> tuple[str, Song, str | None]:
    """Resolve a Spotify *track* URL into a YouTube search query, a clean
    ``Song`` label and the real Spotify cover URL.

    We read the page's Open Graph tags (and fall back to Spotify's public
    oEmbed endpoint) — no Spotify API credentials needed. Albums and playlists
    are intentionally not expanded.
    """
    if '/track/' not in url and ':track:' not in url:
        raise UnsupportedSpotifyLinkError

    title: str | None = None
    artist = ''
    cover_url: str | None = None

    # 1) Scrape Open Graph tags — gives the title, artist(s) and cover image.
    try:
        html = _http_get(url)
        title = _meta_tag(html, 'og:title')
        description = _meta_tag(html, 'og:description')
        cover_url = _meta_tag(html, 'og:image')
        if description:
            # description looks like: "Artist1 · Artist2 · Song · 2026"
            artist = description.split(' · ')[0].strip()
    except Exception:
        pass

    # 2) Fallback: the oEmbed endpoint reliably returns the title and a cover.
    if not title or not cover_url:
        try:
            data = json.loads(_http_get(f'https://open.spotify.com/oembed?url={url}'))
            title = title or data.get('title')
            cover_url = cover_url or data.get('thumbnail_url')
        except Exception:
            pass

    if not title:
        raise UnsupportedSpotifyLinkError

    # Spotify's og:image is 640x640; Telegram thumbnails must be <=320px. The
    # size is encoded in the URL, so swap it for the 300px variant.
    if cover_url:
        cover_url = cover_url.replace('ab67616d0000b273', 'ab67616d00001e02')

    search_query = f'{title} {artist}'.strip()
    return search_query, Song(name=title, artist=artist), cover_url


def _is_youtube_link(query: str) -> bool:
    return 'youtube.com' in query or 'youtu.be' in query


def _youtube_search_query(url: str) -> str | None:
    """Read a YouTube link's title + author via the public oEmbed endpoint.

    oEmbed isn't bot-checked, so we can then fetch the track through the SEARCH
    path (``ytsearch1:``), which YouTube blocks far less than direct extraction.
    """
    try:
        encoded = urllib.parse.quote(url, safe='')
        data = json.loads(_http_get(f'https://www.youtube.com/oembed?url={encoded}'))
    except Exception:
        return None

    title = data.get('title')
    if not title:
        return None

    author = data.get('author_name') or ''
    return f'{title} {author}'.strip()


def _is_spotify_link(query: str) -> bool:
    return 'spotify.com' in query or query.startswith('spotify:')


def _downloaded_path(item: dict[str, Any]) -> Path | None:
    downloads = item.get('requested_downloads')
    if downloads:
        filepath = downloads[0].get('filepath')
        if filepath:
            path = Path(filepath)
            if path.exists():
                return path
    return None


def _download_image(url: str, name: str) -> Path | None:
    path = TRACKS_PATH / f'{name}.jpg'
    try:
        request = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = response.read()
        path.write_bytes(data)
        return path
    except Exception:
        return None


def _download_cover(item: dict[str, Any], cover_url: str | None) -> Path | None:
    """Save a cover image to use as the audio thumbnail.

    For Spotify tracks we use the real album art (``cover_url``).  For YouTube
    tracks we first try to grab the *square* album art from YouTube Music
    (via ``ytmusicapi``) so Telegram doesn't squish a 16:9 video thumbnail.
    Falls back to the extractor's thumbnail if nothing better is found."""
    video_id = item.get('id') or 'cover'

    if cover_url:
        return _download_image(cover_url, video_id)

    # Try YouTube Music's square album art before the 16:9 video thumbnail.
    music_cover = _ytmusic_cover_url(video_id)
    if music_cover:
        result = _download_image(music_cover, video_id)
        if result:
            return result

    thumbnail_url = item.get('thumbnail')
    if thumbnail_url:
        return _download_image(thumbnail_url, video_id)

    return None


def _song_from_item(
    item: dict[str, Any],
    label: Song | None,
    cover_url: str | None,
    path: Path | None = None,
) -> Song:
    extractor_duration = int(item.get('duration') or 0)
    # Cross-check the extractor's duration against the real file when remuxing
    # is enabled; otherwise keep today's extractor-only value.
    duration = (
        _accurate_duration(extractor_duration, path)
        if REMUX_FOR_SEEK
        else extractor_duration
    )
    thumbnail_path = _download_cover(item, cover_url)

    if label is not None:
        # Keep Spotify's clean name/artist, but enrich with what YouTube knows.
        label.duration = duration
        label.thumbnail_path = thumbnail_path
        return label

    name = item.get('track') or item.get('title') or 'Unknown'
    artist = item.get('artist') or item.get('uploader') or ''
    return Song(
        name=name,
        artist=artist,
        duration=duration,
        thumbnail_path=thumbnail_path,
    )


def _raise_for_message(text: str) -> None:
    """Map a yt-dlp error message to a specific exception (if recognised)."""
    t = text.lower()
    if 'sign in to confirm' in t or 'not a bot' in t:
        raise DownloadBlockedError
    if 'drm protected' in t:
        raise DRMProtectedError
    if any(
        s in t
        for s in (
            'private video',
            'video unavailable',
            'been removed',
            'not available in your country',
            'who has blocked',
            'members-only',
            'this live event',
        )
    ):
        raise VideoUnavailableError
    if 'larger than' in t or 'max-filesize' in t or 'max filesize' in t:
        raise TrackTooLargeError
    # Unrecognised: let the caller fall back to the generic "couldn't download".


def _item_filesize(item: dict[str, Any]) -> int | None:
    """Best-effort file size from metadata (before or after download)."""
    downloads = item.get('requested_downloads')
    if downloads:
        size = downloads[0].get('filesize') or downloads[0].get('filesize_approx')
        if size:
            return int(size)
    return int(item.get('filesize') or item.get('filesize_approx') or 0) or None


def _download(
    target: str, label: Song | None, cover_url: str | None
) -> list[tuple[Song, Path | None]]:
    """Download a single audio track from YouTube.

    Two-phase: fetch metadata first and reject oversized tracks before
    downloading a single byte, then download using the same metadata (so
    YouTube isn't queried twice). ``yt_dlp`` is imported at module level.
    """
    try:
        with yt_dlp.YoutubeDL(_ydl_options()) as ydl:
            info = ydl.extract_info(target, download=False)
            if not info:
                return []

            entries = info.get('entries')
            items = [
                item for item in (entries if entries is not None else [info]) if item
            ]
            if not items:
                return []

            for item in items:
                size = _item_filesize(item)
                if size and size > MAX_AUDIO_FILESIZE:
                    raise TrackTooLargeError

            # process_ie_result returns a NEW dict carrying the saved file path.
            downloaded = [
                ydl.process_ie_result(item, download=True) or item for item in items
            ]
    except yt_dlp.utils.DownloadError as error:
        _raise_for_message(str(error))
        return []

    if all(_downloaded_path(item) is None for item in downloaded):
        for item in downloaded:
            size = _item_filesize(item)
            if size and size > MAX_AUDIO_FILESIZE:
                raise TrackTooLargeError
        return []

    results: list[tuple[Song, Path | None]] = []
    for item in downloaded:
        path = _downloaded_path(item)
        # Remux MP4-family files for faststart so Telegram can seek. No-op for
        # non-MP4-family output (e.g. .mp3/.webm) and when the toggle is off.
        if REMUX_FOR_SEEK and path is not None:
            path = _remux_for_faststart(path)
        results.append((_song_from_item(item, label, cover_url, path), path))
    return results


def _warn_soundcloud_fallback(target: str) -> None:
    logger.warning(
        'YouTube download failed; falling back to SoundCloud — is the PO-token '
        'provider running? (%s)',
        target,
    )


def _resolve_and_download(query: str) -> list[tuple[Song, Path | None]]:
    def deliver(
        results: list[tuple[Song, Path | None]], source: str
    ) -> list[tuple[Song, Path | None]]:
        # Record the source that actually delivered so /stats can surface it
        # when YouTube is failing and the bot silently degrades to SoundCloud.
        metrics.record(source if results else metrics.NONE)
        return results

    if _is_youtube_link(query):
        # Exact video (menu picks and pasted YouTube links). The PO-token
        # provider lets this work without cookies; if it still fails, fall back
        # to an equivalent track on SoundCloud.
        with suppress(DownloadError):
            results = _download(query, label=None, cover_url=None)
            if results:
                return deliver(results, metrics.YOUTUBE)
        if SOUNDCLOUD_FALLBACK:
            _warn_soundcloud_fallback(query)
            title = _youtube_search_query(query)
            if title:
                return deliver(
                    _download(f'scsearch1:{title}', label=None, cover_url=None),
                    metrics.SOUNDCLOUD,
                )
        return deliver([], metrics.NONE)

    if _is_spotify_link(query):
        # Raises UnsupportedSpotifyLinkError for albums/playlists.
        search_query, label, cover_url = _spotify_track(query)
        with suppress(DownloadError):
            results = _download(
                f'ytsearch1:{search_query}', label=label, cover_url=cover_url
            )
            if results:
                return deliver(results, metrics.YOUTUBE)
        if SOUNDCLOUD_FALLBACK:
            _warn_soundcloud_fallback(search_query)
            return deliver(
                _download(f'scsearch1:{search_query}', label=label, cover_url=cover_url),
                metrics.SOUNDCLOUD,
            )
        return deliver([], metrics.NONE)

    if query.startswith('http://') or query.startswith('https://'):
        # A direct media link we didn't turn into a search (e.g. SoundCloud).
        return deliver(_download(query, label=None, cover_url=None), metrics.SOUNDCLOUD)

    # Plain text (rare here — the menu normally resolves names to a videoId).
    with suppress(DownloadError):
        results = _download(f'ytsearch1:{query}', label=None, cover_url=None)
        if results:
            return deliver(results, metrics.YOUTUBE)
    if SOUNDCLOUD_FALLBACK:
        _warn_soundcloud_fallback(query)
        return deliver(
            _download(f'scsearch1:{query}', label=None, cover_url=None),
            metrics.SOUNDCLOUD,
        )
    return deliver([], metrics.NONE)


_ytmusic: Any = None
_ytmusic_init_failed = False


def _get_ytmusic() -> Any:
    """Return a lazily-created, unauthenticated YouTube Music client (or None).

    Import and construction are deferred and guarded so the module still loads
    (and the bot still runs on SoundCloud) if ytmusicapi isn't installed.
    """
    global _ytmusic, _ytmusic_init_failed
    if _ytmusic is None and not _ytmusic_init_failed:
        try:
            from ytmusicapi import YTMusic

            _ytmusic = YTMusic()  # no auth needed for search
        except Exception:
            _ytmusic_init_failed = True
            logger.warning(
                'ytmusicapi unavailable; falling back to SoundCloud for search'
            )
    return _ytmusic


def _ytmusic_cover_url(video_id: str) -> str | None:
    """Get a square album-art URL from YouTube Music for *video_id*.

    ``ytmusicapi.search`` returns 60×60/120×120 square thumbnails (album art),
    whereas ``get_song`` only has 16:9 video frames.  We search by videoId,
    grab the thumbnail URL, and bump its size parameter for a 544×544 image.
    Returns ``None`` gracefully if ytmusicapi is unavailable or no match.
    """
    yt = _get_ytmusic()
    if yt is None:
        return None

    try:
        results = yt.search(video_id, filter='songs', limit=1)
        if not results:
            return None
        # Confirm the result matches our videoId.
        item = results[0]
        if item.get('videoId') != video_id:
            return None
        thumbs = item.get('thumbnails') or []
        if not thumbs:
            return None
        # Take the last (largest) thumbnail and request a bigger variant.
        url = thumbs[-1].get('url') or ''
        if not url:
            return None
        # Bump size from e.g. =w120-h120-… to =w544-h544-… for better quality.
        import re as _re
        url = _re.sub(r'=w\d+-h\d+', '=w544-h544', url)
        return url
    except Exception:
        return None


def _search_youtube_music(query: str, limit: int) -> list[dict[str, Any]]:
    """Search YouTube Music for songs. Returns [] if unavailable or on error."""
    yt = _get_ytmusic()
    if yt is None:
        return []

    try:
        raw = yt.search(query, filter='songs', limit=limit)
    except Exception:
        logger.exception('YouTube Music search failed')
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        video_id = item.get('videoId')
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)

        artists = item.get('artists') or []
        artist = ', '.join(a['name'] for a in artists if a.get('name')) or 'Unknown'

        results.append({
            'id': video_id,
            'title': item.get('title') or 'Unknown',
            'artist': artist,
            'duration': int(item.get('duration_seconds') or 0),
            'url': f'https://music.youtube.com/watch?v={video_id}',
        })
        if len(results) >= limit:
            break

    return results


def _search_youtube_ytdlp(query: str, limit: int) -> list[dict[str, Any]]:
    """Search YouTube via yt-dlp (flat, no download).

    A robust middle tier: it works even where YouTube Music isn't available and
    still yields an exact, downloadable videoId. Returns [] on error.
    """
    options = _ydl_options()
    options['extract_flat'] = True

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f'ytsearch{limit}:{query}', download=False)
    except yt_dlp.utils.DownloadError:
        return []

    if not info:
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in info.get('entries') or []:
        video_id = item.get('id')
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        results.append({
            'id': video_id,
            'title': item.get('title') or 'Unknown',
            'artist': item.get('uploader') or 'Unknown',
            'duration': int(item.get('duration') or 0),
            'url': f'https://www.youtube.com/watch?v={video_id}',
        })

    return results


def _search_soundcloud(query: str, limit: int) -> list[dict[str, Any]]:
    """Fetch top SoundCloud results (fallback when YouTube Music has nothing)."""
    options = _ydl_options()
    options['extract_flat'] = True

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f'scsearch{limit}:{query}', download=False)
            if not info:
                return []
            entries = info.get('entries', [])
            results = []
            for item in entries:
                if not item or not item.get('id'):
                    continue
                results.append({
                    'id': item.get('id'),
                    'title': item.get('title', 'Unknown'),
                    'artist': item.get('uploader', 'Unknown'),
                    'duration': item.get('duration', 0),
                    'url': item.get('webpage_url') or item.get('url'),
                    'views': item.get('view_count') or 0,
                })

            # Sort by views descending so the most popular tracks appear first
            results.sort(key=lambda x: x['views'], reverse=True)
            return results
    except yt_dlp.utils.DownloadError:
        return []


def _search_tracks(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search for tracks to offer the user, most accurate source first.

    1. YouTube Music — curated songs with clean title/artist metadata.
    2. YouTube (via yt-dlp) — same downloadable source, works even where
       YouTube Music isn't available.
    3. SoundCloud — last-resort fallback so results still show.
    """
    for search in (_search_youtube_music, _search_youtube_ytdlp, _search_soundcloud):
        results = search(query, limit)
        if results:
            return results
    return []


class Downloader:
    async def download(self, query: str) -> list[tuple[Song, Path | None]]:
        # The blocking yt-dlp work runs in a worker thread; the semaphore keeps
        # it to MAX_PARALLEL_DOWNLOADS at a time.
        async with _download_semaphore:
            return await asyncio.to_thread(_resolve_and_download, query)

    async def search_tracks(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        # Search is a light API call (YouTube Music), so it doesn't take the
        # heavy download semaphore — users can search while downloads run.
        return await asyncio.to_thread(_search_tracks, query, limit)
