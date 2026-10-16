#!/bin/bash

# Dependencies are installed at image build time and the container has no
# internet access, so everything runs straight from the virtualenv (no `uv run`).

python ./manage.py migrate

# The container user cannot write to /app, so beat keeps its schedule in /tmp.
python -m celery -A src.core worker -P solo -B \
    -s /tmp/celerybeat-schedule -l INFO &
python -m gunicorn -b 0.0.0.0:8000 --workers=1 --threads=8 \
    --worker-class=gthread --timeout 120 --preload src.core.wsgi:application &
wait
