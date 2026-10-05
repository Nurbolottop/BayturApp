# BAYTUR — API для мобильного приложения

> **Новая балловая система** (три счётчика, уровни по «Нынешним», закрытие года, задания) — отдельное ТЗ для
> мобилки: [`MOBILE_LOYALTY_V2.md`](MOBILE_LOYALTY_V2.md).

Документ для мобильной команды и её AI-ассистента: как подключить приложение BAYTUR к бекенду вместо
захардкоженных данных и `FakeLoyaltyServer`. Можно целиком передать в контекст Claude/Cursor и работать по нему.

- **Staging:** `https://app.baytur.kg/api/v1` (сейчас это единственное окружение; SMS и оплата — тестовые заглушки, push работают, см. §15)
- **Swagger UI:** https://app.baytur.kg/api/v1/docs
- **OpenAPI 3 (для генерации DTO):** https://app.baytur.kg/api/v1/schema, файл в репозитории — `app/openapi.yaml`
- **Репозиторий бека:** https://github.com/Nurbolottop/BayturApp

---

## Содержание

0. [Инструкция для AI-ассистента](#0-инструкция-для-ai-ассистента)
1. [Главный принцип: всё считает бек](#1-главный-принцип-всё-считает-бек)
2. [Общие правила API](#2-общие-правила-api)
3. [Ошибки](#3-ошибки)
4. [Вход, регистрация, токены](#4-вход-регистрация-токены)
5. [Профиль, настройки, согласия](#5-профиль-настройки-согласия)
6. [Каталог, программа, контент (публичные)](#6-каталог-программа-контент-публичные)
7. [Кошелёк и история](#7-кошелёк-и-история)
8. [Заявки на кешбек](#8-заявки-на-кешбек)
9. [Онлайн-оплата](#9-онлайн-оплата)
10. [Realtime (WebSocket) и push](#10-realtime-websocket-и-push)
11. [Лента уведомлений](#11-лента-уведомлений)
12. [Удаление и восстановление аккаунта](#12-удаление-и-восстановление-аккаунта)
13. [Обращения (поддержка)](#13-обращения-поддержка)
14. [Аналитика, QR участника, прочее](#14-аналитика-qr-участника-прочее)
15. [Тестовые данные и ограничения staging](#15-тестовые-данные-и-ограничения-staging)
16. [Чек-лист экранов](#16-чек-лист-экранов)
17. [Справочник enum-значений](#17-справочник-enum-значений)

---

## 0. Инструкция для AI-ассистента

Если ты — AI-ассистент, который интегрирует этот API в Flutter-приложение BAYTUR:

1. **Не трогай логику экранов.** Меняются только реализации репозиториев из `lib/app/di.dart`:
   `LocalCatalogRepository`, `LocalContentRepository`, `LocalLoyaltyRepository`, `FakeLoyaltyServer`,
   `FakePaymentGateway`, `PrefsProfileRepository` → HTTP-реализации тех же интерфейсов (таблица в §1).
2. **Удали локальные расчёты:** `PaymentCalculator`, `PaymentSplit`-вычисления, `TierProgram.statusFor`.
   Цифры (сумма, лимит баллов, кешбек, доступный баланс, уровень, прогресс) берутся только из ответов API.
   Никогда не отправляй на сервер посчитанные `split`/`rules` — сервер их игнорирует и считает сам.
3. **DTO генерируй из OpenAPI** (`openapi-generator` с генератором `dart-dio`, или вручную по §17).
   Имена enum-значений в JSON совпадают с Dart (`rooms`, `pending`, `freedomPay`) — маппинг-словари не нужны.
4. **Неизвестные enum-значения не должны ронять парсинг:** бек может добавить новые `kind`/иконки —
   пропускай или показывай дефолт.
   **Уровни не фиксированы:** курорт может добавлять, удалять и переименовывать уровни в админке. Не храни
   список уровней в коде (enum `TierId`) — бери его из `GET /loyalty/program` в порядке `order`, а градиент и медаль
   рисуй по `style` (см. §6.3). Медали из `assets/images/tiers/` можно оставить как оформление для известных id
   (`bronze`, `silver`, `gold`, `platinum`, `titanium`, `ambassador`), но для любого другого id — стиль из `style`.
   Уровень, прогресс и удержание **не считай** — всё готово в `GET /wallet` (§7.1).
5. **Каждый запрос** отправляй с заголовками из §2.1; ошибки обрабатывай по `error.code` (§3), текст
   показывай из `error.message` — он уже на языке пользователя.
6. **Токены** храни в Keychain / Keystore (flutter_secure_storage), не в SharedPreferences.
7. Порядок работ, который мы рекомендуем: §2 (клиент, заголовки, ошибки) → §6 (справочники) → §4 (вход) →
   §7–8 (кошелёк, заявки) → §10 (realtime) → §9 (оплата) → §5, §11–14.

---

## 1. Главный принцип: всё считает бек

Мобилка отправляет **только ввод клиента** (услуга, количество/сумма чека, сколько сом оплатить баллами,
способ оплаты) и показывает готовый ответ. Формулы (для понимания, не для реализации):

```
total        = price × quantity            (pricing.type = unit)
             = checkAmount                  (pricing.type = check)
maxPointsSom = min(floor(total × maxPointsShare), floor(available / 100))
pointsSom    = запрошенное, ограниченное 0…maxPointsSom   (сервер обрезает в quote)
moneySom     = total − pointsSom
points       = pointsSom × 100              (100 баллов = 1 сом)
cashback     = round(moneySom × rate × 100) (только с денежной части)
```

`rate` = ставка категории; акция на услугу заменяет её; в неделю дня рождения ставка × 2; если совпали
акция и ДР — берётся большая. **Процент клиенту не показывается**, только баллы.

### Что на что заменяется

| В мобилке сейчас | Что содержит | Эндпоинт |
|---|---|---|
| `LocalCatalogRepository.categories(lang)` | 5 категорий, 15 услуг, правила кешбека | `GET /catalog` |
| `serviceItemProvider(id)` | услуга (в т.ч. скрытая — для истории) | `GET /catalog/items/{id}` |
| `LocalContentRepository` | акции, события, сторис, статьи | `GET /content/promos`, `/content/events`, `/content/stories`, `/content/articles/{id}` |
| `LocalLoyaltyRepository` | 5 уровней, 15 привилегий | `GET /loyalty/program` |
| `FakeLoyaltyServer` — кошелёк | баланс, резерв, уровень, прогресс | `GET /wallet` + realtime `wallet.updated` |
| `FakeLoyaltyServer` — история | операции | `GET /wallet/operations` |
| `FakeLoyaltyServer` — заявки | создание, отмена, статусы | `/cashback-requests…` + realtime `request.updated` |
| `PaymentCalculator` | расчёт на экране оплаты | `POST /cashback-requests/quote` |
| `FakePaymentGateway` | Finik / Freedom Pay / ЭлQR | `POST /payments`, `GET /payments/{id}` |
| `PrefsProfileRepository` | профиль, номер участника, контакты | `GET/PATCH /me`, `GET /resort/contacts`, `GET /me/summary` |
| `PrefsSettingsRepository` | язык, пуши (тема/звуки — локально) | `PATCH /me/settings` |
| Демо-пульт `AdminConsole` в карточке заявки | — | **удалить**: заявки подтверждает сотрудник в админке |

---

## 2. Общие правила API

### 2.1. Заголовки каждого запроса

| Заголовок | Значение | Зачем |
|---|---|---|
| `Authorization` | `Bearer <accessToken>` | для личных эндпоинтов; на публичных можно слать — ответ тот же |
| `Accept-Language` | `ru` \| `ky` \| `en` | язык контента и текстов ошибок; нет перевода → ru |
| `X-Device-Id` | UUID установки (генерировать один раз, хранить) | аналитика воронки, rate limit. Не рекламный ID |
| `X-Platform` | `ios` \| `android` | проверка минимальной версии |
| `X-App-Version` | `1.2.0` | проверка минимальной версии → `426 update_required` |
| `Content-Type` | `application/json` | кроме загрузки фото (`multipart/form-data`) |
| `Idempotency-Key` | случайный UUID на одну попытку отправки | только `POST /cashback-requests` (§8.3) |

### 2.2. Форматы

- **JSON, camelCase.** Деньги — целые сомы (KGS), баллы — целые числа. Дробных сумм нет.
  Дробные только `rate`, `maxPointsShare`, `progress` (0…1).
- **Дата-время** — ISO 8601 с таймзоной курорта: `2026-09-28T18:24:00+06:00`. **Дата** — `YYYY-MM-DD`.
- **Картинки** — абсолютные URL. Уменьшенные варианты: замените `/media/` на `/img/` и добавьте `?w=`:
  `https://app.baytur.kg/media/x.jpg` → `https://app.baytur.kg/img/x.jpg?w=400` (WebP; ширины 200/400/800/1200/1600).
  400 — карточки и кружки сторис, 1200 — шапки и галерея.
- `null` — значение отсутствует; пустые строки в локализованных полях не приходят (fallback на ru).

### 2.3. Пагинация (курсорная)

Списки (`/wallet/operations`, `/cashback-requests`, `/me/notifications`, `/complaints`) — новые сверху:

```
GET /wallet/operations?limit=20            → {"items": [...], "nextCursor": "WyIy..."}
GET /wallet/operations?limit=20&cursor=WyIy...  → следующая страница; nextCursor = null — конец
```

`limit` по умолчанию 20, максимум 100. Курсор непрозрачный — не парсить, просто передавать.

### 2.4. Кеширование справочников

Публичные справочники (`/catalog`, `/catalog/items/{id}`, `/content/*`, `/loyalty/program`, `/resort/contacts`,
`/legal`, `/complaints/categories`) отдают `ETag` и `Cache-Control: public, max-age=300`.

- Храните последний ответ и `ETag` локально — это офлайн-режим.
- При обновлении шлите `If-None-Match: <etag>` → `304 Not Modified` без тела = используйте кеш.
- Ответ одинаков для гостя и вошедшего (зависит только от языка).

### 2.5. Лимиты

| Что | Лимит |
|---|---|
| Любые запросы | 600/мин с IP, 300/мин с `X-Device-Id` |
| Запрос SMS-кода | не чаще 1 раза в 60 с на номер; ≤ 10 в сутки на номер; ≤ 20 в час с IP |
| Ввод кода | 5 попыток, затем код сгорает |
| Новые обращения | 5 в сутки |
| События аналитики | 120 пачек/мин |

Превышение → `429` c `error.retryIn` (секунды) и заголовком `Retry-After`.

### 2.6. Глобальные ответы, которые нужно обработать в HTTP-клиенте (interceptor)

| HTTP | `error.code` | Что делать |
|---|---|---|
| 401 | `auth_required` | гость на личном эндпоинте → показать окно «Войдите…» (§4.6) |
| 401 | `token_invalid` | обновить токен через `/auth/refresh` и повторить запрос; не вышло → разлогин |
| 403 | `account_blocked` | экран «Аккаунт заблокирован» + контакты курорта (`/resort/contacts`) |
| 426 | `update_required` | экран принудительного обновления (`error.minVersion`) |
| 503 | `maintenance` | экран техработ (`error.details` — текст от курорта, может быть null) |

---

## 3. Ошибки

Любая ошибка — единый формат; `message` уже переведён по `Accept-Language`:

```json
{"error": {"code": "insufficient_points", "message": "Недостаточно баллов"}}
```

Иногда есть доп. поля (указаны в таблице). Ошибки валидации полей:

```json
{"error": {"code": "validation_error", "message": "Проверьте введённые данные",
           "fields": {"firstName": ["1–50 символов"]}}}
```

| HTTP | code | Когда | Доп. поля |
|---|---|---|---|
| 400 | `validation_error` | неверные поля | `fields` |
| 400 | `phone_invalid` | номер не E.164 | |
| 400 | `otp_invalid` | неверный код | `attemptsLeft` |
| 400 | `otp_expired` | код просрочен / сгорел после 5 ошибок / не запрашивался | |
| 400 | `registration_expired` | `registrationToken` старше 15 мин или подделан | |
| 400 | `restore_expired` | восстановление недоступно | |
| 401 | `auth_required` | нет токена | |
| 401 | `token_invalid` | токен истёк/отозван | |
| 403 | `account_blocked` | заблокирован админом | |
| 403 | `account_deactivated` | аккаунт удалён (refresh после удаления) | |
| 403 | `account_frozen` | удалённый аккаунт пытается создать заявку/обращение | |
| 403 | `birthday_locked` | попытка сменить уже заданную дату рождения | |
| 403 | `permission_denied` | попытка сменить телефон через `PATCH /me` | |
| 404 | `not_found` | нет объекта (или чужой) | |
| 404 | `item_not_found` | услуга скрыта/не существует | |
| 404 | `consent_unknown` | принятие несуществующей версии документа | |
| 409 | `invalid_status` | действие недоступно в статусе (отмена не-pending) | `status` |
| 409 | `complaint_closed` | ответ в закрытое обращение | |
| 422 | `terms_required` | регистрация без `acceptTerms: true` | |
| 422 | `age_restricted` | младше 16 лет | |
| 422 | `insufficient_points` | баллов не хватает | `maxPointsSom` |
| 422 | `points_limit_exceeded` | превышен лимит оплаты баллами | `maxPointsSom` |
| 422 | `method_not_allowed` | способ оплаты недоступен для услуги | |
| 422 | `amount_out_of_range` | количество/сумма чека вне `pricing.min…max` | `min`, `max` |
| 422 | `payment_invalid` | платёж не найден / не оплачен / сумма не совпадает / уже привязан | `moneySom` (на `/payments`) |
| 503 | `payment_unavailable` | платёжный провайдер недоступен / отклонил создание платежа | — |
| 422 | `file_invalid` | фото не JPEG/PNG/HEIC или > 10 МБ | |
| 426 | `update_required` | версия приложения ниже минимальной | `minVersion` |
| 429 | `otp_too_often` | повторный запрос кода раньше `retryIn` | `retryIn` |
| 429 | `otp_limit` | лимит SMS | `retryIn` |
| 429 | `complaints_limit` | больше 5 обращений в сутки | |
| 429 | `rate_limited` | общий лимит запросов | `retryIn` |
| 503 | `maintenance` | техработы | `details` |
| 500 | `server_error` | ошибка сервера | |

---

## 4. Вход, регистрация, токены

> Полное ТЗ на вход для приложения — экраны, настройка Google/Apple, PIN, тексты, приёмка — в
> [`docs/MOBILE_AUTH.md`](MOBILE_AUTH.md). Ниже — справка по эндпоинтам.

Способ входа — **номер телефона + SMS-код**, один сценарий для входа и регистрации. Паролей нет.
Дополнительно — **Google** и **Apple ID** (§4.7): номер всё равно привязывается один раз, дальше вход в одно нажатие.
И **номер + PIN-код** из 6 цифр (§4.8) — вход без SMS; SMS нужен только при регистрации и если PIN забыт.

### 4.1. Сценарий

```
1. POST /auth/otp/request {phone}
2. POST /auth/otp/verify  {phone, code}  → один из трёх ответов:
   a) {accessToken, refreshToken, expiresIn}          — номер зарегистрирован → на главную
   b) {isNew: true, registrationToken}                — новый номер → форма регистрации (токен живёт 15 мин)
   c) {deactivated: true, restoreToken, purgeAt, balance} — аккаунт удалён < 30 дней назад → §12.3
3. (для b) POST /auth/register {...} → токены + профиль
4. После входа: POST /me/devices {token, platform, appVersion} — push-токен FCM
```

### 4.2. `POST /auth/otp/request`

```json
→ {"phone": "+996555123456"}
← 200 {"expiresIn": 120, "retryIn": 60}
```

Номер — E.164 (пробелы, скобки и дефисы сервер уберёт). Таймер «Отправить ещё раз» — `retryIn` секунд.

### 4.3. `POST /auth/otp/verify`

```json
→ {"phone": "+996555123456", "code": "4821"}
← 200 {"accessToken": "eyJ...", "refreshToken": "Zk9...", "expiresIn": 900}
← 200 {"isNew": true, "registrationToken": "eyJwaG9uZ..."}
← 200 {"deactivated": true, "restoreToken": "...", "purgeAt": "2026-10-29T12:00:00+06:00", "balance": 845000}
← 400 otp_invalid {attemptsLeft} | otp_expired;  403 account_blocked
```

### 4.4. `POST /auth/register` → `201`

```json
→ {
  "registrationToken": "eyJwaG9uZ...",
  "firstName": "Урмат",            // обязательно, 1–50
  "lastName": "Асанов",            // обязательно, 1–50
  "birthday": "1994-05-14",        // обязательно, возраст ≥ 16
  "email": "urmat@example.com",    // необязательно
  "acceptTerms": true,             // обязательно true (условия + политика)
  "marketingConsent": false,       // «Хочу получать акции» — включает notifyPromos
  "language": "ru",                // необязательно, по умолчанию ru
  "pin": "482915"                  // PIN для входа без SMS (§4.8); необязательно — можно задать позже
}
← 201 {"accessToken": "...", "refreshToken": "...", "expiresIn": 900, "profile": { ...как GET /me... }}
```

**Аватарка (необязательно).** Чтобы передать фото сразу при регистрации, отправьте тот же запрос как
`multipart/form-data` с файлом в поле `avatar` (JPEG/PNG/WebP/HEIC до 10 МБ); булевы поля в multipart —
строками `"true"`/`"false"`. Без фото — обычный JSON, как выше. Добавить или сменить фото позже — §5.2.

Ссылки на документы для галочки — из `GET /legal` (§5.4). **Дату рождения** клиент задаёт один раз —
потом её меняет только ресепшен (иначе её меняли бы ради кешбека ×2). Номер телефона — это логин,
клиент его не меняет (только ресепшен). Экраны «сменить номер» в приложении не нужны.

### 4.5. Токены

- `accessToken` — JWT на **15 минут** (`expiresIn` в секундах).
- `refreshToken` — на **30 дней**, **одноразовый**: `POST /auth/refresh {refreshToken}` → новая пара,
  старый refresh сразу недействителен. Повторное использование старого refresh отзывает **всю цепочку**
  (защита от кражи) → потребуется вход заново.
- ⚠️ При параллельных запросах, получивших 401, делайте **один** refresh (mutex/очередь), остальные ждут.
- Хранить — Keychain / Keystore.

```json
POST /auth/refresh  → {"refreshToken": "Zk9..."}
← 200 {"accessToken": "...", "refreshToken": "...(новый)", "expiresIn": 900}
← 401 token_invalid → разлогин;  403 account_blocked / account_deactivated
```

**Выход:** `POST /auth/logout {refreshToken, pushToken}` → `204`. Отзывает refresh и отвязывает push-токен.
После этого удалите токены локально.

### 4.6. Гостевой режим

Без входа работают: каталог, услуги (включая `cashbackPreview` — «сколько баллов вернётся»), сторис, статьи,
акции, события, программа лояльности, контакты, документы, `app/config`. Все личные эндпоинты без токена
отвечают `401 auth_required` → показать **окно поверх текущего экрана** «Войдите, чтобы получить кешбек»
(Войти / Позже). После входа вернуть пользователя туда же (состояние хранит мобилка).
`POST /cashback-requests/quote` тоже требует входа. `X-Device-Id` шлите и гостем — при регистрации бек
свяжет устройство с участником (воронка аналитики).

### 4.7. Вход через Google и Apple ID

Номер телефона остаётся обязательным: по нему клиента находят на точках и подтверждают удаление аккаунта.
Поэтому при первом входе через Google/Apple номер подтверждается SMS-кодом один раз, после чего аккаунт
провайдера привязан и следующие входы идут без SMS.

```
1. Нативный Google Sign-In / Sign in with Apple → id_token / identityToken
2. POST /auth/google {idToken}
   POST /auth/apple  {identityToken, authorizationCode, nonce?, firstName?, lastName?}
   → a) / c) как у /auth/otp/verify            — аккаунт уже привязан → на главную / восстановление
   → {needPhone: true, socialToken, prefill}   — не привязан → экран ввода номера
3. POST /auth/otp/request {phone}
4. POST /auth/otp/verify  {phone, code, socialToken}
   → номер зарегистрирован: токены, аккаунт привязывается к нему
   → новый номер: {isNew, registrationToken} → POST /auth/register (форму заполнить из prefill),
     привязка — при регистрации
```

```json
POST /auth/google → {"idToken": "eyJhbGciOiJSUzI1NiIs..."}
← 200 {"needPhone": true, "socialToken": "eyJwcm92...",
       "prefill": {"firstName": null, "lastName": null, "email": "urmat@gmail.com"}}
← 401 social_invalid — токен не прошёл проверку;  503 social_unavailable — вход не настроен на сервере;
  403 account_blocked
```

- **Google:** `idToken` должен быть выпущен для одного из наших client ID (iOS / Android / Web) — на Android
  в `requestIdToken()` передаётся **Web client ID**.
- **Apple:** имя Apple отдаёт приложению только при **первой** авторизации — передайте `firstName`/`lastName`
  сразу, иначе они потеряются. Если в запрос к Apple передавался `nonce` (SHA-256 от исходной строки), отправьте
  сюда **исходную** строку — сервер её сверит. Email может быть скрытым (`@privaterelay.appleid.com`).
- **Apple:** всегда передавайте `authorizationCode` (из `credential.authorizationCode`). Сервер обменяет его
  на токен Apple и при удалении аккаунта отзовёт доступ — этого требует App Store (5.1.1(v)). Код одноразовый
  и живёт 5 минут — отправляйте сразу после авторизации.
- `socialToken` живёт 15 минут.

**Из профиля:** `POST /me/social/google {idToken}` / `POST /me/social/apple {identityToken, authorizationCode, nonce?}` — привязать
(другой аккаунт того же провайдера заменяет прежний; `409 social_taken` — аккаунт уже у другого участника),
`DELETE /me/social/{provider}` — отвязать. Оба возвращают профиль; в `GET /me` поле
`socialAccounts: ["google", "apple"]` — что привязано.

### 4.8. Вход по номеру и PIN-коду

PIN — 6 цифр, задаётся при регистрации (поле `pin` в `/auth/register`) или позже в профиле. Простые PIN
(`000000`, `111111`, `123456`, `654321`…) не принимаются — `422 pin_weak`. Числа попыток сервер не ограничивает,
есть только общий лимит запросов с одного IP (`429`).

```
Экран входа: номер → [PIN] (основной путь)  или  [Войти по SMS] / [Забыли PIN?] / Google / Apple
```

```json
POST /auth/pin → {"phone": "+996555123456", "pin": "482915"}
← 200 как /auth/otp/verify: токены | {deactivated, restoreToken, ...}
← 400 pin_invalid — неверный номер или PIN (не раскрываем, есть ли номер)
← 400 pin_not_set — у аккаунта нет PIN → войти по SMS (§4.1), затем предложить задать PIN
← 403 account_blocked
```

**Забыли PIN:** `POST /auth/otp/request {phone}` → `POST /auth/pin/reset {phone, code, pin}` → токены.
Все остальные сессии клиента завершаются (на других устройствах — повторный вход).
Если номер не зарегистрирован — ответ `{isNew, registrationToken}`, как у `/auth/otp/verify`.

**В профиле:** `GET /me` → `hasPin`. `false` → после входа предложить задать PIN.
`POST /me/pin {pin}` — задать; `POST /me/pin {pin, currentPin}` — сменить (неверный `currentPin` →
`400 pin_invalid`). Ответ — профиль.

---

## 5. Профиль, настройки, согласия

### 5.1. `GET /me`

```json
{
  "avatar": "https://app.baytur.kg/media/uploads/avatar/2026/09/upl_x7k2....jpg",   // null — фото нет
  "firstName": "Урмат",
  "lastName": "Асанов",
  "phone": "+996555123456",
  "email": "urmat@example.com",
  "birthday": "1994-05-14",
  "memberId": "BT-048219",
  "memberSince": "2023-06-01",
  "settings": {"language": "ru", "notifyCashback": true, "notifyPromos": true},
  "marketingConsent": true,
  "pendingConsents": []
}
```

`memberId` — `BT-` + 6 цифр, не меняется; клиент называет его сотруднику. `avatar`, `email`, `birthday` могут быть `null`
(без аватарки показывайте инициалы, как сейчас).

### 5.2. `PATCH /me`

Поля: `firstName`, `lastName`, `email`, `birthday` (только если сейчас `null`). Ответ — профиль целиком.
`phone` → `403`; смена заданной даты рождения → `403 birthday_locked`.

**Аватарка** (необязательная) — отдельными запросами:

```
POST   /me/avatar   multipart/form-data, поле "file" (JPEG/PNG/WebP/HEIC до 10 МБ) → профиль с новым avatar
DELETE /me/avatar   → профиль, avatar = null
```

Сервер сам обрезает фото в квадрат 512×512 по центру, сжимает и удаляет EXIF (геолокацию). Кроп на клиенте
не обязателен, но экономит трафик. Старое фото удаляется при замене. Ошибка — `422 file_invalid`.

### 5.3. `PATCH /me/settings`

```json
→ {"language": "ky", "notifyCashback": true, "notifyPromos": false}   // любые из полей
← 200 {"language": "ky", "notifyCashback": true, "notifyPromos": false}
```

`language` влияет на язык push. Включение `notifyPromos` = согласие на рекламу, выключение — отзыв.
Тема, цветовая схема, звуки, режим графики — **только локально**, на сервер не отправлять.

### 5.4. Документы и согласия

```json
GET /legal
{"terms":    {"version": "1.0", "url": "https://baytur.kg/ru/terms"},
 "privacy":  {"version": "1.0", "url": "https://baytur.kg/ru/privacy"},
 "deletion": {"version": "1.0", "url": "https://app.baytur.kg/account/delete?lang=ru"}}
```

Если курорт опубликовал новую версию условий/политики, в `GET /me` появится
`pendingConsents: [{"kind": "terms", "version": "2.0", "url": "..."}]` → покажите экран принятия и отправьте
`POST /me/consents {"kind": "terms", "version": "2.0"}` → `{"pendingConsents": [...оставшиеся...]}`.
Проверяйте `pendingConsents` после входа и при открытии приложения.

### 5.5. `GET /resort/contacts` (публичный)

```json
{"phone": "+996312000000", "whatsapp": "996555000000", "mapsUrl": "https://maps.app.goo.gl/...",
 "termsUrl": "https://...", "privacyUrl": "https://...", "deletionUrl": "https://app.baytur.kg/account/delete?lang=ru"}
```

`whatsapp` без «+» — сразу для `https://wa.me/<whatsapp>`. `termsUrl`/`privacyUrl` — пункты «Условия программы»
и «Конфиденциальность» в профиле.

### 5.6. `GET /me/summary` — цифры в профиле

```json
{"available": 845000, "current": 400000, "lifetime": 1400000, "requestsCount": 12}
```

Три цифры профиля: «Доступно» (`available`) · «Нынешние» (`current`) · «Заявок». `lifetime` на главных экранах
не показывается — только в листе «Баллы за всё время» (§7.4).

### 5.7. Push-токен

```
POST   /me/devices           {"token": "<FCM token>", "platform": "android", "appVersion": "1.0.0"} → 204
DELETE /me/devices/{token}   → 204
```

Отправляйте при каждом входе и при обновлении FCM-токена (`onTokenRefresh`). Разрешение на уведомления
запрашивайте после первого реального действия (например, после отправки первой заявки), а не при старте.

### 5.8. `GET /app/config` (публичный)

```json
{"minVersion": {"ios": "1.0.0", "android": "1.0.0"}, "updateRequired": false,
 "maintenance": false, "maintenanceMessage": null}
```

Вызывайте при старте (с `X-Platform`/`X-App-Version`) — `updateRequired: true` → экран обновления.

---

## 6. Каталог, программа, контент (публичные)

### 6.1. `GET /catalog` → `ServiceCategory[]`

Категории с правилами и активными услугами, уже в порядке показа:

```json
[{
  "id": "spa",
  "title": "SPA",
  "cover": "https://app.baytur.kg/media/.../spa.jpg",
  "sortOrder": 2,
  "rules": {"rate": 0.07, "maxPointsShare": 1.0, "methods": ["cash", "finik", "freedomPay", "elqr"]},
  "items": [{
    "id": "spa-bochka",
    "category": "spa",
    "title": "Кедровая бочка",
    "meta": "40 минут · 1 гость",
    "image": "https://app.baytur.kg/media/.../spa-bochka.jpg",
    "gallery": ["https://...spa-bochka.jpg", "https://...spa-bochka-2.jpg"],   // первым идёт image
    "price": 2500,
    "pricing": {"type": "unit", "unit": "session", "min": 1, "max": 10},
    "promoRate": 0.14,              // null — акции нет
    "tag": "×2 баллы",              // null — бейджа нет
    "description": "Фитобочка из кедра: прогрев и травяной пар.",
    "features": [{"icon": "time", "text": "40 минут"}, {"icon": "tea", "text": "Травяной чай"}],
    "outlet": "spa",
    "isActive": true,
    "cashbackPreview": 35000        // баллы за оплату деньгами по цене по умолчанию — «вернётся N баллов»
  }]
}]
```

- `id` категорий фиксирован: `rooms`, `spa`, `food`, `pools`, `sport`.
- `pricing.type = unit` → «цена × количество» (`unit`: night | session | guest | hour | visit; `min…max` количества).
  `pricing.type = check` → клиент вводит сумму чека в `min…max` сом, `price` — средний чек (подсказка и значение по умолчанию).
- `features[].icon` — enum `FeatureIcon` (§17); картинку подбирает мобилка; неизвестное значение — пропустить.
- `rules.rate` клиенту не показывать.
- Акции с датами окончания бек снимает сам: пропадает `promoRate` и бейдж.

### 6.2. `GET /catalog/items/{id}` → `ServiceItem`

Та же структура. Отдаёт **и скрытую** услугу (`isActive: false`) — для старых заявок и истории. `404 item_not_found` —
если услуги нет совсем (тогда используйте `title` из заявки/операции).

### 6.3. `GET /loyalty/program`

```json
{
  "tiers": [
    {"id": "bronze", "order": 0, "name": "Бронза", "threshold": 0, "canBeFloor": true, "retention": "none",
     "entryRule": {"mode": "all", "n": null},
     "style": {"gradient": ["#4A220F", "#99562C", "#D9976A"], "glow": "#D9976A", "medalUrl": null, "icon": null},
     "achievements": [],
     "from": 0, "colors": ["#4A220F", "#99562C", "#D9976A"], "medal": null},
    {"id": "gold", "order": 2, "name": "Золото", "threshold": 300000, "canBeFloor": true, "retention": "points", "...": "..."},
    {"id": "titanium", "order": 4, "name": "Титан", "threshold": 2000000, "canBeFloor": false,
     "retention": "points_and_achievements", "entryRule": {"mode": "all", "n": null},
     "achievements": [{"id": "five-years", "usage": "entry"}, {"id": "annual-evening", "usage": "retention"}],
     "...": "..."}
  ],
  "privileges": [
    {"id": "cashback", "tier": "bronze", "icon": "cashback", "title": "Кешбек баллами", "short": "Кешбек",
     "description": "Баллы за каждую оплату деньгами: 100 баллов = 1 сом."}
  ],
  "achievements": [
    {"id": "five-years", "title": "Быть клиентом 5 лет подряд", "description": "…", "icon": "calendar",
     "scope": "lifetime"}
  ],
  "settings": {"periodType": "calendar_year", "floorDepth": 1}
}
```

- Уровни отсортированы снизу вверх по `order`. **Их количество и id не фиксированы** — курорт создаёт, переименовывает,
  переставляет и удаляет уровни в админке; ETag меняется при любой правке.
- `threshold` — сколько **«Нынешних»** баллов нужно собрать **за один год на предыдущем уровне** (не нарастающий итог).
  В UI: «Соберите N за год».
- `canBeFloor` — может стать вечным; `retention` — как удерживать: `none` · `points` · `points_and_achievements`.
- `achievements[].usage`: `entry` — для получения, `retention` — для подтверждения, `both`. Тексты заданий — в
  `achievements` верхнего уровня (только видимые клиенту).
- `style.gradient` — 3 цвета `#RRGGBB` от тёмного к светлому (`LinearGradient` 135°, остановки 0 / 0.55 / 1),
  `style.glow` — свечение, `style.medalUrl` — PNG/WebP медали или `null` (рисуйте стандартную в цветах градиента).
- `from`, `colors`, `medal` — **устарели**, остаются для старых версий (`from` = накопленная сумма порогов).
- Прогресс и удержание не считайте — они в `GET /wallet` (`tier.next`, `tier.retention`).

### 6.4. Контент

```
GET /content/promos              → Promo[]        (только активные сейчас, по порядку)
GET /content/events              → ResortEvent[]
GET /content/stories             → Story[]        (одна на категорию)
GET /content/articles/{id}       → Article        (диплинк / push)
```

```json
// Article
{"id": "spa-bochka-promo", "image": "https://...", "tag": "Акция", "title": "Кедровая бочка — ×2 баллы",
 "lead": "До 30 сентября — удвоенный кешбек.", "body": ["Абзац 1", "Абзац 2"], "quote": null,
 "date": "2026-09-29", "minutes": 3, "category": "spa"}      // category → кнопка «Открыть в каталоге» (или null)

// Promo — баннер на главной
{"id": 1, "subtitle": "×2 баллы за кедровую бочку", "cta": "Подробнее",
 "cutout": "https://...png",                                 // PNG без фона, «вылезает» за рамку; может быть null
 "article": { ...Article... }}

// ResortEvent — событие недели
{"id": 1, "when": "Сб · 19:00", "place": "Пирс", "article": { ...Article... }}

// Story
{"category": "spa", "title": "SPA", "cover": "https://...", "updatedAt": "2026-09-29T22:40:29+06:00",
 "slides": [{"image": "https://...", "title": "Кедровая бочка", "text": "×2 баллы до конца сентября",
             "itemId": "spa-bochka"}]}                       // itemId → кнопка «Получить кешбек» (или null)
```

«Просмотрено» для сторис храните локально вместе с `updatedAt`: если `updatedAt` новее — снова подсвечивайте.
`date` статьи — реальная дата публикации (не «сегодня минус N»).

---

## 7. Кошелёк и история

### 7.1. `GET /wallet` — единственный источник цифр для главной и уровней

У клиента три счётчика:

| Счётчик | Поле | Что это | Где показывать |
|---|---|---|---|
| Доступные | `available` | можно потратить прямо сейчас (резерв уже вычтен); не сгорают | крупно на карте баланса, оплата баллами |
| Нынешние | `current` | заработанные с последнего сброса; решают уровень; обнуляются при повышении и 1 января; траты их не уменьшают | карточки уровней, подпись к прогрессу |
| За всё время | `lifetime` | всё заработанное; на уровень не влияет | только Профиль → Настройки → «Баллы за всё время» |

```json
{
  "available": 1300000,
  "reserved": 0,
  "current": 400000,
  "lifetime": 1400000,
  "pendingCashback": 0,
  "tier": {
    "id": "gold",
    "since": "2026-08-12T16:00:00+06:00",
    "floor": "silver",                // вечный уровень: ниже него клиент не упадёт
    "isFloor": false,                 // true — показать замок «Навсегда ваш»
    "maxReached": "gold",
    "next": {                         // null на высшем уровне
      "id": "platinum", "threshold": 900000, "left": 500000, "progress": 0.4444,
      "achievements": {"required": 0, "done": 0}
    },
    "retention": {
      "required": true,
      "reason": "check",              // check | floor | new_this_period | not_required
      "periodEnd": "2027-12-31T23:59:59+06:00",
      "limit": 510000, "collected": 400000, "left": 110000, "progress": 0.7843,
      "atRisk": true,                 // показать плашку «Подтвердите Золото: ещё 110 000 до 31 декабря»
      "dropTo": "silver",             // «иначе — Серебро»
      "achievements": {"required": 0, "done": 0}
    }
  },
  "period": {"key": "2027", "start": "2027-01-01T00:00:00+06:00", "end": "2027-12-31T23:59:59+06:00"},

  "balance": 1300000, "nextTier": "platinum", "leftToNext": 500000, "progress": 0.4444
}
```

- `tier.retention.reason`: `check` — в конце года проверка (второй тонкий бар «Подтверждение: collected из limit до …»);
  `floor` — уровень вечный («Навсегда ваш»); `new_this_period` — получен в этом году, подтверждать не нужно;
  `not_required` — уровень без подтверждения (Бронза). Поля `limit…achievements` есть только при `check`.
- `balance`, `nextTier`, `leftToNext`, `progress` — **устарели** (для старых версий: `balance = available + reserved`,
  остальное дублирует `tier.next`). Новая версия их не читает. Поле `expiresAt` удалено — **баллы больше не сгорают**.
- Обновления приходят событием `wallet.updated` (§10) — тот же объект.

**Как работает уровень** (считает сервер, приложению — для текстов):
- кешбек добавляется во все три счётчика; траты уменьшают только «Доступные»;
- когда «Нынешние» ≥ `threshold` следующего уровня (и выполнены его задания «для получения») — повышение,
  «Нынешние» обнуляются, приходит `tier.upgraded`;
- 1 января — закрытие года: если уровень получен до этого года и не вечный, нужно было собрать ≥ `limit`
  (и выполнить задания «для подтверждения»), иначе понижение на один уровень (не ниже пола) — `tier.downgraded`;
- лимит на следующий год = собранное за год + надбавка (10 000), только растёт и хранится по каждому уровню.

### 7.2. `GET /wallet/operations?cursor=&limit=20` — история (ledger)

```json
{"items": [{
  "id": "op_pyd9rxkf31twn6",
  "kind": "cashback",                     // cashback | spend | refund | reversal | adjustment | forfeit (| expire — старые)
  "points": 8000,                         // изменение «Доступных», со знаком
  "at": "2026-09-29T22:40:34+06:00",
  "itemId": "sport-gym",                  // название подставляйте сами на текущем языке (из каталога)
  "category": "sport",                    // для иконки; может быть null
  "requestId": "req_m468s46nqn09b8",      // заявка, породившая операцию; может быть null
  "title": "Тренажёрный зал",             // fallback, если услугу удалили из каталога
  "reason": null,                         // причина корректировки/возврата — показывать клиенту
  "relatedId": null                       // исходная операция для refund/reversal/adjustment
}], "nextCursor": "WyIy..."}
```

Только движения «Доступных». Служебные проводки (резерв, сброс «Нынешних») не отдаются.
`reversal` — «Отмена начисления · {услуга}» (заявку отменили после начисления). `adjustment` — ручная корректировка
курорта (±). `forfeit` — списание при окончательном удалении аккаунта. `expire` больше не создаётся — встречается
только в старых записях. Для операций без услуги `itemId` = null — показывайте `reason`.

### 7.3. `GET /me/achievements` — прогресс по заданиям

```json
{"items": [
  {"id": "five-years", "progress": 3, "target": 5, "completedAt": null, "periodKey": null},
  {"id": "annual-evening", "progress": 1, "target": 1, "completedAt": "2027-06-10T19:00:00+06:00", "periodKey": "2027"}
]}
```

Только видимые клиенту задания; тексты и иконки — из `GET /loyalty/program` → `achievements`. Чек-лист на карте
уровня: «Задания {done} из {total}», «3 из 5 лет», галочка при `completedAt`. Задания «за период» (`periodKey`)
обнуляются 1 января.

### 7.4. `GET /me/loyalty/history` — лист «Баллы за всё время»

```json
{
  "lifetime": 2500000,
  "memberSince": "2026-03-01",
  "periods": [                                   // новые сверху
    {"key": "2028", "tierStart": "silver", "tierEnd": "gold", "collected": 800000, "limit": 510000,
     "result": "promoted_in_period"},
    {"key": "2027", "tierStart": "gold", "tierEnd": "silver", "collected": 400000, "limit": 510000, "result": "dropped"}
  ],
  "tierChanges": [                               // новые сверху
    {"from": "silver", "to": "gold", "at": "2028-05-01T12:00:00+06:00", "cause": "promotion"}
  ]
}
```

`result`: `retained` — «Подтверждён», `promoted_in_period` — «Новый», `dropped` — «Понижен», `floor` — «Навсегда»,
`not_required` — без плашки. `cause`: `promotion`, `period_drop`, `admin`, `migration`.

---

## 8. Заявки на кешбек

### 8.1. Жизненный цикл

```
pending ──(сотрудник подтвердил)──▶ confirmed ──(через 2–3 с)──▶ credited   (кешбек начислен)
   ├──(сотрудник отклонил / истёк срок)──▶ rejected
   └──(клиент отменил)──▶ cancelled
```

- Отмена и отказ — **только из `pending`**. После `confirmed` заявка идёт только в `credited`.
- `pending` держит баллы в резерве (`wallet.reserved`); `confirmed` списывает их (операция `spend`);
  `credited` начисляет кешбек (операция `cashback`: растит `available`, `current` и `lifetime`, может поднять уровень).
- Пока заявка `pending`, сотрудник может **изменить сумму** (не совпала с чеком) — придёт `request.updated`
  с новым `split` и `originalTotal` («Администратор изменил сумму — было …») и `adjustReason`.

### 8.2. Экран оплаты: `POST /cashback-requests/quote` (нужен вход)

Вызывайте **на каждое изменение ввода** (количество, сумма чека, ползунок баллов) с задержкой ~300 мс
(debounce) и рисуйте всё из ответа: сводку «итого → баллами → деньгами → кешбек», предел ползунка,
список способов оплаты.

```json
→ {"itemId": "spa-bochka", "quantity": 2, "checkAmount": null, "pointsSom": 1500}
← 200 {
  "total": 5000,
  "pointsSom": 1500,          // уже обрезано до допустимого
  "points": 150000,
  "moneySom": 3500,
  "rate": 0.14,               // не показывать
  "cashback": 49000,
  "maxPointsSom": 5000,       // предел ползунка «оплатить баллами», сом
  "availablePoints": 845000,
  "methods": ["cash", "finik", "freedomPay", "elqr"],   // пусто, если moneySom = 0
  "bonuses": [{"kind": "promo", "title": "×2 баллы"}]   // или [{"kind": "birthday", "multiplier": 2.0}]
}
```

- Для `pricing.type = unit` передавайте `quantity` (в `pricing.min…max`), для `check` — `checkAmount`.
- Ползунок баллов — шаг 1 сом (100 баллов).
- `bonuses` — подпись «что повлияло на кешбек» (акция / день рождения).
- Ошибки: `404 item_not_found`, `422 amount_out_of_range {min, max}`.

### 8.3. Создание: `POST /cashback-requests`

```http
POST /api/v1/cashback-requests
Idempotency-Key: 7f3c1b2e-...           ← новый UUID на каждую попытку «Отправить»; повтор при плохой сети — с тем же ключом
Content-Type: application/json

{"itemId": "spa-bochka", "quantity": 2, "checkAmount": null, "pointsSom": 1500,
 "method": "finik", "paymentId": "pay_123"}
```

- **Отправляется только ввод.** Сервер пересчитывает всё заново и не доверяет прошлому quote.
- `method`: `cash` | `finik` | `freedomPay` | `elqr`, или `null`, если всё оплачено баллами (`moneySom = 0`).
- `paymentId` — **обязателен** для онлайн-методов (сначала оплата, §9). Для `cash` не передаётся:
  клиент платит на ресепшене, сотрудник подтверждает после приёма денег.
- `201` — создана; `200` с той же заявкой — повтор с тем же `Idempotency-Key` (вторая заявка и второй резерв не создаются).

**Ответ — `CashbackRequest`:**

```json
{
  "id": "req_vfzcxd6myre7a4",
  "status": "pending",
  "createdAt": "2026-09-29T22:40:32+06:00",
  "timeline": {"pending": "2026-09-29T22:40:32+06:00"},
  "item": {"id": "spa-bochka", "category": "spa", "title": "Кедровая бочка", "image": "https://..."},
  "quantity": 2,
  "checkAmount": null,
  "rules": {"rate": 0.14, "maxPointsShare": 1.0, "methods": ["cash", "finik", "freedomPay", "elqr"]},
  "split": {"total": 5000, "pointsSom": 1500, "points": 150000, "moneySom": 3500, "rate": 0.14, "cashback": 49000},
  "method": "finik",
  "receipt": {"id": "pay_123", "method": "finik", "amount": 3500, "at": "2026-09-29T22:40:10+06:00"},
  "originalTotal": null,
  "rejectReason": null,
  "adjustReason": null,
  "bonuses": [{"kind": "promo", "title": "×2 баллы"}]
}
```

- `item` — **снимок на момент заявки**; `item.title` уже на языке запроса. Правила и ставка тоже зафиксированы — смена акции не влияет.
- ⚠️ `timeline` — map `статус → время`, **порядок ключей не гарантирован** (сортируйте по порядку статусов
  pending → confirmed → credited / rejected / cancelled). Может содержать ключ **`adjusted`** (когда правили сумму) —
  это не статус, пропускайте его в шкале этапов или показывайте отдельно.
- `rejectReason` — причина отказа (показывать клиенту в карточке). `receipt` есть, если доплатили онлайн.

**Ошибки создания:**

| HTTP | code | message |
|---|---|---|
| 422 | `insufficient_points` | Недостаточно баллов |
| 422 | `points_limit_exceeded` | Превышен лимит оплаты баллами |
| 422 | `method_not_allowed` | Способ оплаты недоступен для услуги (или `method` не указан при `moneySom > 0`) |
| 422 | `amount_out_of_range` | Сумма / количество вне диапазона |
| 422 | `payment_invalid` | Оплата не найдена или сумма не совпадает |
| 404 | `item_not_found` | Услуга недоступна |
| 403 | `account_frozen` | аккаунт удалён |

Показывайте `message` на шаге оплаты (как сейчас в `FakeLoyaltyServer`).

### 8.4. Список, карточка, отмена

```
GET  /cashback-requests?status=active&cursor=   → {items: CashbackRequest[], nextCursor}   // pending + confirmed — блок «В обработке»
GET  /cashback-requests?status=all&cursor=      → вся история
GET  /cashback-requests/{id}                    → CashbackRequest
POST /cashback-requests/{id}/cancel             → CashbackRequest (status: cancelled); 409 invalid_status, если не pending
```

При отмене/отказе онлайн-оплаченной заявки деньги возвращаются провайдеру автоматически.

---

## 9. Онлайн-оплата

Денежная часть оплачивается **до** отправки заявки (шаги мобилки: redirecting → awaitingScan → processing → paid | failed).

```
1. quote → moneySom
2. POST /payments {method, amountSom: moneySom, itemId, quantity, checkAmount, pointsSom}
     ← 201 Payment {id, status: "created", redirectUrl | qrPayload, expiresAt}
3. Finik / Freedom Pay → открыть redirectUrl (диплинк в приложение провайдера / браузер);
   возврат в приложение по диплинку baytur://payment/{id}
   ЭлQR → нарисовать QR из qrPayload, таймер «Код действует mm:ss» до expiresAt;
   кнопка «Я оплатил» → POST /payments/{id}/check
4. Ждать paid: событие payment.updated (§10) или опрос GET /payments/{id} каждые 2–3 с
5. paid → POST /cashback-requests {..., method, paymentId: id} (с Idempotency-Key)
   failed / expired → показать ошибку, можно создать новый платёж
```

```json
// Payment
{"id": "pay_7m2k...", "method": "elqr", "amount": 3500,
 "status": "created",                         // created | pending | paid | failed | expired | refunded
 "redirectUrl": null, "qrPayload": "00020101021232...", "expiresAt": "2026-09-29T22:45:00+06:00",
 "paidAt": null, "requestId": null}
```

- Сервер сам проверяет, что `amountSom` = `moneySom` по переданным параметрам; иначе `422 payment_invalid`
  с правильной суммой в `error.moneySom`.
- Если клиент закрыл приложение после оплаты и заявку не отправил — **сервер создаст её сам** через ~10 минут
  по данным платежа (деньги не «повиснут»). Если создать уже нельзя (не хватает баллов, услугу скрыли) — вернёт деньги.
- **Freedom Pay** подключён: `redirectUrl` — страница оплаты Freedom Pay (открывать в браузере / WebView).
  После оплаты или отказа она возвращает на `{API}/payments/{id}/return`, а та — на `baytur://payment/{id}`.
  Результат приходит серверу напрямую от Freedom Pay → `payment.updated`; «Я оплатил» (`/check`) тоже спрашивает
  статус у Freedom Pay. Если провайдер недоступен — `503 payment_unavailable`, можно повторить позже.
- ⚠️ Finik и ЭлQR ещё не подключены (и Freedom Pay, пока на сервере не заданы ключи). `redirectUrl` ведёт на тестовую страницу
  «Оплатить / Отказ» — после нажатия она переходит на `baytur://payment/{id}`. Для ЭлQR в тестовом режиме
  `/check` ничего не делает — оплату можно провести только через страницу (§15).

---

## 10. Realtime (WebSocket) и push

### 10.1. WebSocket

```
wss://app.baytur.kg/api/v1/events?token=<accessToken>
```

- Неверный/просроченный токен → сервер отклоняет подключение (рукопожатие WebSocket завершается **HTTP 403**):
  обновите токен через `/auth/refresh` и переподключитесь.
- Токен проверяется только при подключении; после refresh переподключаться не обязательно, но при обрыве —
  подключайтесь со свежим токеном. Переподключение с экспоненциальной задержкой (1, 2, 4… до 30 с).
- Keep-alive: можно слать `{"type": "ping"}` → придёт `{"type": "pong"}`.
- После (пере)подключения сделайте `GET /wallet` и `GET /cashback-requests?status=active` — события,
  пришедшие во время обрыва, не повторяются.

Формат сообщений: `{"type": "<событие>", "data": {...}}`

| type | data | Что делает мобилка |
|---|---|---|
| `request.updated` | `CashbackRequest` | обновить карточку и шкалу этапов; если `status = credited` — праздничный баннер «+N баллов» (N = `split.cashback`), звук, вибрация; `rejected` — тост «Заявка отклонена» |
| `wallet.updated` | `Wallet` | обновить карту баланса и уровень (любое изменение счётчиков или уровня) |
| `tier.upgraded` | `{type, tierId, fromTierId?}` | праздничный экран нового уровня (один раз на `tier.since`) |
| `tier.downgraded` | `{type, tierId, fromTierId}` | спокойный лист понижения при следующем открытии |
| `tier.retained` | `{type, tierId}` | тост с медалью «Уровень подтверждён» |
| `achievement.completed` | `{type, achievementId, tierId?}` | тост с иконкой задания, галочка в чек-листе |
| `notification.created` | `Notification` (§11) | счётчик на колокольчике |
| `payment.updated` | `Payment` | шаг онлайн-оплаты |
| `complaint.updated` | `Complaint` (§13) | обновить переписку |

Если WebSocket недоступен — работает запасной путь: push + повторный GET при открытии экрана/возврате в приложение.

### 10.2. Push (FCM)

Firebase-проект — **`baytur-2add6`**: конфиги `google-services.json` (Android) и `GoogleService-Info.plist` (iOS)
берите из этого проекта, иначе токены устройств не подойдут бэку. Для iOS в Firebase нужно загрузить APNs-ключ.
Токен регистрируйте после входа и при `onTokenRefresh` (§5.7). Недействительные токены бек удаляет сам.

`notification` — заголовок и текст (уже на языке из `settings.language`), `data` — для диплинка (все значения строки):

| `data.type` | Доп. поля в `data` | Куда вести |
|---|---|---|
| `request.credited` | `requestId`, `points` | карточка заявки |
| `request.rejected` | `requestId` | карточка заявки |
| `request.paid` | `requestId`, `points` (отрицательное) | карточка заявки — «Оплачено баллами» (§14.2) |
| `tier.upgraded` | `tierId`, `fromTierId` (и устаревшее `tier`) | вкладка «Уровни» → уровень `tierId` |
| `tier.downgraded` | `tierId`, `fromTierId` | вкладка «Уровни» → уровень `tierId` |
| `tier.retained` | `tierId` | вкладка «Уровни» → уровень `tierId` |
| `tier.at_risk` | `tierId`, `dropTo` | вкладка «Уровни» (за 60, 30 и 7 дней до конца года; по `notifyPromos`) |
| `achievement.completed` | `achievementId`, `tierId?` | вкладка «Уровни» → уровень с этим заданием |
| `points.adjusted` | — | история |
| `complaint.reply` | `complaintId` | обращение |
| `campaign` | `campaignId`, `articleId` и/или `itemId` | статья (`GET /content/articles/{articleId}`) или услуга |

Правила на стороне бека (мобилке делать ничего не нужно): сервисные push — по `notifyCashback`, «заявка
отклонена» и ответ на обращение — всегда; реклама — только `notifyPromos` + согласие, не чаще 4 в месяц;
тихие часы 22:00–09:00 для всего, кроме операций с баллами. При открытии push отправьте событие
аналитики `push_opened` (§14.1) с `campaignId`, если он есть.

Приложение обязано работать и без разрешения на push — все статусы видны через API.

---

## 11. Лента уведомлений

```
GET  /me/notifications?cursor=      → {items: Notification[], nextCursor, unread}
POST /me/notifications/read         {"id": "ntf_..."}  или  {"all": true}   → {"unread": 0}
```

```json
{"id": "ntf_pzbrbbv16jmmdf", "type": "request.credited", "title": "Кешбек начислен",
 "body": "+8 000 баллов за «Тренажёрный зал»", "data": {"type": "request.credited", "requestId": "req_...", "points": 8000},
 "createdAt": "2026-09-29T22:40:34+06:00", "read": false}
```

Хранятся 30 дней. `data` — тот же диплинк, что в push. Колокольчик на главной: `unread` > 0 — точка/счётчик.

---

## 12. Удаление и восстановление аккаунта

Требование App Store и Google Play. Для клиента аккаунт удаляется сразу; на беке он хранится 30 дней и
восстанавливается входом по тому же номеру.

### 12.1. Экран предупреждения

```json
GET /me/deletion/request
{"balance": 845000, "tier": "gold", "purgeDays": 30, "purgeAt": "2026-10-29T12:00:00+06:00",
 "keeps": [{"requestId": "req_...", "itemId": "room-deluxe", "category": "rooms", "title": "Делюкс, вид на озеро",
            "status": "confirmed"}]}
```

Текст: баланс, уровень и история станут недоступны; восстановить можно в течение `purgeDays` дней, войдя по
тому же номеру; потом данные удалятся, а баллы сгорят. `keeps` — брони и заявки, которые сохранятся
(«Ваша бронь … сохранится»).

### 12.2. Подтверждение SMS-кодом

```
POST /me/deletion/request            → {expiresIn, retryIn, ...те же поля} — SMS с кодом отправлен
POST /me/deletion/confirm {"code"}   → {"deleted": true}
```

После этого все токены отозваны, push-токены удалены → локально разлогиньтесь и покажите «Аккаунт удалён».

### 12.3. Восстановление при входе

`/auth/otp/verify` вернёт `{"deactivated": true, "restoreToken", "purgeAt", "balance"}` → спросить
«Восстановить аккаунт? Баллы сохранены (balance)»:

- **Восстановить:** `POST /auth/restore {"restoreToken"}` → `{accessToken, refreshToken, expiresIn, profile}`.
- **Начать заново:** `POST /auth/restart {"restoreToken"}` → `{"isNew": true, "registrationToken"}` — старый
  аккаунт стирается сразу, дальше обычная регистрация (§4.4).

`restoreToken` живёт 15 минут.

Веб-страница удаления без приложения (для Play Console): `deletionUrl` из `/resort/contacts` / `/legal`.

---

## 13. Обращения (поддержка)

Входы: Профиль → «Написать в поддержку»; карточка заявки → «Сообщить о проблеме» (подставить `requestId`);
операция в истории → «Сообщить о проблеме» (подставить `operationId`, `category = points`, `subtype`).

```
GET  /complaints/categories                → {categories: [{id, title}], outlets: [{id, name}], pointsSubtypes: [...]}
POST /uploads/complaint-photo  (multipart, поле "file")  → 201 {id, url}   // JPEG/PNG/HEIC ≤ 10 МБ, до 5 фото
POST /complaints               → 201 Complaint
GET  /complaints?cursor=       → {items: Complaint[] (без messages), nextCursor}
GET  /complaints/{id}          → Complaint с перепиской
POST /complaints/{id}/messages {"text", "attachmentIds": []}   → 201 Complaint   // пока не closed
POST /complaints/{id}/rating   {"rating": 1..5, "comment"?}    → Complaint        // только после closed
```

```json
// POST /complaints
{"category": "points", "outletId": null, "requestId": "req_...", "operationId": "op_...",
 "subtype": "credited_less",             // только для operationId: not_credited | credited_less | overcharged | other
 "text": "Начислили меньше, чем обещали",  // 10–2000 символов
 "attachmentIds": ["upl_..."]}

// Complaint
{"id": "cmp_...", "number": "О-000123", "category": "points", "categoryTitle": "Баллы и заявки",
 "subtype": "credited_less", "outletId": null, "requestId": "req_...", "operationId": "op_...",
 "status": "new",                        // new → in_progress → answered → closed
 "rating": null, "createdAt": "...", "updatedAt": "...",
 "messages": [{"id": 1, "author": "client", "authorName": "Урмат Асанов", "text": "...", "attachments": ["https://..."], "at": "..."},
              {"id": 2, "author": "resort", "authorName": "Команда BAYTUR", "text": "...", "attachments": [], "at": "..."}]}
```

После отправки показывайте номер (`number`). Ответ курорта приходит push `complaint.reply` и событием `complaint.updated`.
Сервер сжимает фото и удаляет EXIF (геолокацию). Лимит — 5 новых обращений в сутки (`429 complaints_limit`).

---

## 14. Аналитика, QR участника, прочее

### 14.1. События аналитики — `POST /events`

Пачкой раз в 30 секунд и при уходе приложения в фон (гостем тоже, токен необязателен) → `202 {accepted, dropped}`.

```json
{"deviceId": "3f1c1a2e-...", "platform": "android", "appVersion": "1.0.0", "language": "ru",
 "events": [{"name": "story_view", "at": "2026-09-28T18:24:00+06:00", "props": {"category": "spa", "slide": 2}}]}
```

Разрешённые `name`: `app_open`, `screen_view`, `login_prompt_shown`, `login_prompt_accepted`, `otp_requested`,
`registration_completed`, `service_view`, `story_view`, `article_view`, `promo_click`, `cashback_flow_started`,
`cashback_flow_step`, `cashback_flow_submitted`, `cashback_flow_abandoned`, `push_opened`. Остальные отбрасываются.

Разрешённые ключи `props` (остальные отбрасываются): `screen`, `category`, `itemId`, `slide`, `articleId`, `promoId`,
`step`, `source`, `requestId`, `campaignId`, `kind`, `method`, `from`, `duration`. **Никаких персональных данных**
(имя, телефон, тексты). Для досмотра сторис отправляйте `story_view` с номером `slide` (с 0) или `kind: "complete"`.

Сторонние SDK аналитики не нужны.

### 14.2. QR участника (вместо диктовки memberId)

```
GET /me/member-qr → {"token": "eyJt...", "expiresAt": "2026-09-29T22:42:00+06:00"}
```

Нарисуйте QR из `token` в профиле и обновляйте за ~10 с до `expiresAt` (живёт ~90 с — скриншот чужого QR не сработает).
Сотрудник сканирует его на планшете.

**Оплата баллами по QR.** Клиент заказал услугу и показывает QR — сотрудник сканирует его, выбирает услугу,
и если баллов хватает, списывает их (иначе просит оплатить деньгами). Для мобилки это обычная заявка:

- приходит `request.updated` (статус `confirmed`, `method: null`, `split.moneySom = 0`, `split.cashback = 0`)
  и `wallet.updated`, затем push/уведомление **`request.paid`** «Оплачено баллами: −N баллов за …»;
- в истории — операция `spend` с `requestId`; в списке заявок — заявка этой услуги.

Отдельного экрана в приложении не нужно: достаточно, чтобы QR в профиле открывался быстро (кнопка на главной
или в профиле) и чтобы `request.paid` показывался в ленте.

---

## 15. Тестовые данные и ограничения staging

| Что | Значение |
|---|---|
| Базовый URL | `https://app.baytur.kg/api/v1` |
| Тестовый номер (для сторов и разработки) | `+996700000000`, код **`1234`** (SMS не отправляется). У аккаунта есть баллы, история и заявки во всех статусах; новые заявки подтверждаются автоматически через ~5 с |
| Демо-профиль из ТЗ | `BT-048219`, `+996555123456` (код `1234`), баланс 845 000, «Золото» |
| SMS на любые номера | **временно не отправляются** — для любого номера подходит код **`1234`** (пока не подключён SMS-провайдер; в production будет настоящая SMS) |
| Онлайн-оплата | тестовая страница вместо Finik / Freedom Pay / ЭлQR, деньги не списываются |
| Push | **работают** через FCM, Firebase-проект `baytur-2add6`. В приложении должен быть `google-services.json` / `GoogleService-Info.plist` **этого же проекта**, а FCM-токен — зарегистрирован через `POST /me/devices` |
| Фото каталога | пока заглушки (URL есть, файлов нет) — используйте плейсхолдер при ошибке загрузки |
| Тексты каталога/контента | заготовка; реальные данные из мобилки ещё переносятся |

Для проверки «наличных» заявок нужен сотрудник: курорт подтверждает их в админке `https://app.baytur.kg/panel/`.
Тестовый аккаунт подтверждает заявки сам.

---

## 16. Чек-лист экранов

| Экран / элемент | Эндпоинты |
|---|---|
| Сплэш | `GET /app/config`; при наличии токена — `GET /me` (`pendingConsents`) |
| Главная: приветствие, аватар | `GET /me` (гость — без имени) |
| Главная: карта баланса | `GET /wallet` + `wallet.updated`: крупно `available`, подпись и бар — по `tier.next`, плашка риска при `tier.retention.atRisk`; гость — карточка «Войдите — начислим баллы» |
| Главная: быстрые разделы | `GET /catalog` |
| Главная: «В обработке» | `GET /cashback-requests?status=active` + `request.updated` |
| Главная: акции, события | `GET /content/promos`, `GET /content/events` |
| Главная: колокольчик | `GET /me/notifications` (`unread`) + `notification.created` |
| Уровни | `GET /loyalty/program` + `GET /wallet` + `GET /me/achievements` (гость — пороги «Соберите N за год», кнопка «Войти и начать копить») |
| Каталог, сторис | `GET /catalog`, `GET /content/stories` |
| Страница услуги | данные из `/catalog` или `GET /catalog/items/{id}`; `cashbackPreview` |
| Статья / диплинк | `GET /content/articles/{id}` |
| Кешбек: выбор → детали → оплата | `GET /catalog`, `POST /cashback-requests/quote` (debounce 300 мс) |
| Кешбек: онлайн-оплата | `POST /payments`, `GET /payments/{id}` / `payment.updated`, `POST /payments/{id}/check` |
| Кешбек: «Заявка отправлена» | `POST /cashback-requests` (Idempotency-Key), затем realtime |
| Карточка заявки | `GET /cashback-requests/{id}`, `POST …/cancel`, `rejectReason`, `originalTotal` |
| История | `GET /cashback-requests?status=all`, `GET /wallet/operations` |
| Профиль: карточка участника | `GET /me`, `GET /me/summary` (Доступно · Нынешние · Заявок), `GET /me/member-qr` |
| Профиль → Настройки → «Баллы за всё время» | `GET /me/loyalty/history` |
| Профиль: редактирование | `PATCH /me` (без телефона; ДР — один раз), `POST/DELETE /me/avatar` |
| Профиль: уведомления, язык | `PATCH /me/settings` |
| Профиль: курорт, документы | `GET /resort/contacts` |
| Профиль: выход | `POST /auth/logout` |
| **Новые экраны** | |
| Ввод номера и кода | `POST /auth/otp/request`, `POST /auth/otp/verify` |
| Вход по номеру и PIN, «Забыли PIN?» | `POST /auth/pin`, `POST /auth/pin/reset` |
| Профиль: задать / сменить PIN | `POST /me/pin` |
| Вход через Google / Apple | `POST /auth/google`, `POST /auth/apple` → номер + код с `socialToken` |
| Профиль: привязка Google / Apple | `POST`/`DELETE /me/social/{google\|apple}` |
| Регистрация с согласиями и фото (необязательно) | `POST /auth/register` (JSON или multipart с `avatar`), `GET /legal` |
| Принятие новой версии условий | `GET /me` → `pendingConsents`, `POST /me/consents` |
| Удаление аккаунта | `GET/POST /me/deletion/request`, `POST /me/deletion/confirm` |
| Восстановление при входе | `/auth/otp/verify` (deactivated), `POST /auth/restore`, `POST /auth/restart` |
| «Нужно обновить» / «Заблокирован» / техработы | `GET /app/config`, ошибки 426 / 403 / 503 |
| Поддержка, мои обращения | §13 |
| QR участника | `GET /me/member-qr` |
| Удалить из мобилки | демо-пульт администратора, подпись «Демо: оплата имитируется», `PaymentCalculator`, `TierProgram.statusFor` |

---

## 17. Справочник enum-значений

| Enum | Значения |
|---|---|
| `CategoryId` | `rooms`, `spa`, `food`, `pools`, `sport` |
| `PaymentMethod` | `cash`, `finik`, `freedomPay`, `elqr` |
| Уровень (`tier.id`) | **не enum** — строка-id из `GET /loyalty/program`; по умолчанию `bronze`, `silver`, `gold`, `platinum`, `titanium`, `ambassador`, но курорт может добавлять и удалять уровни (`diamond` больше не приходит — это `titanium`) |
| `retention.reason` | `check`, `floor`, `new_this_period`, `not_required` |
| `PeriodResult` | `retained`, `dropped`, `promoted_in_period`, `floor`, `not_required` |
| `RequestStatus` | `pending`, `confirmed`, `credited`, `rejected`, `cancelled` |
| `OperationKind` | `cashback`, `spend`, `refund`, `reversal`, `adjustment`, `forfeit` (`expire` — только старые записи) |
| `PaymentStatus` | `created`, `pending`, `paid`, `failed`, `expired`, `refunded` |
| `PricingType` / `PricingUnit` | `unit`, `check` / `night`, `session`, `guest`, `hour`, `visit` |
| `BonusKind` | `promo`, `birthday` |
| `FeatureIcon` | `view`, `bed`, `people`, `area`, `wifi`, `breakfast`, `terrace`, `pool`, `time`, `towel`, `tea`, `music`, `fire`, `chef`, `drink`, `sun`, `water`, `gym`, `trainer`, `bath`, `nature`, `cold`, `warm`, `tv`, `flower` |
| `PerkIcon` | `cashback`, `birthday`, `drink`, `earlyCheckIn`, `beach`, `parking`, `lateCheckOut`, `upgrade`, `spa`, `transfer`, `concierge`, `chef`, `villa`, `events`, `gift` |
| `Language` | `ru`, `ky`, `en` |
| `Platform` | `ios`, `android` |
| `ComplaintStatus` | `new`, `in_progress`, `answered`, `closed` |
| `ComplaintSubtype` | `not_credited`, `credited_less`, `overcharged`, `other` |
| `ConsentKind` | `terms`, `privacy` |
| Push / realtime `type` | `request.updated`, `wallet.updated`, `notification.created`, `payment.updated`, `complaint.updated`, `request.credited`, `request.rejected`, `request.paid`, `tier.upgraded`, `tier.downgraded`, `tier.retained`, `tier.at_risk`, `achievement.completed`, `points.adjusted`, `complaint.reply`, `campaign` (`points.expiring` / `points.expired` удалены) |

Новые значения `FeatureIcon` / `PerkIcon` / способов оплаты появляются только вместе с релизом мобилки;
остальные enum могут расширяться — неизвестное значение не должно ломать парсинг.

---

*Вопросы по API — бек-команде. Полная машинно-читаемая схема: https://app.baytur.kg/api/v1/schema.*
