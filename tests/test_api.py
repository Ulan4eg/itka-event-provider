from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone

from src.events.models import Ticket
from src.events.provider.exceptions import (
    ProviderBadRequestError,
    ProviderUnavailableError,
)

pytestmark = pytest.mark.django_db


def registration_body(event, **overrides):
    body = {
        "event_id": str(event.id),
        "first_name": "Ivan",
        "last_name": "Ivanov",
        "email": "ivan@example.com",
        "seat": "A5",
    }
    body.update(overrides)
    return body


@pytest.fixture
def provider():
    with patch("src.events.services.get_client") as get_client:
        yield get_client.return_value


def test_health(api):
    response = api.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sync_trigger(api):
    with patch("src.events.views.trigger_sync") as trigger:
        response = api.post("/api/sync/trigger")

    assert response.status_code == 200
    trigger.assert_called_once()


def test_event_list_pagination_and_shape(api, make_event):
    for _ in range(3):
        make_event()

    response = api.get("/api/events", {"page_size": 2})

    data = response.json()
    assert response.status_code == 200
    assert data["count"] == 3
    assert len(data["results"]) == 2
    assert data["previous"] is None
    assert "page=2" in data["next"]
    item = data["results"][0]
    assert set(item) == {
        "id",
        "name",
        "place",
        "event_time",
        "registration_deadline",
        "status",
        "number_of_visitors",
    }
    assert set(item["place"]) == {"id", "name", "city", "address"}


def test_event_list_date_from_filter(api, make_event):
    now = timezone.now()
    make_event(name="soon", event_time=now + timedelta(days=2))
    make_event(name="later", event_time=now + timedelta(days=30))
    date_from = (now + timedelta(days=10)).date().isoformat()

    response = api.get("/api/events", {"date_from": date_from})

    assert [item["name"] for item in response.json()["results"]] == ["later"]


def test_event_list_invalid_date(api):
    response = api.get("/api/events", {"date_from": "yesterday"})

    assert response.status_code == 400


def test_event_detail(api, make_event):
    event = make_event()

    response = api.get(f"/api/events/{event.id}")

    assert response.status_code == 200
    assert response.json()["place"]["seats_pattern"] == "A1-10,B1-5"


def test_event_detail_not_found(api):
    response = api.get(f"/api/events/{uuid4()}")

    assert response.status_code == 404


def test_seats_are_fetched_from_provider_and_cached(api, make_event, provider):
    event = make_event()
    provider.seats.return_value = ["A1", "A2"]

    first = api.get(f"/api/events/{event.id}/seats")
    second = api.get(f"/api/events/{event.id}/seats")

    assert first.status_code == 200
    assert first.json() == {"event_id": str(event.id), "available_seats": ["A1", "A2"]}
    assert second.json() == first.json()
    provider.seats.assert_called_once()


def test_seats_of_unpublished_event_do_not_hit_provider(api, make_event, provider):
    event = make_event(status="new")

    response = api.get(f"/api/events/{event.id}/seats")

    assert response.status_code == 400
    provider.seats.assert_not_called()


def test_seats_provider_down(api, make_event, provider):
    event = make_event()
    provider.seats.side_effect = ProviderUnavailableError("down")

    response = api.get(f"/api/events/{event.id}/seats")

    assert response.status_code == 502


def test_register_ticket(api, make_event, provider):
    event = make_event()
    ticket_id = str(uuid4())
    provider.seats.return_value = ["A4", "A5"]
    provider.register.return_value = ticket_id

    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 201
    assert response.json() == {"ticket_id": ticket_id}
    ticket = Ticket.objects.get(pk=ticket_id)
    assert ticket.seat == "A5"
    assert ticket.status == Ticket.Status.ACTIVE
    event.refresh_from_db()
    assert event.number_of_visitors == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"seat": "a5"},
        {"first_name": ""},
        {"event_id": "nope"},
    ],
)
def test_register_validates_input(api, make_event, provider, overrides):
    event = make_event()

    response = api.post(
        "/api/tickets", registration_body(event, **overrides), format="json"
    )

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_register_requires_published_event(api, make_event, provider):
    event = make_event(status="new")

    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_register_after_deadline(api, make_event, provider):
    event = make_event(registration_deadline=timezone.now() - timedelta(hours=1))

    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_register_seat_outside_of_pattern(api, make_event, provider):
    event = make_event()

    response = api.post(
        "/api/tickets", registration_body(event, seat="Z99"), format="json"
    )

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_register_taken_seat(api, make_event, provider):
    event = make_event()
    provider.seats.return_value = ["A1", "A2"]

    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 400
    provider.register.assert_not_called()


def test_register_race_condition_is_a_business_error(api, make_event, provider):
    event = make_event()
    provider.seats.return_value = ["A5"]
    provider.register.side_effect = ProviderBadRequestError("already sold")

    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 400
    assert Ticket.objects.count() == 0


def test_register_unknown_event(api, provider):
    body = {
        "event_id": str(uuid4()),
        "first_name": "Ivan",
        "last_name": "Ivanov",
        "email": "ivan@example.com",
        "seat": "A5",
    }

    response = api.post("/api/tickets", body, format="json")

    assert response.status_code == 404


def test_cancel_ticket(api, make_event, provider):
    event = make_event(number_of_visitors=1)
    ticket = Ticket.objects.create(
        ticket_id=uuid4(),
        event=event,
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A5",
    )

    response = api.delete(f"/api/tickets/{ticket.ticket_id}")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    provider.unregister.assert_called_once_with(event.id, ticket.ticket_id)
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.CANCELLED
    event.refresh_from_db()
    assert event.number_of_visitors == 0


def test_cancel_unknown_ticket(api, provider):
    response = api.delete(f"/api/tickets/{uuid4()}")

    assert response.status_code == 404
    provider.unregister.assert_not_called()


def test_cancel_ticket_of_past_event(api, make_event, provider):
    event = make_event(event_time=timezone.now() - timedelta(days=1))
    ticket = Ticket.objects.create(
        ticket_id=uuid4(),
        event=event,
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A5",
    )

    response = api.delete(f"/api/tickets/{ticket.ticket_id}")

    assert response.status_code == 400
    provider.unregister.assert_not_called()


def test_same_seat_reuses_ticket_id_after_cancellation(api, make_event, provider):
    event = make_event()
    ticket_id = str(uuid4())
    provider.seats.return_value = ["A5"]
    provider.register.return_value = ticket_id

    api.post("/api/tickets", registration_body(event), format="json")
    api.delete(f"/api/tickets/{ticket_id}")
    response = api.post("/api/tickets", registration_body(event), format="json")

    assert response.status_code == 201
    assert Ticket.objects.count() == 1
    assert Ticket.objects.get().status == Ticket.Status.ACTIVE
