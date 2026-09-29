"""
Единый формат ошибок API: {"error": {"code": "...", "message": "..."}}.

message — на языке из Accept-Language. Коды совпадают с FakeLoyaltyServer мобилки.
"""
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .i18n import current_language

MESSAGES = {
    # общие
    'validation_error': {'ru': 'Проверьте введённые данные', 'ky': 'Киргизилген маалыматтарды текшериңиз', 'en': 'Please check the entered data'},
    'not_found': {'ru': 'Не найдено', 'ky': 'Табылган жок', 'en': 'Not found'},
    'auth_required': {'ru': 'Войдите, чтобы продолжить', 'ky': 'Улантуу үчүн кириңиз', 'en': 'Please sign in to continue'},
    'token_invalid': {'ru': 'Сессия истекла, войдите заново', 'ky': 'Сессия бүттү, кайра кириңиз', 'en': 'Session expired, please sign in again'},
    'permission_denied': {'ru': 'Недостаточно прав', 'ky': 'Укук жетишсиз', 'en': 'Permission denied'},
    'rate_limited': {'ru': 'Слишком много запросов, попробуйте позже', 'ky': 'Сурамдар өтө көп, кийинчерээк аракет кылыңыз', 'en': 'Too many requests, try again later'},
    'method_not_supported': {'ru': 'Метод не поддерживается', 'ky': 'Ыкма колдоого алынбайт', 'en': 'Method not allowed'},
    'server_error': {'ru': 'Ошибка сервера, попробуйте позже', 'ky': 'Сервер катасы, кийинчерээк аракет кылыңыз', 'en': 'Server error, try again later'},
    'idempotency_conflict': {'ru': 'Запрос с этим ключом уже обрабатывается', 'ky': 'Бул ачкыч менен сурам иштетилүүдө', 'en': 'A request with this key is already being processed'},
    # вход
    'otp_too_often': {'ru': 'Код можно запросить повторно чуть позже', 'ky': 'Кодду бир аздан кийин кайра сураса болот', 'en': 'You can request a new code a bit later'},
    'otp_invalid': {'ru': 'Неверный код', 'ky': 'Код туура эмес', 'en': 'Invalid code'},
    'otp_expired': {'ru': 'Код устарел, запросите новый', 'ky': 'Коддун мөөнөтү бүттү, жаңысын сураңыз', 'en': 'The code has expired, request a new one'},
    'otp_limit': {'ru': 'Превышен лимит SMS, попробуйте позже', 'ky': 'SMS лимити ашып кетти, кийинчерээк аракет кылыңыз', 'en': 'SMS limit exceeded, try again later'},
    'phone_invalid': {'ru': 'Неверный номер телефона', 'ky': 'Телефон номери туура эмес', 'en': 'Invalid phone number'},
    'registration_expired': {'ru': 'Время регистрации истекло, войдите заново', 'ky': 'Каттоо убактысы бүттү, кайра кириңиз', 'en': 'Registration time expired, sign in again'},
    'terms_required': {'ru': 'Нужно принять условия программы', 'ky': 'Программанын шарттарын кабыл алуу керек', 'en': 'You must accept the program terms'},
    'age_restricted': {'ru': 'Программа доступна с 16 лет', 'ky': 'Программа 16 жаштан баштап жеткиликтүү', 'en': 'The program is available from age 16'},
    'account_blocked': {'ru': 'Аккаунт заблокирован. Свяжитесь с курортом', 'ky': 'Аккаунт бөгөттөлгөн. Курорт менен байланышыңыз', 'en': 'Account is blocked. Please contact the resort'},
    'account_deactivated': {'ru': 'Аккаунт удалён', 'ky': 'Аккаунт өчүрүлгөн', 'en': 'Account has been deleted'},
    'restore_expired': {'ru': 'Восстановление больше недоступно', 'ky': 'Калыбына келтирүү мындан ары жеткиликсиз', 'en': 'Restore is no longer available'},
    'update_required': {'ru': 'Обновите приложение', 'ky': 'Колдонмону жаңылаңыз', 'en': 'Please update the app'},
    'maintenance': {'ru': 'Идут технические работы', 'ky': 'Техникалык иштер жүрүүдө', 'en': 'Maintenance in progress'},
    'birthday_locked': {'ru': 'Дату рождения меняет только ресепшен', 'ky': 'Туулган күндү ресепшн гана өзгөртөт', 'en': 'Birthday can only be changed at the reception'},
    'consent_unknown': {'ru': 'Документ не найден', 'ky': 'Документ табылган жок', 'en': 'Document not found'},
    # кешбек
    'insufficient_points': {'ru': 'Недостаточно баллов', 'ky': 'Упай жетишсиз', 'en': 'Not enough points'},
    'points_limit_exceeded': {'ru': 'Превышен лимит оплаты баллами', 'ky': 'Упай менен төлөө лимити ашып кетти', 'en': 'Points payment limit exceeded'},
    'method_not_allowed': {'ru': 'Способ оплаты недоступен для услуги', 'ky': 'Бул кызмат үчүн төлөм ыкмасы жеткиликсиз', 'en': 'Payment method is not available for this service'},
    'amount_out_of_range': {'ru': 'Сумма / количество вне диапазона', 'ky': 'Сумма / саны чектен тышкары', 'en': 'Amount / quantity out of range'},
    'payment_invalid': {'ru': 'Оплата не найдена или сумма не совпадает', 'ky': 'Төлөм табылган жок же сумма дал келбейт', 'en': 'Payment not found or amount mismatch'},
    'payment_required': {'ru': 'Сначала оплатите денежную часть', 'ky': 'Адегенде акчалай бөлүгүн төлөңүз', 'en': 'Pay the money part first'},
    'item_not_found': {'ru': 'Услуга недоступна', 'ky': 'Кызмат жеткиликсиз', 'en': 'Service unavailable'},
    'invalid_status': {'ru': 'Действие недоступно в текущем статусе', 'ky': 'Учурдагы статуста бул аракет жеткиликсиз', 'en': 'Action is not available in the current status'},
    'account_frozen': {'ru': 'Аккаунт заморожен', 'ky': 'Аккаунт тоңдурулган', 'en': 'Account is frozen'},
    # сотрудник
    'outlet_forbidden': {'ru': 'Заявка другой точки обслуживания', 'ky': 'Башка тейлөө түйүнүнүн өтүнмөсү', 'en': 'Request belongs to another outlet'},
    'cash_not_received': {'ru': 'Отметьте, что деньги приняты', 'ky': 'Акча кабыл алынганын белгилеңиз', 'en': 'Confirm that cash was received'},
    'own_account': {'ru': 'Нельзя обработать заявку со своего аккаунта', 'ky': 'Өз аккаунтуңуздун өтүнмөсүн иштетүүгө болбойт', 'en': 'You cannot process your own request'},
    'needs_manager': {'ru': 'Требуется подтверждение менеджера', 'ky': 'Менеджердин ырастоосу керек', 'en': 'Manager approval required'},
    'qr_invalid': {'ru': 'QR-код недействителен или устарел', 'ky': 'QR-код жараксыз же эскирген', 'en': 'QR code is invalid or expired'},
    'two_factor_required': {'ru': 'Введите код из приложения-аутентификатора', 'ky': 'Аутентификатор колдонмосунан кодду киргизиңиз', 'en': 'Enter the authenticator code'},
    'invalid_credentials': {'ru': 'Неверный email или пароль', 'ky': 'Email же сырсөз туура эмес', 'en': 'Invalid email or password'},
    # админка
    'item_in_use': {'ru': 'На услугу есть заявки — её можно только скрыть', 'ky': 'Кызматка өтүнмөлөр бар — аны жашырууга гана болот', 'en': 'Service has requests — it can only be hidden'},
    'translations_missing': {'ru': 'Заполните все переводы или включите «использовать ru»', 'ky': 'Бардык котормолорду толтуруңуз', 'en': 'Fill in all translations or enable "use ru"'},
    'tiers_invalid': {'ru': 'Пороги уровней должны строго возрастать, у первого — 0', 'ky': 'Деңгээл босоголору өсүшү керек, биринчиси — 0', 'en': 'Tier thresholds must strictly increase, the first is 0'},
    'in_use': {'ru': 'Объект используется — удалить нельзя', 'ky': 'Объект колдонулууда — өчүрүүгө болбойт', 'en': 'The object is in use and cannot be deleted'},
    'phone_taken': {'ru': 'Этот номер уже занят другим участником', 'ky': 'Бул номер башка катышуучуда бар', 'en': 'This phone number is already taken'},
    'password_change_required': {'ru': 'Смените временный пароль', 'ky': 'Убактылуу сырсөздү алмаштырыңыз', 'en': 'Please change your temporary password'},
    # обращения
    'complaints_limit': {'ru': 'Слишком много обращений за сутки', 'ky': 'Бир суткада кайрылуулар өтө көп', 'en': 'Too many requests per day'},
    'complaint_closed': {'ru': 'Обращение закрыто', 'ky': 'Кайрылуу жабылган', 'en': 'The request is closed'},
    'file_invalid': {'ru': 'Файл не подходит (JPEG/PNG/HEIC до 10 МБ)', 'ky': 'Файл туура келбейт (JPEG/PNG/HEIC 10 МБ чейин)', 'en': 'Invalid file (JPEG/PNG/HEIC up to 10 MB)'},
}


def message_for(code, lang=None):
    lang = lang or current_language()
    texts = MESSAGES.get(code)
    if not texts:
        return code
    return texts.get(lang) or texts['ru']


class ApiError(exceptions.APIException):
    """Бизнес-ошибка: ApiError('insufficient_points', status=422)."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code, status=None, message=None, extra=None):
        self.code = code
        if status:
            self.status_code = status
        self.message = message
        self.extra = extra or {}
        super().__init__(detail=code, code=code)


def error_response(code, http_status, message=None, extra=None):
    body = {'code': code, 'message': message or message_for(code)}
    if extra:
        body.update(extra)
    return Response({'error': body}, status=http_status)


def exception_handler(exc, context):
    if isinstance(exc, ApiError):
        response = error_response(exc.code, exc.status_code, exc.message, exc.extra)
        if exc.status_code == 429 and 'retryIn' in exc.extra:
            response['Retry-After'] = str(exc.extra['retryIn'])
        return response

    if isinstance(exc, Http404):
        exc = exceptions.NotFound()

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        return error_response('validation_error', 400, extra={'fields': exc.detail})
    if isinstance(exc, exceptions.NotAuthenticated):
        return error_response('auth_required', 401)
    if isinstance(exc, exceptions.AuthenticationFailed):
        return error_response('token_invalid', 401)
    if isinstance(exc, exceptions.PermissionDenied):
        return error_response('permission_denied', 403)
    if isinstance(exc, exceptions.NotFound):
        return error_response('not_found', 404)
    if isinstance(exc, exceptions.MethodNotAllowed):
        return error_response('method_not_supported', 405)
    if isinstance(exc, exceptions.Throttled):
        resp = error_response('rate_limited', 429, extra={'retryIn': int(exc.wait or 60)})
        resp['Retry-After'] = str(int(exc.wait or 60))
        return resp
    return error_response('server_error' if response.status_code >= 500 else 'validation_error',
                          response.status_code)
