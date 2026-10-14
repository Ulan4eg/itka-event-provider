from datetime import date
from unittest.mock import Mock

import pytest
import requests

from src.events.provider.client import EventsProviderClient
from src.events.provider.exceptions import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderNotFoundError,
    ProviderUnavailableError,
)

BASE = "http://provider.test"


def response(status=200, payload=None):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload
    return mock


@pytest.fixture
def session():
    return Mock()


@pytest.fixture
def client(session):
    return EventsProviderClient(BASE, "secret", timeout=5, session=session)


def test_events_sends_changed_at_cursor_and_api_key(client, session):
    session.request.return_value = response(payload={"results": [], "next": None})

    result = client.events(date(2026, 1, 1), cursor="abc")

    assert result == {"results": [], "next": None}
    args, kwargs = session.request.call_args
    assert args == ("GET", f"{BASE}/api/events/")
    assert kwargs["params"] == {"changed_at": "2026-01-01", "cursor": "abc"}
    assert kwargs["headers"] == {"x-api-key": "secret"}
    assert kwargs["timeout"] == 5


def test_events_without_cursor_omits_it(client, session):
    session.request.return_value = response(payload={"results": []})

    client.events(date(2000, 1, 1))

    assert session.request.call_args.kwargs["params"] == {"changed_at": "2000-01-01"}


def test_seats_returns_list(client, session):
    session.request.return_value = response(payload={"seats": ["A1", "A2"]})

    assert client.seats("event-1") == ["A1", "A2"]
    url = f"{BASE}/api/events/event-1/seats/"
    assert session.request.call_args.args == ("GET", url)


def test_register_returns_ticket_id(client, session):
    session.request.return_value = response(201, {"ticket_id": "t-1"})

    ticket_id = client.register("event-1", "Ivan", "Ivanov", "i@example.com", "A15")

    assert ticket_id == "t-1"
    args, kwargs = session.request.call_args
    assert args == ("POST", f"{BASE}/api/events/event-1/register/")
    assert kwargs["json"] == {
        "first_name": "Ivan",
        "last_name": "Ivanov",
        "email": "i@example.com",
        "seat": "A15",
    }


def test_unregister_sends_ticket_id(client, session):
    session.request.return_value = response(payload={"success": True})

    client.unregister("event-1", "t-1")

    args, kwargs = session.request.call_args
    assert args == ("DELETE", f"{BASE}/api/events/event-1/unregister/")
    assert kwargs["json"] == {"ticket_id": "t-1"}


def test_bad_request_with_list_body(client, session):
    body = ["This ticket is not available (already sold)."]
    session.request.return_value = response(400, body)

    with pytest.raises(ProviderBadRequestError, match="already sold"):
        client.register("event-1", "Ivan", "Ivanov", "i@example.com", "A15")


def test_not_found(client, session):
    session.request.return_value = response(404, {"detail": "Event not found"})

    with pytest.raises(ProviderNotFoundError, match="Event not found"):
        client.seats("event-1")


def test_unauthorized(client, session):
    session.request.return_value = response(401, {"detail": "bad key"})

    with pytest.raises(ProviderAuthError):
        client.events(date(2000, 1, 1))


def test_server_error_is_unavailable(client, session):
    session.request.return_value = response(500)

    with pytest.raises(ProviderUnavailableError):
        client.seats("event-1")


def test_network_error_is_unavailable(client, session):
    session.request.side_effect = requests.ConnectionError("boom")

    with pytest.raises(ProviderUnavailableError):
        client.events(date(2000, 1, 1))


def test_unexpected_payload(client, session):
    session.request.return_value = response(payload={"oops": 1})

    with pytest.raises(ProviderError):
        client.seats("event-1")
