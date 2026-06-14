from __future__ import annotations

from aiogram.types import FSInputFile

from musicbot.config import MAX_AUDIO_FILESIZE
from musicbot.downloader import Song

from . import bot

from contextlib import suppress
from pathlib import Path
from typing import Any
import os


def _remove(path: Path | None) -> None:
    if path:
        with suppress(OSError):
            os.remove(path)


async def reply_song(
    chat_id: int, user_message_id: int, song: Song, song_path: Path | None
) -> str | None:
    """Send the audio (or a failure notice) and return the Telegram audio
    file_id on success, so the caller can cache it for instant re-sends."""
    bot_message_kwargs: dict[str, Any] = {
        'chat_id': chat_id,
        'reply_to_message_id': user_message_id,
    }

    too_large = (
        song_path is not None
        and song_path.exists()
        and os.path.getsize(song_path) > MAX_AUDIO_FILESIZE
    )

    if song_path and song_path.exists() and not too_large:
        audio_kwargs: dict[str, Any] = {
            'audio': FSInputFile(song_path),
            'title': song.name or None,
            'performer': song.artist or None,
        }
        if song.duration > 0:
            audio_kwargs['duration'] = song.duration
        if song.thumbnail_path and song.thumbnail_path.exists():
            audio_kwargs['thumbnail'] = FSInputFile(song.thumbnail_path)

        try:
            message = await bot.send_audio(**bot_message_kwargs, **audio_kwargs)
            return message.audio.file_id if message.audio else None
        finally:
            # Free the disk immediately: once Telegram has the file we no longer
            # need a local copy. This keeps usage near zero on a 1 GB disk.
            _remove(song_path)
            _remove(song.thumbnail_path)
    else:
        # Clean up any partial/oversized files we won't send.
        _remove(song_path)
        _remove(song.thumbnail_path)

        text = (
            f'<code>{song.display_name}</code> is over 50 MB — too large to send.'
            if too_large
            else f"Couldn't download <code>{song.display_name}</code>. Try again."
        )
        await bot.send_message(**bot_message_kwargs, text=text)
        return None


async def send_cached_audio(chat_id: int, user_message_id: int, file_id: str) -> None:
    """Re-send a previously uploaded audio by its file_id (no download). The
    original title/performer/duration/thumbnail are preserved by Telegram."""
    await bot.send_audio(
        chat_id=chat_id,
        reply_to_message_id=user_message_id,
        audio=file_id,
    )
