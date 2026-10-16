"""Business logic of the aggregator. Views only call functions from here."""

import logging
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .exceptions import BusinessError, NotFoundError, UpstreamError
from .models import Event, EventStatus, Ticket
from .provider.client import EventsProviderClient
from .provider.exceptions import (
    ProviderBadRequestError,
    ProviderError,
    ProviderNotFoundError,
)
from .seats import seat_exists

logger = logging.getLogger(__name__)


def get_client():
    return EventsProviderClient(
        base_url=settings.EVENTS_PROVIDER_URL,
        api_key=settings.EVENTS_PROVIDER_API_KEY,
        timeout=settings.EVENTS_PROVIDER_TIMEOUT,
    )


@contextmanager
def translated_provider_errors():
    """Turn provider exceptions into API exceptions with proper HTTP codes."""
    try:
        yield
    except ProviderBadRequestError as exc:
        raise BusinessError(str(exc)) from exc
    except ProviderNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except ProviderError as exc:
        logger.error("Events Provider error: %s", exc)
        raise UpstreamError() from exc


def list_events(date_from=None):
    queryset = Event.objects.select_related("place")
    if date_from is not None:
        queryset = queryset.filter(event_time__date__gte=date_from)
    return queryset.order_by("event_time", "id")


def get_event(event_id):
    try:
        event = Event.objects.select_related("place").filter(pk=event_id).first()
    except (ValidationError, ValueError):
        event = None
    if event is None:
        raise NotFoundError("Event not found.")
    return event


def _seats_cache_key(event_id):
    return f"event-seats:{event_id}"


def _load_seats(event, use_cache):
    if event.status != EventStatus.PUBLISHED:
        # The provider answers 500 for such events, so we never ask it.
        raise BusinessError("Event is not published, seats are unavailable.")
    key = _seats_cache_key(event.id)
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached
    with translated_provider_errors():
        seats = get_client().seats(event.id)
    cache.set(key, seats, settings.SEATS_CACHE_TTL)
    return seats


def get_available_seats(event_id):
    return _load_seats(get_event(event_id), use_cache=True)


def register_ticket(event_id, first_name, last_name, email, seat):
    event = get_event(event_id)
    if event.status != EventStatus.PUBLISHED:
        raise BusinessError("Registration is not open for this event.")
    if timezone.now() >= event.registration_deadline:
        raise BusinessError("Registration deadline has passed.")

    try:
        exists = seat_exists(event.place.seats_pattern, seat)
    except ValueError:
        exists = True  # unknown pattern format - let the provider decide
    if not exists:
        raise BusinessError(f"Seat {seat} does not exist at this venue.")

    # Always check against fresh data, the cache may be up to 30s old.
    if seat not in _load_seats(event, use_cache=False):
        raise BusinessError(f"Seat {seat} is not available.")

    with translated_provider_errors():
        ticket_id = get_client().register(
            event.id, first_name, last_name, email, seat
        )

    with transaction.atomic():
        # Same seat -> same ticket id, so a cancelled ticket gets reactivated.
        ticket, _ = Ticket.objects.update_or_create(
            ticket_id=ticket_id,
            defaults={
                "event": event,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
                "status": Ticket.Status.ACTIVE,
                "cancelled_at": None,
            },
        )
        Event.objects.filter(pk=event.pk).update(
            number_of_visitors=F("number_of_visitors") + 1
        )
    cache.delete(_seats_cache_key(event.id))
    return ticket


def cancel_ticket(ticket_id):
    ticket = (
        Ticket.objects.select_related("event")
        .filter(pk=ticket_id, status=Ticket.Status.ACTIVE)
        .first()
    )
    if ticket is None:
        raise NotFoundError("Ticket not found.")
    event = ticket.event
    if event.event_time <= timezone.now():
        raise BusinessError("Event has already taken place.")

    with translated_provider_errors():
        get_client().unregister(event.id, ticket.ticket_id)

    with transaction.atomic():
        ticket.status = Ticket.Status.CANCELLED
        ticket.cancelled_at = timezone.now()
        ticket.save(update_fields=["status", "cancelled_at"])
        Event.objects.filter(pk=event.pk, number_of_visitors__gt=0).update(
            number_of_visitors=F("number_of_visitors") - 1
        )
    cache.delete(_seats_cache_key(event.id))
