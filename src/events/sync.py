"""Incremental synchronisation of events from the Events Provider API."""

import logging
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Event, Place, SyncMetadata
from .provider.paginator import FIRST_SYNC_DATE, EventsPaginator
from .services import get_client

logger = logging.getLogger(__name__)

# A "running" status older than this is treated as a crashed sync.
RUNNING_TIMEOUT = timedelta(hours=1)


def _parse_dt(value):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid datetime: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def save_event(payload):
    """Insert or update an event together with its place."""
    place_data = payload["place"]
    with transaction.atomic():
        Place.objects.update_or_create(
            id=place_data["id"],
            defaults={
                "name": place_data["name"],
                "city": place_data["city"],
                "address": place_data["address"],
                "seats_pattern": place_data["seats_pattern"],
                "changed_at": _parse_dt(place_data["changed_at"]),
                "created_at": _parse_dt(place_data["created_at"]),
            },
        )
        status_changed_at = payload.get("status_changed_at")
        event, _ = Event.objects.update_or_create(
            id=payload["id"],
            defaults={
                "name": payload["name"],
                "place_id": place_data["id"],
                "event_time": _parse_dt(payload["event_time"]),
                "registration_deadline": _parse_dt(payload["registration_deadline"]),
                "status": payload["status"],
                "number_of_visitors": payload["number_of_visitors"],
                "changed_at": _parse_dt(payload["changed_at"]),
                "created_at": _parse_dt(payload["created_at"]),
                "status_changed_at": (
                    _parse_dt(status_changed_at) if status_changed_at else None
                ),
            },
        )
    return event


def _acquire_lock():
    """Mark the sync as running. Returns (metadata, acquired)."""
    with transaction.atomic():
        meta, _ = SyncMetadata.objects.select_for_update().get_or_create(pk=1)
        now = timezone.now()
        is_running = (
            meta.sync_status == SyncMetadata.Status.RUNNING
            and meta.started_at is not None
            and now - meta.started_at < RUNNING_TIMEOUT
        )
        if is_running:
            return meta, False
        meta.sync_status = SyncMetadata.Status.RUNNING
        meta.started_at = now
        meta.save(update_fields=["sync_status", "started_at"])
    return meta, True


def _changed_since(meta):
    if meta.last_changed_at is None:
        return FIRST_SYNC_DATE
    # changed_at is a date for the provider, step one day back to be safe with
    # time zones. Upserts are idempotent so the overlap costs nothing.
    return (meta.last_changed_at - timedelta(days=1)).date()


def _finish(meta, status, last_changed_at=None, error=""):
    meta.sync_status = status
    meta.last_sync_time = timezone.now()
    meta.last_error = error
    update_fields = ["sync_status", "last_sync_time", "last_error"]
    if last_changed_at is not None:
        meta.last_changed_at = last_changed_at
        update_fields.append("last_changed_at")
    meta.save(update_fields=update_fields)


def run_sync(client=None):
    """Fetch new and changed events from the provider into the local DB.

    The first run loads everything (changed_at=2000-01-01), the next ones only
    what changed since the last successful run. Returns the sync metadata.
    """
    meta, acquired = _acquire_lock()
    if not acquired:
        logger.warning("Sync is already running, skipping this run.")
        return meta

    client = client or get_client()
    changed_since = _changed_since(meta)
    logger.info("Sync started, changed_at=%s", changed_since)

    latest = meta.last_changed_at
    saved = skipped = 0
    try:
        for payload in EventsPaginator(client, changed_since):
            try:
                event = save_event(payload)
            except (KeyError, TypeError, ValueError, ValidationError):
                skipped += 1
                logger.exception("Skipping malformed event: %.200r", payload)
                continue
            saved += 1
            if latest is None or event.changed_at > latest:
                latest = event.changed_at
    except Exception as exc:
        logger.exception("Sync failed")
        _finish(meta, SyncMetadata.Status.FAILED, error=str(exc))
        return meta

    _finish(meta, SyncMetadata.Status.SUCCESS, last_changed_at=latest)
    logger.info("Sync finished: saved=%s skipped=%s", saved, skipped)
    return meta
