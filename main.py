import os
import sys

# Cap glibc malloc arenas BEFORE anything allocates. On Linux, Python opens a
# separate malloc arena per thread by default, which inflates RSS in threaded
# apps (our downloads run in worker threads) and gets the bot OOM-killed on a
# 256 MB host. Re-exec once with the limit applied. No effect on macOS/Windows.
if os.name == 'posix' and os.environ.get('MALLOC_ARENA_MAX') != '2':
    os.environ['MALLOC_ARENA_MAX'] = '2'
    os.environ.setdefault('MALLOC_TRIM_THRESHOLD_', '65536')
    os.execv(sys.executable, [sys.executable, *sys.argv])

from musicbot.bot import bot, dispatcher  # noqa: E402
from musicbot.worker import run_tasks  # noqa: E402

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
import asyncio  # noqa: E402


async def main() -> None:
    # Downloads are serialized by a semaphore, so a single worker thread is
    # enough. One thread means one malloc arena and the lowest possible memory
    # footprint, which keeps the bot alive on a small (~512 MB) host.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='worker')
    )
    await run_tasks()
    await dispatcher.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
