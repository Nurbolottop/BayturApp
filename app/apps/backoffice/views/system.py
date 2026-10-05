"""
Администрирование (ТЗ §7.2 «Настройки», «Аудит-лог»): настройки программы, документы, сотрудники админки,
загрузка изображений, журнал действий.
"""
import secrets

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.common.audit import audit, model_snapshot
from apps.common.errors import ApiError
from apps.common.i18n import iso
from apps.common.media import process_upload
from apps.common.models import AuditLog, ProgramSettings, Upload
from apps.common.pagination import paginate
from apps.members.models import LegalDocument, LegalKind, Member, MemberStatus
from apps.staff.models import StaffRefreshToken, StaffUser
from apps.staff.roles import PERMISSIONS, Role

from ..base import (ANY_STAFF, AdminAPIView, CollectionView, DetailView, ObjectView, body, field_error,
                    parse_moment, period_filter)
from ..serializers import LegalDocumentSerializer, ProgramSettingsSerializer, StaffSerializer

OWNER = 'settings.edit'


# ---------------------------------------------------------------- настройки программы

class SettingsView(AdminAPIView):
    """GET / PATCH — все параметры ProgramSettings (camelCase). Действуют только на новые заявки."""

    required_perms = OWNER

    def get_object(self):
        # мимо кеша ProgramSettings.get(): правим актуальную строку из БД
        obj, _ = ProgramSettings.objects.get_or_create(pk=1)
        return obj

    def get(self, request):
        return Response(ProgramSettingsSerializer(self.get_object(), context=self.ctx()).data)

    def patch(self, request):
        obj = self.get_object()
        before = model_snapshot(obj)
        s = ProgramSettingsSerializer(obj, data=body(request), partial=True, context=self.ctx())
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = s.save()
            after = model_snapshot(obj)
            changed = {k for k in after if before.get(k) != after.get(k) and k != 'updated_at'}
            audit(request, 'settings.update', obj, before={k: before.get(k) for k in changed},
                  after={k: after[k] for k in changed})
        return Response(ProgramSettingsSerializer(obj, context=self.ctx()).data)

    put = patch


# ---------------------------------------------------------------- документы

class LegalView(CollectionView):
    """GET ?kind= ; POST — новая версия (черновик, публикуется отдельно)."""

    model = LegalDocument
    serializer_class = LegalDocumentSerializer
    audit_name = 'legal'
    required_perms = OWNER

    def filter_queryset(self, qs):
        kind = self.request.query_params.get('kind')
        return (qs.filter(kind=kind) if kind else qs).order_by('kind', '-created_at')


class LegalDetailView(DetailView):
    """Опубликованную версию не меняют и не удаляют — выпускают новую."""

    model = LegalDocument
    serializer_class = LegalDocumentSerializer
    audit_name = 'legal'
    required_perms = OWNER

    def ensure_draft(self, doc):
        if doc.published_at is not None:
            raise ApiError('invalid_status', 409, extra={'status': 'published'})

    def patch(self, request, pk):
        self.ensure_draft(self.get_object())
        return super().patch(request, pk=pk)

    put = patch

    def check_delete(self, doc):
        self.ensure_draft(doc)


class LegalPublishView(ObjectView):
    """
    POST {publishedAt?} — публикация версии (сразу или с даты). Новая версия terms/privacy с
    requiresAcceptance → у всех клиентов появляется pendingConsents (GET /me).
    """

    model = LegalDocument
    serializer_class = LegalDocumentSerializer
    audit_name = 'legal'
    required_perms = OWNER

    def post(self, request, pk):
        doc = self.get_object()
        if doc.published_at is not None:
            raise ApiError('invalid_status', 409, extra={'status': 'published'})
        at = parse_moment(body(request).get('publishedAt'), 'publishedAt') or timezone.now()
        with transaction.atomic():
            doc.published_at = at
            doc.save(update_fields=['published_at'])
            audit(request, 'legal.publish', doc, before={'publishedAt': None}, after={'publishedAt': iso(at)})
        needs_consent = doc.requires_acceptance and doc.kind in (LegalKind.TERMS, LegalKind.PRIVACY)
        return Response({
            **self.serialize(doc),
            'requiresConsentFrom': Member.objects.filter(status=MemberStatus.ACTIVE).count() if needs_consent else 0,
        })


# ---------------------------------------------------------------- сотрудники админки

def temporary_password():
    return secrets.token_urlsafe(9)


def check_password(value):
    try:
        validate_password(value)
    except DjangoValidationError as e:
        raise ApiError('validation_error', 400, extra={'fields': {'password': e.messages}})


def revoke_staff_sessions(user):
    StaffRefreshToken.objects.filter(staff=user, revoked_at__isnull=True).update(revoked_at=timezone.now())


def staff_snapshot(user):
    return {**model_snapshot(user, ['email', 'full_name', 'role', 'phone', 'is_active', 'totp_enabled']),
            'outlets': sorted(user.outlets.values_list('id', flat=True))}


class StaffListView(CollectionView):
    """GET ?role=&active= ; POST {email, fullName, role, phone, outletIds, password?} → temporaryPassword."""

    model = StaffUser
    serializer_class = StaffSerializer
    audit_name = 'staff'
    required_perms = 'staff.manage'

    def get_queryset(self):
        return StaffUser.objects.prefetch_related('outlets').order_by('full_name')

    def filter_queryset(self, qs):
        p = self.request.query_params
        if p.get('role'):
            qs = qs.filter(role=p['role'])
        if p.get('active') in ('0', '1', 'true', 'false'):
            qs = qs.filter(is_active=p['active'] in ('1', 'true'))
        return qs

    def snapshot(self, obj):
        return staff_snapshot(obj)

    def post(self, request):
        data = body(request)
        s = StaffSerializer(data=data, context=self.ctx())
        s.is_valid(raise_exception=True)
        password = data.get('password') or temporary_password()
        if data.get('password'):
            check_password(password)
        with transaction.atomic():
            outlets = s.validated_data.pop('outlets', [])
            user = StaffUser.objects.create_user(password=password, **s.validated_data,
                                                 must_change_password=not data.get('password'))
            user.outlets.set(outlets)
            audit(request, 'staff.create', user, after=staff_snapshot(user))
        payload = self.serialize(user)
        if not data.get('password'):
            payload['temporaryPassword'] = password  # показывается один раз
        return Response(payload, status=201)


class StaffDetailView(DetailView):
    model = StaffUser
    serializer_class = StaffSerializer
    audit_name = 'staff'
    required_perms = 'staff.manage'

    def snapshot(self, obj):
        return staff_snapshot(obj)

    def patch(self, request, pk):
        user = self.get_object()
        role = body(request).get('role')
        if user.pk == request.user.pk and role and role != user.role:
            raise field_error('role', 'нельзя менять роль самому себе')
        return super().patch(request, pk=pk)

    put = patch

    def delete(self, request, pk):
        # сотрудники фигурируют в заявках и аудите — только отключение
        raise ApiError('method_not_supported', 405, message='Сотрудника можно только отключить')


class StaffActionView(ObjectView):
    model = StaffUser
    serializer_class = StaffSerializer
    audit_name = 'staff'
    required_perms = 'staff.manage'
    action = None

    def post(self, request, pk):
        user = self.get_object()
        before = staff_snapshot(user)
        extra = {}
        with transaction.atomic():
            if self.action == 'activate':
                user.is_active = True
                user.save(update_fields=['is_active'])
            elif self.action == 'deactivate':
                if user.pk == request.user.pk:
                    raise field_error('id', 'нельзя отключить самого себя')
                user.is_active = False
                user.save(update_fields=['is_active'])
                revoke_staff_sessions(user)
            elif self.action == 'reset-2fa':
                user.totp_enabled = False
                user.totp_secret = ''
                user.save(update_fields=['totp_enabled', 'totp_secret'])
                revoke_staff_sessions(user)
            elif self.action == 'reset-password':
                password = temporary_password()
                user.set_password(password)
                user.must_change_password = True
                user.save(update_fields=['password', 'must_change_password'])
                revoke_staff_sessions(user)
                extra['temporaryPassword'] = password
            audit(request, f'staff.{self.action}', user, before=before, after=staff_snapshot(user))
        return Response({**self.serialize(user), **extra})


class RolesView(AdminAPIView):
    """Роли и матрица прав — для экрана сотрудников и интерфейса админки."""

    required_perms = ANY_STAFF

    def get(self, request):
        return Response({'items': [{'id': role, 'label': label,
                                    'permissions': sorted(p for p, roles in PERMISSIONS.items() if role in roles)}
                                   for role, label in Role.choices]})


class StaffDirectoryView(AdminAPIView):
    """Короткий список активных сотрудников (назначить ответственного, фильтр «сотрудник»)."""

    required_perms = ['complaints.view', 'requests.view_all', 'requests.process', 'audit.view_own']

    def get(self, request):
        qs = StaffUser.objects.filter(is_active=True).prefetch_related('outlets').order_by('full_name')
        role = request.query_params.get('role')
        if role:
            qs = qs.filter(role__in=role.split(','))
        return Response({'items': [{'id': u.pk, 'fullName': u.full_name, 'role': u.role,
                                    'outletIds': sorted(o.pk for o in u.outlets.all())} for u in qs]})


# ---------------------------------------------------------------- загрузка изображений

MAX_UPLOAD = 10 * 1024 * 1024


class UploadView(AdminAPIView):
    """POST multipart file → {id, url}. EXIF убирается; PNG/WebP с прозрачностью сохраняются как PNG (cutout)."""

    required_perms = ['content.edit', 'catalog.texts', 'tiers.texts', 'settings.edit', 'campaigns.draft',
                      'complaints.reply']

    def post(self, request):
        f = request.FILES.get('file')
        if f is None or f.size > MAX_UPLOAD:
            raise ApiError('file_invalid', 422)
        processed = process_upload(f)
        if processed is None:
            raise ApiError('file_invalid', 422)
        content, ext, w, h = processed
        upload = Upload(kind=Upload.KIND_IMAGE, staff=request.user, width=w, height=h)
        upload.file.save(f'{upload.id}.{ext}', content, save=False)
        upload.save()
        audit(request, 'upload.create', upload, after={'path': upload.file.name, 'width': w, 'height': h})
        return Response({'id': upload.pk, 'url': upload.url, 'path': upload.file.name, 'width': w, 'height': h},
                        status=201)


# ---------------------------------------------------------------- аудит-лог

def audit_payload(e):
    return {
        'id': e.pk,
        'at': iso(e.at),
        'actor': {'id': e.actor_id, 'label': e.actor_label, 'name': e.actor.full_name if e.actor else None},
        'ip': e.ip,
        'action': e.action,
        'objectType': e.object_type,
        'objectId': e.object_id,
        'before': e.before,
        'after': e.after,
        'comment': e.comment or None,
    }


class AuditView(AdminAPIView):
    """GET ?actor=&action=&objectType=&objectId=&from=&to=&cursor= ; менеджер видит только свои действия."""

    required_perms = ['audit.view_all', 'audit.view_own']

    def get(self, request):
        p = request.query_params
        qs = AuditLog.objects.select_related('actor')
        if not request.user.can('audit.view_all'):
            qs = qs.filter(actor=request.user)
        elif p.get('actor'):
            qs = qs.filter(actor_id=p['actor'])
        if p.get('action'):
            a = p['action']
            qs = qs.filter(action__startswith=a) if a.endswith('.') else qs.filter(action=a)
        if p.get('objectType'):
            qs = qs.filter(object_type=p['objectType'])
        if p.get('objectId'):
            qs = qs.filter(object_id=p['objectId'])
        qs = period_filter(qs, request, 'at')
        return Response(paginate(request, qs, lambda rows: [audit_payload(e) for e in rows], time_field='at',
                                 default_limit=50))
