import uuid

from django.db import models
from django.utils import timezone


class EventStatus:
    NEW = "new"
    PUBLISHED = "published"


class Place(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=255, db_index=True)
    address = models.CharField(max_length=500)
    seats_pattern = models.CharField(max_length=500)
    changed_at = models.DateTimeField()
    created_at = models.DateTimeField()

    def __str__(self):
        return f"{self.name} ({self.city})"


class Event(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)
    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name="events")
    event_time = models.DateTimeField(db_index=True)
    registration_deadline = models.DateTimeField()
    # The provider may introduce new statuses, so no fixed choices here.
    status = models.CharField(max_length=32, db_index=True)
    number_of_visitors = models.PositiveIntegerField(default=0)
    changed_at = models.DateTimeField()
    created_at = models.DateTimeField()
    status_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["event_time", "id"]

    def __str__(self):
        return self.name


class Ticket(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Cancelled"

    # The provider ties ticket id to a seat: the same seat gives the same id
    # after cancellation, so ticket_id is the primary key and gets reactivated.
    ticket_id = models.UUIDField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tickets")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    seat = models.CharField(max_length=16)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.ticket_id} ({self.seat})"


class SyncMetadata(models.Model):
    """Single-row table with the state of the events synchronisation."""

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    last_sync_time = models.DateTimeField(null=True, blank=True)
    last_changed_at = models.DateTimeField(null=True, blank=True)
    sync_status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.IDLE
    )
    started_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")


class IdempotencyKey(models.Model):
    """Result of a successful ``POST /api/tickets`` made with an idempotency key.

    The key is the primary key: that gives uniqueness and a fast lookup. The
    request fingerprint lets us tell a retry from a different request that
    reuses the same key (409).
    """

    key = models.CharField(max_length=255, primary_key=True)
    request_hash = models.CharField(max_length=64)
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.key} -> {self.ticket_id}"


class OutboxMessage(models.Model):
    """Transactional outbox: side effects that must not be lost.

    A row is written in the same DB transaction as the business data and is
    delivered later by the outbox worker (see ``outbox.py``).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        # Gave up: attempts exhausted or the receiver rejected the data for good.
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    # Retry with backoff: the worker takes a row only when this time has come.
    next_attempt_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "outbox"
        indexes = [
            # Partial index: only the rows still waiting are indexed, so
            # picking the next batch stays cheap however many rows are "sent".
            models.Index(
                fields=["next_attempt_at"],
                condition=models.Q(status="pending"),
                name="outbox_pending_idx",
            ),
        ]

    def __str__(self):
        return f"{self.event_type} {self.id} ({self.status})"
