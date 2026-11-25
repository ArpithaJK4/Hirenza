"""Optional: for always-on deployments (docker compose / EKS). The zero-cost setup uses
GitHub Actions cron instead and does not need Celery or Redis."""
from celery import Celery

from app.core.config import get_settings

s = get_settings()
celery = Celery("hirenza", broker=s.redis_url, backend=s.redis_url, include=["app.workers.tasks"])
celery.conf.update(
    task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=900, timezone="UTC",
    beat_schedule={"pipeline": {"task": "hirenza.pipeline", "schedule": 15 * 60}},
)
