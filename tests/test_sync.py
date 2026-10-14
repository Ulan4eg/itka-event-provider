from datetime import date, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from src.events.models import Event, Place, SyncMetadata
from src.events.provider.exceptions import ProviderUnavailableError
from src.events.sync import run_sync

pytestmark = pytest.mark.django_db


def event_payload(event_id=None, changed_at="2026-01-04T22:28:35.325270+03:00"):
    return {
        "id": str(event_id or uuid4()),
        "name": "Python Conf",
        "place": {
            "id": "650e8400-e29b-41d4-a716-446655440001",
            "name": "Hall",
            "city": "Moscow",
            "address": "Lenina 1",
            "seats_pattern": "A1-1000",
            "changed_at": "2025-01-01T03:00:00+03:00",
            "created_at": "2025-01-01T03:00:00+03:00",
        },
        "event_time": "2026-01-11T17:00:00+03:00",
        "registration_deadline": "2026-01-10T17:00:00+03:00",
        "status": "published",
        "number_of_visitors": 5,
        "changed_at": changed_at,
        "created_at": "2026-01-04T22:28:35.325302+03:00",
        "status_changed_at": "2026-01-04T22:28:35.325386+03:00",
    }


def client_with(*results, next_url=None):
    client = Mock()
    client.events.return_value = {
        "next": next_url,
        "previous": None,
        "results": list(results),
    }
    return client


def test_first_sync_loads_everything():
    client = client_with(event_payload(), event_payload())

    meta = run_sync(client=client)

    client.events.assert_called_once_with(date(2000, 1, 1), None)
    assert Event.objects.count() == 2
    assert Place.objects.count() == 1
    assert meta.sync_status == SyncMetadata.Status.SUCCESS
    assert meta.last_sync_time is not None
    assert meta.last_changed_at is not None


def test_next_sync_is_incremental_and_updates_events():
    event_id = uuid4()
    run_sync(client=client_with(event_payload(event_id)))

    updated = event_payload(event_id, changed_at="2026-01-06T10:00:00+03:00")
    updated["name"] = "Renamed"
    client = client_with(updated)
    run_sync(client=client)

    # last changed_at 2026-01-04 (UTC) minus one day of safety margin
    assert client.events.call_args.args[0] == date(2026, 1, 3)
    assert Event.objects.count() == 1
    assert Event.objects.get(pk=event_id).name == "Renamed"
    meta = SyncMetadata.objects.get()
    assert meta.last_changed_at.date() == date(2026, 1, 6)


def test_failed_sync_keeps_cursor_and_records_error():
    client = Mock()
    client.events.side_effect = ProviderUnavailableError("boom")

    meta = run_sync(client=client)

    assert meta.sync_status == SyncMetadata.Status.FAILED
    assert "boom" in meta.last_error
    assert meta.last_changed_at is None
    assert Event.objects.count() == 0


def test_malformed_event_is_skipped():
    client = client_with({"id": "not-a-uuid"}, event_payload())

    meta = run_sync(client=client)

    assert meta.sync_status == SyncMetadata.Status.SUCCESS
    assert Event.objects.count() == 1


def test_parallel_run_is_skipped():
    SyncMetadata.objects.create(
        pk=1,
        sync_status=SyncMetadata.Status.RUNNING,
        started_at=timezone.now() - timedelta(minutes=5),
    )
    client = client_with(event_payload())

    run_sync(client=client)

    client.events.assert_not_called()


def test_stale_running_status_does_not_block():
    SyncMetadata.objects.create(
        pk=1,
        sync_status=SyncMetadata.Status.RUNNING,
        started_at=timezone.now() - timedelta(hours=3),
    )

    meta = run_sync(client=client_with(event_payload()))

    assert meta.sync_status == SyncMetadata.Status.SUCCESS
