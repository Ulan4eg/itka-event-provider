#!/bin/bash

uv run --no-dev ./manage.py migrate
uv run --no-dev ./manage.py collectstatic --noinput

uv run --no-dev python -m celery -A src.core worker -P solo -B -l INFO &
uv run --no-dev python -m gunicorn -b 0.0.0.0:8000 --workers=1 --threads=8 \
    --worker-class=gthread --timeout 120 --preload src.core.wsgi:application &
wait
