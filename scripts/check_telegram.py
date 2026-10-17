"""Telegram connectivity checkpoint.

Verifies the bot token via getMe and that a test message is delivered to every
whitelisted chat id (catches wrong/missing chat ids, blocked bot, bad token).
Prints a PASS/FAIL summary and exits non-zero on failure.

Requires a filled-in .env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS.
"""

import asyncio

from telegram import Bot
from telegram.error import TelegramError

from email_agent.config import Settings
from email_agent.utils.helpers import ensure_utf8_stdout

TEST_MESSAGE = (
    "email-ai-agent: Telegram connectivity check passed.\n"
    "Real emails will arrive here with Delete / Archive / Keep buttons."
)


async def main() -> None:
    ensure_utf8_stdout()
    settings = Settings()
    chat_ids = settings.chat_id_whitelist

    async with Bot(settings.telegram_bot_token) as bot:
        try:
            me = await bot.get_me()
        except TelegramError as exc:
            print(f"Bot: FAIL - {exc}")
            raise SystemExit(1)
        print(f"Bot:   PASS - @{me.username} (id={me.id}, name={me.first_name})")
        print(f"       (that id is the BOT's own id - it must NOT be in TELEGRAM_CHAT_IDS)")

        if not chat_ids:
            print("Chats: FAIL - TELEGRAM_CHAT_IDS is empty")
            raise SystemExit(1)
        print(f"Chats: {sorted(chat_ids)} (notifications go to {settings.primary_chat_id})")

        ok = True
        for chat_id in sorted(chat_ids):
            try:
                message = await bot.send_message(chat_id=chat_id, text=TEST_MESSAGE)
                print(f"  chat {chat_id}: PASS (message_id={message.message_id})")
            except TelegramError as exc:
                ok = False
                print(f"  chat {chat_id}: FAIL - {exc}")

        if not ok:
            print("\nTELEGRAM_CHAT_IDS must be YOUR chat id (or a group's), not the bot's id.")
            print("To find it: send any message (e.g. /start) to the bot in Telegram, then re-run this script.")
            await _print_candidate_chats(bot)

    print("Telegram check PASSED" if ok else "Telegram check FAILED")
    raise SystemExit(0 if ok else 1)


async def _print_candidate_chats(bot: Bot) -> None:
    try:
        updates = await bot.get_updates()
    except TelegramError as exc:
        print(f"(could not read the bot's update queue: {exc})")
        return
    candidates: set[int] = set()
    for update in updates:
        message = update.message or (update.callback_query.message if update.callback_query else None)
        if message is not None and message.chat is not None:
            candidates.add(message.chat.id)
    if candidates:
        print(f"Chats that have messaged your bot: {sorted(candidates)}")
        print("Put one of these ids in TELEGRAM_CHAT_IDS in .env and re-run.")
    else:
        print("No messages found in the bot's update queue yet - send /start to the bot first.")


if __name__ == "__main__":
    asyncio.run(main())
