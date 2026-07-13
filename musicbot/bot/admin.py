from __future__ import annotations

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from sqlalchemy import func, select

from musicbot import metrics
from musicbot.config import ADMIN_IDS
from musicbot.db import async_session
from musicbot.db.models import CachedTrack, DownloadQueue, User
from musicbot.downloader.client import pot_provider_reachable

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
        total_users: int = (
            await session.scalar(select(func.count()).select_from(User)) or 0
        )

        today_start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        new_today: int = (
            await session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.joined_date >= today_start)
            )
            or 0
        )

        cached_tracks: int = (
            await session.scalar(select(func.count()).select_from(CachedTrack)) or 0
        )

        queue_size: int = (
            await session.scalar(select(func.count()).select_from(DownloadQueue)) or 0
        )

    # Live download-source health (since the last restart) plus a direct check
    # of the PO-token provider, so a silent degrade to SoundCloud is visible.
    counts = metrics.snapshot()
    yt = counts.get(metrics.YOUTUBE, 0)
    sc = counts.get(metrics.SOUNDCLOUD, 0)
    failed = counts.get(metrics.NONE, 0)
    provider_up = await asyncio.to_thread(pot_provider_reachable)

    await message.answer(
        f'<b>Users:</b> {total_users:,} ({new_today} today)\n'
        f'<b>Cached tracks:</b> {cached_tracks:,}\n'
        f'<b>Download queue:</b> {queue_size:,}\n\n'
        f'<b>Downloads since restart:</b>\n'
        f'• YouTube: {yt:,}\n'
        f'• SoundCloud (fallback): {sc:,}\n'
        f'• Failed: {failed:,}\n'
        f'<b>PO-token provider:</b> {"🟢 up" if provider_up else "🔴 down"}'
    )


@router.message(Command('broadcast'))
async def broadcast_handler(message: Message, command: CommandObject, bot: Bot) -> None:
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
            (await session.scalars(select(User.telegram_id))).all()
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
