from unittest.mock import Mock

import pytest
import requests

from src.events.notifications import (
    CapashinoClient,
    NotificationError,
    NotificationRejectedError,
)

BASE = "http://capashino.test"


def response(status=201, payload=None):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = payload if payload is not None else {}
    return mock


@pytest.fixture
def session():
    return Mock()


@pytest.fixture
def client(session):
    return CapashinoClient(BASE + "/", "token", timeout=3, session=session)


def test_create_notification_request_shape(client, session):
    session.post.return_value = response(201, {"id": "n1"})

    result = client.create_notification("Hello", "ticket-1", "key-1")

    assert result == {"id": "n1"}
    args, kwargs = session.post.call_args
    assert args == (f"{BASE}/api/notifications",)
    assert kwargs["json"] == {
        "message": "Hello",
        "reference_id": "ticket-1",
        "idempotency_key": "key-1",
    }
    assert kwargs["headers"]["X-API-Key"] == "token"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["timeout"] == 3


def test_409_means_already_created(client, session):
    session.post.return_value = response(409, {"detail": "exists"})

    assert client.create_notification("m", "t", "k") == {}


@pytest.mark.parametrize("status", [401, 429, 500, 502, 503])
def test_temporary_errors_are_retryable(client, session, status):
    session.post.return_value = response(status)

    with pytest.raises(NotificationError) as info:
        client.create_notification("m", "t", "k")

    assert not isinstance(info.value, NotificationRejectedError)


@pytest.mark.parametrize("status", [400, 422])
def test_rejected_data_is_permanent(client, session, status):
    session.post.return_value = response(status, {"detail": "bad"})

    with pytest.raises(NotificationRejectedError):
        client.create_notification("m", "t", "k")


def test_network_error_is_retryable(client, session):
    session.post.side_effect = requests.ConnectionError("boom")

    with pytest.raises(NotificationError) as info:
        client.create_notification("m", "t", "k")

    assert not isinstance(info.value, NotificationRejectedError)
