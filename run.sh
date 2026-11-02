#!/bin/bash

# Dependencies are installed at image build time and the container has no
# internet access, so everything runs straight from the virtualenv (no `uv run`).

python ./manage.py migrate

# The container user cannot write to /app, so beat keeps its schedule in /tmp.
python -m celery -A src.core worker -P solo -B \
    -s /tmp/celerybeat-schedule -l INFO &
# gunicorn.conf.py starts the outbox worker (a coroutine) inside each web worker.
python -m gunicorn -c gunicorn.conf.py -b 0.0.0.0:8000 --workers=1 --threads=8 \
    --worker-class=gthread --timeout 120 --preload src.core.wsgi:application &
wait
