# Events Aggregator

REST-сервис (Django + DRF) поверх Events Provider API: хранит события локально,
синхронизирует их раз в сутки (Celery, брокер — PostgreSQL), умеет фильтровать
по дате, отдавать постраничный список, места (кэш 30 с), регистрировать и
отменять билеты.

## Запуск локально

```bash
cp .env.example .env        # вписать EVENTS_PROVIDER_API_KEY из LMS
uv sync
export $(grep -v '^#' .env | xargs)
uv run ./manage.py migrate
uv run ./manage.py runserver
uv run pytest
uv run ruff check .
```

Без `DATABASE_URL` используется sqlite (только для разработки).

## Конфигурация (переменные окружения)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | PostgreSQL для локальной работы и CI, он же брокер Celery |
| `POSTGRES_CONNECTION_STRING` или `POSTGRES_DATABASE_NAME`, `POSTGRES_USERNAME`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | то же самое, переменные платформы |
| `SECRET_KEY` | секрет Django (в проде обязателен) |
| `EVENTS_PROVIDER_URL` | для кластера: `http://student-system-events-provider-web.student-system-events-provider.svc:8000` |
| `EVENTS_PROVIDER_API_KEY` | ключ из профиля LMS (хранить в GitHub Secrets) |
| `SYNC_CRON_HOUR` | час ежедневной синхронизации, по умолчанию 3 (MSK) |

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/health` | проверка живости |
| POST | `/api/sync/trigger` | ручной запуск синхронизации |
| GET | `/api/events?date_from=&page=&page_size=` | список событий из БД |
| GET | `/api/events/{id}` | детали события |
| GET | `/api/events/{id}/seats` | свободные места (кэш 30 с) |
| POST | `/api/tickets` | регистрация, 201 `{"ticket_id": ...}` |
| DELETE | `/api/tickets/{ticket_id}` | отмена, `{"success": true}` |

Все пути работают с `/` на конце и без него.

## Структура

- `src/events/provider/` — `EventsProviderClient` (весь код общения с провайдером)
  и `EventsPaginator` (итератор по cursor-пагинации).
- `src/events/services.py` — бизнес-логика билетов и мест; `sync.py` — синхронизация.
- `src/events/serializers.py` — только валидация и формат данных.
- `tests/` — pytest, внешний сервис мокается через `unittest.mock`.

## CI/CD

`.github/workflows/ci.yml`: `lint` (ruff) и `test` → `deploy`. Деплой стартует
только после успешного линтера и тестов.
