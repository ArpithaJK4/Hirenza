from app.core.db import session_scope
from app.workers.celery_app import celery
from app.workers.pipeline import run_pipeline


@celery.task(name="hirenza.pipeline", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def pipeline_task(force: bool = False):
    with session_scope() as db:
        return run_pipeline(db, trigger="celery", force=force)
