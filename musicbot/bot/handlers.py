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
    'Send me:\n'
    '• a song name (e.g. <code>Hans Zimmer - Cornfield Chase</code>)\n'
    '• a YouTube link\n'
    '• a single Spotify <b>track</b> link\n\n'
    "and I'll send you the audio.\n\n"
    '<b>Note:</b> Spotify albums and playlists are not supported — '
    'send individual tracks or search by name.'
)
if REQUIRED_CHANNEL:
    USAGE_TEXT += f'\n\nPlease subscribe to {REQUIRED_CHANNEL} to use this bot.'


@dispatcher.message(CommandStart())
async def start_command_handler(message: Message, event_from_user: User) -> None:
    await message.answer(
        f'<b>Hi, {event_from_user.full_name}!</b>\n\n'
        "I'm a free bot that downloads music from YouTube.\n\n" + USAGE_TEXT
    )


@dispatcher.message(Command('help'))
async def help_command_handler(message: Message) -> None:
    await message.answer(USAGE_TEXT)


@dispatcher.callback_query(F.data == 'check_subscription')
async def check_subscription_handler(callback: CallbackQuery) -> None:
    if not await is_channel_member(bot, callback.from_user.id):
        await callback.answer(
            "You haven't subscribed to the channel yet. Please subscribe first.",
            show_alert=True,
        )
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.delete()
        await callback.message.answer(
            '<b>Thank you!</b>\n\nYou can now use the bot — send a song name or a link.'
        )


@dispatcher.message(F.text & ~F.text.startswith('/'))
async def message_handler(message: Message, event_chat: Chat) -> None:
    query: str | None = message.text

    if not query:
        return None

    bot_message: Message = await message.reply('🎧 Looking for your track...')

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
