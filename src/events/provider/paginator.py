from datetime import date
from urllib.parse import parse_qs, urlparse

from .exceptions import ProviderError

FIRST_SYNC_DATE = date(2000, 1, 1)


def extract_cursor(next_url):
    values = parse_qs(urlparse(next_url).query).get("cursor")
    return values[0] if values else None


class EventsPaginator:
    """Iterates over all events of the provider hiding cursor pagination."""

    def __init__(self, client, changed_at=FIRST_SYNC_DATE):
        self._client = client
        self._changed_at = changed_at

    def __iter__(self):
        cursor = None
        seen = set()
        while True:
            page = self._client.events(self._changed_at, cursor)
            yield from page["results"]

            next_url = page.get("next")
            if not next_url:
                return
            cursor = extract_cursor(next_url)
            if cursor is None or cursor in seen:
                raise ProviderError(f"Broken pagination link: {next_url}")
            seen.add(cursor)
