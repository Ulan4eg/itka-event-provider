import logging

from celery import shared_task

from .sync import run_sync

logger = logging.getLogger(__name__)


@shared_task(name="src.events.tasks.sync_events")
def sync_events():
    meta = run_sync()
    return meta.sync_status


def trigger_sync():
    """Queue a sync. If the broker is down, run it right here instead."""
    try:
        sync_events.apply_async(retry=False)
    except Exception:
        logger.exception("Cannot queue sync task, running it inline")
        run_sync()
