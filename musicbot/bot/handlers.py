from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Chat, Message, User

from musicbot.config import BOT_TOKEN
from musicbot.db import async_session
from musicbot.db.models import DownloadQueue

from .middlewares import CreateUserMiddleware
from .session import ResilientSession

bot = Bot(
    token=BOT_TOKEN,
    session=ResilientSession(),
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML, link_preview_is_disabled=True
    ),
)

dispatcher = Dispatcher(bot=bot)
dispatcher.update.middleware(CreateUserMiddleware())


@dispatcher.message(CommandStart())
async def start_command_handler(message: Message, event_from_user: User) -> None:
    await message.answer(
        (
            f'<b>Hi, {event_from_user.full_name}!</b>\n\n'
            "I'm a free Telegram bot that downloads music from YouTube.\n\n"
            'Just send me:\n'
            '• a song name (e.g. <code>Shakira Waka Waka</code>)\n'
            '• a YouTube link\n'
            '• a single Spotify <b>track</b> link\n\n'
            "You can also subscribe to @ozodbek, the developer's Telegram channel, "
            'to stay updated on news and other projects.\n\n'
            '<b>Note:</b> Spotify albums and playlists are not supported — '
            'send individual tracks or search by name.'
        ),
    )


@dispatcher.message()
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
