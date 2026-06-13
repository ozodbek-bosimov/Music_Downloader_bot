from musicbot.bot import bot, dispatcher
from musicbot.worker import run_tasks

import asyncio


async def main() -> None:
    await run_tasks()
    await dispatcher.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
