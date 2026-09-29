# BAYTUR — backend программы лояльности

Бек мобильного приложения BAYTUR (курорт на Иссык-Куле) по «ТЗ на backend для приложения Baytur.docx»:
клиентский API, рабочее место сотрудника, веб-админка, аналитика. **Все расчёты делает бек** — мобилка
отправляет только ввод клиента и показывает готовые цифры.

**Стек:** Django 5.2 · DRF · drf-spectacular (OpenAPI 3) · Channels (WebSocket) · Celery + beat · PostgreSQL 14 · Redis 7 · Docker Compose

---

## Быстрый старт

```bash
cp .envtest .env            # или ./scripts/init-project.sh baytur
docker compose up -d --build
docker compose exec web python manage.py seed           # справочники из хардкода мобилки
docker compose exec web python manage.py seed_demo      # только staging: демо-профиль и тестовый аккаунт сторов
docker compose exec web python manage.py createsuperuser
```

| Что | Где |
|---|---|
| API | `http://127.0.0.1:${WEB_PORT}/api/v1/` |
| Swagger / OpenAPI | `/api/v1/docs`, `/api/v1/schema`; файл — `app/openapi.yaml` |
| Веб-админка и рабочее место сотрудника | `/panel/` (email + пароль + TOTP) |
| Удаление аккаунта без приложения (Google Play) | `/account/delete` |
| Технический Django admin (разработчики) | `/django-admin/` |

Сервисы compose: `web` (HTTP + WebSocket), `worker` (Celery), `beat` (расписание), `db`, `redis`.

## Тесты

```bash
docker compose run --rm --no-deps -e DJANGO_SETTINGS_MODULE=core.settings.test web python manage.py test apps
```

## OpenAPI (для генерации DTO в Dart)

```bash
docker compose run --rm --no-deps web python manage.py spectacular --file /app/openapi.yaml --validate
```

Схемы клиентского API и API сотрудника описаны в `core/api_schema.py` и `apps/common/openapi.py`;
имена enum совпадают с Dart (`CategoryId`, `PaymentMethod`, `TierId`, `RequestStatus`, …).

---

## Устройство

```
app/
├── core/                 settings (base/dev/prod/test), urls, api_urls (все маршруты /api/v1), asgi, celery
└── apps/
    ├── common/           ошибки {error:{code,message}}, i18n {ru,ky,en}, кеш+ETag, пагинация, аудит, настройки программы, сиды
    ├── members/          участники, вход по SMS, JWT/refresh, профиль, согласия, удаление/восстановление (§2)
    ├── staff/            сотрудники админки, роли и матрица прав (§7.1), TOTP
    ├── catalog/          точки обслуживания, категории с правилами кешбека, услуги, акции с датами (§3.1)
    ├── loyalty/          уровни, привилегии, кошелёк, журнал операций (ledger), сгорание баллов (§3.2, 3.3, 5.3)
    ├── cashback/         расчёт (calc.py), заявки и их жизненный цикл, рабочее место сотрудника (§4, 5, 8)
    ├── payments/         онлайн-оплата, шлюзы, вебхуки, возвраты (§4.3)
    ├── content/          статьи, акции-баннеры, события, сторис (§3.5)
    ├── notifications/    лента, push (FCM), тихие часы, рассылки, WebSocket-каналы (§5.4)
    ├── complaints/       обращения и переписка (§9)
    ├── analytics/        события мобилки, отчёты, аналитика, выгрузки (§7.2, 7.5)
    ├── backoffice/       админ-API /api/v1/admin/* (§7.3)
    └── panel/            веб-админка и рабочее место сотрудника в стиле приложения (§7.4)
```

### Ключевые правила

- **Расчёт** (`apps/cashback/calc.py`) — эталон из мобилки: `maxPointsSom = min(floor(total × maxPointsShare), floor(available / 100))`,
  `cashback = round(moneySom × rate × 100)` только с денежной части. Акция заменяет ставку; ДР — ставка × множитель; берётся большая.
- **Ledger:** `balance = Σ operations.points`, операции не редактируются, любое движение — в транзакции с `select_for_update`;
  CHECK-ограничения в БД: `balance ≥ 0`, `reserved ≥ 0`, `reserved ≤ balance`. Сверка: `manage.py check_ledger`.
- **Заявка:** `pending → confirmed → credited`, отказ/отмена только из `pending`. `pending` держит баллы в резерве;
  `confirm` списывает их, `credit` начисляет кешбек и растит `lifetime` (уровень не понижается никогда).
  Правила и ставка фиксируются снимком при отправке. Повтор с тем же `Idempotency-Key` не создаёт вторую заявку.
- **Фоновые сроки** (автоподтверждение, начисление с задержкой, автоотказ, сгорание, окончательное удаление)
  хранятся в БД и обрабатываются периодическими задачами — рестарт ничего не теряет.
- **Публичные справочники** — без токена, один кеш для всех, `ETag` + `Cache-Control: max-age=300`;
  любое изменение каталога/контента сбрасывает кеш.
- **Язык** — `Accept-Language: ru|ky|en`, пустой перевод → ru. **Даты** — ISO 8601 в Asia/Bishkek (`+06:00`).
- **Realtime** — WebSocket `/api/v1/events?token=<access>` (клиент), `/api/v1/staff/events` (сотрудник/админка).

### Провайдеры (заказчик ещё не выбрал — ТЗ §11)

| Что | Сейчас | Как подключить |
|---|---|---|
| SMS | `SMS_BACKEND=console` — код пишется в лог | класс с `send(phone, text)` в `apps/members/sms.py` |
| Оплата Finik / Freedom Pay / ЭлQR | `PAYMENT_BACKEND=fake` — тестовая страница оплаты + подписанный вебхук | класс `Gateway` в `apps/payments/gateways.py` |
| Push | `PUSH_BACKEND=console`; `fcm` — FCM HTTP v1 | `FCM_CREDENTIALS_FILE` — JSON сервисного аккаунта |
| Файлы | локальный `media/` | `S3_BUCKET` (+ `django-storages[s3]`) |

### Команды

| Команда | Что делает |
|---|---|
| `seed` | Справочники: 5 категорий с правилами, 15 услуг, 5 уровней, 15 привилегий, контент, темы обращений, документы, шаблоны push |
| `seed_demo` | Staging: BT-048219 (845 000, Золото), тестовый номер сторов с заявками во всех статусах |
| `check_ledger` | Сверка кошельков с журналом и резервов с заявками |
| `build_tokens` | Генерация CSS-переменных админки и `AppColors` для Dart из `static/design/tokens.json` |

---

## Переменные окружения

См. `.envtest` — каждая переменная помечена `[МЕНЯТЬ]` / `[УНИКАЛЬНОЕ]` / `[НЕ ТРОГАТЬ]`. Для BAYTUR добавлены
`PUBLIC_BASE_URL`, `APP_ENV` (`dev|staging|production`), `SMS_BACKEND`, `PUSH_BACKEND`, `FCM_CREDENTIALS_FILE`,
`PAYMENT_BACKEND`, `PAYMENT_WEBHOOK_SECRET`, `S3_*`.

## Деплой

`docker-compose.prod.yml`: gunicorn с uvicorn-воркерами (HTTP + WebSocket), `worker`, `beat`. Наружу — через nginx
на хосте с TLS 1.2+; для WebSocket nginx должен проксировать `Upgrade`/`Connection`:

```nginx
location /api/v1/events       { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1;
                                proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
location /api/v1/staff/events { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1;
                                proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
```

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Приватные выгрузки (`app/private/`) не отдаются nginx — только через view с проверкой прав.
