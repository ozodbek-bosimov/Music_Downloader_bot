from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from musicbot.config import DATABASE_URL

# Settings tuned for a long-running bot on a small host:
# - pool_pre_ping: check a connection is alive before using it, so a link the
#   database closed while idle is transparently replaced instead of erroring.
# - pool_recycle: drop connections older than 30 min to stay under server-side
#   idle timeouts (PostgreSQL, PgBouncer, NAT/firewall).
# - small pool: this bot issues only light, short queries, so a few connections
#   are plenty and keep memory low.
async_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=5,
)
async_session = async_sessionmaker(async_engine, expire_on_commit=False)

__all__ = ['async_engine', 'async_session']
