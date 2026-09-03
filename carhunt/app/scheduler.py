"""Job orario: fa girare tutte le ricerche attive."""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from .pipeline import run_all

log = logging.getLogger(__name__)

JOB_ID = "carhunt-hourly"
_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    log.info("avvio giro programmato delle ricerche")
    results = run_all(notify=True)
    log.info("giro completato: %s", results)


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = BackgroundScheduler(timezone=str(datetime.now().astimezone().tzinfo))
    kwargs = {}
    if settings.run_on_start:
        # attenzione: passare next_run_time=None esplicitamente creerebbe il job in pausa
        kwargs["next_run_time"] = datetime.now()
    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(minutes=settings.interval_minutes),
        id=JOB_ID,
        name="Ricerca annunci auto",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        **kwargs,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler avviato: ogni %s minuti", settings.interval_minutes)
    return scheduler


def stop() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def next_run() -> str | None:
    if not _scheduler:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def trigger_now() -> None:
    """Anticipa il job programmato (usato dal pulsante 'Esegui adesso')."""
    if _scheduler:
        job = _scheduler.get_job(JOB_ID)
        if job:
            job.modify(next_run_time=datetime.now())
