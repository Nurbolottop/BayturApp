"""Обращения в админке: область видимости, права ответа, шаблоны на языке клиента, заметки."""
from apps.common.models import AuditLog
from apps.complaints.models import ComplaintCategory, ComplaintMessage, ComplaintNote, ReplyTemplate
from apps.complaints.services import create_complaint

from .base import AdminTestCase


class ComplaintTests(AdminTestCase):
    def setUp(self):
        ComplaintCategory.objects.create(id='service', title={'ru': 'Обслуживание'})
        self.complaint = create_complaint(self.member, {'category': 'service', 'outletId': 'reception',
                                                        'text': 'Долго ждали администратора'})
        self.url = f'/complaints/{self.complaint.pk}'

    def test_staff_reads_and_notes_but_never_replies(self):
        r = self.get(self.staff, self.url)
        self.assertStatus(r, 200)
        self.assertFalse(r.data['canReply'])
        r = self.post(self.staff, self.url + '/reply', {'text': 'Извините'})
        self.assertError(r, 403, 'permission_denied')
        self.assertFalse(ComplaintMessage.objects.filter(author='resort').exists())
        r = self.post(self.staff, self.url + '/notes', {'text': 'Клиент был в 14:00'})
        self.assertStatus(r, 201)
        self.assertEqual(ComplaintNote.objects.get().staff, self.staff)
        self.assertStatus(self.post(self.staff, self.url + '/status', {'status': 'closed'}), 403)

    def test_staff_of_other_outlet_does_not_see(self):
        self.assertStatus(self.get(self.spa_staff, self.url), 404)
        self.assertEqual(self.get(self.spa_staff, '/complaints').data['items'], [])
        self.assertStatus(self.post(self.spa_staff, self.url + '/notes', {'text': 'x'}), 404)

    def test_staff_app_routes(self):
        """Приложение кассира: те же обращения своих точек по /staff/complaints."""
        app = self.as_(self.staff)
        self.assertEqual(len(app.get('/api/v1/staff/complaints').data['items']), 1)
        self.assertEqual(app.get(f'/api/v1/staff/complaints/{self.complaint.pk}').status_code, 200)
        r = app.post(f'/api/v1/staff/complaints/{self.complaint.pk}/notes', {'text': 'клиент у кассы'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_care_replies_with_template_in_client_language(self):
        t = ReplyTemplate.objects.create(title='Извинение', text={'ru': 'Здравствуйте, {name}! {number}',
                                                                   'ky': 'Саламатсызбы, {name}! {number}'})
        r = self.post(self.care, self.url + '/reply', {'templateId': t.pk})
        self.assertStatus(r, 201)
        msg = ComplaintMessage.objects.get(author='resort')
        self.assertEqual(msg.text, f'Саламатсызбы, Айбек! {self.complaint.number}')
        self.assertEqual(r.data['status'], 'answered')
        self.assertEqual(r.data['assigneeId'], self.care.pk)
        self.assertTrue(AuditLog.objects.filter(action='complaint.reply', actor=self.care).exists())

    def test_filters_assign_and_compensate(self):
        r = self.get(self.manager, '/complaints', status='new', outlet='reception', category='service')
        self.assertEqual(len(r.data['items']), 1)
        r = self.post(self.manager, self.url + '/assign', {'assigneeId': self.spa_staff.pk})
        self.assertStatus(r, 400)  # не видит обращение чужой точки
        r = self.post(self.manager, self.url + '/assign', {'assigneeId': self.care.pk})
        self.assertStatus(r, 200)
        self.assertEqual(r.data['status'], 'in_progress')
        r = self.get(self.care, '/complaints', assignee='me')
        self.assertEqual(len(r.data['items']), 1)
        self.assertStatus(self.post(self.staff, self.url + '/compensate', {'points': 100, 'comment': 'x'}), 403)
        r = self.post(self.manager, self.url + '/compensate', {'points': 100, 'comment': 'Извините за ожидание'})
        self.assertStatus(r, 201)
        self.assertEqual(r.data['compensations'][0]['points'], 100)

    def test_categories_and_templates_crud(self):
        r = self.post(self.manager, '/complaint-categories', {'id': 'food', 'title': {'ru': 'Еда', 'ky': 'Тамак',
                                                                                        'en': 'Food'}})
        self.assertStatus(r, 201)
        self.assertStatus(self.post(self.staff, '/complaint-categories', {'id': 'x', 'title': {'ru': 'X'}}), 403)
        self.assertError(self.delete(self.manager, '/complaint-categories/service'), 409, 'in_use')
        r = self.post(self.manager, '/reply-templates', {'title': 'T', 'text': {'ru': 'Ответ'}, 'category': 'food'})
        self.assertStatus(r, 201)
        self.assertStatus(self.get(self.care, '/reply-templates'), 200)
