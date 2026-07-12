from __future__ import annotations

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Chat, Message, User

from musicbot.config import BOT_TOKEN, REQUIRED_CHANNEL
from musicbot.db import async_session
from musicbot.db.models import DownloadQueue

from .admin import router as admin_router
from .middlewares import (
    CreateUserMiddleware,
    MembershipCheckMiddleware,
    is_channel_member,
)
from .session import ResilientSession

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
    'Send me a <b>song name</b>, a <b>YouTube link</b>, or a '
    "<b>Spotify track link</b> — I'll send back the audio.\n\n"
    "<i>Albums and playlists aren't supported.</i>"
)
if REQUIRED_CHANNEL:
    USAGE_TEXT += f'\n\nJoin {REQUIRED_CHANNEL} to use the bot.'


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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import uuid

SEARCH_CACHE: dict[str, list[dict]] = {}

def get_search_keyboard(search_id: str, page: int) -> InlineKeyboardMarkup:
    results = SEARCH_CACHE.get(search_id, [])
    items_per_page = 5
    max_page = max(0, (len(results) - 1) // items_per_page)
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = results[start_idx:end_idx]
    
    buttons = []
    for item in page_items:
        track_id = item['id']
        title = item['title'][:30] + "..." if len(item['title']) > 30 else item['title']
        artist = item['artist'][:20] + "..." if len(item['artist']) > 20 else item['artist']
        duration = int(item.get('duration') or 0)
        
        mins, secs = divmod(duration, 60)
        dur_str = f"{mins}:{secs:02d}"
        
        btn_text = f"{title} - {artist} ({dur_str})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_sc:{track_id}")])
        
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"page:{search_id}:{page-1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    nav_buttons.append(InlineKeyboardButton(text=f"{page+1}/{max_page+1}", callback_data="ignore"))
    
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"page:{search_id}:{page+1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    buttons.append(nav_buttons)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dispatcher.message(F.text & ~F.text.startswith('/'))
async def message_handler(message: Message, event_chat: Chat) -> None:
    query: str | None = message.text

    if not query:
        return None

    bot_message: Message = await message.reply('🔍 Searching…')

    is_link = 'http://' in query or 'https://' in query

    if is_link:
        from musicbot.downloader.client import _is_youtube_link, _is_spotify_link, _youtube_search_query, _spotify_track
        
        if _is_youtube_link(query):
            extracted = _youtube_search_query(query)
            if extracted:
                query = extracted[0]
                is_link = False
        elif _is_spotify_link(query):
            try:
                extracted = _spotify_track(query)
                if extracted:
                    query = extracted[0]
                    is_link = False
            except Exception:
                pass

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

    results = await downloader.search_tracks(query, limit=20)
    
    if not results:
        await bot_message.edit_text('🔍 Nothing found. Check the spelling or try a link.')
        return

    search_id = uuid.uuid4().hex[:8]
    SEARCH_CACHE[search_id] = results
    
    if len(SEARCH_CACHE) > 500:
        oldest_key = next(iter(SEARCH_CACHE))
        del SEARCH_CACHE[oldest_key]
        
    markup = get_search_keyboard(search_id, 0)
    await bot_message.edit_text('🎧 Choose a track to download:', reply_markup=markup)


@dispatcher.callback_query(F.data.startswith('page:'))
async def page_callback_handler(callback: CallbackQuery) -> None:
    _, search_id, page_str = callback.data.split(':')
    page = int(page_str)
    
    if search_id not in SEARCH_CACHE:
        await callback.answer("Qidiruv eskirgan, iltimos boshqadan qidiring.", show_alert=True)
        return
        
    markup = get_search_keyboard(search_id, page)
    await callback.message.edit_reply_markup(reply_markup=markup)
    await callback.answer()

@dispatcher.callback_query(F.data == 'ignore')
async def ignore_callback_handler(callback: CallbackQuery) -> None:
    await callback.answer()


@dispatcher.callback_query(F.data.startswith('dl_sc:'))
async def dl_sc_callback_handler(callback: CallbackQuery) -> None:
    parts = callback.data.split(':')
    track_id = parts[1]
    url = f"https://api.soundcloud.com/tracks/{track_id}"
    
    for results in SEARCH_CACHE.values():
        for item in results:
            if str(item.get('id')) == track_id and item.get('url'):
                url = item['url']
                break
        else:
            continue
        break
    
    await callback.answer()
    
    if isinstance(callback.message, Message):
        await callback.message.edit_text('⏳ Queued for download...')
        
        user_msg_id = callback.message.message_id
        if callback.message.reply_to_message:
            user_msg_id = callback.message.reply_to_message.message_id

        async with async_session() as session:
            session.add(
                DownloadQueue(
                    chat_id=callback.message.chat.id,
                    bot_message_id=callback.message.message_id,
                    user_message_id=user_msg_id,
                    query=url,
                )
            )
            await session.commit()
