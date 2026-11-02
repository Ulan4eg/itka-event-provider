from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone

from src.events import services
from src.events.models import IdempotencyKey, OutboxMessage, Ticket
from src.events.provider.exceptions import (
    ProviderBadRequestError,
    ProviderUnavailableError,
)

pytestmark = pytest.mark.django_db


def body(event, **overrides):
    data = {
        "event_id": str(event.id),
        "first_name": "Ivan",
        "last_name": "Ivanov",
        "email": "ivan@example.com",
        "seat": "A5",
    }
    data.update(overrides)
    return data


@pytest.fixture
def provider():
    with patch("src.events.services.get_client") as get_client:
        client = get_client.return_value
        client.seats.return_value = ["A4", "A5", "A6"]
        client.register.return_value = str(uuid4())
        yield client


def post(api, payload):
    return api.post("/api/tickets", payload, format="json")


def test_registration_creates_outbox_row_with_the_ticket(api, make_event, provider):
    event = make_event(name="Python Conf")

    response = post(api, body(event))

    assert response.status_code == 201
    message = OutboxMessage.objects.get()
    assert message.status == OutboxMessage.Status.PENDING
    assert message.event_type == "ticket_purchased"
    assert message.payload["ticket_id"] == response.json()["ticket_id"]
    assert message.payload["event_name"] == "Python Conf"
    assert message.payload["seat"] == "A5"


def test_ticket_and_outbox_row_are_saved_atomically(api, make_event, provider):
    event = make_event()

    with patch(
        "src.events.services.enqueue_ticket_purchased",
        side_effect=RuntimeError("db failure"),
    ):
        with pytest.raises(RuntimeError):
            post(api, body(event))

    assert Ticket.objects.count() == 0
    assert OutboxMessage.objects.count() == 0
    event.refresh_from_db()
    assert event.number_of_visitors == 0


def test_failed_registration_creates_no_outbox_row(api, make_event, provider):
    event = make_event()
    provider.register.side_effect = ProviderBadRequestError("sold")

    response = post(api, body(event))

    assert response.status_code == 400
    assert OutboxMessage.objects.count() == 0


def test_same_key_returns_same_ticket_without_calling_provider(
    api, make_event, provider
):
    event = make_event()
    payload = body(event, idempotency_key="key-1")

    first = post(api, payload)
    second = post(api, payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    provider.register.assert_called_once()
    assert Ticket.objects.count() == 1
    assert OutboxMessage.objects.count() == 1
    event.refresh_from_db()
    assert event.number_of_visitors == 1


def test_retry_works_even_if_the_seat_is_taken_now(api, make_event, provider):
    event = make_event()
    payload = body(event, idempotency_key="key-1")
    first = post(api, payload)
    provider.seats.return_value = []  # A5 is not free anymore - we hold it

    second = post(api, payload)

    assert second.status_code == 201
    assert second.json() == first.json()


@pytest.mark.parametrize(
    "overrides",
    [
        {"seat": "A6"},
        {"email": "other@example.com"},
        {"first_name": "Petr"},
        {"last_name": "Petrov"},
    ],
)
def test_same_key_with_other_data_is_a_conflict(api, make_event, provider, overrides):
    event = make_event()
    first = post(api, body(event, idempotency_key="key-1"))

    response = post(api, body(event, idempotency_key="key-1", **overrides))

    assert response.status_code == 409
    provider.register.assert_called_once()
    assert Ticket.objects.count() == 1
    saved = IdempotencyKey.objects.get(key="key-1")
    assert str(saved.ticket_id) == first.json()["ticket_id"]


def test_same_key_with_other_event_is_a_conflict(api, make_event, provider):
    event = make_event()
    other_event = make_event(name="Other")
    post(api, body(event, idempotency_key="key-1"))

    response = post(api, body(other_event, idempotency_key="key-1"))

    assert response.status_code == 409


def test_different_keys_are_independent(api, make_event, provider):
    event = make_event()
    provider.register.side_effect = [str(uuid4()), str(uuid4())]

    first = post(api, body(event, seat="A4", idempotency_key="key-1"))
    second = post(api, body(event, seat="A5", idempotency_key="key-2"))

    assert first.status_code == second.status_code == 201
    assert first.json() != second.json()
    assert Ticket.objects.count() == 2


def test_without_key_every_request_is_new(api, make_event, provider):
    event = make_event()
    provider.register.side_effect = [str(uuid4()), str(uuid4())]

    first = post(api, body(event))
    second = post(api, body(event))

    assert first.json() != second.json()
    assert provider.register.call_count == 2
    assert IdempotencyKey.objects.count() == 0


@pytest.mark.parametrize(
    "error", [ProviderBadRequestError("sold"), ProviderUnavailableError("down")]
)
def test_provider_error_does_not_store_the_key(api, make_event, provider, error):
    event = make_event()
    payload = body(event, idempotency_key="key-1")
    provider.register.side_effect = error

    failed = post(api, payload)

    assert failed.status_code in (400, 502)
    assert IdempotencyKey.objects.count() == 0

    ticket_id = str(uuid4())
    provider.register.side_effect = None
    provider.register.return_value = ticket_id
    retry = post(api, payload)

    assert retry.status_code == 201
    assert retry.json() == {"ticket_id": ticket_id}
    assert str(IdempotencyKey.objects.get().ticket_id) == ticket_id


def test_expired_key_is_treated_as_new(api, make_event, provider, settings):
    settings.IDEMPOTENCY_KEY_TTL_HOURS = 1
    event = make_event()
    payload = body(event, idempotency_key="key-1")
    post(api, payload)
    IdempotencyKey.objects.update(created_at=timezone.now() - timedelta(hours=2))
    new_ticket_id = str(uuid4())
    provider.register.return_value = new_ticket_id

    response = post(api, payload)

    assert response.status_code == 201
    assert response.json() == {"ticket_id": new_ticket_id}
    assert provider.register.call_count == 2


def test_purge_expired_keys(api, make_event, provider, settings):
    settings.IDEMPOTENCY_KEY_TTL_HOURS = 1
    event = make_event()
    provider.register.side_effect = [str(uuid4()), str(uuid4())]
    post(api, body(event, seat="A4", idempotency_key="old"))
    post(api, body(event, seat="A5", idempotency_key="fresh"))
    IdempotencyKey.objects.filter(key="old").update(
        created_at=timezone.now() - timedelta(hours=2)
    )

    deleted = services.purge_expired_idempotency_keys()

    assert deleted == 1
    assert list(IdempotencyKey.objects.values_list("key", flat=True)) == ["fresh"]


@pytest.mark.parametrize("key", ["", "x" * 256, None, [], {}])
def test_invalid_key_is_rejected(api, make_event, provider, key):
    event = make_event()

    response = post(api, body(event, idempotency_key=key))

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_sentry_debug_endpoint_is_hidden_by_default(api):
    assert api.get("/api/debug/sentry-error").status_code == 404


def test_sentry_debug_endpoint_raises_when_enabled(api, settings):
    settings.SENTRY_DEBUG_ENDPOINT = True

    with pytest.raises(RuntimeError):
        api.get("/api/debug/sentry-error")
