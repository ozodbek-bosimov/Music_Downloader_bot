from __future__ import annotations

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from sqlalchemy import select

from musicbot.config import BOT_TOKEN, MUSIC_SEARCH_LIMIT, REQUIRED_CHANNEL
from musicbot.db import async_session
from musicbot.db.models import DownloadQueue

from .admin import router as admin_router
from .middlewares import (
    CreateUserMiddleware,
    MembershipCheckMiddleware,
    is_channel_member,
)
from .session import ResilientSession

from contextlib import suppress
from typing import Any
import uuid

bot = Bot(
    token=BOT_TOKEN,
    session=ResilientSession(),
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True
    ),
)

dispatcher = Dispatcher(bot=bot)
dispatcher.include_router(admin_router)
dispatcher.update.middleware(CreateUserMiddleware())
dispatcher.update.middleware(MembershipCheckMiddleware())

USAGE_TEXT = (
    'Send me a <b>song name</b>, a <b>SoundCloud link</b>, a '
    '<b>YouTube link</b>, or a <b>Spotify track link</b> — '
    "I'll search and send back the audio.\n\n"
    "<i>Albums and playlists aren't supported.</i>"
)
if REQUIRED_CHANNEL:
    USAGE_TEXT += f'\n\nJoin {REQUIRED_CHANNEL} to use the bot.'

# Maps a short search id to its list of SoundCloud result dicts, so paginating
# and tapping a track later can look the results up without re-searching.
SEARCH_CACHE: dict[str, list[dict[str, Any]]] = {}

ITEMS_PER_PAGE = 5


@dispatcher.message(CommandStart())
async def start_command_handler(message: Message, event_from_user: User) -> None:
    await message.answer(f'Hey {event_from_user.first_name} 🎧\n\n' + USAGE_TEXT)


@dispatcher.message(Command('help'))
async def help_command_handler(message: Message) -> None:
    await message.answer(USAGE_TEXT)


@dispatcher.callback_query(F.data == 'check_subscription')
async def check_subscription_handler(callback: CallbackQuery) -> None:
    if not await is_channel_member(bot, callback.from_user.id):
        await callback.answer(
            "You haven't joined yet.",
            show_alert=True,
        )
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.delete()


def _format_duration(seconds: int) -> str:
    """Format a track length as ``M:SS`` (or ``H:MM:SS`` past an hour).

    Missing or zero durations render as ``--:--``.
    """
    if not seconds or seconds <= 0:
        return '--:--'

    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def _truncate(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars, appending a real ellipsis if cut."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + '…'


def _max_page(search_id: str) -> int:
    results = SEARCH_CACHE.get(search_id, [])
    return max(0, (len(results) - 1) // ITEMS_PER_PAGE)


def _results_header(search_id: str, page: int) -> str:
    return '🎧 Choose a track:'


def get_search_keyboard(search_id: str, page: int) -> InlineKeyboardMarkup:
    results = SEARCH_CACHE.get(search_id, [])
    max_page = _max_page(search_id)

    start_idx = page * ITEMS_PER_PAGE
    page_items = results[start_idx : start_idx + ITEMS_PER_PAGE]

    buttons: list[list[InlineKeyboardButton]] = []
    for item in page_items:
        track_id = item['id']
        title = _truncate(str(item.get('title') or 'Unknown'), 30)
        artist = _truncate(str(item.get('artist') or 'Unknown'), 20)
        dur = _format_duration(int(item.get('duration') or 0))
        btn_text = f'{title} — {artist} · {dur}'
        buttons.append(
            [InlineKeyboardButton(text=btn_text, callback_data=f'dl_sc:{track_id}')]
        )

    # Only show navigation when there's more than one page.
    if max_page > 0:
        nav_buttons: list[InlineKeyboardButton] = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text='◀️', callback_data=f'page:{search_id}:{page - 1}'
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(
                text=f'{page + 1}/{max_page + 1}', callback_data='ignore'
            )
        )
        if page < max_page:
            nav_buttons.append(
                InlineKeyboardButton(
                    text='▶️', callback_data=f'page:{search_id}:{page + 1}'
                )
            )
        buttons.append(nav_buttons)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dispatcher.message(F.text & ~F.text.startswith('/'))
async def message_handler(message: Message, event_chat: Chat) -> None:
    query: str | None = message.text

    if not query:
        return None

    bot_message: Message = await message.reply('🔎 Searching…')

    is_link = 'http://' in query or 'https://' in query

    if is_link:
        from musicbot.downloader.client import (
            _is_spotify_link,
            _is_youtube_link,
            _spotify_track,
            _youtube_search_query,
        )

        if _is_youtube_link(query):
            yt_query = _youtube_search_query(query)
            if yt_query:
                query = yt_query
                is_link = False
        elif _is_spotify_link(query):
            with suppress(Exception):
                track = _spotify_track(query)
                if track:
                    query = track[0]
                    is_link = False

    if is_link:
        async with async_session() as session:
            session.add(
                DownloadQueue(
                    chat_id=event_chat.id,
                    bot_message_id=bot_message.message_id,
                    user_message_id=message.message_id,
                    query=query,
                )
            )
            await session.commit()
        return

    from musicbot.downloader import downloader

    results = await downloader.search_tracks(query, limit=MUSIC_SEARCH_LIMIT)

    if not results:
        await bot_message.edit_text(
            '😕 Nothing found. Check the spelling or paste a link.'
        )
        return

    search_id = uuid.uuid4().hex[:8]
    SEARCH_CACHE[search_id] = results

    if len(SEARCH_CACHE) > 500:
        oldest_key = next(iter(SEARCH_CACHE))
        del SEARCH_CACHE[oldest_key]

    markup = get_search_keyboard(search_id, 0)
    await bot_message.edit_text(_results_header(search_id, 0), reply_markup=markup)


@dispatcher.callback_query(F.data.startswith('page:'))
async def page_callback_handler(callback: CallbackQuery) -> None:
    if not callback.data:
        return

    _, search_id, page_str = callback.data.split(':')
    page = int(page_str)

    if search_id not in SEARCH_CACHE:
        await callback.answer(
            '⌛ This search expired. Please search again.', show_alert=True
        )
        return

    markup = get_search_keyboard(search_id, page)
    if isinstance(callback.message, Message):
        with suppress(TelegramAPIError):
            await callback.message.edit_text(
                _results_header(search_id, page), reply_markup=markup
            )
    await callback.answer()


@dispatcher.callback_query(F.data == 'ignore')
async def ignore_callback_handler(callback: CallbackQuery) -> None:
    await callback.answer()


@dispatcher.callback_query(F.data.startswith('dl_sc:'))
async def dl_sc_callback_handler(callback: CallbackQuery) -> None:
    if not callback.data:
        return

    track_id = callback.data.split(':', 1)[1]
    url: str | None = None

    for results in SEARCH_CACHE.values():
        for item in results:
            if str(item.get('id')) == track_id and item.get('url'):
                url = item['url']
                break
        else:
            continue
        break

    if url is None:
        await callback.answer(
            '⌛ This search expired. Please search again.', show_alert=True
        )
        return

    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    user_msg_id = callback.message.message_id
    if callback.message.reply_to_message:
        user_msg_id = callback.message.reply_to_message.message_id

    chat_id = callback.message.chat.id

    async with async_session() as session:
        # A matching pending row means the track is already queued or in
        # progress (rows are deleted once processed), so don't enqueue twice.
        existing = await session.scalar(
            select(DownloadQueue).where(
                DownloadQueue.chat_id == chat_id,
                DownloadQueue.query == url,
            )
        )
        if existing is not None:
            await callback.answer('⏳ Already downloading this track…')
            return

        session.add(
            DownloadQueue(
                chat_id=chat_id,
                bot_message_id=callback.message.message_id,
                user_message_id=user_msg_id,
                query=url,
                # Marks this request as menu-originated so the worker keeps the
                # menu in place instead of deleting its status message.
                callback_query_id=callback.id,
            )
        )
        await session.commit()

    # Leave the callback unanswered: the worker answers it at completion time
    # (silently on success, or as a top alert on error). The button keeps its
    # loading spinner until then, which signals the work is in progress.
