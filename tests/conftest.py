from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from src.events.models import Event, Place


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def place(db):
    now = timezone.now()
    return Place.objects.create(
        id=uuid4(),
        name="Hall",
        city="Moscow",
        address="Lenina 1",
        seats_pattern="A1-10,B1-5",
        changed_at=now,
        created_at=now,
    )


@pytest.fixture
def make_event(place):
    def _make(**overrides):
        now = timezone.now()
        params = {
            "id": uuid4(),
            "name": "Python Conf",
            "place": place,
            "event_time": now + timedelta(days=10),
            "registration_deadline": now + timedelta(days=5),
            "status": "published",
            "number_of_visitors": 0,
            "changed_at": now,
            "created_at": now,
        }
        params.update(overrides)
        return Event.objects.create(**params)

    return _make
