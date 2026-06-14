from sqlalchemy import TIMESTAMP, text
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from datetime import datetime


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'user'

    id: Mapped[int] = mapped_column(BIGINT(), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BIGINT(), unique=True, index=True)
    joined_date: Mapped[datetime] = mapped_column(
        TIMESTAMP(), server_default=text('NOW()')
    )


class DownloadQueue(Base):
    __tablename__ = 'download_queue'

    id: Mapped[int] = mapped_column(BIGINT(), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BIGINT())
    bot_message_id: Mapped[int] = mapped_column(BIGINT())
    user_message_id: Mapped[int] = mapped_column(BIGINT())
    query: Mapped[str] = mapped_column()
    queued_date: Mapped[datetime] = mapped_column(
        TIMESTAMP(), server_default=text('NOW()')
    )


class CachedTrack(Base):
    """Maps a normalized query to a Telegram audio file_id.

    Once a track has been sent, Telegram keeps the file on its servers and the
    file_id can be reused forever, so repeat requests are served instantly
    without touching YouTube at all (this also avoids YouTube rate-limiting).
    Only the tiny file_id string is stored — no audio is kept on disk.
    """

    __tablename__ = 'cached_track'

    id: Mapped[int] = mapped_column(BIGINT(), primary_key=True)
    query_key: Mapped[str] = mapped_column(unique=True, index=True)
    file_id: Mapped[str] = mapped_column()
    cached_date: Mapped[datetime] = mapped_column(
        TIMESTAMP(), server_default=text('NOW()')
    )
