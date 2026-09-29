"""
Общая основа админ-API (/api/v1/admin, ТЗ §7.3).

- Токен админа (StaffAuthentication), права — матрица staff.roles через HasPerm.
  По умолчанию доступ закрыт: у каждого view должен быть явный required_perms.
- Локализуемые поля — объектом {ru, ky, en} в обе стороны (context full_l10n).
- Каждое изменение пишется в аудит-лог (было / стало).
- Типовой CRUD: CollectionView (список + создание) и DetailView (карточка, правка, удаление).
  Для ролей «только тексты» (редактор) правка ограничена serializer.TEXT_FIELDS.
"""
from datetime import datetime, time

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.audit import audit, model_snapshot
from apps.common.errors import ApiError
from apps.common.pagination import paginate
from apps.staff.auth import HasPerm, StaffAuthentication
from apps.staff.roles import PERMISSIONS

# «любой сотрудник админки»: у каждой роли есть хотя бы одно право
ANY_STAFF = sorted(PERMISSIONS)


def body(request):
    return request.data if isinstance(request.data, dict) else {}


def not_found():
    return ApiError('not_found', 404)


def in_use(message='Объект используется — его можно только скрыть'):
    return ApiError('in_use', 409, message=message)


def forbidden(fields=None):
    return ApiError('permission_denied', 403, extra={'fields': sorted(fields)} if fields else None)


def field_error(field, message):
    return ApiError('validation_error', 400, extra={'fields': {field: [message]}})


def parse_moment(value, field, end_of_day=False):
    """'2026-09-01' или ISO datetime → aware datetime; пусто → None."""
    if value in (None, ''):
        return None
    dt = parse_datetime(str(value))
    if dt is None:
        d = parse_date(str(value))
        if d is None:
            raise field_error(field, 'формат YYYY-MM-DD или ISO 8601')
        dt = datetime.combine(d, time.max if end_of_day else time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


def period_filter(qs, request, field, from_param='from', to_param='to'):
    start = parse_moment(request.query_params.get(from_param), from_param)
    end = parse_moment(request.query_params.get(to_param), to_param, end_of_day=True)
    if start:
        qs = qs.filter(**{f'{field}__gte': start})
    if end:
        qs = qs.filter(**{f'{field}__lte': end})
    return qs


def truthy(value):
    return str(value).lower() in ('1', 'true', 'yes')


class AdminAPIView(APIView):
    authentication_classes = [StaffAuthentication]
    permission_classes = [HasPerm]
    required_perms = {}  # пусто = запрещено всем

    def ctx(self, **extra):
        return {'full_l10n': True, 'request': self.request, **extra}


class ModelMixin:
    model = None
    serializer_class = None
    audit_name = None          # 'item' → item.create / item.update / item.delete
    full_perm = None           # право на любые поля
    texts_perm = None          # право только на TEXT_FIELDS (редактор)

    def get_queryset(self):
        return self.model.objects.all()

    def serialize(self, obj):
        return self.serializer_class(obj, context=self.ctx()).data

    def serialize_many(self, rows):
        return self.serializer_class(rows, many=True, context=self.ctx()).data

    def snapshot(self, obj):
        return model_snapshot(obj)

    def check_field_access(self, data):
        """Редактор меняет только тексты и фото: остальные поля → 403 с их списком."""
        user = self.request.user
        if self.full_perm is None or user.can(self.full_perm):
            return
        allowed = getattr(self.serializer_class, 'TEXT_FIELDS', set())
        if self.texts_perm and user.can(self.texts_perm):
            extra = set(data) - set(allowed)
            if extra:
                raise forbidden(extra)
            return
        raise forbidden()


class CollectionView(ModelMixin, AdminAPIView):
    paginated = False
    time_field = 'created_at'

    def filter_queryset(self, qs):
        return qs

    def get(self, request):
        qs = self.filter_queryset(self.get_queryset())
        if self.paginated:
            return Response(paginate(request, qs, self.serialize_many, time_field=self.time_field))
        return Response({'items': self.serialize_many(qs)})

    def perform_create(self, serializer):
        return serializer.save()

    def post(self, request):
        s = self.serializer_class(data=body(request), context=self.ctx())
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = self.perform_create(s)
            audit(request, f'{self.audit_name}.create', obj, after=self.snapshot(obj))
        return Response(self.serialize(obj), status=201)


class ObjectView(ModelMixin, AdminAPIView):
    """Основа для действий над одним объектом (/{id}/publish, /{id}/hide…): только get_object."""

    lookup_kwarg = 'pk'

    def get_object(self):
        obj = self.get_queryset().filter(pk=self.kwargs[self.lookup_kwarg]).first()
        if obj is None:
            raise not_found()
        return obj


class DetailView(ObjectView):
    def get(self, request, **kwargs):
        return Response(self.serialize(self.get_object()))

    def perform_update(self, serializer):
        return serializer.save()

    def patch(self, request, **kwargs):
        obj = self.get_object()
        data = body(request)
        self.check_field_access(data)
        before = self.snapshot(obj)
        s = self.serializer_class(obj, data=data, partial=True, context=self.ctx())
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            obj = self.perform_update(s)
            audit(request, f'{self.audit_name}.update', obj, before=before, after=self.snapshot(obj))
        return Response(self.serialize(obj))

    put = patch

    def check_delete(self, obj):
        pass

    def delete(self, request, **kwargs):
        obj = self.get_object()
        self.check_delete(obj)
        before = self.snapshot(obj)
        object_type, object_id = obj._meta.label_lower, str(obj.pk)
        try:
            with transaction.atomic():
                obj.delete()
                audit(request, f'{self.audit_name}.delete', None, before=before, object_type=object_type,
                      object_id=object_id)
        except ProtectedError:
            raise in_use()
        return Response(status=204)


class SortView(AdminAPIView):
    """POST {ids: [...]} → sort_order по порядку списка."""

    model = None
    audit_name = None
    field = 'sort_order'

    def get_queryset(self):
        return self.model.objects.all()

    def post(self, request):
        ids = body(request).get('ids')
        if not isinstance(ids, list) or not ids:
            raise field_error('ids', 'ожидается непустой список')
        ids = [str(i) if not isinstance(i, int) else i for i in ids]
        objs = {str(o.pk): o for o in self.get_queryset().filter(pk__in=ids)}
        if len(objs) != len(set(map(str, ids))):
            raise field_error('ids', 'неизвестные id')
        with transaction.atomic():
            before = {k: getattr(o, self.field) for k, o in objs.items()}
            for index, pk in enumerate(ids):
                obj = objs[str(pk)]
                setattr(obj, self.field, (index + 1) * 10)
                obj.save(update_fields=[self.field])
            audit(request, f'{self.audit_name}.sort', None, object_type=self.model._meta.label_lower,
                  before=before, after={str(pk): (i + 1) * 10 for i, pk in enumerate(ids)})
        return Response({'ids': ids})
