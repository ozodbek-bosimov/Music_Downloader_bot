from __future__ import annotations

import os
import sys

# On Linux, cap glibc malloc arenas to reduce RSS waste from thread-local
# heaps. Not needed for macOS/Windows. Once set, re-exec so the environment
# variable applies to all subsequent allocations.
if os.name == 'posix' and os.environ.get('MALLOC_ARENA_MAX') != '4':
    os.environ['MALLOC_ARENA_MAX'] = '4'
    os.execv(sys.executable, [sys.executable, *sys.argv])

from musicbot.bot import bot, dispatcher  # noqa: E402
from musicbot.worker import run_tasks  # noqa: E402

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
import asyncio  # noqa: E402


async def main() -> None:
    # A pool of 4 threads matches MAX_PARALLEL_DOWNLOADS default, so downloads
    # can run truly in parallel across threads.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=4, thread_name_prefix='worker')
    )
    await run_tasks()
    await dispatcher.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
