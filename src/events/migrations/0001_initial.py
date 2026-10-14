import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Place",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("city", models.CharField(db_index=True, max_length=255)),
                ("address", models.CharField(max_length=500)),
                ("seats_pattern", models.CharField(max_length=500)),
                ("changed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name="SyncMetadata",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("last_sync_time", models.DateTimeField(blank=True, null=True)),
                ("last_changed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "sync_status",
                    models.CharField(
                        choices=[
                            ("idle", "Idle"),
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                        ],
                        default="idle",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.CreateModel(
            name="Event",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("event_time", models.DateTimeField(db_index=True)),
                ("registration_deadline", models.DateTimeField()),
                ("status", models.CharField(db_index=True, max_length=32)),
                ("number_of_visitors", models.PositiveIntegerField(default=0)),
                ("changed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField()),
                ("status_changed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "place",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="events.place",
                    ),
                ),
            ],
            options={"ordering": ["event_time", "id"]},
        ),
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("ticket_id", models.UUIDField(primary_key=True, serialize=False)),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(max_length=100)),
                ("email", models.EmailField(max_length=254)),
                ("seat", models.CharField(max_length=16)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("cancelled", "Cancelled")],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tickets",
                        to="events.event",
                    ),
                ),
            ],
        ),
    ]
