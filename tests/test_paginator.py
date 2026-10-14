from datetime import date
from unittest.mock import Mock, call

import pytest

from src.events.provider.exceptions import ProviderError
from src.events.provider.paginator import (
    FIRST_SYNC_DATE,
    EventsPaginator,
    extract_cursor,
)


def page(results, next_url=None):
    return {"next": next_url, "previous": None, "results": results}


def test_extract_cursor():
    url = "http://host/api/events/?changed_at=2000-01-01&cursor=abc123"
    assert extract_cursor(url) == "abc123"
    assert extract_cursor("http://host/api/events/?changed_at=2000-01-01") is None


def test_iterates_over_all_pages():
    client = Mock()
    client.events.side_effect = [
        page([{"id": 1}, {"id": 2}], "http://h/api/events/?cursor=abc"),
        page([{"id": 3}], "http://h/api/events/?cursor=def"),
        page([{"id": 4}]),
    ]

    events = list(EventsPaginator(client))

    assert [event["id"] for event in events] == [1, 2, 3, 4]
    assert client.events.call_args_list == [
        call(FIRST_SYNC_DATE, None),
        call(FIRST_SYNC_DATE, "abc"),
        call(FIRST_SYNC_DATE, "def"),
    ]


def test_uses_given_changed_at():
    client = Mock()
    client.events.return_value = page([])

    assert list(EventsPaginator(client, date(2026, 1, 5))) == []

    client.events.assert_called_once_with(date(2026, 1, 5), None)


def test_next_without_cursor_is_an_error():
    client = Mock()
    client.events.return_value = page([{"id": 1}], "http://h/api/events/")

    with pytest.raises(ProviderError):
        list(EventsPaginator(client))


def test_repeating_cursor_does_not_loop_forever():
    client = Mock()
    client.events.return_value = page([{"id": 1}], "http://h/api/events/?cursor=abc")

    with pytest.raises(ProviderError):
        list(EventsPaginator(client))
