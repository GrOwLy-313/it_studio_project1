from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

from core.models import User, Subject, Lesson, TeacherRate, TeacherStudent, Homework, Notification, Message


# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФАБРИКИ
# ============================================================

def make_admin(**kw):
    return User.objects.create_user(username='admin_u', password='pass', role='admin', **kw)

def make_teacher(**kw):
    return User.objects.create_user(username='teacher_u', password='pass', role='teacher', **kw)

def make_student(**kw):
    return User.objects.create_user(username='student_u', password='pass', role='student', **kw)

def make_subject(**kw):
    return Subject.objects.create(name='Python', price_per_lesson=Decimal('1000'), **kw)

def make_lesson(teacher, student, subject, hours_from_now=1, status='scheduled'):
    return Lesson.objects.create(
        teacher=teacher,
        student=student,
        subject=subject,
        date_time=timezone.now() + timedelta(hours=hours_from_now),
        status=status,
    )


# ============================================================
#  ТЕСТЫ МОДЕЛЕЙ
# ============================================================

class UserModelTest(TestCase):
    def test_str(self):
        u = make_student()
        self.assertIn('student_u', str(u))
        self.assertIn('Ученик', str(u))

    def test_default_balance(self):
        u = make_student()
        self.assertEqual(u.balance, Decimal('0'))

    def test_role_choices(self):
        admin = make_admin()
        self.assertEqual(admin.get_role_display(), 'Администратор')


class SubjectModelTest(TestCase):
    def test_str(self):
        s = make_subject()
        self.assertEqual(str(s), 'Python')

    def test_default_color(self):
        s = make_subject()
        self.assertEqual(s.color, '#3b82f6')

    def test_is_universal_default_false(self):
        s = make_subject()
        self.assertFalse(s.is_universal)


class LessonModelTest(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student()
        self.subject = make_subject()

    def test_str(self):
        lesson = make_lesson(self.teacher, self.student, self.subject)
        self.assertIn('Python', str(lesson))
        self.assertIn('student_u', str(lesson))

    def test_default_status_scheduled(self):
        lesson = make_lesson(self.teacher, self.student, self.subject)
        self.assertEqual(lesson.status, 'scheduled')

    def test_original_date_time_null_by_default(self):
        lesson = make_lesson(self.teacher, self.student, self.subject)
        self.assertIsNone(lesson.original_date_time)


class TeacherRateModelTest(TestCase):
    def test_str(self):
        teacher = make_teacher()
        subject = make_subject()
        rate = TeacherRate.objects.create(teacher=teacher, subject=subject, rate=Decimal('500'))
        self.assertIn('teacher_u', str(rate))
        self.assertIn('Python', str(rate))
        self.assertIn('500', str(rate))


class TeacherStudentModelTest(TestCase):
    def test_unique_together(self):
        teacher = make_teacher()
        student = make_student()
        TeacherStudent.objects.create(teacher=teacher, student=student)
        with self.assertRaises(Exception):
            TeacherStudent.objects.create(teacher=teacher, student=student)


class HomeworkModelTest(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.student = make_student()
        self.subject = make_subject()

    def test_str(self):
        hw = Homework.objects.create(
            teacher=self.teacher, student=self.student,
            subject=self.subject, title='Задача #1',
            description='Решить задачу'
        )
        self.assertIn('Задача #1', str(hw))
        self.assertIn('student_u', str(hw))

    def test_default_status_assigned(self):
        hw = Homework.objects.create(
            teacher=self.teacher, student=self.student,
            subject=self.subject, title='T', description='D'
        )
        self.assertEqual(hw.status, 'assigned')


class MessageModelTest(TestCase):
    def test_str(self):
        sender = make_teacher()
        receiver = make_student()
        msg = Message.objects.create(sender=sender, receiver=receiver, text='Привет!')
        self.assertIn('teacher_u', str(msg))
        self.assertIn('student_u', str(msg))

    def test_is_read_default_false(self):
        sender = make_teacher()
        receiver = make_student()
        msg = Message.objects.create(sender=sender, receiver=receiver, text='Тест')
        self.assertFalse(msg.is_read)


class NotificationModelTest(TestCase):
    def test_str(self):
        user = make_student()
        n = Notification.objects.create(user=user, text='Урок перенесён')
        self.assertIn('student_u', str(n))
        self.assertIn('Урок перенесён', str(n))

    def test_is_read_default_false(self):
        user = make_student()
        n = Notification.objects.create(user=user, text='Тест')
        self.assertFalse(n.is_read)


# ============================================================
#  ТЕСТЫ ПРАВ ДОСТУПА (анонимный пользователь)
# ============================================================

class AnonymousAccessTest(TestCase):
    """Неавторизованный пользователь должен редиректиться на логин."""

    PROTECTED_URLS = [
        '/',
        '/profile/',
        '/materials/',
        '/messages/',
        '/admin-panel/',
        '/reports/',
        '/dashboard/',
        '/notifications/',
        '/homework/',
        '/archive/',
    ]

    def test_redirects_to_login(self):
        c = Client()
        for url in self.PROTECTED_URLS:
            resp = c.get(url)
            self.assertIn(resp.status_code, [301, 302], msg=f'URL {url} должен редиректить')
            self.assertIn('/login/', resp['Location'], msg=f'URL {url} должен вести на логин')


# ============================================================
#  ТЕСТЫ VIEWS
# ============================================================

class CalendarViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = make_teacher()
        self.student = make_student()
        self.subject = make_subject()
        self.client.login(username='teacher_u', password='pass')

    def test_calendar_opens(self):
        resp = self.client.get(reverse('calendar'))
        self.assertEqual(resp.status_code, 200)

    def test_calendar_shows_own_lessons_for_teacher(self):
        make_lesson(self.teacher, self.student, self.subject)
        resp = self.client.get(reverse('calendar'))
        self.assertIn(self.student.username, resp.content.decode())

    def test_student_cannot_see_other_teacher_lessons(self):
        other_teacher = User.objects.create_user(
            username='other_t', password='pass', role='teacher'
        )
        other_student = User.objects.create_user(
            username='other_s', password='pass', role='student'
        )
        make_lesson(other_teacher, other_student, self.subject)

        self.client.login(username='student_u', password='pass')
        resp = self.client.get(reverse('calendar'))
        self.assertNotIn('other_s', resp.content.decode())

    def test_create_lesson_as_teacher(self):
        TeacherRate.objects.create(teacher=self.teacher, subject=self.subject, rate=500)
        TeacherStudent.objects.create(teacher=self.teacher, student=self.student)

        future = timezone.now() + timedelta(days=1)
        resp = self.client.post(reverse('calendar'), {
            'subject': self.subject.id,
            'student': self.student.id,
            'date_time': future.strftime('%Y-%m-%dT%H:%M'),
        })
        self.assertIn(resp.status_code, [200, 302])
        self.assertEqual(Lesson.objects.count(), 1)


class AdminPanelAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = make_teacher()
        self.student = make_student()

    def test_teacher_cannot_access_admin_panel(self):
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(reverse('admin_panel'))
        self.assertEqual(resp.status_code, 403)

    def test_student_cannot_access_admin_panel(self):
        self.client.login(username='student_u', password='pass')
        resp = self.client.get(reverse('admin_panel'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_access_admin_panel(self):
        admin = make_admin()
        self.client.login(username='admin_u', password='pass')
        resp = self.client.get(reverse('admin_panel'))
        self.assertEqual(resp.status_code, 200)


class UpdateLessonStatusTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = make_teacher()
        self.student = make_student()
        self.subject = make_subject()
        TeacherRate.objects.create(teacher=self.teacher, subject=self.subject, rate=Decimal('500'))
        self.lesson = make_lesson(self.teacher, self.student, self.subject)

    def test_teacher_can_mark_done(self):
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.post(
            reverse('update_status', args=[self.lesson.id, 'done']),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, 'done')

    def test_marking_done_deducts_balance(self):
        self.client.login(username='teacher_u', password='pass')
        self.client.post(
            reverse('update_status', args=[self.lesson.id, 'done']),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.balance, Decimal('-500'))

    def test_student_cannot_update_status(self):
        self.client.login(username='student_u', password='pass')
        resp = self.client.post(
            reverse('update_status', args=[self.lesson.id, 'done']),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 403)


class HomeworkViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = make_teacher()
        self.student = make_student()
        self.subject = make_subject()
        TeacherStudent.objects.create(teacher=self.teacher, student=self.student)
        TeacherRate.objects.create(teacher=self.teacher, subject=self.subject, rate=500)

    def test_teacher_sees_homework_page(self):
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(reverse('homework'))
        self.assertEqual(resp.status_code, 200)

    def test_create_homework_creates_notification(self):
        self.client.login(username='teacher_u', password='pass')
        self.client.post(reverse('create_homework'), {
            'student': self.student.id,
            'subject': self.subject.id,
            'title': 'Тестовое задание',
            'description': 'Сделать что-нибудь',
        })
        self.assertEqual(Homework.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.student).count(), 1)

    def test_student_can_view_own_homework(self):
        Homework.objects.create(
            teacher=self.teacher, student=self.student,
            subject=self.subject, title='ДЗ', description='Описание'
        )
        self.client.login(username='student_u', password='pass')
        resp = self.client.get(reverse('homework'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ДЗ', resp.content.decode())


class ChatTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.teacher = make_teacher()
        self.student = make_student()

    def test_chat_page_opens(self):
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(reverse('chat', args=[self.student.id]))
        self.assertEqual(resp.status_code, 200)

    def test_send_message_via_ajax(self):
        import json
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.post(
            reverse('chat_send', args=[self.student.id]),
            data=json.dumps({'text': 'Привет!'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['message']['text'], 'Привет!')
        self.assertEqual(Message.objects.count(), 1)

    def test_poll_returns_new_messages(self):
        import json
        msg = Message.objects.create(
            sender=self.student, receiver=self.teacher, text='Тест'
        )
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(
            reverse('chat_poll', args=[self.student.id]),
            {'after': 0},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['messages']), 1)
        self.assertEqual(data['messages'][0]['text'], 'Тест')


class DashboardAccessTest(TestCase):
    def test_teacher_cannot_access_dashboard(self):
        make_teacher()
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_access_dashboard(self):
        make_admin()
        self.client.login(username='admin_u', password='pass')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)


class NotificationsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.student = make_student()

    def test_notifications_page_opens(self):
        self.client.login(username='student_u', password='pass')
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(resp.status_code, 200)

    def test_notifications_marked_read_on_visit(self):
        Notification.objects.create(user=self.student, text='Тест', is_read=False)
        self.client.login(username='student_u', password='pass')
        self.client.get(reverse('notifications'))
        self.assertEqual(
            Notification.objects.filter(user=self.student, is_read=False).count(), 0
        )


class ReportsAccessTest(TestCase):
    def test_teacher_cannot_access_reports(self):
        make_teacher()
        self.client.login(username='teacher_u', password='pass')
        resp = self.client.get(reverse('reports_page'))
        # redirect на calendar
        self.assertEqual(resp.status_code, 302)

    def test_admin_can_access_reports(self):
        make_admin()
        self.client.login(username='admin_u', password='pass')
        resp = self.client.get(reverse('reports_page'))
        self.assertEqual(resp.status_code, 200)