import asyncio
import logging
import os
import re

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special_chars) + r"])", r"\\\1", text)


async def send_message(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """Send a message to the configured Telegram chat.

    Returns True on success, False on failure.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    try:
        async with Bot(token=token) as bot:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        return True
    except TelegramError as e:
        logger.error("Telegram API error: %s", e)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = asyncio.run(send_message("Hello from FX brief bot 🚀", parse_mode=None))
    print("Sent:" if success else "Failed")
