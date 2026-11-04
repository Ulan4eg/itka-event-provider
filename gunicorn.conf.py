"""Gunicorn hooks.

The outbox worker is a coroutine that lives in the same process as the web
application. Threads do not survive ``fork``, so it is started in every gunicorn
worker after the fork (this also works with ``--preload``).
"""


def post_fork(server, worker):
    from src.events.outbox import start_background_worker

    start_background_worker()
