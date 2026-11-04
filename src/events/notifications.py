"""HTTP client for the Capashino notification service.

All communication with Capashino lives here and nowhere else.
"""

import logging

import requests

logger = logging.getLogger(__name__)

# Client errors that will not go away by retrying the same request.
_RETRYABLE_4XX = {401, 408, 425, 429}


class NotificationError(Exception):
    """Temporary failure: the message must be sent again later."""


class NotificationRejectedError(NotificationError):
    """Capashino rejected the data for good (400, 422...), retrying is useless."""


def _error_text(response):
    try:
        return str(response.json())[:500]
    except ValueError:
        return f"HTTP {response.status_code}"


class CapashinoClient:
    def __init__(self, base_url, api_token, timeout=10.0, session=None):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_token,
        }
        self._timeout = timeout
        self._session = session or requests.Session()

    def create_notification(self, message, reference_id, idempotency_key):
        """POST /api/notifications. Returns the notification as a dict.

        With the same ``idempotency_key`` Capashino does not create a duplicate,
        so repeating this call after a crash or a timeout is safe.
        """
        url = f"{self._base_url}/api/notifications"
        body = {
            "message": message,
            "reference_id": str(reference_id),
            "idempotency_key": idempotency_key,
        }
        try:
            response = self._session.post(
                url, json=body, headers=self._headers, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise NotificationError(f"Capashino is unreachable: {exc}") from exc

        status = response.status_code
        if status == 201:
            try:
                return response.json()
            except ValueError:
                return {}
        if status == 409:
            # The notification with this idempotency key already exists: an
            # earlier attempt did succeed, we just did not see the answer.
            logger.info("Capashino already has notification %s", idempotency_key)
            return {}
        if status in _RETRYABLE_4XX or status >= 500:
            raise NotificationError(
                f"Capashino answered HTTP {status}: {_error_text(response)}"
            )
        if 400 <= status < 500:
            raise NotificationRejectedError(
                f"Capashino rejected the request (HTTP {status}): "
                f"{_error_text(response)}"
            )
        raise NotificationError(f"Unexpected Capashino answer HTTP {status}.")
