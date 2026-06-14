from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from sqlalchemy import func, select

from musicbot.config import ADMIN_IDS
from musicbot.db import async_session
from musicbot.db.models import CachedTrack, DownloadQueue, User

from datetime import UTC, datetime
import asyncio
import logging

logger = logging.getLogger(__name__)

router = Router()


def _is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in ADMIN_IDS


@router.message(Command('stats'))
async def stats_handler(message: Message) -> None:
    if not _is_admin(message):
        return

    async with async_session() as session:
        total_users: int = await session.scalar(
            select(func.count()).select_from(User)
        ) or 0

        today_start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        new_today: int = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.joined_date >= today_start)
        ) or 0

        banned_users: int = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_banned.is_(True))
        ) or 0

        cached_tracks: int = await session.scalar(
            select(func.count()).select_from(CachedTrack)
        ) or 0

        queue_size: int = await session.scalar(
            select(func.count()).select_from(DownloadQueue)
        ) or 0

    await message.answer(
        f'<b>Users:</b> {total_users:,} ({new_today} today)\n'
        f'<b>Banned:</b> {banned_users:,}\n'
        f'<b>Cached tracks:</b> {cached_tracks:,}\n'
        f'<b>Download queue:</b> {queue_size:,}'
    )


@router.message(Command('broadcast'))
async def broadcast_handler(
    message: Message, command: CommandObject, bot: Bot
) -> None:
    if not _is_admin(message):
        return

    # Two ways to broadcast:
    #   /broadcast your text here   -> sends that text to everyone
    #   reply to a message + /broadcast -> copies that message to everyone
    source = message.reply_to_message
    text = (command.args or '').strip()

    if source is None and not text:
        await message.answer(
            'To broadcast, either:\n'
            '• send <code>/broadcast your message here</code>, or\n'
            '• reply to any message with <code>/broadcast</code>.'
        )
        return

    async with async_session() as session:
        user_ids: list[int] = list(
            (
                await session.scalars(
                    select(User.telegram_id).where(User.is_banned.is_(False))
                )
            ).all()
        )

    sent = 0
    failed = 0
    progress = await message.answer(f'Broadcasting to {len(user_ids):,} users...')

    for uid in user_ids:
        try:
            if source is not None:
                await source.copy_to(chat_id=uid)
            else:
                await bot.send_message(chat_id=uid, text=text)
            sent += 1
        except TelegramAPIError:
            failed += 1

        # Telegram allows ~30 messages/second to different chats.
        # A small delay keeps us well under the limit.
        if (sent + failed) % 25 == 0:
            await asyncio.sleep(1)

    await progress.edit_text(
        f'Broadcast complete: {sent:,} delivered, {failed:,} failed.'
    )


@router.message(Command('ban'))
async def ban_handler(message: Message) -> None:
    if not _is_admin(message):
        return

    args = (message.text or '').split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer('Usage: /ban &lt;telegram_user_id&gt;')
        return

    target_id = int(args[1])

    async with async_session() as session:
        user: User | None = await session.scalar(
            select(User).where(User.telegram_id == target_id)
        )
        if not user:
            await message.answer(f'User {target_id} not found.')
            return

        user.is_banned = True
        await session.commit()

    await message.answer(f'User {target_id} has been banned.')


@router.message(Command('unban'))
async def unban_handler(message: Message) -> None:
    if not _is_admin(message):
        return

    args = (message.text or '').split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer('Usage: /unban &lt;telegram_user_id&gt;')
        return

    target_id = int(args[1])

    async with async_session() as session:
        user: User | None = await session.scalar(
            select(User).where(User.telegram_id == target_id)
        )
        if not user:
            await message.answer(f'User {target_id} not found.')
            return

        user.is_banned = False
        await session.commit()

    await message.answer(f'User {target_id} has been unbanned.')
