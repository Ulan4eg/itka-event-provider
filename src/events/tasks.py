import logging
import time

from celery import shared_task
from django.utils import timezone

from .models import SyncMetadata
from .sync import run_sync

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.5


@shared_task(name="src.events.tasks.sync_events")
def sync_events():
    meta = run_sync()
    return meta.sync_status


def _finished_since(started):
    meta = SyncMetadata.objects.filter(pk=1).first()
    return (
        meta is not None
        and meta.sync_status != SyncMetadata.Status.RUNNING
        and meta.last_sync_time is not None
        and meta.last_sync_time >= started
    )


def trigger_sync(wait=0.0):
    """Queue a sync and optionally wait for it to finish for up to ``wait`` s.

    If the broker is down, the sync runs right here instead.
    """
    started = timezone.now()
    try:
        sync_events.apply_async(retry=False)
    except Exception:
        logger.exception("Cannot queue sync task, running it inline")
        run_sync()
        return

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if _finished_since(started):
            return
        time.sleep(POLL_INTERVAL)
