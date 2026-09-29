import secrets

_ALPHABET = '0123456789abcdefghjkmnpqrstvwxyz'  # base32 без похожих символов


def new_id(prefix, length=14):
    return f'{prefix}_' + ''.join(secrets.choice(_ALPHABET) for _ in range(length))


# Отдельные функции на уровне модуля — миграции ссылаются на них по имени
def new_request_id():
    return new_id('req')


def new_operation_id():
    return new_id('op')


def new_payment_id():
    return new_id('pay')


def new_notification_id():
    return new_id('ntf')


def new_upload_id():
    return new_id('upl')


def new_complaint_id():
    return new_id('cmp')
