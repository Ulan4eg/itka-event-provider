from django.db import models


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
