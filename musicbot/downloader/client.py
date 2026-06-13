import yt_dlp

from musicbot.config import (
    CONVERT_TO_MP3,
    FFMPEG_LOCATION,
    MAX_AUDIO_FILESIZE,
    MAX_PARALLEL_DOWNLOADS,
    TRACKS_PATH,
    YTDLP_COOKIEFILE,
    YTDLP_PLAYER_CLIENTS,
)

from .exceptions import (
    DownloadBlockedError,
    TrackTooLargeError,
    UnsupportedSpotifyLinkError,
    VideoUnavailableError,
)
from .models import Song

from asyncio import Semaphore
from html import unescape
from pathlib import Path
from typing import Any
import asyncio
import json
import re
import urllib.parse
import urllib.request

_download_semaphore = Semaphore(MAX_PARALLEL_DOWNLOADS)

# Spotify serves server-rendered metadata (Open Graph tags) to simple,
# bot-like user agents, but a full browser UA gets a JavaScript app shell with
# no metadata. So we deliberately use a minimal user agent here.
_USER_AGENT = 'Mozilla/5.0'


def _ydl_options() -> dict[str, Any]:
    # We download the best available audio-only stream. By default we keep it in
    # its native container (usually .m4a) and DON'T transcode, because FFmpeg
    # transcoding is too CPU-heavy for a 0.25 CPU host. Telegram plays .m4a fine.
    # NOTE: no video fallback — we never download a video stream, which keeps
    # disk/IO usage and file sizes low on a tiny host.
    options: dict[str, Any] = {
        'format': 'bestaudio[ext=m4a]/bestaudio',
        'outtmpl': str(TRACKS_PATH / '%(title).200B.%(ext)s'),
        'restrictfilenames': True,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'noplaylist': True,
        'ignoreerrors': False,
        # Reject anything bigger than Telegram's upload limit. This (not video
        # length) is what bounds disk and I/O usage per download.
        'max_filesize': MAX_AUDIO_FILESIZE,
    }

    if YTDLP_PLAYER_CLIENTS:
        options['extractor_args'] = {
            'youtube': {'player_client': YTDLP_PLAYER_CLIENTS}
        }

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
    ``Song`` label and the real Spotify cover URL (so we can use the actual
    album art instead of YouTube's thumbnail).

    We read the page's Open Graph tags (and fall back to Spotify's public
    oEmbed endpoint) instead of using the Spotify API, so no API credentials
    are required. Albums and playlists are intentionally not expanded on this
    lightweight instance.
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
            data = json.loads(
                _http_get(f'https://open.spotify.com/oembed?url={url}')
            )
            title = title or data.get('title')
            cover_url = cover_url or data.get('thumbnail_url')
        except Exception:
            pass

    if not title:
        raise UnsupportedSpotifyLinkError

    # Spotify's og:image is 640x640; Telegram thumbnails must be <=320px. The
    # size is encoded in the URL, so swap it for the 300px variant of the very
    # same cover.
    if cover_url:
        cover_url = cover_url.replace('ab67616d0000b273', 'ab67616d00001e02')

    search_query = f'{title} {artist}'.strip()
    return search_query, Song(name=title, artist=artist), cover_url


def _is_youtube_link(query: str) -> bool:
    return 'youtube.com' in query or 'youtu.be' in query


def _youtube_search_query(url: str) -> str | None:
    """Read a YouTube link's title + author via the public oEmbed endpoint.

    oEmbed isn't bot-checked, so we can then fetch the track through the SEARCH
    path (``ytsearch1:``). YouTube blocks direct watch-page extraction with
    "Sign in to confirm you're not a bot" far more aggressively than search, so
    routing links through search makes them as reliable as a name search.
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

    For Spotify tracks we use the real album art (``cover_url``). Otherwise we
    grab YouTube's small 320x180 JPEG, which fits Telegram's thumbnail limits
    (JPEG, <=320px, <200 KB) and costs almost nothing to fetch."""
    video_id = item.get('id') or 'cover'

    if cover_url:
        return _download_image(cover_url, video_id)

    if not item.get('id'):
        return None

    return _download_image(
        f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg', video_id
    )


def _song_from_item(
    item: dict[str, Any], label: Song | None, cover_url: str | None
) -> Song:
    duration = int(item.get('duration') or 0)
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


def _exceeds_size_limit(item: dict[str, Any]) -> bool:
    downloads = item.get('requested_downloads')
    if downloads:
        size = downloads[0].get('filesize') or downloads[0].get('filesize_approx')
        return bool(size and size > MAX_AUDIO_FILESIZE)
    return False


def _download(
    target: str, label: Song | None, cover_url: str | None
) -> list[tuple[Song, Path | None]]:
    """Download a single track from YouTube (audio only).

    ``target`` is either a YouTube URL or a ``ytsearch1:...`` expression. When a
    ``label`` is given (e.g. metadata scraped from Spotify) it's used to name the
    result instead of YouTube's own (often noisy) title, and ``cover_url`` (if
    given) is used as the cover instead of YouTube's thumbnail.

    Raises a specific ``DownloadError`` subclass when the reason is known
    (blocked, too large, unavailable); otherwise returns an empty list.
    """
    try:
        with yt_dlp.YoutubeDL(_ydl_options()) as ydl:
            info = ydl.extract_info(target, download=True)
    except yt_dlp.utils.DownloadError as error:
        _raise_for_message(str(error))
        return []

    if not info:
        return []

    entries = info.get('entries')
    items = [item for item in (entries if entries is not None else [info]) if item]

    # Got metadata but nothing was actually saved (e.g. the file was skipped
    # because it exceeds max_filesize). Explain why if we can.
    if items and all(_downloaded_path(item) is None for item in items):
        if any(_exceeds_size_limit(item) for item in items):
            raise TrackTooLargeError
        return []

    return [
        (_song_from_item(item, label, cover_url), _downloaded_path(item))
        for item in items
    ]


class Downloader:
    def _resolve_and_download(self, query: str) -> list[tuple[Song, Path | None]]:
        if _is_youtube_link(query):
            # YouTube blocks direct watch-page extraction far more than search,
            # so prefer the search path (via the link's oEmbed title). Fall back
            # to direct extraction only if search finds nothing.
            search_query = _youtube_search_query(query)
            if search_query:
                results = _download(
                    f'ytsearch1:{search_query}', label=None, cover_url=None
                )
                if results:
                    return results
            return _download(query, label=None, cover_url=None)

        if _is_spotify_link(query):
            # Raises UnsupportedSpotifyLinkError for albums/playlists.
            search_query, label, cover_url = _spotify_track(query)
            return _download(
                f'ytsearch1:{search_query}', label=label, cover_url=cover_url
            )

        # Plain text: treat it as a search.
        return _download(f'ytsearch1:{query}', label=None, cover_url=None)

    async def download(self, query: str) -> list[tuple[Song, Path | None]]:
        async with _download_semaphore:
            return await asyncio.to_thread(self._resolve_and_download, query)
