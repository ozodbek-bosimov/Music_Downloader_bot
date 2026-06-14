from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from aiogram.types import User as TUser

from sqlalchemy import select

from musicbot.config import ADMIN_IDS, REQUIRED_CHANNEL
from musicbot.db import async_session
from musicbot.db.models import User

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[Update, dict[str, Any]], Awaitable[Any]]


async def is_channel_member(bot: Any, user_id: int) -> bool:
    """Whether the user is subscribed to REQUIRED_CHANNEL.

    Fails open (returns True) if the membership can't be checked — e.g. the bot
    isn't an admin of the channel — so the bot keeps working regardless.
    """
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
    except TelegramAPIError:
        return True
    return member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)


class CreateUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Handler,
        event: Update,  # type: ignore [override]
        data: dict[str, Any],
    ) -> Any:
        event_from_user: TUser | None = data.get('event_from_user')

        # Some updates (e.g. channel posts, polls) have no associated user.
        # There's nothing to create for them, so just pass through.
        if event_from_user is None:
            return await handler(event, data)

        user_telegram_id: int = event_from_user.id

        async with async_session() as session:
            user: User | None = await session.scalar(
                select(User).where(User.telegram_id == user_telegram_id)
            )
            is_new_user: bool = not user

            if is_new_user:
                user = User(telegram_id=user_telegram_id)

                session.add(user)
                await session.commit()
                await session.refresh(user)

        data['user'] = user
        data['is_new_user'] = is_new_user

        # Block banned users, but let admins through so /unban still works.
        if (
            user is not None
            and user.is_banned
            and user_telegram_id not in ADMIN_IDS
        ):
            if event.message:
                await event.message.answer(
                    'You have been banned from using this bot.'
                )
            return None

        return await handler(event, data)



class MembershipCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Handler,
        event: Update,  # type: ignore [override]
        data: dict[str, Any],
    ) -> Any:
        event_from_user: TUser | None = data.get('event_from_user')
        bot = data.get('bot')

        # Nothing to gate on: requirement disabled, no user, or no bot.
        if not REQUIRED_CHANNEL or event_from_user is None or bot is None:
            return await handler(event, data)

        # Always let the "verify" button through so users can re-check.
        if event.callback_query and event.callback_query.data == 'check_subscription':
            return await handler(event, data)

        # Admins are never blocked by the subscription gate.
        if event_from_user.id in ADMIN_IDS:
            return await handler(event, data)

        # Only gate private chats (ignore groups, channel posts, etc.).
        chat = None
        if event.message:
            chat = event.message.chat
        elif event.callback_query and isinstance(event.callback_query.message, Message):
            chat = event.callback_query.message.chat

        if chat is None or chat.type != 'private':
            return await handler(event, data)

        if await is_channel_member(bot, event_from_user.id):
            return await handler(event, data)

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text='Subscribe',
                        url=f'https://t.me/{REQUIRED_CHANNEL.lstrip("@")}',
                    )
                ],
                [
                    InlineKeyboardButton(
                        text='Verify', callback_data='check_subscription'
                    )
                ],
            ]
        )
        text = (
            '<b>Access denied</b>\n\n'
            f'To use this bot, please subscribe to {REQUIRED_CHANNEL} first.'
        )

        if event.message:
            await event.message.answer(text, reply_markup=keyboard)
        elif event.callback_query:
            if isinstance(event.callback_query.message, Message):
                await event.callback_query.message.answer(text, reply_markup=keyboard)
            await event.callback_query.answer()

        return None
