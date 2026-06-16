from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.core.config import settings
from app.telegram.runner import TelegramCommand, run_telegram_discussion

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Send one of:\n"
    "compare: your prompt\n"
    "debate 2: your prompt\n"
    "relay: your prompt"
)

MAX_TELEGRAM_MESSAGE = 3900
DEBATE_RE = re.compile(r"^debate(?:\s+(\d+))?\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
MODE_RE = re.compile(r"^(compare|relay)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


@dataclass
class TelegramBotHandle:
    application: Application

    async def stop(self) -> None:
        if self.application.updater is not None:
            with contextlib.suppress(TelegramError):
                await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()


def parse_telegram_command(text: str) -> TelegramCommand | None:
    text = text.strip()
    if not text or text.startswith("/"):
        return None

    debate_match = DEBATE_RE.match(text)
    if debate_match:
        rounds = int(debate_match.group(1) or "2")
        rounds = max(1, min(rounds, 5))
        prompt = debate_match.group(2).strip()
        return TelegramCommand(mode="debate", prompt=prompt, rounds=rounds) if prompt else None

    mode_match = MODE_RE.match(text)
    if mode_match:
        mode = mode_match.group(1).lower()
        prompt = mode_match.group(2).strip()
        if mode in {"compare", "relay"} and prompt:
            return TelegramCommand(mode=mode, prompt=prompt)  # type: ignore[arg-type]
        return None

    return TelegramCommand(mode="compare", prompt=text)


def _is_allowed(update: Update) -> bool:
    user = update.effective_user
    return (
        settings.telegram_allowed_user_id is not None
        and user is not None
        and user.id == settings.telegram_allowed_user_id
    )


def _message_chunks(title: str, body: str) -> list[str]:
    text = f"{title}\n\n{body}".strip()
    if len(text) <= MAX_TELEGRAM_MESSAGE:
        return [text]

    chunks: list[str] = []
    while text:
        chunk = text[:MAX_TELEGRAM_MESSAGE]
        split_at = chunk.rfind("\n\n")
        if split_at < MAX_TELEGRAM_MESSAGE // 2:
            split_at = len(chunk)
        chunks.append(chunk[:split_at].strip())
        text = text[split_at:].strip()
    return chunks


async def _send_chunks(context: ContextTypes.DEFAULT_TYPE, chat_id: int, title: str, body: str) -> None:
    for chunk in _message_chunks(title, body):
        await context.bot.send_message(chat_id=chat_id, text=chunk)


async def _help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.effective_chat is None:
        return
    await context.bot.send_message(chat_id=update.effective_chat.id, text=HELP_TEXT)


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update) or update.message is None or update.effective_chat is None:
        return

    command = parse_telegram_command(update.message.text or "")
    if command is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=HELP_TEXT)
        return

    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Queued {command.mode}. I will post results here.",
    )
    context.application.create_task(_run_and_send(command, context, chat_id))


async def _run_and_send(
    command: TelegramCommand,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    try:
        async for result in run_telegram_discussion(command):
            await _send_chunks(context, chat_id, result.title, result.body)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Telegram discussion failed.")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Run failed. Check the backend logs.",
        )


def _polling_error(exc: TelegramError) -> None:
    logger.warning("Telegram polling error: %s", exc)


async def start_telegram_bot() -> TelegramBotHandle | None:
    if not settings.telegram_bot_token:
        return None

    if settings.telegram_allowed_user_id is None:
        logger.warning("TELEGRAM_BOT_TOKEN is set but TELEGRAM_ALLOWED_USER_ID is missing; bot disabled.")
        return None

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .build()
    )
    application.add_handler(CommandHandler(["start", "help"], _help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

    await application.initialize()
    if application.updater is None:
        await application.shutdown()
        raise RuntimeError("Telegram application was built without an updater.")

    await application.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
        error_callback=_polling_error,
    )
    await application.start()
    logger.info("Telegram bot started.")
    return TelegramBotHandle(application=application)
