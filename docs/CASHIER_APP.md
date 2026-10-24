# BAYTUR — приложение кассира: ТЗ для мобильного разработчика

Для мобильного разработчика и его AI-ассистента. Бэкенд готов и выложен на `https://app.baytur.kg`
(staging). Общие правила API — в `docs/MOBILE_API.md` §2–3 (заголовки, формат ошибок `{error: {code, message}}`,
даты ISO 8601 `+06:00`, тексты на языке `Accept-Language`). Машинная схема: `https://app.baytur.kg/api/v1/schema`,
тег «Сотрудник».

---

## 0. Инструкция для AI-ассистента

1. Это **отдельное приложение** (или отдельный режим в общем Flutter-проекте) для администраторов касс курорта.
   Клиентское приложение не трогаем.
2. **Приложение ничего не считает.** Суммы, кешбек, баллы, лимиты, «хватает ли баллов» — только из ответов API.
3. **Кассир не видит баланс и историю клиента** — бэкенд их не отдаёт; не пытайся их показать.
4. Все действия — только по заявкам и обращениям **своих точек** (`profile.outlets`); чужие бэкенд вернёт как 404.
5. Ошибки обрабатывай по `error.code`, текст показывай из `error.message` (уже на языке пользователя).
6. Токены — в Keychain / Keystore (flutter_secure_storage).
7. Порядок работ: вход и сессия (§3) → очередь и карточка заявки (§4) → realtime (§5) → поиск/QR клиента (§6) →
   оплата баллами (§7) → обращения (§8) → итог смены и профиль (§9).

---

## 1. Кто пользуется

| Роль | Где работает | Вход |
|---|---|---|
| **Директор** | веб-панель `https://app.baytur.kg/panel/` (полный доступ) | email + пароль + 2FA |
| **Администратор кассы** | **это приложение** | номер телефона + 6-значный PIN |

Администратор привязан к одной или нескольким **точкам** (кассам): Ресепшен, SPA, Спорт, бассейн, баня и т. д.
Точки и администраторов создаёт директор в панели (Сотрудники → «Сотрудник» → роль «Администратор кассы»).
PIN задаёт директор; администратор может сменить свой PIN в приложении.

Что умеет администратор (только по своим точкам):
- видеть очередь заявок клиентов, подтверждать, отклонять, править сумму;
- найти клиента по номеру / номеру участника или отсканировать QR клиента;
- провести оплату баллами по QR клиента;
- видеть обращения своей точки и оставлять внутренние заметки;
- смотреть итог смены.

---

## 2. Экраны

| Экран | Содержание | API |
|---|---|---|
| Вход | Телефон (маска +996), PIN 6 цифр (цифровая клавиатура, точки). Ошибка — тряска поля + текст | `POST /staff/auth/login` |
| Очередь (главная) | Заявки `pending` своих точек, старые сверху; карточка: услуга, клиент (имя, маск. телефон, уровень), сумма, «наличные N сом» / «оплачено онлайн» / «баллами», бейдж «у директора» при `escalated`. Новые приходят по WebSocket со звуком | `GET /staff/queue`, WS |
| Карточка заявки | Детали + кнопки «Подтвердить» (для наличных — чекбокс «деньги приняты»), «Изменить сумму» (лист с предпросмотром), «Отклонить» (причина) | §4 |
| Клиент | Поиск по номеру / `memberId`; сканер QR. Показ: имя, маск. телефон, уровень, заявки в моих точках | `GET /staff/members`, `POST /staff/scan` |
| Оплата баллами | После скана QR: выбрать услугу своей точки → количество / сумма чека → «Хватает баллов?» → «Списать» | §7 |
| Обращения | Список обращений своих точек, карточка с перепиской, поле «Внутренняя заметка» | §8 |
| Итог смены | Подтверждено / отклонено сегодня, сколько правок, сумма наличных для сверки кассы | `GET /staff/shift` |
| Профиль | Имя, точки, «Сменить PIN», «Выйти» | `GET /staff/me`, `POST /staff/me/pin`, `POST /staff/auth/logout` |

---

## 3. Вход и сессия

### `POST /api/v1/staff/auth/login`
```json
→ {"phone": "+996700900001", "pin": "482913"}
← 200 {
  "accessToken": "eyJ...", "refreshToken": "ZDX...", "expiresIn": 900,
  "profile": {"id": 3, "email": null, "phone": "+996700900001", "fullName": "Тест: касса ресепшена",
              "role": "staff", "outlets": ["reception"],
              "permissions": ["complaints.notes", "complaints.view", "members.view", "requests.process"],
              "mustChangePassword": false}
}
```
Телефон можно присылать с пробелами — бэкенд нормализует. Ошибки:

| Код | HTTP | Когда | Что показать |
|---|---|---|---|
| `invalid_credentials` | 401 | неверный номер или PIN | «Неверные данные для входа» |
| `rate_limited` | 429 | 5 неверных PIN подряд → блок на 15 мин; `retryIn` — секунд до разблокировки | таймер «Попробуйте через N мин» |

- `accessToken` живёт 15 минут (`expiresIn`), шлите его в `Authorization: Bearer …`.
- `POST /staff/auth/refresh` `{refreshToken}` → новая пара (ротация: старый refresh одноразовый). `401 token_invalid` → на экран входа.
- `POST /staff/auth/logout` `{refreshToken}` → 204.
- `GET /staff/me` → `profile`. Если директор отключил сотрудника или сменил PIN — refresh вернёт 401: на вход.
- `POST /staff/me/pin` `{currentPin, newPin}` → `profile`. Ошибки: `invalid_credentials` (текущий неверный),
  `pin_weak` (одинаковые цифры или подряд: 111111, 123456), `validation_error` (не 6 цифр).

---

## 4. Заявки

Заявку создаёт клиент в своём приложении («получить кешбек» / оплата), она попадает в очередь точки услуги.

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/staff/queue?outlet=` | — | `{items: [StaffRequest], count}` — pending своих точек, старые сверху |
| GET | `/staff/requests/{id}` | — | `StaffRequest` |
| POST | `/staff/requests/{id}/confirm` | `{cashReceived: true}` (для наличных обязательно) | `200 StaffRequest`; **`202`** — ушло на подтверждение директору (кешбек выше лимита) |
| POST | `/staff/requests/{id}/adjust/preview` | `{total}` | новый расчёт без сохранения + `needsManager`; `422 insufficient_points` (`shortSom`) — заявке баллами не хватит баллов на новую сумму |
| POST | `/staff/requests/{id}/adjust` | `{total, reason}` | `200` / **`202`** — правка больше порога ушла директору; `422 insufficient_points` — см. ниже |
| POST | `/staff/requests/{id}/reject` | `{reasonCode, comment?}` | `StaffRequest` |

**Оплата «всё или ничего».** Заявка оплачена либо целиком деньгами, либо целиком баллами — смешанной нет.
Правка суммы это сохраняет: денежная заявка остаётся денежной (при уменьшении онлайн-оплаты разница
возвращается клиенту), заявка баллами списывает баллами всю новую сумму (при уменьшении лишние баллы
возвращаются в доступные). Если баллов на новую сумму не хватает — `422 insufficient_points` с `shortSom`,
заявка не меняется: отклоните её (`wrong_amount`), клиент создаст новую на верную сумму.

`reasonCode`: `not_provided` (услуга не оказана), `wrong_amount` (неверная сумма), `duplicate` (дубль), `other`
(комментарий обязателен).

```json
// StaffRequest (сокращённо)
{
  "id": "req_m468s46nqn09b8", "status": "pending", "createdAt": "2026-10-06T12:00:00+06:00",
  "outlet": "reception",
  "item": {"id": "room-deluxe", "category": "rooms", "title": "Делюкс", "image": "https://..."},
  "quantity": 2, "checkAmount": null,
  "split": {"total": 12000, "pointsSom": 0, "points": 0, "moneySom": 12000, "rate": 0.07, "cashback": 84000},
  "method": "cash", "paidOnline": false, "cashToCollect": 12000, "cashReceived": false,
  "escalated": false, "escalationReason": null, "proposedTotal": null, "originalTotal": null,
  "member": {"id": 6, "memberId": "BT-957857", "name": "Тест Клиент касс", "phone": "+996•••••010",
             "tier": "bronze", "status": "active"},
  "timeline": {"pending": "2026-10-06T12:00:00+06:00"}
}
```

Ошибки действий: `invalid_status` 409 (заявка уже обработана), `cash_not_received` 422 (не отмечено «деньги приняты»),
`own_account` 403 (своя клиентская заявка), `outlet_forbidden` 403 / 404 (чужая точка).

---

## 5. Realtime

WebSocket `wss://app.baytur.kg/api/v1/staff/events?token=<accessToken>` — события по своим точкам:
`{"type": "request.created" | "request.updated", "data": StaffRequest}`. При `request.created` — добавить в очередь
со звуком и вибрацией; при `request.updated` — обновить/убрать из очереди. После (пере)подключения — заново
`GET /staff/queue`. Токен истёк — переподключиться с новым.

---

## 6. Клиент: поиск и QR

- `GET /staff/members?q=<телефон или BT-…>` → `{items: [MemberBrief]}`.
- `POST /staff/scan` `{token}` — `token` из QR клиентского приложения (живёт ~90 с) →
  `{...MemberBrief, payToken}`. `payToken` — разрешение на оплату баллами этого клиента 10 минут.
  Ошибка `qr_invalid` 400 — QR устарел, попросить клиента обновить.

```json
// MemberBrief — без баланса и истории
{"id": 6, "memberId": "BT-957857", "name": "Тест Клиент касс", "phone": "+996•••••010", "tier": "bronze",
 "status": "active", "deletedNote": null, "requests": [StaffRequest]}
```

---

## 7. Оплата баллами по QR

1. `POST /staff/scan` → `payToken`.
2. `GET /staff/points/items` → услуги своих точек: `{items: [{id, category, title, price, pricing, outlet}]}`.
3. `POST /staff/points/quote` `{payToken, itemId, quantity? | checkAmount?}` →
   `{itemId, total, quantity, points, enough, shortSom, reason: "balance"|null}`. Лимита доли по разделам нет —
   баллами можно оплатить любую услугу целиком (`limitPercent` устарел, всегда 100).
   Сам баланс не раскрывается — только «хватает / не хватает N сом».
4. `POST /staff/points/charge` (те же поля) → `201 StaffRequest` (заявка «оплачено баллами», уже подтверждена).
   Ошибки: `insufficient_points` 422 (`shortSom`), `qr_invalid` (payToken истёк).

Клиент получает push «Оплачено баллами: −N баллов».

---

## 7б. Оформление по QR клиента (с 24.10.2026)

Кассир оформляет клиента сам по QR клиента. Способов оплаты два:
- **наличными** — по QR фискального чека: `/staff/cash/preview` и `/staff/cash/accept`
  `{payToken, itemId, receiptQr, quantity?, requestId?, amount?}`. `amount` — сумма со скидкой, которую вписал кассир:
  сумма чека должна совпасть с ней; без `amount` — с цена × `quantity` (номер × 6 ночей). Не совпала → `422
  receipt_amount_mismatch {amount (из чека), expected, price, quantity}`; без `quantity` и `amount` количество =
  сумма чека / цена. Принимаются только чеки нашей организации: ИНН продавца из чека сверяется с ИНН из настроек
  админки («Настройки» → «Чеки», можно несколько), чужой → `422 receipt_wrong_seller` (и в preview, и в accept).
  В ответе preview и в заявке — `originalTotal` (сумма по прайсу, если была скидка). В ответе accept — `cancelUntil`;
- **баллами** — списываются, только когда клиент подтвердит у себя в телефоне.

1. `POST /staff/scan` → `payToken`; `GET /staff/points/items` — у услуги есть `receiptRequired`.
2. `POST /staff/sales/quote` `{payToken, itemId, quantity?, amount? | checkAmount?}` →
   `{itemId, total, originalTotal, quantity, cashback, points, enough, shortSom, duplicate: {requestId, at} | null, …}`.
   **Скидка кассира:** для услуг с ценой за единицу `amount` — итог со скидкой, от 0 до цена × quantity
   (выше → `422 amount_out_of_range {min: 0, max}`). Баллы, кешбек и заявка считаются от `amount`, акции не
   применяются; `originalTotal` — сумма по прайсу (null, если скидки нет). `amount = 0` допустим: баллов 0, клиент
   всё равно подтверждает. Без `amount` — по прайсу с акциями, как раньше. Баланс не раскрывается. `cashback` — сколько клиент получит при оплате наличными.
   `duplicate` — той же услуге этому клиенту оформляли за последние 10 минут.
3. `POST /staff/sales` + `Idempotency-Key`, тело `{payToken, itemId, quantity?, amount? | checkAmount?}` → `201 StaffRequest`
   в статусе `awaiting_client`, с `confirmUntil` (+2 мин) и `cancelUntil` (+10 мин). Баллы в резерве, не списаны.
   Клиенту — WS `charge.confirm` и push того же `type`: `{requestId, itemTitle, total, points, quantity,
   outletTitle, staffName, expiresAt}` (в push — строки). Клиент: `POST /cashback-requests/{id}/approve`
   (Idempotency-Key) → `confirmed`; `POST /cashback-requests/{id}/decline` → `rejected` (`client_declined`);
   не успел → `rejected` (`client_timeout`); поздно / уже обработано → `409 invalid_status`.
   Ошибки: `qr_invalid`, `insufficient_points {shortSom}`, `own_account`, `outlet_forbidden`, `amount_out_of_range`.
   Каждое изменение — `request.updated` в WS кассира. После оформления клиенту — push `type: request.credited`
   с `requestId` («Сообщить о проблеме»).
4. Отмена: `POST /staff/requests/{id}/cancel` `{reason}` → `StaffRequest` (`cancelled`). Своё оформление (баллами
   или наличными по чеку) — до `cancelUntil`, позже — `409 cancel_expired` (отменяет директор в панели). Работает и в
   `awaiting_client`. Баллы возвращаются, кешбек отзывается, наличные выпадают из смены, чек можно принять заново.
   Клиенту — push `type: request.updated` с `requestId`. `cancelUntil` есть и в ответе `/staff/cash/accept`.
5. Новое в `StaffRequest`: статус `awaiting_client`; поля `originalTotal` (по прайсу при скидке), `cancelUntil`, `confirmUntil`, а также `createdBy`,
   `rejectCode`, `cancelReason`, `cancelledBy`, `cancelledAt`, `duplicateOf`.
6. Старые `/staff/points/quote` и `/staff/points/charge` (списание без подтверждения клиента) оставлены для старых
   версий приложения и будут отключены.

---

## 7а. Купон «подарок за регистрацию»

**Основной путь — через QR участника.** `POST /staff/scan` теперь отдаёт и `coupons` — неиспользованные подарки
клиента (тот же формат, что ниже). Кассир видит их сразу, клиент выбирает, кассир нажимает «Выдать»:
`POST /staff/coupons/redeem` `{payToken, couponId, note?}` → купон со статусом `redeemed`. После этого подарок
пропадает у клиента (`coupon.updated`) и из следующих сканов. Пустой `coupons` — подарков нет.

**Запасной путь — QR самого купона** (если клиент открыл экран купона):

Клиент показывает QR купона из приложения (живёт ~90 с) — это другой QR, не QR участника.

1. `POST /staff/coupons/scan` `{token}` → купон: `{id, kind, value, valueText, title, description, terms, status,
   expiresAt, member: {memberId, name, phone}, redeemedBy, note}`. Показать, что даёт купон и его статус.
2. `POST /staff/coupons/redeem` `{token, note?}` → купон со статусом `redeemed`. Кнопка только отмечает
   купон использованным — скидку или подарок кассир оформляет по условиям купона.
   Ошибки: `invalid_status` 409 (уже использован / истёк — текст в `message`), `qr_invalid` 400 (QR устарел),
   `own_account` 403.

Подсказка: если сканер получил токен, а `/staff/scan` ответил `qr_invalid`, попробуйте `/staff/coupons/scan`
(или различайте по экрану, откуда сканируют).

---

## 8. Обращения своих точек

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/staff/complaints?status=&cursor=` | `{items: [...], nextCursor}` |
| GET | `/staff/complaints/{id}` | карточка: тема, статус, переписка `messages`, `internalNotes`, клиент |
| POST | `/staff/complaints/{id}/notes` `{text}` | `201` карточка с новой заметкой |

Отвечать клиенту, менять статус и начислять компенсацию может только директор (`canReply: false` у кассира).
Заметки клиент не видит.

---

## 9. Итог смены

`GET /staff/shift` → `{date, confirmed: [StaffRequest], rejected: [StaffRequest], cancelled: [StaffRequest],
adjustedCount, cashTotal}` — за сегодня по этому сотруднику. `confirmed` — всё оформленное, включая
`awaiting_client`. `cashTotal` — сколько наличных должно быть в кассе (без отменённых).

---

## 10. Приёмка

- ☐ Вход по телефону и PIN; неверный PIN — ошибка; после 5 ошибок — таймер блокировки.
- ☐ Очередь показывает только заявки своих точек; новая заявка клиента появляется без обновления (WebSocket).
- ☐ Подтверждение наличной заявки требует отметки «деньги приняты»; `202` показывается как «Отправлено директору».
- ☐ Правка суммы: предпросмотр до сохранения, причина обязательна.
- ☐ Отклонение с причиной; «Другое» — с комментарием.
- ☐ Скан QR клиента → карточка без баланса; оплата баллами: quote → charge; недостаток баллов — понятный текст.
- ☐ Обращения своей точки: просмотр и заметка; кнопки ответа клиенту нет.
- ☐ Итог смены, смена PIN, выход; после смены PIN директором — выход на экран входа.
- ☐ Тексты на ru / ky / en.

Тестовые входы (staging) выдаёт бэкенд-команда отдельно — в репозиторий они не кладутся.
