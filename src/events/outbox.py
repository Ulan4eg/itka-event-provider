"""Transactional outbox: enqueueing and the background delivery worker.

* ``enqueue`` is called inside the same DB transaction as the business change,
  so either both are saved or both are rolled back.
* ``process_next`` / ``process_batch`` deliver pending rows (one DB transaction
  per row, ``SELECT ... FOR UPDATE SKIP LOCKED`` so several workers never take
  the same row).
* ``run_worker`` is the coroutine that calls them periodically;
  ``start_background_worker`` runs it inside the web process.

Delivery is at-least-once. A crash between the HTTP call and the commit leads to
a repeated call, which is harmless because Capashino gets a stable
idempotency key (derived from the outbox row id).
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import OutboxMessage
from .notifications import CapashinoClient, NotificationRejectedError

logger = logging.getLogger(__name__)

TICKET_PURCHASED = "ticket_purchased"


# --- producing ---------------------------------------------------------------
def enqueue(event_type, payload):
    """Save an outbox row. Call it inside the caller's ``transaction.atomic()``."""
    return OutboxMessage.objects.create(event_type=event_type, payload=payload)


def enqueue_ticket_purchased(ticket):
    """Outbox row with everything needed to notify the user about the ticket."""
    event = ticket.event
    return enqueue(
        TICKET_PURCHASED,
        {
            "ticket_id": str(ticket.ticket_id),
            "event_id": str(event.id),
            "event_name": event.name,
            "event_time": event.event_time.isoformat(),
            "place_name": event.place.name,
            "seat": ticket.seat,
            "first_name": ticket.first_name,
            "last_name": ticket.last_name,
            "email": ticket.email,
        },
    )


# --- handlers ----------------------------------------------------------------
def get_notification_client():
    if not settings.CAPASHINO_API_TOKEN:
        logger.warning("CAPASHINO_API_TOKEN is empty, Capashino will answer 401")
    return CapashinoClient(
        base_url=settings.CAPASHINO_URL,
        api_token=settings.CAPASHINO_API_TOKEN,
        timeout=settings.CAPASHINO_TIMEOUT,
    )


def build_ticket_message(payload):
    """Text of the notification, built from the outbox payload."""
    parts = [f"Вы успешно зарегистрированы на мероприятие - {payload['event_name']}"]
    event_time = parse_datetime(payload.get("event_time") or "")
    if event_time is not None:
        if timezone.is_aware(event_time):
            event_time = timezone.localtime(event_time)
        parts.append(f"дата: {event_time:%d.%m.%Y %H:%M}")
    if payload.get("place_name"):
        parts.append(f"место проведения: {payload['place_name']}")
    parts.append(f"место в зале: {payload['seat']}")
    return ", ".join(parts) + "."


def _send_ticket_purchased(message):
    payload = message.payload
    get_notification_client().create_notification(
        message=build_ticket_message(payload),
        reference_id=payload["ticket_id"],
        # Stable for this row, so a repeated delivery never duplicates it.
        idempotency_key=f"ticket-purchased-{message.id}",
    )


HANDLERS = {TICKET_PURCHASED: _send_ticket_purchased}


# --- consuming ---------------------------------------------------------------
def _retry_delay(attempts):
    delay = settings.OUTBOX_RETRY_BASE_DELAY * (2 ** (attempts - 1))
    return timedelta(seconds=min(delay, settings.OUTBOX_RETRY_MAX_DELAY))


def _mark_failed_attempt(message, error, permanent):
    message.attempts += 1
    message.last_error = str(error)[:1000]
    if permanent or message.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
        message.status = OutboxMessage.Status.FAILED
        logger.error(
            "Outbox message %s (%s) given up after %s attempt(s): %s",
            message.id,
            message.event_type,
            message.attempts,
            error,
        )
    else:
        message.next_attempt_at = timezone.now() + _retry_delay(message.attempts)
        logger.warning(
            "Outbox message %s (%s) failed, attempt %s/%s: %s",
            message.id,
            message.event_type,
            message.attempts,
            settings.OUTBOX_MAX_ATTEMPTS,
            error,
        )


def process_next():
    """Deliver one pending message.

    Returns ``None`` if there is nothing to do, ``True`` if the message was
    delivered and ``False`` if the attempt failed (retry or give up).
    """
    with transaction.atomic():
        message = (
            OutboxMessage.objects.select_for_update(skip_locked=True)
            .filter(
                status=OutboxMessage.Status.PENDING,
                next_attempt_at__lte=timezone.now(),
            )
            .order_by("created_at")
            .first()
        )
        if message is None:
            return None

        handler = HANDLERS.get(message.event_type)
        delivered = False
        if handler is None:
            _mark_failed_attempt(
                message, f"Unknown event type {message.event_type!r}", permanent=True
            )
        else:
            try:
                handler(message)
            except NotificationRejectedError as exc:
                _mark_failed_attempt(message, exc, permanent=True)
            except Exception as exc:  # any other failure means "retry later"
                _mark_failed_attempt(message, exc, permanent=False)
            else:
                delivered = True
                message.status = OutboxMessage.Status.SENT
                message.sent_at = timezone.now()
                message.last_error = ""
                logger.info("Outbox message %s sent", message.id)
        message.save(
            update_fields=[
                "status",
                "attempts",
                "last_error",
                "next_attempt_at",
                "sent_at",
            ]
        )
    return delivered


def process_batch(limit=None):
    """Deliver up to ``limit`` messages. Returns how many rows were handled.

    Stops at the first failed delivery: most likely the receiver is down and
    hammering it with the other messages would only waste time.
    """
    limit = limit or settings.OUTBOX_BATCH_SIZE
    handled = 0
    try:
        while handled < limit:
            result = process_next()
            if result is None:
                break
            handled += 1
            if result is False:
                break
    finally:
        close_old_connections()
    return handled


# --- the worker --------------------------------------------------------------
async def run_worker(stop=None):
    """Poll the outbox until ``stop`` (an ``asyncio.Event``) is set.

    The Django ORM and ``requests`` are blocking, so every batch runs in a
    dedicated single thread and the event loop stays free.
    """
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="outbox-db")
    logger.info("Outbox worker started")
    try:
        while stop is None or not stop.is_set():
            try:
                handled = await loop.run_in_executor(executor, process_batch)
            except Exception:
                logger.exception("Outbox worker iteration failed")
                handled = 0
            if not handled:
                await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL)
    finally:
        executor.shutdown(wait=False)
        logger.info("Outbox worker stopped")


_worker_thread = None
_worker_lock = threading.Lock()


def start_background_worker():
    """Run ``run_worker`` as a coroutine in a daemon thread of this process."""
    global _worker_thread
    if not settings.OUTBOX_WORKER_ENABLED:
        logger.info("Outbox worker is disabled (OUTBOX_WORKER_ENABLED=false)")
        return None
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return _worker_thread
        _worker_thread = threading.Thread(
            target=lambda: asyncio.run(run_worker()),
            name="outbox-worker",
            daemon=True,
        )
        _worker_thread.start()
    return _worker_thread
