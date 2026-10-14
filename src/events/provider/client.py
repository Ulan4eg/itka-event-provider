"""HTTP client for the external Events Provider API.

All communication with the provider lives here and nowhere else.
"""

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderNotFoundError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


def build_session(max_retries=3):
    """Session that retries only safe (GET) requests on transient failures."""
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _error_message(response):
    try:
        data = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(data, list):
        return " ".join(str(item) for item in data)
    if isinstance(data, dict):
        return str(data.get("detail") or data)
    return str(data)


def _parse_response(response):
    status = response.status_code
    if status == 400:
        raise ProviderBadRequestError(_error_message(response))
    if status == 401:
        raise ProviderAuthError("Events Provider rejected the API key.")
    if status == 404:
        raise ProviderNotFoundError(_error_message(response))
    if status >= 400:
        raise ProviderUnavailableError(f"Events Provider answered HTTP {status}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("Events Provider returned invalid JSON.") from exc


def _field(payload, key):
    try:
        return payload[key]
    except (KeyError, TypeError) as exc:
        raise ProviderError(f"Unexpected provider response, no {key!r}.") from exc


class EventsProviderClient:
    def __init__(self, base_url, api_key, timeout=10.0, session=None):
        self._base_url = base_url.rstrip("/")
        self._headers = {"x-api-key": api_key}
        self._timeout = timeout
        self._session = session or build_session()

    def events(self, changed_at, cursor=None):
        """One page of events changed since ``changed_at`` (a date)."""
        params = {"changed_at": changed_at.isoformat()}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/api/events/", params=params)

    def seats(self, event_id):
        payload = self._request("GET", f"/api/events/{event_id}/seats/")
        return _field(payload, "seats")

    def register(self, event_id, first_name, last_name, email, seat):
        """Register a participant, returns the ticket id as a string."""
        payload = self._request(
            "POST",
            f"/api/events/{event_id}/register/",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )
        return _field(payload, "ticket_id")

    def unregister(self, event_id, ticket_id):
        self._request(
            "DELETE",
            f"/api/events/{event_id}/unregister/",
            json={"ticket_id": str(ticket_id)},
        )

    def _request(self, method, path, params=None, json=None):
        # Trailing slash is mandatory: the provider answers 301 without it,
        # and a redirect would turn POST/DELETE into GET.
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Events Provider request failed: %s %s", method, url)
            raise ProviderUnavailableError(
                f"Events Provider is unreachable: {exc}"
            ) from exc
        return _parse_response(response)
