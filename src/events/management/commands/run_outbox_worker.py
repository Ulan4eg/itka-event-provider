import asyncio

from django.core.management.base import BaseCommand

from src.events.outbox import run_worker


class Command(BaseCommand):
    help = (
        "Run the outbox worker alone (for local work). In production it is "
        "started inside the gunicorn process, see gunicorn.conf.py."
    )

    def handle(self, *args, **options):
        try:
            asyncio.run(run_worker())
        except KeyboardInterrupt:
            self.stdout.write("Outbox worker stopped.")
