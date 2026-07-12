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
        await callback.message.answer('All set 🎧 Send me a song name or a link.')


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

@dispatcher.message(F.text & ~F.text.startswith('/'))
async def message_handler(message: Message, event_chat: Chat) -> None:
    query: str | None = message.text

    if not query:
        return None

    bot_message: Message = await message.reply('🔍 Searching…')

    is_link = 'http://' in query or 'https://' in query

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

    results = await downloader.search_tracks(query, limit=5)
    
    if not results:
        await bot_message.edit_text('🔍 Nothing found. Check the spelling or try a link.')
        return

    buttons = []
    for item in results:
        track_id = item['id']
        title = item['title']
        artist = item['artist']
        duration = item['duration']
        
        mins, secs = divmod(duration, 60)
        dur_str = f"{mins}:{secs:02d}"
        
        btn_text = f"{title} - {artist} ({dur_str})"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_sc:{track_id}")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await bot_message.edit_text('🎧 Choose a track to download:', reply_markup=markup)


@dispatcher.callback_query(F.data.startswith('dl_sc:'))
async def dl_sc_callback_handler(callback: CallbackQuery) -> None:
    track_id = callback.data.split(':', 1)[1]
    url = f"https://api.soundcloud.com/tracks/{track_id}"
    
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
