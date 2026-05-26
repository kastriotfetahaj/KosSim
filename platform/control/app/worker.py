"""Celery entrypoint for KosSim background workers."""

from __future__ import annotations

import os
from typing import Any

from celery import Celery

from .checker_jobs import run_checker_job
from .vulnboxes import run_vulnbox_action


def _broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://redis:6379/0")


def _result_backend() -> str:
    return os.getenv("CELERY_RESULT_BACKEND") or os.getenv("REDIS_URL", "redis://redis:6379/0")


celery_app = Celery("kossim", broker=_broker_url(), backend=_result_backend())
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    result_expires=int(os.getenv("CELERY_RESULT_EXPIRES", "86400")),
    task_acks_late=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_time_limit=int(os.getenv("CHECKER_TASK_HARD_TIME_LIMIT", "90")),
    task_soft_time_limit=int(os.getenv("CHECKER_TASK_SOFT_TIME_LIMIT", "75")),
)


@celery_app.task(name="app.worker.run_checker_job", bind=True)
def run_checker_job_task(self: Any, job_id: int) -> str:
    return run_checker_job(int(job_id), celery_task_id=getattr(self.request, "id", None))


@celery_app.task(name="app.worker.run_vulnbox_action", bind=True)
def run_vulnbox_action_task(self: Any, vulnbox_id: int, action: str) -> str:
    return run_vulnbox_action(
        int(vulnbox_id),
        str(action),
        celery_task_id=getattr(self.request, "id", None),
    )
