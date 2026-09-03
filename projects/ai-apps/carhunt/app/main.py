"""Entry point FastAPI: API + webapp statica + scheduler."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .api import router
from .config import settings
from .db import init_db

logging.basicConfig(
    level=os.getenv("CARHUNT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("carhunt")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.start()
    log.info(
        "Carhunt pronto — ricerche ogni %s minuti, Telegram %s",
        settings.interval_minutes,
        "attivo" if settings.telegram_enabled else "NON configurato",
    )
    yield
    scheduler.stop()


app = FastAPI(title="Carhunt", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "telegram": settings.telegram_enabled,
        "interval_minutes": settings.interval_minutes,
        "next_run": scheduler.next_run(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
