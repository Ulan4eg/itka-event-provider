# Events Aggregator

REST-сервис (Django + DRF) поверх Events Provider API: хранит события локально,
синхронизирует их раз в сутки (Celery, брокер — PostgreSQL), умеет фильтровать
по дате, отдавать постраничный список, места (кэш 30 с), регистрировать и
отменять билеты. При покупке билета в той же транзакции пишется запись в
outbox (Transactional Outbox), а фоновый воркер доставляет уведомление в
Capashino. Регистрация поддерживает ключ идемпотентности, ошибки уходят в
GlitchTip.

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
| `EVENTS_PROVIDER_URL` | по умолчанию внутренний адрес кластера; локально указать публичный `http://events-provider.dev-2.python-labs.ru` |
| `EVENTS_PROVIDER_API_KEY` | ключ из профиля LMS (хранить в GitHub Secrets) |
| `SYNC_TRIGGER_WAIT` | сколько секунд `POST /api/sync/trigger` ждёт завершения синхронизации, по умолчанию 20 |
| `SYNC_CRON_HOUR` | час ежедневной синхронизации, по умолчанию 3 (MSK) |
| `CAPASHINO_URL` | по умолчанию внутренний адрес кластера `http://student-system-capashino-web.student-system-capashino.svc:8000`; локально `https://capashino.dev-2.python-labs.ru` |
| `CAPASHINO_API_TOKEN` | токен со страницы профиля на портале (`X-API-Key`), хранить в секретах |
| `CAPASHINO_TIMEOUT` | таймаут запроса к Capashino, секунды, по умолчанию 10 |
| `OUTBOX_WORKER_ENABLED` | запускать воркер outbox вместе с веб-процессом, по умолчанию `true` |
| `OUTBOX_POLL_INTERVAL` | пауза воркера, когда нет записей, секунды, по умолчанию 2 |
| `OUTBOX_BATCH_SIZE` | сколько записей обрабатывать за итерацию, по умолчанию 10 |
| `OUTBOX_MAX_ATTEMPTS` | число попыток отправки, после него статус `failed`, по умолчанию 10 |
| `OUTBOX_RETRY_BASE_DELAY`, `OUTBOX_RETRY_MAX_DELAY` | экспоненциальная пауза между попытками (5 с → до 300 с) |
| `IDEMPOTENCY_KEY_TTL_HOURS` | срок хранения ключей идемпотентности, часы, по умолчанию 24 |
| `SENTRY_DSN` (или `GLITCHTIP_DSN`) | DSN GlitchTip; пусто — отправка ошибок выключена |
| `SENTRY_ENVIRONMENT` | окружение в GlitchTip, по умолчанию `production` |
| `SENTRY_DEBUG_ENDPOINT` | `true` включает `GET /api/debug/sentry-error` для проверки интеграции |

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/health` | проверка живости |
| POST | `/api/sync/trigger` | ручной запуск синхронизации |
| GET | `/api/events?date_from=&page=&page_size=` | список событий из БД |
| GET | `/api/events/{id}` | детали события |
| GET | `/api/events/{id}/seats` | свободные места (кэш 30 с) |
| POST | `/api/tickets` | регистрация, 201 `{"ticket_id": ...}`; поддерживает `idempotency_key` |
| DELETE | `/api/tickets/{ticket_id}` | отмена, `{"success": true}` |

Все пути работают с `/` на конце и без него.

### POST /api/tickets

Тело запроса (JSON):

```json
{
  "event_id": "uuid",
  "first_name": "Ivan",
  "last_name": "Ivanov",
  "email": "ivan@example.com",
  "seat": "A15",
  "idempotency_key": "6b1c...-any-unique-string"
}
```

`idempotency_key` — необязательная строка (1–255 символов), передаётся **в теле
запроса**. Рекомендуется UUID, один на «намерение» пользователя (на всё время
повторов одного и того же клика/запроса).

| Ситуация | Ответ |
|---|---|
| ключ не передан | как раньше: каждый запрос обрабатывается как новый |
| ключ передан впервые | обычная регистрация, `201 {"ticket_id": ...}`; пара «ключ → билет» сохраняется |
| ключ уже использован с **теми же** данными | `201` и тот же `ticket_id`; новый билет не создаётся, Events Provider не вызывается |
| ключ уже использован с **другими** данными (другое событие, место, email, имя) | `409 Conflict`, билет не создаётся, сохранённый результат не меняется |
| Events Provider вернул ошибку (400/502 и т.д.) | ошибка клиенту, ключ **не** сохраняется — повтор с тем же ключом обрабатывается как новый |
| пустой ключ или длиннее 255 символов | `400` |

Ключ хранится `IDEMPOTENCY_KEY_TTL_HOURS` часов (по умолчанию 24), затем
удаляется Celery-задачей раз в час; просроченный ключ считается неиспользованным.
Одновременные запросы с одним ключом сериализуются advisory-блокировкой
PostgreSQL, поэтому провайдер вызывается ровно один раз.

Остальные ответы: `400` — ошибка валидации или бизнес-правил (событие не
опубликовано, дедлайн, место занято), `404` — событие не найдено,
`409` — конфликт ключа идемпотентности, `502` — Events Provider недоступен.

## Transactional Outbox и уведомления (Capashino)

При успешной регистрации билет, счётчик посетителей и запись в таблицу `outbox`
сохраняются **одной транзакцией**: либо всё, либо ничего.

Таблица `outbox`: `id` (UUID), `event_type` (`ticket_purchased`), `payload`
(JSON: `ticket_id`, `event_name`, `event_time`, `place_name`, `seat`, данные
покупателя), `status` (`pending` — ожидает отправки / `sent` — отправлено /
`failed` — отказ после исчерпания попыток или 400/422 от Capashino),
`attempts`, `last_error`, `next_attempt_at`, `created_at`, `sent_at`. Для выборки
ожидающих записей есть частичный индекс `outbox_pending_idx` по
`next_attempt_at WHERE status = 'pending'`.

Воркер (`src/events/outbox.py`) — корутина `run_worker`, которая крутится в
том же процессе, что и веб-приложение (в отдельном потоке с собственным
event loop; блокирующий ORM/HTTP выполняется в отдельном executor-потоке):

1. выбирает самую старую запись `pending` с наступившим `next_attempt_at`
   (`SELECT ... FOR UPDATE SKIP LOCKED`, одна транзакция на запись);
2. вызывает `POST /api/notifications` с `message`, `reference_id = ticket_id`
   и `idempotency_key = ticket-purchased-<outbox id>`;
3. при ответе 201 (или 409 — уведомление с таким ключом уже есть) помечает запись
   `sent`; при ошибке (сеть, 5xx, 401, 429) запись остаётся `pending`, попытка
   логируется, следующая — через экспоненциальную паузу; после
   `OUTBOX_MAX_ATTEMPTS` запись получает `failed`.

Доставка at-least-once: если процесс упал между вызовом Capashino и сохранением
статуса, запись отправится повторно, но Capashino по тому же `idempotency_key`
вернёт уже созданное уведомление — дубликатов нет.

### Запуск воркера

В Docker/на платформе `run.sh` запускает gunicorn с `-c gunicorn.conf.py`; хук
`post_fork` стартует корутину воркера внутри каждого процесса gunicorn (потоки не
переживают `fork`, поэтому запуск именно после него, это работает и с
`--preload`). Рядом в том же контейнере работает Celery (синхронизация событий и
очистка ключей идемпотентности). Отключить воркер: `OUTBOX_WORKER_ENABLED=false`.

Локально при `runserver` воркер сам не стартует — запустите его отдельно:

```bash
uv run ./manage.py run_outbox_worker
```

Состояние очереди: `SELECT status, count(*) FROM outbox GROUP BY status;`

## GlitchTip

Подключён `sentry-sdk` (интеграции Django и Celery). SDK инициализируется при
загрузке настроек, если задан `SENTRY_DSN` (или `GLITCHTIP_DSN`), — то есть в
gunicorn, Celery и management-командах. Необработанные исключения запросов и
задач Celery, а также сообщения `logger.error/exception` (в том числе ошибки
воркера outbox) отправляются автоматически. Секреты и PII не отправляются
(`send_default_pii=False`).

Подготовка: на портале запросить интеграцию с GlitchTip → дождаться одобрения →
выполнить повторный provisioning на странице «Мои сервисы» → убедиться, что в
окружение сервиса попала переменная с DSN. Если платформа назовёт её иначе, чем
`SENTRY_DSN`/`GLITCHTIP_DSN`, достаточно поправить имя в `src/core/settings.py`.

Проверка: выставить `SENTRY_DEBUG_ENDPOINT=true`, вызвать
`GET /api/debug/sentry-error` (вернёт 500) и найти `RuntimeError: GlitchTip
integration test error` в интерфейсе GlitchTip; после проверки выключить.

## Структура

- `src/events/provider/` — `EventsProviderClient` (весь код общения с провайдером)
  и `EventsPaginator` (итератор по cursor-пагинации).
- `src/events/services.py` — бизнес-логика билетов, мест и идемпотентности;
  `sync.py` — синхронизация.
- `src/events/outbox.py` — запись в outbox и воркер доставки;
  `src/events/notifications.py` — клиент Capashino.
- `src/core/observability.py` — инициализация GlitchTip (sentry-sdk).
- `src/events/serializers.py` — только валидация и формат данных.
- `tests/` — pytest, внешний сервис мокается через `unittest.mock`.

## CI/CD

`.github/workflows/ci.yml`: `lint` (ruff) и `test` → `deploy`. Деплой стартует
только после успешного линтера и тестов.
