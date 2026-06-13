from aiogram import BaseMiddleware
from aiogram.types import Update
from aiogram.types import User as TUser

from sqlalchemy import select

from musicbot.db import async_session
from musicbot.db.models import User

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[Update, dict[str, Any]], Awaitable[Any]]


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

        return await handler(event, data)
