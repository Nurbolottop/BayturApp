"""
Документация OpenAPI для клиентского API и API сотрудника — в одном месте, чтобы
view оставались короткими. Вызывается из core/api_urls.py при импорте.
"""
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as s

from apps.common import openapi as o


def doc(view, method, tags, summary, request=None, response=None, params=(), status=200, auth=True, errors=None,
        operation_id=None):
    responses = {status: response if response is not None else OpenApiResponse(description='Без тела')}
    for code in (errors or (400, 401) if auth else errors or (400,)):
        responses[code] = o.Error
    handler = getattr(view, method)
    extend_schema(tags=tags, summary=summary, request=request, responses=responses, operation_id=operation_id,
                  parameters=[o.LANG_HEADER, o.DEVICE_HEADER, *params])(handler)


def apply():
    from apps.analytics import api as analytics
    from apps.cashback import api as cashback
    from apps.cashback import staff_api as staffdesk
    from apps.catalog import api as catalog
    from apps.complaints import api as complaints
    from apps.content import api as content
    from apps.loyalty import api as loyalty
    from apps.members import api as members
    from apps.payments import api as payments
    from apps.staff import api as staff_auth

    AUTH, ME, CAT, LOY, CB, PAY, CNT, CMP, STAFF, SYS = (
        ['Вход'], ['Профиль'], ['Каталог'], ['Лояльность'], ['Заявки'], ['Оплата'], ['Контент'], ['Обращения'],
        ['Сотрудник'], ['Служебное'])

    # вход
    doc(members.OtpRequestView, 'post', AUTH, 'Запросить SMS-код', o.OtpRequest, o.OtpRequested, auth=False,
        errors=(400, 429))
    doc(members.OtpVerifyView, 'post', AUTH, 'Проверить код: токены | регистрация | восстановление',
        o.OtpVerify, o.OtpVerified, auth=False, errors=(400, 403))
    pin_field = s.RegexField(r'^\d{6}$', help_text='6 цифр')
    doc(members.PinLoginView, 'post', AUTH, 'Вход по номеру и PIN (без SMS)',
        inline_serializer('PinLoginInput', {'phone': s.CharField(), 'pin': pin_field}),
        o.OtpVerified, auth=False, errors=(400, 403, 429))
    doc(members.PinResetView, 'post', AUTH, '«Забыл PIN»: SMS-код + новый PIN; другие сессии завершаются',
        inline_serializer('PinResetInput', {'phone': s.CharField(), 'code': s.CharField(), 'pin': pin_field}),
        o.OtpVerified, auth=False, errors=(400, 403, 422, 429))
    doc(members.GoogleLoginView, 'post', AUTH, 'Вход через Google', o.GoogleLogin, o.SocialLoginResult,
        auth=False, errors=(400, 401, 403, 503))
    doc(members.AppleLoginView, 'post', AUTH, 'Вход через Apple ID', o.AppleLogin, o.SocialLoginResult,
        auth=False, errors=(400, 401, 403, 503))
    doc(members.RegisterView, 'post', AUTH, 'Регистрация нового участника', o.Register, o.TokensWithProfile,
        status=201, auth=False, errors=(400, 422))
    doc(members.RefreshView, 'post', AUTH, 'Обновить пару токенов (ротация)',
        inline_serializer('RefreshInput', {'refreshToken': s.CharField()}), o.Tokens, auth=False, errors=(401,))
    doc(members.RestoreView, 'post', AUTH, 'Восстановить удалённый аккаунт (30 дней)',
        inline_serializer('RestoreInput', {'restoreToken': s.CharField()}), o.TokensWithProfile, auth=False)
    doc(members.StartOverView, 'post', AUTH, '«Начать заново»: стереть старый аккаунт и зарегистрироваться',
        inline_serializer('RestartInput', {'restoreToken': s.CharField()}),
        inline_serializer('RestartOutput', {'isNew': s.BooleanField(), 'registrationToken': s.CharField()}),
        auth=False)
    doc(members.LogoutView, 'post', AUTH, 'Выход: отзыв refresh и отвязка push-токена',
        inline_serializer('LogoutInput', {'refreshToken': s.CharField(required=False),
                                          'pushToken': s.CharField(required=False)}), status=204)

    # профиль
    doc(members.MeView, 'get', ME, 'Профиль', response=o.Profile)
    doc(members.MeView, 'patch', ME, 'Изменить профиль (телефон — только через ресепшен)', o.ProfilePatch, o.Profile,
        errors=(400, 401, 403))
    avatar_in = inline_serializer('AvatarUpload', {'file': s.ImageField()})
    doc(members.MeAvatarView, 'post', ME, 'Загрузить аватар (необязательно; JPEG/PNG/WebP/HEIC до 10 МБ)', avatar_in,
        o.Profile, errors=(401, 422))
    doc(members.MeAvatarView, 'delete', ME, 'Убрать аватар', response=o.Profile)
    doc(members.MePinView, 'post', ME, 'Задать или сменить PIN (currentPin — если PIN уже задан)',
        inline_serializer('PinChangeInput', {'pin': pin_field, 'currentPin': s.CharField(required=False)}),
        o.Profile, errors=(400, 401, 422))
    provider = OpenApiParameter('provider', str, OpenApiParameter.PATH, enum=['google', 'apple'])
    doc(members.MeSocialView, 'post', ME, 'Привязать Google / Apple ID',
        inline_serializer('SocialLinkInput', {'idToken': s.CharField(required=False, help_text='google'),
                                              'identityToken': s.CharField(required=False, help_text='apple'),
                                              'authorizationCode': s.CharField(required=False, help_text='apple'),
                                              'nonce': s.CharField(required=False)}),
        o.Profile, params=[provider], errors=(400, 401, 409, 503))
    doc(members.MeSocialView, 'delete', ME, 'Отвязать Google / Apple ID', response=o.Profile, params=[provider])
    doc(members.MeSettingsView, 'patch', ME, 'Настройки: язык и уведомления', o.SettingsPatch, o.Settings)
    doc(members.ConsentsView, 'post', ME, 'Принять новую версию документа',
        inline_serializer('ConsentInput', {'kind': s.ChoiceField(choices=['terms', 'privacy']),
                                           'version': s.CharField()}),
        inline_serializer('ConsentOutput', {'pendingConsents': o.PendingConsent(many=True)}))
    doc(members.DevicesView, 'post', ME, 'Зарегистрировать push-токен',
        inline_serializer('DeviceInput', {'token': s.CharField(), 'platform': s.ChoiceField(choices=['ios', 'android']),
                                          'appVersion': s.CharField(required=False)}), status=204)
    doc(members.DeviceDeleteView, 'delete', ME, 'Удалить push-токен', status=204)
    doc(members.DeletionRequestView, 'get', ME, 'Данные для экрана предупреждения об удалении',
        response=o.DeletionInfo)
    doc(members.DeletionRequestView, 'post', ME, 'Удаление аккаунта: отправить SMS-код',
        response=inline_serializer('DeletionRequested', {**{k: v for k, v in o.DeletionInfo().fields.items()},
                                                         'expiresIn': s.IntegerField(), 'retryIn': s.IntegerField()}))
    doc(members.DeletionConfirmView, 'post', ME, 'Удаление аккаунта: подтвердить кодом',
        inline_serializer('DeletionConfirmInput', {'code': s.CharField()}),
        inline_serializer('DeletionConfirmed', {'deleted': s.BooleanField()}))
    doc(members.MemberQrView, 'get', ME, 'QR участника (подписанный токен, 1–2 мин)',
        response=inline_serializer('MemberQr', {'token': s.CharField(), 'expiresAt': s.DateTimeField()}))
    doc(members.NotificationsView, 'get', ME, 'Лента уведомлений (30 дней)',
        response=inline_serializer('NotificationsPage', {'items': o.Notification(many=True),
                                                          'nextCursor': s.CharField(allow_null=True),
                                                          'unread': s.IntegerField()}),
        params=[o.CURSOR, o.LIMIT])
    doc(members.NotificationsReadView, 'post', ME, 'Отметить прочитанными (одно или все)',
        inline_serializer('ReadInput', {'id': s.CharField(required=False), 'all': s.BooleanField(required=False)}),
        inline_serializer('ReadOutput', {'unread': s.IntegerField()}))
    doc(loyalty.SummaryView, 'get', ME, 'Цифры в профиле', response=o.Summary)
    doc(loyalty.AchievementsView, 'get', ME, 'Прогресс по видимым заданиям', response=o.Achievements)
    doc(loyalty.LoyaltyHistoryView, 'get', ME, 'Баллы за всё время: итоги по годам и история уровней',
        response=o.LoyaltyHistory)

    # справочники
    doc(members.LegalView, 'get', SYS, 'Версии и URL документов', auth=False,
        response=inline_serializer('Legal', {k: inline_serializer(f'LegalDoc{k.title()}', {
            'version': s.CharField(), 'url': s.URLField()}, allow_null=True) for k in ('terms', 'privacy', 'deletion')}))
    doc(members.AppConfigView, 'get', SYS, 'Минимальная версия приложения и техработы', response=o.AppConfig,
        auth=False, params=[OpenApiParameter('X-Platform', str, OpenApiParameter.HEADER, enum=['ios', 'android']),
                            OpenApiParameter('X-App-Version', str, OpenApiParameter.HEADER)])
    doc(members.ResortContactsView, 'get', SYS, 'Контакты курорта', response=o.ResortContacts, auth=False)
    doc(catalog.CatalogView, 'get', CAT, 'Каталог курорта на Иссык-Куле (старое приложение): категории с услугами',
        response=o.ServiceCategory(many=True), auth=False)
    doc(catalog.CatalogItemView, 'get', CAT, 'Услуга (в т.ч. неактивная — для истории)', response=o.ServiceItem,
        auth=False, errors=(404,))
    doc(catalog.VenuesView, 'get', CAT, 'Объекты экосистемы BAYTUR (у каждого своё приложение)',
        response=o.Venue(many=True), auth=False)
    doc(catalog.VenueDetailView, 'get', CAT, 'Объект: контакты, адрес, инфоблоки', response=o.Venue, auth=False,
        errors=(404,))
    doc(catalog.VenueCatalogView, 'get', CAT, 'Прайс объекта: подразделы и услуги', response=o.VenueCatalog,
        auth=False, errors=(404,))
    doc(loyalty.ProgramView, 'get', LOY, 'Уровни и привилегии', response=o.Program, auth=False)
    doc(content.PromosView, 'get', CNT, 'Акции-баннеры (активные сегодня)', response=o.Promo(many=True), auth=False)
    doc(content.EventsView, 'get', CNT, 'События недели', response=o.ResortEvent(many=True), auth=False)
    doc(content.StoriesView, 'get', CNT, 'Сторис разделов каталога', response=o.Story(many=True), auth=False)
    doc(content.ArticleView, 'get', CNT, 'Статья (диплинк / push)', response=o.Article, auth=False, errors=(404,))

    # кошелёк и заявки
    doc(loyalty.WalletView, 'get', LOY, 'Счётчики, уровень, удержание — единственный источник цифр', response=o.Wallet)
    doc(loyalty.OperationsView, 'get', LOY, 'История операций, новые сверху',
        response=o.page_of('OperationsPage', o.Operation), params=[o.CURSOR, o.LIMIT])
    doc(cashback.QuoteView, 'post', CB, 'Расчёт оплаты и кешбека (на каждое изменение ввода)', o.RequestInput,
        o.Quote, errors=(400, 401, 404, 422))
    doc(cashback.RequestsView, 'get', CB, 'Заявки', response=o.page_of('RequestsPage', o.CashbackRequest),
        params=[OpenApiParameter('status', str, enum=['active', 'all']), o.CURSOR, o.LIMIT],
        operation_id='cashback_requests_list')
    doc(cashback.RequestsView, 'post', CB, 'Создать заявку (сервер пересчитывает всё сам)', o.RequestInput,
        o.CashbackRequest, status=201, params=[o.IDEMPOTENCY_HEADER], errors=(400, 401, 403, 404, 422))
    doc(cashback.RequestDetailView, 'get', CB, 'Заявка', response=o.CashbackRequest, errors=(401, 404))
    doc(cashback.RequestCancelView, 'post', CB, 'Отменить заявку (только pending)', response=o.CashbackRequest,
        errors=(401, 404, 409))

    # оплата
    doc(payments.PaymentsView, 'post', PAY, 'Создать онлайн-оплату денежной части', o.PaymentInput, o.Payment,
        status=201, errors=(400, 401, 422))
    doc(payments.PaymentDetailView, 'get', PAY, 'Статус оплаты', response=o.Payment, errors=(401, 404))
    doc(payments.PaymentCheckView, 'post', PAY, '«Я оплатил» — проверить у провайдера', response=o.Payment)
    doc(payments.WebhookView, 'post', PAY, 'Вебхук провайдера (подпись X-Signature)', auth=False,
        response=inline_serializer('WebhookOk', {'ok': s.BooleanField()}), errors=(401, 404))

    # обращения
    doc(complaints.CategoriesView, 'get', CMP, 'Темы обращений и точки обслуживания',
        response=inline_serializer('ComplaintRefs', {
            'categories': inline_serializer('ComplaintCategoryRef', {'id': s.CharField(), 'title': s.CharField()},
                                            many=True),
            'outlets': inline_serializer('OutletRef', {'id': s.CharField(), 'name': s.CharField()}, many=True),
            'pointsSubtypes': s.ListField(child=s.CharField())}))
    doc(complaints.UploadPhotoView, 'post', CMP, 'Загрузить фото (JPEG/PNG/HEIC до 10 МБ, EXIF удаляется)',
        inline_serializer('PhotoUpload', {'file': s.FileField()}),
        inline_serializer('Uploaded', {'id': s.CharField(), 'url': s.URLField()}), status=201)
    doc(complaints.ComplaintsView, 'get', CMP, 'Мои обращения', response=o.page_of('ComplaintsPage', o.Complaint),
        params=[o.CURSOR, o.LIMIT], operation_id='complaints_list')
    doc(complaints.ComplaintsView, 'post', CMP, 'Новое обращение', o.ComplaintInput, o.Complaint, status=201,
        errors=(400, 401, 403, 429))
    doc(complaints.ComplaintDetailView, 'get', CMP, 'Обращение с перепиской', response=o.Complaint)
    doc(complaints.ComplaintMessagesView, 'post', CMP, 'Ответ клиента',
        inline_serializer('ComplaintReply', {'text': s.CharField(), 'attachmentIds': s.ListField(
            child=s.CharField(), required=False)}), o.Complaint, status=201, errors=(400, 401, 404, 409))
    doc(complaints.ComplaintRatingView, 'post', CMP, 'Оценка после закрытия',
        inline_serializer('RatingInput', {'rating': s.IntegerField(min_value=1, max_value=5),
                                          'comment': s.CharField(required=False)}), o.Complaint)
    doc(analytics.EventsIngestView, 'post', SYS, 'События аналитики пачкой', o.EventsBatch,
        inline_serializer('EventsAccepted', {'accepted': s.IntegerField(), 'dropped': s.IntegerField()}),
        status=202, auth=False)

    # сотрудник
    staff_err = (401, 403, 404, 409, 422)
    doc(staffdesk.QueueView, 'get', STAFF, 'Очередь pending своих точек (старые сверху)',
        response=inline_serializer('StaffQueue', {'items': o.StaffRequest(many=True), 'count': s.IntegerField()}),
        params=[OpenApiParameter('outlet', str)])
    doc(staffdesk.StaffRequestView, 'get', STAFF, 'Карточка заявки', response=o.StaffRequest)
    doc(staffdesk.ConfirmView, 'post', STAFF, 'Подтвердить (202 — ушло директору)',
        inline_serializer('ConfirmInput', {'cashReceived': s.BooleanField(required=False)}), o.StaffRequest,
        errors=staff_err)
    doc(staffdesk.AdjustPreviewView, 'post', STAFF, 'Правка суммы: расчёт без сохранения',
        inline_serializer('AdjustPreviewInput', {'total': s.IntegerField()}),
        inline_serializer('AdjustPreview', {**{k: v for k, v in o.PaymentSplit().fields.items()},
                                            'maxPointsSom': s.IntegerField(), 'needsManager': s.BooleanField()}))
    doc(staffdesk.AdjustView, 'post', STAFF, 'Изменить сумму (202 — ушло директору)',
        inline_serializer('AdjustInput', {'total': s.IntegerField(), 'reason': s.CharField()}), o.StaffRequest,
        errors=staff_err)
    doc(staffdesk.RejectView, 'post', STAFF, 'Отклонить',
        inline_serializer('RejectInput', {'reasonCode': s.ChoiceField(
            choices=['not_provided', 'wrong_amount', 'duplicate', 'other']), 'comment': s.CharField(required=False)}),
        o.StaffRequest, errors=staff_err)
    brief = inline_serializer('StaffMemberCard', {**{k: v for k, v in o.StaffMemberBrief().fields.items()},
                                                   'points': s.IntegerField(help_text='Доступно баллов'),
                                                   'pointsSom': s.IntegerField(help_text='Доступно в сомах'),
                                                   'deletedNote': s.DateTimeField(allow_null=True),
                                                   'requests': o.StaffRequest(many=True)})
    doc(staffdesk.MemberSearchView, 'get', STAFF, 'Поиск клиента по memberId / телефону',
        response=inline_serializer('StaffMemberSearch', {'items': brief.__class__(many=True)}),
        params=[OpenApiParameter('q', str)])
    doc(staffdesk.ScanView, 'post', STAFF, 'QR участника → клиент + payToken для оплаты баллами',
        inline_serializer('ScanInput', {'token': s.CharField()}),
        inline_serializer('ScanResult', {**brief.fields, 'payToken': s.CharField()}))
    pay_in = inline_serializer('PayInput', {'payToken': s.CharField(), 'itemId': s.CharField(),
                                           'quantity': s.IntegerField(required=False),
                                           'checkAmount': s.IntegerField(required=False)})
    doc(staffdesk.PayItemsView, 'get', STAFF, 'Услуги своих точек для оплаты баллами',
        response=inline_serializer('PayItems', {'items': inline_serializer('PayItem', {
            'id': s.CharField(), 'category': s.CharField(), 'title': s.CharField(), 'price': s.IntegerField(),
            'pricing': o.Pricing(), 'outlet': s.CharField(allow_null=True)}, many=True)}))
    doc(staffdesk.PayQuoteView, 'post', STAFF, 'Оплата баллами: хватает ли баллов (баланс не раскрывается)', pay_in,
        inline_serializer('PayQuote', {'itemId': s.CharField(), 'total': s.IntegerField(), 'quantity': s.IntegerField(),
                                       'points': s.IntegerField(), 'enough': s.BooleanField(),
                                       'shortSom': s.IntegerField(), 'reason': s.ChoiceField(
                                           choices=['limit', 'balance'], allow_null=True),
                                       'limitPercent': s.IntegerField()}), errors=(400, 401, 403, 404, 422))
    doc(staffdesk.PayChargeView, 'post', STAFF, 'Оплата баллами: списать (payToken из /staff/scan, 10 мин)', pay_in,
        o.StaffRequest, status=201, errors=(400, 401, 403, 404, 422))
    receipt_in = inline_serializer('ReceiptInput', {
        'payToken': s.CharField(), 'itemId': s.CharField(), 'receiptQr': s.CharField(help_text='Текст QR чека'),
        'requestId': s.CharField(required=False, help_text='Заявка клиента «наличными», к которой привязать чек')})
    doc(staffdesk.ReceiptPreviewView, 'post', STAFF, 'Наличные: скан QR чека → сумма и кешбек (ничего не сохраняет)',
        receipt_in, inline_serializer('ReceiptPreview', {
            'itemId': s.CharField(), 'amount': s.IntegerField(), 'total': s.IntegerField(),
            'quantity': s.IntegerField(), 'cashback': s.IntegerField(), 'rate': s.CharField(),
            'receiptNumber': s.CharField(), 'requestId': s.CharField(allow_null=True),
            'receipt': s.DictField(allow_null=True, help_text='Чек из налоговой: number, shift, dateTime, seller, '
                                   'address, tin, total, cash, cashless, items[], verified')}),
        errors=(400, 401, 403, 404, 409, 422))
    doc(staffdesk.ReceiptAcceptView, 'post', STAFF, 'Наличные: «Принять оплату» по чеку — проводится сразу',
        receipt_in, o.StaffRequest, status=201, errors=(400, 401, 403, 404, 409, 422))
    doc(staffdesk.ShiftView, 'get', STAFF, 'Итог смены',
        response=inline_serializer('Shift', {'date': s.DateField(), 'confirmed': o.StaffRequest(many=True),
                                             'rejected': o.StaffRequest(many=True), 'adjustedCount': s.IntegerField(),
                                             'cashTotal': s.IntegerField()}))

    # приложение кассира: вход по телефону и PIN
    tokens = inline_serializer('StaffTokens', {'accessToken': s.CharField(), 'refreshToken': s.CharField(),
                                               'expiresIn': s.IntegerField(), 'profile': s.DictField()})
    doc(staff_auth.PinLoginView, 'post', STAFF, 'Вход администратора кассы: телефон + 6-значный PIN',
        inline_serializer('StaffPinLogin', {'phone': s.CharField(), 'pin': s.CharField()}), tokens, auth=False,
        errors=(400, 401, 429))
    doc(staff_auth.DevicesView, 'post', STAFF, 'Push-токен приложения кассира (онлайн-оплаты своих точек)',
        inline_serializer('StaffDeviceInput', {'token': s.CharField(), 'platform': s.ChoiceField(
            choices=['ios', 'android']), 'appVersion': s.CharField(required=False)}), status=204)
    doc(staff_auth.DeviceDeleteView, 'delete', STAFF, 'Отвязать push-токен', status=204)
    doc(staff_auth.PinChangeView, 'post', STAFF, 'Сменить свой PIN',
        inline_serializer('StaffPinChange', {'currentPin': s.CharField(), 'newPin': s.CharField()}),
        s.DictField(), errors=(400, 401))
    from apps.backoffice.views import complaints as staff_complaints
    doc(staff_complaints.ComplaintsView, 'get', STAFF, 'Обращения своих точек', response=s.DictField(),
        params=[o.CURSOR, o.LIMIT], operation_id='staff_complaints_list')
    doc(staff_complaints.ComplaintDetailView, 'get', STAFF, 'Карточка обращения', response=s.DictField(),
        errors=(401, 403, 404))
    doc(staff_complaints.ComplaintDetailView, 'patch', STAFF, 'Изменить обращение (только директор)',
        s.DictField(), s.DictField(), errors=(400, 401, 403, 404))
    doc(staff_complaints.NotesView, 'post', STAFF, 'Внутренняя заметка к обращению (клиенту не видна)',
        inline_serializer('StaffComplaintNote', {'text': s.CharField()}), s.DictField(), status=201,
        errors=(400, 401, 403, 404))

    # вход в админку
    ADM = ['Админка: вход']
    doc(staff_auth.LoginView, 'post', ADM, 'Email + пароль → токен второго шага',
        inline_serializer('StaffLogin', {'email': s.EmailField(), 'password': s.CharField()}),
        inline_serializer('StaffLoginStep', {'twoFactorRequired': s.BooleanField(), 'twoFactorToken': s.CharField(),
                                             'twoFactorSetup': s.BooleanField(required=False),
                                             'otpauthUri': s.CharField(required=False)}), auth=False, errors=(401, 429))
    doc(staff_auth.TwoFactorView, 'post', ADM, 'TOTP-код → токены',
        inline_serializer('StaffTwoFactor', {'twoFactorToken': s.CharField(), 'code': s.CharField()}),
        o.Tokens, auth=False, errors=(401, 429))
    doc(staff_auth.RefreshView, 'post', ADM, 'Обновить токены сотрудника',
        inline_serializer('StaffRefresh', {'refreshToken': s.CharField()}), o.Tokens, auth=False)
    doc(staff_auth.LogoutView, 'post', ADM, 'Выход сотрудника', status=204)
    doc(staff_auth.PasswordView, 'post', ADM, 'Сменить пароль (обязательно после временного)',
        inline_serializer('StaffPassword', {'currentPassword': s.CharField(), 'newPassword': s.CharField()}),
        inline_serializer('StaffProfileAfterPassword', {'mustChangePassword': s.BooleanField()}))
    doc(staff_auth.MeView, 'get', ADM, 'Профиль и права сотрудника',
        response=inline_serializer('StaffProfile', {'id': s.IntegerField(), 'email': s.EmailField(),
                                                    'fullName': s.CharField(), 'role': s.CharField(),
                                                    'outlets': s.ListField(child=s.CharField()),
                                                    'permissions': s.ListField(child=s.CharField())}))


ADMIN_DOCUMENTED = ('/api/v1/admin/me', '/api/v1/admin/me/password')


def exclude_admin_crud(endpoints, **kwargs):
    """Схема для мобилки: клиентский API, API сотрудника и вход в админку. CRUD админки — внутренний."""
    return [e for e in endpoints if not e[0].startswith('/api/v1/admin/') or e[0].startswith('/api/v1/admin/auth/')
            or e[0] in ADMIN_DOCUMENTED]
