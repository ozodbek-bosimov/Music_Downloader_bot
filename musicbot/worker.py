from __future__ import annotations

from aiogram.exceptions import TelegramAPIError

from sqlalchemy import delete, select

from musicbot.bot import bot
from musicbot.bot.sender import reply_song, send_cached_audio
from musicbot.cache import get_cached_file_id, store_file_id
from musicbot.config import MAX_TRACK_STORAGE_SIZE, TRACKS_PATH
from musicbot.db import async_session
from musicbot.db.models import DownloadQueue
from musicbot.downloader import Song, downloader
from musicbot.downloader.exceptions import (
    DownloadBlockedError,
    TrackTooLargeError,
    UnsupportedSpotifyLinkError,
    VideoUnavailableError,
)

from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any
import asyncio
import gc
import logging
import os
import time

logger = logging.getLogger(__name__)


async def cleanup_old_tracks() -> None:
    while True:
        try:
            now = time.time()
            entries: list[Path] = [
                TRACKS_PATH / name for name in os.listdir(TRACKS_PATH)
            ]

            # 1) Remove orphaned partial/temp files left by aborted downloads
            #    (e.g. a file that hit the 50 MB limit). A download in progress
            #    keeps writing, so we only drop temp files untouched for a while.
            tracks: list[Path] = []
            for path in entries:
                is_temp = path.suffix in ('.part', '.ytdl', '.temp', '.tmp') or (
                    '.part-Frag' in path.name
                )
                if is_temp:
                    with suppress(OSError):
                        if now - os.path.getmtime(path) > 300:  # 5 minutes
                            os.remove(path)
                else:
                    tracks.append(path)

            # 2) Cap the total size of finished tracks (least-recently-used go first).
            total_size: int = sum(
                os.path.getsize(track) for track in tracks if track.exists()
            )
            if total_size > MAX_TRACK_STORAGE_SIZE:
                for track in sorted(tracks, key=lambda track: os.path.getatime(track)):
                    track_size: int = os.path.getsize(track)

                    os.remove(track)
                    total_size -= track_size

                    if total_size <= MAX_TRACK_STORAGE_SIZE:
                        break
        except Exception:
            # Never let a transient filesystem error kill the cleanup loop.
            logger.exception('Track cleanup failed')

        await asyncio.sleep(60)


async def _serve_from_cache(
    query: str,
    chat_id: int,
    user_message_id: int,
    bot_message_kwargs: dict[str, Any],
) -> bool:
    """Send the track from cache if we have it. Returns True on success."""
    file_id = await get_cached_file_id(query)
    if file_id is None:
        return False

    try:
        await send_cached_audio(chat_id, user_message_id, file_id)
    except TelegramAPIError:
        # The cached file_id is no longer usable — re-download instead.
        return False

    with suppress(TelegramAPIError):
        await bot.delete_message(**bot_message_kwargs)
    return True


async def _download_and_serve(
    query: str,
    chat_id: int,
    user_message_id: int,
    bot_message_kwargs: dict[str, Any],
) -> None:
    logger.info(
        "Starting download and serve for query: '%s' in chat: %d", query, chat_id
    )
    with suppress(TelegramAPIError):
        try:
            songs: list[tuple[Song, Path | None]] = await downloader.download(query)

            if songs:
                logger.info(
                    "Found %d tracks to send for query: '%s'", len(songs), query
                )
                file_ids = await asyncio.gather(
                    *[
                        reply_song(
                            chat_id=chat_id,
                            user_message_id=user_message_id,
                            song=song,
                            song_path=path,
                        )
                        for song, path in songs
                    ]
                )
                await bot.delete_message(**bot_message_kwargs)

                # Cache single-track results so repeats skip YouTube entirely.
                sent_file_ids = [file_id for file_id in file_ids if file_id]
                if len(songs) == 1 and sent_file_ids:
                    logger.info("Caching file_id for single track: '%s'", query)
                    await store_file_id(query, sent_file_ids[0])
            else:
                logger.warning("No songs returned for query: '%s'", query)
                await bot.edit_message_text(
                    **bot_message_kwargs,
                    text=(
                        "🔍 I couldn't find anything for this.\n\n"
                        'Please check the spelling and try again, or send a '
                        'YouTube link or a Spotify track link.'
                    ),
                )
        except UnsupportedSpotifyLinkError:
            logger.warning("Unsupported Spotify link: '%s'", query)
            await bot.edit_message_text(
                **bot_message_kwargs,
                text=(
                    "Spotify albums and playlists aren't supported.\n\n"
                    'Please send a single Spotify track link, a YouTube link, '
                    'or just the song name (for example: <code>Hans Zimmer - Cornfield Chase</code>).'
                ),
            )
        except TrackTooLargeError:
            logger.warning("Track too large error for query: '%s'", query)
            await bot.edit_message_text(
                **bot_message_kwargs,
                text=(
                    "This track is larger than 50 MB, which is Telegram's "
                    "upload limit for bots, so I can't send it."
                ),
            )
        except DownloadBlockedError:
            logger.warning("YouTube blocked error for query: '%s'", query)
            await bot.edit_message_text(
                **bot_message_kwargs,
                text=(
                    'YouTube is temporarily blocking downloads from this '
                    'server.\n\nThis is usually short-lived — please try this '
                    'track again in a few minutes.'
                ),
            )
        except VideoUnavailableError:
            logger.warning("Video unavailable error for query: '%s'", query)
            await bot.edit_message_text(
                **bot_message_kwargs,
                text=(
                    "This video isn't available — it may be private, "
                    'removed, or blocked in this region.\n\nTry a different '
                    'link, or search by the song name.'
                ),
            )
        except Exception as e:
            logger.exception(
                "Unexpected exception downloading query '%s': %s", query, e
            )
            await bot.edit_message_text(
                **bot_message_kwargs,
                text=(
                    'Something went wrong while downloading this track.\n\n'
                    'Please try again in a moment, or search by the song name '
                    '(for example: <code>Hans Zimmer - Cornfield Chase</code>).'
                ),
            )


async def process_download_request(request_id: int) -> None:
    async with async_session() as session:
        request: DownloadQueue | None = await session.scalar(
            select(DownloadQueue).where(DownloadQueue.id == request_id)
        )

    if not request:
        return

    chat_id: int = request.chat_id
    user_message_id: int = request.user_message_id
    query: str = request.query

    logger.info(
        "Processing queue request_id: %d, query: '%s' for chat_id: %d",
        request_id,
        query,
        chat_id,
    )

    bot_message_kwargs: dict[str, Any] = {
        'chat_id': chat_id,
        'message_id': request.bot_message_id,
    }

    try:
        served = await _serve_from_cache(
            query, chat_id, user_message_id, bot_message_kwargs
        )
        if served:
            logger.info('Request_id: %d served from cache', request_id)
        else:
            logger.info('Request_id: %d cache miss, downloading...', request_id)
            await _download_and_serve(
                query, chat_id, user_message_id, bot_message_kwargs
            )
    finally:
        async with async_session() as session:
            await session.execute(
                delete(DownloadQueue).where(DownloadQueue.id == request_id)
            )
            await session.commit()
        logger.info('Finished processing request_id: %d', request_id)


# Requests that are currently being processed, so the polling loop below
# doesn't pick the same request up again while it's still downloading.
_in_progress_request_ids: set[int] = set()


async def _process_and_release(request_id: int) -> None:
    try:
        await process_download_request(request_id)
    except Exception:
        logger.exception('Failed to process request %s', request_id)
    finally:
        _in_progress_request_ids.discard(request_id)
        gc.collect()


async def process_download_queue() -> None:
    while True:
        try:
            async with async_session() as session:
                request_ids: Sequence[int] = (
                    await session.scalars(select(DownloadQueue.id))
                ).all()

            for request_id in request_ids:
                if request_id in _in_progress_request_ids:
                    continue

                _in_progress_request_ids.add(request_id)
                # Fire-and-forget: new requests start immediately instead of
                # waiting for the current batch to finish. Concurrency is
                # bounded by the download semaphore in `Downloader.download`.
                asyncio.create_task(_process_and_release(request_id))
        except Exception:
            # Never let a transient DB error kill the queue loop.
            logger.exception('Queue polling failed')

        await asyncio.sleep(1)


async def run_tasks() -> None:
    asyncio.create_task(cleanup_old_tracks())
    asyncio.create_task(process_download_queue())
