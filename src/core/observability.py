"""Error tracking: GlitchTip speaks the Sentry protocol, so sentry-sdk is used."""

import logging

logger = logging.getLogger(__name__)


def init_sentry(dsn, environment="production"):
    """Enable the SDK if a DSN is configured. Returns True if it was enabled.

    Called from settings, so it covers gunicorn, the Celery worker and
    management commands alike. Unhandled exceptions of Django views, Celery
    tasks and ``logger.error/exception`` calls (e.g. in the outbox worker) are
    sent to GlitchTip automatically.
    """
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    return True
