"""Django settings of the events aggregator. Everything secret comes from env."""

import os
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import quote

import dj_database_url
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DEBUG")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("ALLOWED_HOSTS", "*").split(",")
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "src.events",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "src.core.urls"
WSGI_APPLICATION = "src.core.wsgi.application"

# Endpoints are served both with and without trailing slash (see events/urls.py),
# so Django must not redirect POST/DELETE requests.
APPEND_SLASH = False


def _database_config():
    # DATABASE_URL is for local work and CI, the POSTGRES_* names are the ones
    # the deployment platform injects into the container.
    url = os.environ.get("DATABASE_URL") or os.environ.get(
        "POSTGRES_CONNECTION_STRING"
    )
    if url:
        return dj_database_url.parse(url, conn_max_age=60)
    if os.environ.get("POSTGRES_DATABASE_NAME"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DATABASE_NAME"],
            "USER": os.environ.get("POSTGRES_USERNAME", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


DATABASES = {"default": _database_config()}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The provider returns times in +03:00, we answer in the same zone.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Moscow"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "events-aggregator",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

# --- Events Provider API ---------------------------------------------------
EVENTS_PROVIDER_URL = os.environ.get(
    "EVENTS_PROVIDER_URL", "http://events-provider.dev-2.python-labs.ru"
)
EVENTS_PROVIDER_API_KEY = os.environ.get("EVENTS_PROVIDER_API_KEY", "")
EVENTS_PROVIDER_TIMEOUT = float(os.environ.get("EVENTS_PROVIDER_TIMEOUT", "10"))
SEATS_CACHE_TTL = 30  # seconds


# --- Celery (PostgreSQL is used as the broker via the SQLAlchemy transport) --
def _broker_url(db):
    explicit = os.environ.get("CELERY_BROKER_URL")
    if explicit:
        return explicit
    if "postgresql" in db["ENGINE"]:
        user = quote(db.get("USER") or "", safe="")
        password = quote(db.get("PASSWORD") or "", safe="")
        host = db.get("HOST") or "localhost"
        port = db.get("PORT") or 5432
        driver = "psycopg2" if find_spec("psycopg2") else "psycopg"
        auth = f"{user}:{password}"
        return f"sqla+postgresql+{driver}://{auth}@{host}:{port}/{db['NAME']}"
    return "memory://"  # local sqlite / tests


CELERY_BROKER_URL = _broker_url(DATABASES["default"])
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "sync-events-daily": {
        "task": "src.events.tasks.sync_events",
        "schedule": crontab(
            hour=int(os.environ.get("SYNC_CRON_HOUR", "3")),
            minute=0,
        ),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
