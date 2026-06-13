from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from musicbot.config import CACHE_MAX_ENTRIES
from musicbot.db import async_session
from musicbot.db.models import CachedTrack

import logging

logger = logging.getLogger(__name__)


def cache_key(query: str) -> str:
    """Normalize a query so equivalent requests share one cache entry."""
    return ' '.join(query.split()).lower()


async def get_cached_file_id(query: str) -> str | None:
    """Return a cached Telegram file_id for this query, or None.

    Best-effort: any error is logged and treated as a cache miss so the normal
    download path still runs.
    """
    try:
        async with async_session() as session:
            return await session.scalar(
                select(CachedTrack.file_id).where(
                    CachedTrack.query_key == cache_key(query)
                )
            )
    except Exception:
        logger.exception('Cache lookup failed')
        return None


async def store_file_id(query: str, file_id: str) -> None:
    """Remember the file_id for this query. Best-effort: errors are ignored.

    Keeps at most CACHE_MAX_ENTRIES rows by dropping the oldest ones, so the
    table can never grow without bound.
    """
    try:
        async with async_session() as session:
            await session.execute(
                pg_insert(CachedTrack)
                .values(query_key=cache_key(query), file_id=file_id)
                .on_conflict_do_nothing(index_elements=['query_key'])
            )

            # Drop the oldest rows beyond the cap so the table stays bounded.
            await session.execute(
                delete(CachedTrack).where(
                    CachedTrack.id.not_in(
                        select(CachedTrack.id)
                        .order_by(CachedTrack.id.desc())
                        .limit(CACHE_MAX_ENTRIES)
                    )
                )
            )

            await session.commit()
    except Exception:
        logger.exception('Cache store failed')
