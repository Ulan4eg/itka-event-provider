import asyncio
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.utils import timezone

from src.events import outbox
from src.events.models import OutboxMessage, Ticket
from src.events.notifications import NotificationError, NotificationRejectedError

pytestmark = pytest.mark.django_db


@pytest.fixture
def notifier():
    with patch("src.events.outbox.get_notification_client") as get_client:
        yield get_client.return_value


@pytest.fixture
def ticket(make_event):
    event = make_event(name="Python Conf")
    return Ticket.objects.create(
        ticket_id=uuid4(),
        event=event,
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A5",
    )


@pytest.fixture
def message(ticket):
    return outbox.enqueue_ticket_purchased(ticket)


def test_enqueue_stores_everything_needed_for_the_notification(ticket):
    message = outbox.enqueue_ticket_purchased(ticket)

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.PENDING
    assert message.event_type == outbox.TICKET_PURCHASED
    assert message.attempts == 0
    assert message.payload["ticket_id"] == str(ticket.ticket_id)
    assert message.payload["event_name"] == "Python Conf"
    assert message.payload["seat"] == "A5"


def test_success_marks_message_as_sent(notifier, message):
    result = outbox.process_next()

    assert result is True
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.SENT
    assert message.sent_at is not None
    kwargs = notifier.create_notification.call_args.kwargs
    assert kwargs["reference_id"] == message.payload["ticket_id"]
    assert kwargs["idempotency_key"] == f"ticket-purchased-{message.id}"
    assert "Python Conf" in kwargs["message"]
    assert kwargs["message"].startswith("Вы успешно зарегистрированы")
    assert "A5" in kwargs["message"]


def test_nothing_to_do(notifier):
    assert outbox.process_next() is None
    notifier.create_notification.assert_not_called()


def test_sent_messages_are_not_processed_again(notifier, message):
    outbox.process_next()
    notifier.reset_mock()

    assert outbox.process_next() is None
    notifier.create_notification.assert_not_called()


def test_failure_keeps_message_pending_and_retries_later(notifier, message):
    notifier.create_notification.side_effect = NotificationError("down")

    result = outbox.process_next()

    assert result is False
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.PENDING
    assert message.attempts == 1
    assert "down" in message.last_error
    assert message.next_attempt_at > timezone.now()
    # not taken again until the backoff has passed
    assert outbox.process_next() is None

    OutboxMessage.objects.filter(pk=message.pk).update(
        next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    notifier.create_notification.side_effect = None
    assert outbox.process_next() is True
    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.SENT
    assert message.attempts == 1


def test_gives_up_after_max_attempts(notifier, message, settings):
    settings.OUTBOX_MAX_ATTEMPTS = 2
    notifier.create_notification.side_effect = NotificationError("down")

    outbox.process_next()
    OutboxMessage.objects.filter(pk=message.pk).update(next_attempt_at=timezone.now())
    outbox.process_next()

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.FAILED
    assert message.attempts == 2


def test_rejected_data_fails_immediately(notifier, message):
    notifier.create_notification.side_effect = NotificationRejectedError("422")

    outbox.process_next()

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.FAILED
    assert message.attempts == 1


def test_unknown_event_type_fails(notifier):
    message = outbox.enqueue("something_else", {})

    outbox.process_next()

    message.refresh_from_db()
    assert message.status == OutboxMessage.Status.FAILED
    notifier.create_notification.assert_not_called()


def test_batch_stops_on_first_failure(notifier, ticket):
    outbox.enqueue_ticket_purchased(ticket)
    outbox.enqueue_ticket_purchased(ticket)
    notifier.create_notification.side_effect = NotificationError("down")

    assert outbox.process_batch() == 1
    assert notifier.create_notification.call_count == 1


def test_batch_delivers_all_pending(notifier, ticket):
    for _ in range(3):
        outbox.enqueue_ticket_purchased(ticket)

    assert outbox.process_batch() == 3
    assert OutboxMessage.objects.filter(status=OutboxMessage.Status.SENT).count() == 3


def test_oldest_messages_go_first(notifier, ticket):
    first = outbox.enqueue_ticket_purchased(ticket)
    second = outbox.enqueue_ticket_purchased(ticket)

    outbox.process_next()

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == OutboxMessage.Status.SENT
    assert second.status == OutboxMessage.Status.PENDING


def test_worker_coroutine_polls_until_stopped(settings):
    settings.OUTBOX_POLL_INTERVAL = 0.01
    calls = []

    async def scenario():
        stop = asyncio.Event()

        def fake_batch():
            calls.append(1)
            if len(calls) >= 3:
                stop.set()
            return 0

        with patch("src.events.outbox.process_batch", Mock(side_effect=fake_batch)):
            await asyncio.wait_for(outbox.run_worker(stop), timeout=5)

    asyncio.run(scenario())

    assert len(calls) == 3


def test_worker_survives_an_unexpected_error(settings):
    settings.OUTBOX_POLL_INTERVAL = 0.01
    results = [RuntimeError("db down"), 0]

    async def scenario():
        stop = asyncio.Event()

        def fake_batch():
            result = results.pop(0)
            if not results:
                stop.set()
            if isinstance(result, Exception):
                raise result
            return result

        with patch("src.events.outbox.process_batch", Mock(side_effect=fake_batch)):
            await asyncio.wait_for(outbox.run_worker(stop), timeout=5)

    asyncio.run(scenario())

    assert results == []


def test_background_worker_can_be_disabled(settings):
    settings.OUTBOX_WORKER_ENABLED = False

    assert outbox.start_background_worker() is None
