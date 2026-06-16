"""
FastAPI application entrypoint.

Step 1 wires up:
  - lifespan startup that initialises the SQLite schema, and reserves the place
    where the Telegram long-polling task will be launched (step 8) so the bot
    runs in-process, sharing this event loop and DB.
  - a /health endpoint so you can verify the server runs.

Run endpoints (compare/debate, SSE) are added in later steps. The CORS config
allows the Vite dev server (localhost:5173) to talk to this during development.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.runs import router as runs_router
from app.api.threads import router as threads_router
from app.core.config import settings
from app.core.db import init_db
from app.telegram.bot import start_telegram_bot


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- startup ---
    init_db()

    # The Telegram app uses official async long-polling and stays inert unless
    # TELEGRAM_BOT_TOKEN plus TELEGRAM_ALLOWED_USER_ID are configured.
    telegram_bot = await start_telegram_bot()

    try:
        yield
    finally:
        # --- shutdown ---
        if telegram_bot is not None:
            with contextlib.suppress(Exception):
                await telegram_bot.stop()


app = FastAPI(title="multichat", lifespan=lifespan)

# Allow the local Vite dev server to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(runs_router)
app.include_router(threads_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check + confirms which models are currently configured."""
    return {
        "status": "ok",
        "anthropic_model": settings.anthropic_model_default,
        "openai_model": settings.openai_model_default,
        "gemini_model": settings.gemini_model_default,
        "synthesis_provider": settings.synthesis_provider,
    }
