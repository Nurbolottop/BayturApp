# BAYTUR — вход и регистрация: ТЗ для мобильного приложения

Для мобильного разработчика и его AI-ассистента (Claude). Документ самодостаточный по теме входа: способы входа,
настройка Google и Apple в проекте, экраны, все эндпоинты с примерами, ошибки, тексты, приёмка.
Общие правила API (заголовки, пагинация, кеш) — в [`docs/MOBILE_API.md`](MOBILE_API.md) §2–3; здесь повторено
только то, что нужно для входа.

**Статус бэкенда (06.10.2026):** всё из этого документа реализовано, покрыто тестами и **уже работает** на
`https://app.baytur.kg`. Демо-сервер не нужен — разрабатывайте сразу против сервера (тестовые номера — §9).

| Что | Ссылка |
|---|---|
| Базовый URL API | `https://app.baytur.kg/api/v1` |
| Swagger (попробовать запросы) | https://app.baytur.kg/api/v1/docs |
| Машинная схема OpenAPI (для генерации DTO) | https://app.baytur.kg/api/v1/schema |
| Этот документ | https://github.com/Nurbolottop/BayturApp/blob/main/docs/MOBILE_AUTH.md |
| Общий API | https://github.com/Nurbolottop/BayturApp/blob/main/docs/MOBILE_API.md |

---

## Содержание

0. [Инструкция для AI-ассистента](#0-инструкция-для-ai-ассистента)
1. [Способы входа за 1 минуту](#1-способы-входа-за-1-минуту)
2. [Настройка проекта: bundle ID, Google, Apple, пакеты](#2-настройка-проекта)
3. [Общие правила API для входа](#3-общие-правила-api-для-входа)
4. [Экраны и сценарии](#4-экраны-и-сценарии)
5. [Справочник эндпоинтов](#5-справочник-эндпоинтов)
6. [Код Flutter](#6-код-flutter)
7. [Ошибки](#7-ошибки)
8. [Тексты (.arb)](#8-тексты-arb)
9. [Тестирование на сервере](#9-тестирование-на-сервере)
10. [Приёмка](#10-приёмка)
11. [Что ещё не готово](#11-что-ещё-не-готово)

---

## 0. Инструкция для AI-ассистента

Ты делаешь в Flutter-приложении BAYTUR вход и регистрацию. Правила:

1. **Сервер — единственный источник правды.** Проверку PIN, токенов Google/Apple, SMS-кодов делает сервер.
   Приложение ничего не проверяет само, кроме формата (6 цифр PIN, номер в E.164).
2. **Не храни PIN на устройстве** ни в каком виде. Номер телефона последнего входа хранить можно (для удобства).
3. **Токены** (`accessToken`, `refreshToken`) — только во `flutter_secure_storage` (Keychain / Keystore).
4. **Тексты ошибок** показывай из `error.message` — он уже на языке пользователя. Логику строй по `error.code` (§7).
5. **Любой вход заканчивается одинаково:** пришли токены → сохранить → `GET /me` → `POST /me/devices` → главная (§4.8).
   Пришло `{deactivated: true, ...}` → экран восстановления (§4.7). Не дублируй эту логику в каждом способе входа —
   сделай один обработчик ответа входа.
6. **Кнопка Apple — только на iOS.** На Android её не показывать.
7. **DTO** генерируй из `https://app.baytur.kg/api/v1/schema` или вручную по §5. Неизвестные поля в ответах игнорируй.
8. **Не трогай стиль** — используй существующие компоненты и токены дизайна приложения. Новые тексты — в три
   .arb (ru, ky, en), ключи из §8.
9. **Порядок работ:** §2 (настройка) → общий обработчик ответа входа и refresh (§3, §4.8) → вход по SMS и
   регистрация (§4.2) → PIN (§4.3–4.5, §4.9) → Google и Apple (§4.6) → профиль: PIN и привязки (§4.9–4.10) → §10.
10. Если ответ сервера расходится с этим документом — прав сервер (схема по ссылке выше); сообщи о расхождении.

---

## 1. Способы входа за 1 минуту

**Номер телефона обязателен для каждого клиента**: по нему клиента находят на точках курорта и им подтверждают
удаление аккаунта. Поэтому при регистрации через Google/Apple номер всё равно подтверждается SMS-кодом — один раз.

| | Регистрация (первый раз) | Вход (дальше) |
|---|---|---|
| **Номер** | номер → SMS-код → анкета + **PIN** | номер → **PIN** (без SMS) |
| **Google** | Google → номер → SMS-код → анкета (имя/email подставлены) + PIN | кнопка Google — в одно нажатие |
| **Apple ID** (только iOS) | Apple → номер → SMS-код → анкета (имя/email подставлены) + PIN | кнопка Apple — в одно нажатие |

Запасные пути:
- **«Войти по SMS»** — номер → SMS-код → вход. Нужен, если PIN ещё не задан (старые аккаунты).
- **«Забыли PIN?»** — номер → SMS-код → новый PIN → вход. Остальные устройства выходят из аккаунта.

PIN — **6 цифр**. Простые (`000000`, `111111`, `123456`, `654321` и т. п.) сервер не принимает.
Число попыток ввода PIN сервер не ограничивает (только общий лимит 30 запросов в минуту с одного IP).

---

## 2. Настройка проекта

### 2.1. Идентификаторы

| Что | Значение |
|---|---|
| iOS Bundle ID | **`kg.baytur.resort`** |
| Android package name (`applicationId`) | **`kg.baytur.resort`** |
| Apple Team ID | `UDAX38HB36` |
| Google **Web** client ID (`serverClientId`, обе платформы) | `37115875856-uons424a6fd6t8fo9b32vldulss4kpes.apps.googleusercontent.com` |
| Google **iOS** client ID (`clientId` на iOS) | `37115875856-u0pofb98mun98b56j3slk5au55h40phi.apps.googleusercontent.com` |
| iOS URL scheme для Google (reversed iOS client ID) | `com.googleusercontent.apps.37115875856-u0pofb98mun98b56j3slk5au55h40phi` |
| Google **Android** client | в коде не используется — должен существовать в Google Cloud; создаётся по вашим SHA-1 (§2.3, §11) |

⚠️ Если сейчас в проекте другой bundle ID / package name (например `kg.baytur.app`) — поменяйте на `kg.baytur.resort`.
Google и Apple выпускают токены только для этого ID; с другим вход не заработает. После смены проверьте, что
`GoogleService-Info.plist` / `google-services.json` (Firebase-проект `baytur-2add6`, push) выпущены для
`kg.baytur.resort`; если нет — добавьте приложение с этим ID в Firebase и скачайте конфиги заново.

### 2.2. Пакеты

```yaml
dependencies:
  google_sign_in: ^7.1.0        # API 7.x — код в §6.2 написан под него
  sign_in_with_apple: ^7.0.1
  crypto: ^3.0.6                # SHA-256 для nonce Apple
  flutter_secure_storage: ^9.2.4
```

### 2.3. Google

**iOS** — `ios/Runner/Info.plist`:

```xml
<key>GIDClientID</key>
<string>37115875856-u0pofb98mun98b56j3slk5au55h40phi.apps.googleusercontent.com</string>
<key>GIDServerClientID</key>
<string>37115875856-uons424a6fd6t8fo9b32vldulss4kpes.apps.googleusercontent.com</string>
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLSchemes</key>
    <array>
      <string>com.googleusercontent.apps.37115875856-u0pofb98mun98b56j3slk5au55h40phi</string>
    </array>
  </dict>
</array>
```

(если `CFBundleURLTypes` уже есть — добавьте схему в существующий массив).

**Android** — ничего прописывать в коде не нужно, но **в Google Cloud должен быть Android-клиент** с package name
`kg.baytur.resort` и SHA-1 каждого ключа подписи. Его создаёт владелец аккаунта — пришлите ему SHA-1:

| Ключ | Как получить SHA-1 |
|---|---|
| debug | `cd android && ./gradlew signingReport` → вариант `debug` |
| upload (которым подписываете сборку для Play) | там же, вариант `release`, или `keytool -list -v -keystore <upload.jks>` |
| Google Play App Signing | Play Console → приложение → Test and release → **App integrity** → App signing key certificate |

Без SHA-1 ключа Play App Signing вход в отладке будет работать, а в сборке из Google Play — нет (`DEVELOPER_ERROR`).

На Android `idToken` выдаётся только если передан `serverClientId` = **Web** client ID (§6.2).

### 2.4. Apple (только iOS)

1. Xcode → Runner → Signing & Capabilities → **+ Capability → Sign in with Apple**. Team — `UDAX38HB36`.
   В App ID `kg.baytur.resort` возможность уже включена на стороне Apple Developer.
2. Ключ `.p8` приложению **не нужен** — он лежит только на сервере.
3. Правило App Store 4.8: раз есть вход через Google, на iOS **обязан** быть вход через Apple. Кнопки — по
   [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/sign-in-with-apple) (компонент
   `SignInWithAppleButton` из пакета подходит).

---

## 3. Общие правила API для входа

**Заголовки каждого запроса** (подробно — `MOBILE_API.md` §2.1):

| Заголовок | Значение |
|---|---|
| `Accept-Language` | `ru` \| `ky` \| `en` — язык текстов ошибок |
| `X-Device-Id` | UUID установки — сгенерировать один раз, хранить. Шлите всегда, в том числе на запросах входа: к нему привязывается сессия |
| `X-Platform` | `ios` \| `android` |
| `X-App-Version` | версия приложения, например `1.3.0` |
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <accessToken>` — для `/me/...` |

**Формат ошибки** — всегда:
```json
{"error": {"code": "pin_invalid", "message": "Неверный номер или PIN-код"}}
```

**Токены:**
- `accessToken` — JWT на 15 минут (`expiresIn` в секундах).
- `refreshToken` — на 30 дней, **одноразовый**: `POST /auth/refresh {refreshToken}` → новая пара, старый сразу
  недействителен. Повторное использование старого отзывает **все** сессии этой цепочки.
- При нескольких параллельных `401 token_invalid` делайте **один** refresh (mutex), остальные запросы ждут.
- `401 token_invalid` на `/auth/refresh` → разлогин → экран входа.

**Ответ входа** — один формат у **всех** способов (`/auth/otp/verify`, `/auth/pin`, `/auth/pin/reset`,
`/auth/google`, `/auth/apple`). Разбирайте его одной функцией:

| Ответ | Что делать |
|---|---|
| `{accessToken, refreshToken, expiresIn}` | вход выполнен → §4.8 |
| `{isNew: true, registrationToken}` | номер не зарегистрирован → анкета (§4.2) |
| `{needPhone: true, socialToken, prefill}` | Google/Apple ещё не привязан → ввод номера (§4.6) |
| `{deactivated: true, restoreToken, purgeAt, balance}` | аккаунт удалён < 30 дней назад → восстановление (§4.7) |
| `403 account_blocked` | экран «Аккаунт заблокирован» + контакты из `GET /resort/contacts` |

`registrationToken`, `socialToken`, `restoreToken` живут **15 минут**. Истёк → `400 registration_expired` /
`restore_expired` → вернуть пользователя на первый экран входа.

---

## 4. Экраны и сценарии

### 4.1. Экран входа

```
┌──────────────────────────────┐
│  Номер телефона  [+996 ...]  │
│  [ Продолжить ]              │  → экран PIN (§4.3)
│                              │
│  ──────── или ────────       │
│  [ G  Войти через Google ]   │  → §4.6
│  [   Войти через Apple ]    │  → §4.6 (только iOS)
└──────────────────────────────┘
```

Экран PIN: 6 ячеек, автоотправка после 6-й цифры, под ними ссылки **«Забыли PIN?»** (§4.5) и
**«Войти по SMS»** (§4.4).

Номер последнего входа можно подставлять в поле при следующем открытии (хранить локально можно, PIN — нельзя).

### 4.2. Регистрация по номеру

```
1. POST /auth/otp/request {phone}                  → {expiresIn: 120, retryIn: 60}  — таймер «Отправить ещё раз»
2. POST /auth/otp/verify  {phone, code}            → {isNew: true, registrationToken}
3. Анкета: имя, фамилия, дата рождения, email (необяз.), галочка условий, «хочу получать акции»
4. Экран «Придумайте PIN-код» → «Повторите PIN-код» (сверка — на клиенте)
5. POST /auth/register {registrationToken, ..., pin} → 201 {accessToken, refreshToken, expiresIn, profile}
6. → §4.8
```

Если на шаге 2 пришли токены — номер уже зарегистрирован, это вход (→ §4.8).
`pin` в `/auth/register` необязателен, но **в приложении шаг с PIN делайте обязательным** — без PIN клиент
будет каждый раз входить по SMS. Слабый PIN → `422 pin_weak` на шаге 5: вернуть на шаг 4, данные анкеты не терять.

### 4.3. Вход по номеру и PIN

```
POST /auth/pin {phone, pin}
  → токены                          → §4.8
  → 400 pin_invalid                 → «Неверный номер или PIN-код», очистить ячейки, дать ввести снова
  → 400 pin_not_set                 → PIN не задан у этого аккаунта → вход по SMS (§4.4), после входа — задать PIN
  → {deactivated: true, ...}        → §4.7
  → 403 account_blocked
  → 429 rate_limited                → «Слишком много попыток, попробуйте через {retryIn} с»
```

`pin_invalid` приходит и когда номер не зарегистрирован — сервер специально не говорит, есть ли такой номер.
Поэтому под ошибкой полезно показать: «Нет аккаунта? Зарегистрируйтесь по SMS» → §4.2.

### 4.4. Вход по SMS (запасной)

```
POST /auth/otp/request {phone} → POST /auth/otp/verify {phone, code} → ответ входа (§3)
```

После входа: если `GET /me` → `hasPin: false` — сразу экран «Придумайте PIN-код» (§4.9).

### 4.5. «Забыли PIN?»

```
1. POST /auth/otp/request {phone}
2. Экран: SMS-код + новый PIN + повтор
3. POST /auth/pin/reset {phone, code, pin}
     → токены                                   → §4.8 (все другие устройства клиента разлогинены)
     → {isNew: true, registrationToken}         → номер не зарегистрирован → анкета (§4.2), PIN передать в register
     → 422 pin_weak / 400 pin_format            → код НЕ сгорает, можно исправить PIN и отправить снова
     → 400 otp_invalid {attemptsLeft} / otp_expired
```

### 4.6. Google и Apple ID

```
1. Нативный вход (§6.2 / §6.3) → idToken (Google) или identityToken + authorizationCode (Apple)
2. POST /auth/google {idToken}
   POST /auth/apple  {identityToken, authorizationCode, nonce, firstName, lastName}
     → токены                    → аккаунт уже привязан → §4.8
     → {deactivated: true, ...}  → §4.7
     → {needPhone: true, socialToken, prefill: {firstName, lastName, email}} → шаг 3
3. Экран «Подтвердите номер телефона» (одна строка пояснения: «Номер нужен, чтобы вас узнавали на точках курорта»)
   POST /auth/otp/request {phone}
4. POST /auth/otp/verify {phone, code, socialToken}
     → токены                    → номер уже был зарегистрирован, Google/Apple привязан к нему → §4.8
     → {isNew: true, registrationToken} → анкета (§4.2, шаги 3–6) с подставленными prefill.firstName/lastName/email
```

Привязка к аккаунту происходит автоматически на шаге 4 или при `/auth/register`. В следующий раз шаг 2
сразу вернёт токены.

**Apple — важно:**
- Имя Apple отдаёт **только при первой** авторизации приложения — передавайте `firstName`/`lastName` в
  `/auth/apple` всегда, когда они есть, иначе они потеряются.
- `authorizationCode` передавайте **всегда**: сервер обменивает его на токен Apple, чтобы при удалении аккаунта
  отозвать доступ (требование App Store 5.1.1(v)). Код одноразовый и живёт 5 минут — отправляйте сразу.
- `nonce`: в запрос к Apple передаётся SHA-256 (hex) случайной строки, а на сервер — **исходная** строка (§6.3).
- Email может быть скрытым (`...@privaterelay.appleid.com`) — это нормально.

**Отмена** пользователем (закрыл окно Google/Apple) — не ошибка: молча вернуться на экран входа.

### 4.7. Восстановление удалённого аккаунта

Любой способ входа может вернуть `{deactivated: true, restoreToken, purgeAt, balance}`:
«Аккаунт удалён. Восстановить? Баллы сохранены: {balance}. Удалится навсегда {purgeAt}».

- **Восстановить:** `POST /auth/restore {restoreToken}` → `{accessToken, refreshToken, expiresIn, profile}` → §4.8.
- **Начать заново:** `POST /auth/restart {restoreToken}` → `{isNew: true, registrationToken}` → анкета (§4.2).
  Старый аккаунт стирается сразу.

### 4.8. После любого входа

```
1. Сохранить accessToken, refreshToken в secure storage
2. GET /me                                → профиль (если пришёл в ответе входа — можно взять оттуда)
3. POST /me/devices {token, platform, appVersion} — FCM-токен (push)
4. Если profile.hasPin == false           → экран «Придумайте PIN-код» (§4.9), можно с кнопкой «Позже»
5. Если profile.pendingConsents не пуст   → экран принятия документов (MOBILE_API.md §5.4)
6. → главная
```

### 4.9. Профиль → «PIN-код»

- `hasPin: false` → «Задать PIN-код»: новый + повтор → `POST /me/pin {pin}`.
- `hasPin: true` → «Изменить PIN-код»: текущий → новый → повтор → `POST /me/pin {pin, currentPin}`.
  Неверный текущий → `400 pin_invalid`. Забыл текущий → выйти и «Забыли PIN?» (§4.5).
- Ответ — профиль целиком (обновите локальный).

### 4.10. Профиль → «Способы входа»

`GET /me` → `socialAccounts: ["google", "apple"]` — что привязано.

| Строка | Не привязан | Привязан |
|---|---|---|
| Google | «Привязать» → нативный вход → `POST /me/social/google {idToken}` | «Отвязать» → `DELETE /me/social/google` |
| Apple (только iOS) | «Привязать» → `POST /me/social/apple {identityToken, authorizationCode, nonce}` | «Отвязать» → `DELETE /me/social/apple` |

`409 social_taken` — этот Google/Apple уже привязан к другому клиенту BAYTUR. Привязка другого Google-аккаунта
заменяет прежний. Ответ — профиль.

### 4.11. Выход и удаление

- **Выход:** `POST /auth/logout {refreshToken, pushToken}` → `204`; удалить токены локально; для Google — ещё
  `GoogleSignIn.instance.signOut()`, чтобы в следующий раз снова был выбор аккаунта.
- **Удаление аккаунта** — без изменений, по SMS-коду (`MOBILE_API.md` §12). Отзыв доступа у Apple сервер делает
  сам; приложению достаточно, чтобы при входе через Apple передавался `authorizationCode`.

---

## 5. Справочник эндпоинтов

Все пути — относительно `https://app.baytur.kg/api/v1`. «🔓» — без токена, «🔒» — нужен `Authorization`.

### 5.1. `POST /auth/otp/request` 🔓 — отправить SMS-код
```json
→ {"phone": "+996555123456"}
← 200 {"expiresIn": 120, "retryIn": 60}
← 400 phone_invalid;  429 otp_too_often {retryIn} | otp_limit {retryIn}
```

### 5.2. `POST /auth/otp/verify` 🔓 — проверить SMS-код
```json
→ {"phone": "+996555123456", "code": "1234", "socialToken": "..."}   // socialToken — только в сценарии §4.6
← 200 ответ входа (§3): токены | {isNew, registrationToken} | {deactivated, ...}
← 400 otp_invalid {attemptsLeft} | otp_expired | registration_expired (socialToken истёк);  403 account_blocked
```

### 5.3. `POST /auth/register` 🔓 → `201`
```json
→ {
  "registrationToken": "eyJwaG9uZ...",
  "firstName": "Урмат",            // 1–50
  "lastName": "Асанов",            // 1–50
  "birthday": "1994-05-14",        // возраст ≥ 16
  "email": "urmat@example.com",    // необязательно
  "acceptTerms": true,             // обязательно true
  "marketingConsent": false,
  "language": "ru",
  "pin": "482915"                  // 6 цифр
}
← 201 {"accessToken": "...", "refreshToken": "...", "expiresIn": 900, "profile": {...как GET /me}}
← 400 validation_error {fields} | registration_expired | pin_format;  422 terms_required | age_restricted | pin_weak
```
С фото аватара — тот же запрос как `multipart/form-data`, файл в поле `avatar` (`MOBILE_API.md` §4.4).

### 5.4. `POST /auth/pin` 🔓 — вход по номеру и PIN
```json
→ {"phone": "+996555123456", "pin": "482915"}
← 200 ответ входа (§3)
← 400 pin_invalid | pin_not_set | phone_invalid;  403 account_blocked;  429 rate_limited {retryIn}
```

### 5.5. `POST /auth/pin/reset` 🔓 — «Забыли PIN?»
```json
→ {"phone": "+996555123456", "code": "1234", "pin": "730264"}      // code — из /auth/otp/request
← 200 ответ входа (§3) — все прочие сессии клиента завершены
← 400 pin_format | otp_invalid {attemptsLeft} | otp_expired;  422 pin_weak;  403 account_blocked;  429 rate_limited
```

### 5.6. `POST /auth/google` 🔓
```json
→ {"idToken": "eyJhbGciOiJSUzI1NiIs..."}
← 200 ответ входа (§3) или {"needPhone": true, "socialToken": "eyJwcm92...",
                            "prefill": {"firstName": "Урмат", "lastName": "Асанов", "email": "urmat@gmail.com"}}
← 401 social_invalid — токен не прошёл проверку (не тот client ID, истёк, подделан)
← 503 social_unavailable — вход через этого провайдера выключен на сервере;  403 account_blocked
```

### 5.7. `POST /auth/apple` 🔓
```json
→ {"identityToken": "eyJraWQiOi...", "authorizationCode": "c1a2b3...", "nonce": "<исходная строка>",
   "firstName": "Урмат", "lastName": "Асанов"}        // имя — только если Apple его отдал
← как /auth/google
```

### 5.8. `POST /auth/restore` 🔓 и `POST /auth/restart` 🔓
```json
POST /auth/restore {"restoreToken": "..."} → 200 {accessToken, refreshToken, expiresIn, profile}
POST /auth/restart {"restoreToken": "..."} → 200 {"isNew": true, "registrationToken": "..."}
← 400 restore_expired
```

### 5.9. `POST /auth/refresh` 🔓 и `POST /auth/logout` 🔒
```json
POST /auth/refresh {"refreshToken": "Zk9..."} → 200 {accessToken, refreshToken (новый), expiresIn}
                                              ← 401 token_invalid → разлогин;  403 account_blocked | account_deactivated
POST /auth/logout  {"refreshToken": "...", "pushToken": "..."} → 204
```

### 5.10. `GET /me` 🔒 — профиль (поля входа)
```json
{
  "firstName": "Урмат", "lastName": "Асанов", "phone": "+996555123456", "email": "urmat@example.com",
  "birthday": "1994-05-14", "avatar": null, "memberId": "BT-048219", "memberSince": "2023-06-01",
  "settings": {"language": "ru", "notifyCashback": true, "notifyPromos": true},
  "marketingConsent": true, "pendingConsents": [],
  "socialAccounts": ["google"],     // привязанные способы входа: "google", "apple"
  "hasPin": true                    // false → предложить задать PIN
}
```

### 5.11. `POST /me/pin` 🔒 — задать или сменить PIN
```json
→ {"pin": "730264"}                              // PIN ещё не задан
→ {"pin": "730264", "currentPin": "482915"}      // смена
← 200 профиль
← 400 pin_format | pin_invalid (неверный currentPin);  422 pin_weak
```

### 5.12. `POST /me/social/{google|apple}` 🔒 и `DELETE /me/social/{google|apple}` 🔒
```json
POST /me/social/google {"idToken": "..."}                                          → 200 профиль
POST /me/social/apple  {"identityToken": "...", "authorizationCode": "...", "nonce": "..."} → 200 профиль
DELETE /me/social/google                                                           → 200 профиль
← 401 social_invalid;  409 social_taken;  503 social_unavailable
```

### 5.13. `POST /me/devices` 🔒 — push-токен
```json
→ {"token": "<FCM token>", "platform": "ios", "appVersion": "1.3.0"} ← 204
```

---

## 6. Код Flutter

Примеры — ориентир; встраивайте в существующие репозитории и DI приложения.

### 6.1. Один обработчик ответа входа

```dart
sealed class AuthResult {}
class SignedIn extends AuthResult { SignedIn(this.tokens, this.profile); final Tokens tokens; final Profile? profile; }
class NeedsRegistration extends AuthResult { NeedsRegistration(this.registrationToken); final String registrationToken; }
class NeedsPhone extends AuthResult { NeedsPhone(this.socialToken, this.prefill); final String socialToken; final Prefill prefill; }
class Deactivated extends AuthResult {
  Deactivated(this.restoreToken, this.purgeAt, this.balance);
  final String restoreToken; final DateTime? purgeAt; final int balance;
}

AuthResult parseAuthResult(Map<String, dynamic> j) {
  if (j['accessToken'] != null) {
    return SignedIn(Tokens.fromJson(j), j['profile'] == null ? null : Profile.fromJson(j['profile']));
  }
  if (j['needPhone'] == true) return NeedsPhone(j['socialToken'], Prefill.fromJson(j['prefill'] ?? {}));
  if (j['isNew'] == true) return NeedsRegistration(j['registrationToken']);
  if (j['deactivated'] == true) {
    return Deactivated(j['restoreToken'], DateTime.tryParse(j['purgeAt'] ?? ''), j['balance'] ?? 0);
  }
  throw StateError('Unknown auth response');
}
```

### 6.2. Google (`google_sign_in` 7.x)

```dart
const webClientId = '37115875856-uons424a6fd6t8fo9b32vldulss4kpes.apps.googleusercontent.com';
const iosClientId = '37115875856-u0pofb98mun98b56j3slk5au55h40phi.apps.googleusercontent.com';

Future<void> initGoogle() => GoogleSignIn.instance.initialize(
      clientId: Platform.isIOS ? iosClientId : null,
      serverClientId: webClientId, // без него на Android не будет idToken
    );

/// null — пользователь отменил.
Future<String?> googleIdToken() async {
  try {
    final account = await GoogleSignIn.instance.authenticate();
    return account.authentication.idToken;
  } on GoogleSignInException catch (e) {
    if (e.code == GoogleSignInExceptionCode.canceled) return null;
    rethrow;
  }
}

// вход: final r = await api.post('/auth/google', {'idToken': idToken}); parseAuthResult(r);
```

`initGoogle()` вызывать один раз при старте приложения.

### 6.3. Apple (`sign_in_with_apple`, только iOS)

```dart
String _randomNonce([int length = 32]) {
  const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._';
  final r = Random.secure();
  return List.generate(length, (_) => chars[r.nextInt(chars.length)]).join();
}

/// null — пользователь отменил.
Future<Map<String, dynamic>?> appleSignInBody() async {
  final rawNonce = _randomNonce();
  try {
    final c = await SignInWithApple.getAppleIDCredential(
      scopes: [AppleIDAuthorizationScopes.email, AppleIDAuthorizationScopes.fullName],
      nonce: sha256.convert(utf8.encode(rawNonce)).toString(), // в Apple — хеш
    );
    return {
      'identityToken': c.identityToken,
      'authorizationCode': c.authorizationCode,
      'nonce': rawNonce,                                      // на сервер — исходная строка
      if (c.givenName != null) 'firstName': c.givenName,
      if (c.familyName != null) 'lastName': c.familyName,
    };
  } on SignInWithAppleAuthorizationException catch (e) {
    if (e.code == AuthorizationErrorCode.canceled) return null;
    rethrow;
  }
}

// вход: api.post('/auth/apple', body); привязка из профиля: api.post('/me/social/apple', body)
```

### 6.4. Поле PIN

- 6 ячеек, только цифры (`keyboardType: TextInputType.number`, `inputFormatters: [FilteringTextInputFormatter.digitsOnly]`),
  автоотправка после 6-й цифры.
- При создании PIN — два шага (ввод и повтор), сравнение на клиенте; простые PIN сервер отклонит `pin_weak`,
  но можно отсечь заранее: все цифры одинаковые или подряд по возрастанию/убыванию.
- PIN не логировать, не отправлять в аналитику, не хранить.

---

## 7. Ошибки

| HTTP | `code` | Где | Что делать |
|---|---|---|---|
| 400 | `phone_invalid` | любой ввод номера | подсветить поле номера |
| 400 | `otp_invalid` | verify, pin/reset | «Неверный код», показать `attemptsLeft` |
| 400 | `otp_expired` | verify, pin/reset | код сгорел/истёк → «Отправить код ещё раз» |
| 429 | `otp_too_often` / `otp_limit` | otp/request | таймер на `retryIn` секунд |
| 400 | `pin_invalid` | `/auth/pin`, `/me/pin` | очистить ячейки, «Неверный номер или PIN-код» |
| 400 | `pin_not_set` | `/auth/pin` | перейти ко входу по SMS (§4.4) |
| 400 | `pin_format` | везде, где PIN | PIN — 6 цифр |
| 422 | `pin_weak` | register, pin/reset, `/me/pin` | вернуть на «Придумайте PIN-код» |
| 401 | `social_invalid` | google, apple, `/me/social` | «Не удалось войти, попробуйте ещё раз» (обычно — не тот bundle ID / client ID) |
| 503 | `social_unavailable` | google, apple | показать `message`, предложить вход по номеру |
| 409 | `social_taken` | `/me/social` | «Этот аккаунт уже привязан к другому клиенту» |
| 400 | `registration_expired` | register, verify с socialToken | вернуться на экран входа |
| 400 | `restore_expired` | restore, restart | вернуться на экран входа |
| 422 | `terms_required` / `age_restricted` | register | показать `message` |
| 403 | `account_blocked` | любой вход | экран блокировки + `GET /resort/contacts` |
| 429 | `rate_limited` | любой | «Слишком много попыток», ждать `retryIn` |

Тексты ошибок брать из `error.message` — в .arb их дублировать не нужно.

---

## 8. Тексты (.arb)

Только тексты интерфейса (ошибки приходят с сервера). Киргизский перевод — черновой, проверьте у носителя языка.

| Ключ | ru | ky | en |
|---|---|---|---|
| `authContinue` | Продолжить | Улантуу | Continue |
| `authOr` | или | же | or |
| `authWithGoogle` | Войти через Google | Google аркылуу кирүү | Sign in with Google |
| `authWithApple` | Войти через Apple | Apple аркылуу кирүү | Sign in with Apple |
| `authWithSms` | Войти по SMS | SMS аркылуу кирүү | Sign in with SMS |
| `authEnterPin` | Введите PIN-код | PIN-кодду киргизиңиз | Enter your PIN |
| `authForgotPin` | Забыли PIN? | PIN-кодду унуттуңузбу? | Forgot PIN? |
| `authNoAccount` | Нет аккаунта? Зарегистрируйтесь по SMS | Аккаунтуңуз жокпу? SMS аркылуу катталыңыз | No account? Sign up with SMS |
| `pinCreateTitle` | Придумайте PIN-код | PIN-код ойлоп табыңыз | Create a PIN |
| `pinCreateHint` | 6 цифр — для быстрого входа без SMS | SMSсиз тез кирүү үчүн 6 сан | 6 digits for quick sign-in without SMS |
| `pinRepeatTitle` | Повторите PIN-код | PIN-кодду кайталаңыз | Repeat your PIN |
| `pinMismatch` | PIN-коды не совпадают | PIN-коддор дал келбейт | PINs do not match |
| `pinCurrent` | Текущий PIN-код | Учурдагы PIN-код | Current PIN |
| `pinNew` | Новый PIN-код | Жаңы PIN-код | New PIN |
| `pinChanged` | PIN-код изменён | PIN-код өзгөртүлдү | PIN changed |
| `pinSetLater` | Позже | Кийинчерээк | Later |
| `pinResetTitle` | Новый PIN-код | Жаңы PIN-код | New PIN |
| `pinResetHint` | Введите код из SMS и придумайте новый PIN | SMSтеги кодду киргизип, жаңы PIN ойлоп табыңыз | Enter the SMS code and create a new PIN |
| `phoneConfirmTitle` | Подтвердите номер телефона | Телефон номериңизди ырастаңыз | Confirm your phone number |
| `phoneConfirmHint` | Номер нужен, чтобы вас узнавали на точках курорта | Курорттун түйүндөрүндө сизди таануу үчүн номер керек | We need your number so resort staff can find you |
| `profilePinSet` | Задать PIN-код | PIN-код коюу | Set PIN |
| `profilePinChange` | Изменить PIN-код | PIN-кодду өзгөртүү | Change PIN |
| `profileSignInMethods` | Способы входа | Кирүү ыкмалары | Sign-in methods |
| `profileLink` | Привязать | Байлоо | Link |
| `profileUnlink` | Отвязать | Ажыратуу | Unlink |
| `restoreTitle` | Восстановить аккаунт? | Аккаунтту калыбына келтиресизби? | Restore your account? |
| `restoreBody` | Баллы сохранены: {balance}. Аккаунт удалится навсегда {date} | Упайлар сакталган: {balance}. Аккаунт {date} биротоло өчөт | Your points are saved: {balance}. The account will be deleted for good on {date} |
| `restoreYes` | Восстановить | Калыбына келтирүү | Restore |
| `restoreStartOver` | Начать заново | Кайрадан баштоо | Start over |

---

## 9. Тестирование на сервере

| Что | Значение |
|---|---|
| Сервер | `https://app.baytur.kg/api/v1` — всё из документа уже работает |
| SMS | **пока не отправляются** — для любого номера подходит код **`1234`** (до подключения SMS-провайдера) |
| Тестовый аккаунт сторов | `+996700000000`, код `1234`; PIN не задан — задайте через `POST /me/pin` после входа по SMS |
| Демо-профиль | `+996555123456`, код `1234` |
| Новый клиент | любой свой номер + код `1234` → регистрация |
| Google | iOS — работает сразу; Android — после создания Android-клиента в Google Cloud (§2.3, §11) |
| Apple | на реальном iPhone с Apple ID (в симуляторе тоже, если вошли в Apple ID в настройках) |
| Swagger | https://app.baytur.kg/api/v1/docs |

Проверить, что Google-токен подходит серверу, можно без приложения: получить `idToken` и отправить в Swagger
`POST /auth/google` — ответ `needPhone` или токены значит, что настройка верная; `401 social_invalid` — не тот
bundle ID / client ID.

Чтобы проверить сценарий «первый вход через Apple» повторно: на iPhone → Настройки → [имя] → «Вход и
безопасность» → «Вход с Apple» → BAYTUR → «Прекратить использование» — после этого Apple снова отдаст имя.

---

## 10. Приёмка

**Регистрация и вход по номеру**
- [ ] Новый номер: SMS → анкета → PIN (два шага) → главная; в `GET /me` `hasPin: true`.
- [ ] Повторный вход: номер → PIN → главная, SMS не запрашивается.
- [ ] Неверный PIN: ошибка, ячейки очищены, можно ввести снова сколько угодно раз.
- [ ] Незарегистрированный номер + PIN → `pin_invalid` и подсказка «Зарегистрируйтесь по SMS».
- [ ] Аккаунт без PIN → `pin_not_set` → вход по SMS → предложение задать PIN.
- [ ] «Забыли PIN?»: SMS → новый PIN → вход; на втором устройстве сессия завершилась (следующий refresh → экран входа).
- [ ] Простой PIN (`123456`) отклоняется понятной ошибкой на всех экранах, где задаётся PIN.

**Google / Apple**
- [ ] Google, первый раз: номер → SMS → анкета с подставленными именем и email → PIN → главная.
- [ ] Google, второй раз: одно нажатие → главная.
- [ ] Google, номер уже зарегистрирован по SMS: после SMS-кода сразу вход, Google привязан (`socialAccounts`).
- [ ] Apple (iOS): то же самое; имя из Apple подставлено в анкету; `authorizationCode` и `nonce` уходят на сервер.
- [ ] На Android кнопки Apple нет.
- [ ] Отмена окна Google/Apple — без ошибки, остаёмся на экране входа.
- [ ] Профиль → «Способы входа»: привязать и отвязать Google и Apple; привязка чужого → понятная ошибка.

**Общее**
- [ ] Удалённый аккаунт при любом способе входа → экран «Восстановить?»; оба варианта работают.
- [ ] Заблокированный → экран блокировки.
- [ ] Профиль → смена PIN с текущим PIN; неверный текущий → ошибка.
- [ ] Выход → `POST /auth/logout`; повторный вход Google показывает выбор аккаунта.
- [ ] Токены только в secure storage; PIN нигде не сохраняется и не логируется.
- [ ] Тексты на трёх языках; ошибки — из `error.message`.

---

## 11. Что ещё не готово

| Что | Кто | Что нужно |
|---|---|---|
| Вход через Google на **Android** | мобильный разработчик → владелец аккаунта Google Cloud | прислать 3 SHA-1 (§2.3); владелец создаёт Android-клиент. До этого окно Google на Android завершается ошибкой (`DEVELOPER_ERROR` / «нет учётных данных») и до сервера не доходит. Сервер уже готов: токен выпускается для Web client ID, который он принимает |
| SMS на реальные номера | бэкенд | подключение SMS-провайдера; до этого код `1234` для всех номеров |

*Вопросы по API — бэкенду. Если формат ответа отличается от документа — прав сервер:
`https://app.baytur.kg/api/v1/schema`.*
