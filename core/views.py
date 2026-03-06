from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Lesson, Message, User, Material, Subject, TeacherRate, TeacherStudent, Notification, Homework, UserNote
from django.db import models, transaction
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
import csv


def is_admin(user):
    if user.role == 'admin':
        return True
    raise PermissionDenied


def is_teacher_or_admin(user):
    if user.role in ['teacher', 'admin']:
        return True
    raise PermissionDenied


@login_required
def calendar_view(request):
    now = timezone.now()
    # Граница архива — уроки старше 3 дней уходят в архив
    archive_threshold = now - timedelta(days=3)

    # --- 1. АВТОМАТИЧЕСКАЯ ПРОВЕРКА ПРОШЕДШИХ УРОКОВ ---
    with transaction.atomic():
        past_lessons = Lesson.objects.select_for_update().filter(
            date_time__lt=now, status='scheduled'
        ).select_related('student', 'subject')

        for lesson in past_lessons:
            price = lesson.subject.price_per_lesson
            lesson.status = 'done'
            lesson.save()
            User.objects.filter(id=lesson.student.id).update(
                balance=models.F('balance') - price
            )

    # --- 2. ФИЛЬТРАЦИЯ УРОКОВ (только не-архивные) ---
    teacher_filter_id = request.GET.get('teacher_filter')
    period_filter = request.GET.get('period')

    if request.user.role == 'student':
        lessons = Lesson.objects.filter(
            student=request.user,
            date_time__gte=archive_threshold  # БАГ 2: исключаем архивные
        ).order_by('date_time')
    elif request.user.role == 'teacher':
        lessons = Lesson.objects.filter(
            teacher=request.user,
            date_time__gte=archive_threshold  # БАГ 2: исключаем архивные
        ).order_by('date_time')
    else:  # Админ
        lessons = Lesson.objects.filter(
            date_time__gte=archive_threshold  # БАГ 2: исключаем архивные
        ).order_by('date_time')
        if teacher_filter_id:
            lessons = lessons.filter(teacher_id=teacher_filter_id)

    # Фильтр по периоду
    if period_filter == 'week':
        lessons = lessons.filter(
            date_time__gte=now,
            date_time__lte=now + timedelta(days=7)
        )
    elif period_filter == 'month':
        lessons = lessons.filter(
            date_time__gte=now,
            date_time__lte=now + timedelta(days=30)
        )

    # --- 3. ОБРАБОТКА СОЗДАНИЯ НОВОГО ЗАНЯТИЯ ---
    if request.method == 'POST' and request.user.role in ['teacher', 'admin']:
        subject_id = request.POST.get('subject')
        student_id = request.POST.get('student')
        teacher_id = request.POST.get('teacher')
        start_date_str = request.POST.get('date_time')

        try:
            iterations = max(1, min(52, int(request.POST.get('repeat_count', 1))))
        except (ValueError, TypeError):
            iterations = 1

        if subject_id and student_id and start_date_str:
            subject = Subject.objects.get(id=subject_id)
            student = User.objects.get(id=student_id)

            if request.user.role == 'admin':
                teacher = User.objects.get(id=teacher_id)
            else:
                teacher = request.user

            start_date = parse_datetime(start_date_str)
            if start_date is None:
                from datetime import datetime as dt
                start_date = dt.fromisoformat(start_date_str)
            if timezone.is_naive(start_date):
                start_date = timezone.make_aware(start_date)

            # БАГ 1: строго < 1 час (не <=), уроки длятся ровно 1 час
            conflicts = []
            duplicates = []
            for i in range(iterations):
                lesson_time = start_date + timedelta(weeks=i)

                # Полный дубль: тот же учитель + ученик + предмет + точное время
                exact_dup = Lesson.objects.filter(
                    teacher=teacher, student=student, subject=subject,
                    date_time=lesson_time
                ).exists()
                if exact_dup:
                    duplicates.append(lesson_time.strftime('%d.%m.%Y %H:%M'))
                    continue

                conflict = Lesson.objects.filter(
                    teacher=teacher,
                    status='scheduled',
                    date_time__gt=lesson_time - timedelta(hours=1),
                    date_time__lt=lesson_time + timedelta(hours=1),
                ).exists()
                if conflict:
                    conflicts.append(lesson_time.strftime('%d.%m.%Y %H:%M'))

            if conflicts or duplicates:
                error_parts = []
                if duplicates:
                    error_parts.append(f'Такое занятие уже существует: {", ".join(duplicates)}')
                if conflicts:
                    error_parts.append(f'У учителя уже есть занятие в это время: {", ".join(conflicts)}')
                conflict_str = '. '.join(error_parts)
                if request.user.role == 'admin':
                    available_subjects = Subject.objects.all()
                    students = User.objects.filter(role='student')
                else:
                    assigned_ids = TeacherRate.objects.filter(
                        teacher=request.user
                    ).values_list('subject_id', flat=True)
                    available_subjects = Subject.objects.filter(
                        models.Q(id__in=assigned_ids) | models.Q(is_universal=True)
                    )
                    student_ids = TeacherStudent.objects.filter(
                        teacher=request.user
                    ).values_list('student_id', flat=True)
                    students = User.objects.filter(id__in=student_ids)

                # Пагинация при ошибке
                page_lessons = Lesson.objects.filter(
                    teacher=teacher if request.user.role == 'teacher' else models.Q(),
                    date_time__gte=archive_threshold
                ).order_by('date_time') if request.user.role == 'teacher' else Lesson.objects.filter(
                    date_time__gte=archive_threshold
                ).order_by('date_time')

                return render(request, 'core/calendar.html', {
                    'lessons': page_lessons,
                    'subjects': available_subjects,
                    'students': students,
                    'teachers': User.objects.filter(role='teacher'),
                    'period_filter': 'all',
                    'conflict_error': conflict_str,
                })

            for i in range(iterations):
                Lesson.objects.create(
                    subject=subject,
                    student=student,
                    teacher=teacher,
                    date_time=start_date + timedelta(weeks=i),
                    status='scheduled'
                )
            return redirect('calendar')

    # --- 4. ОГРАНИЧЕНИЕ ПРЕДМЕТОВ И СТУДЕНТОВ ---
    if request.user.role == 'admin':
        available_subjects = Subject.objects.all()
        students = User.objects.filter(role='student')
    else:
        assigned_ids = TeacherRate.objects.filter(
            teacher=request.user
        ).values_list('subject_id', flat=True)
        available_subjects = Subject.objects.filter(
            models.Q(id__in=assigned_ids) | models.Q(is_universal=True)
        )
        student_ids = TeacherStudent.objects.filter(
            teacher=request.user
        ).values_list('student_id', flat=True)
        students = User.objects.filter(id__in=student_ids)

    # Пометки учителя об учениках (только для учителя/админа)
    student_notes = {}
    if request.user.role in ['teacher', 'admin']:
        notes_qs = UserNote.objects.filter(author=request.user)
        student_notes = {n.target_id: n.text for n in notes_qs}

    # --- БАГ 3: ПАГИНАЦИЯ (20 уроков на страницу) ---
    from django.core.paginator import Paginator
    paginator = Paginator(lessons, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'core/calendar.html', {
        'lessons': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'subjects': available_subjects,
        'students': students,
        'teachers': User.objects.filter(role='teacher'),
        'period_filter': period_filter or 'all',
        'student_notes': student_notes,
    })


@login_required
def delete_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    if lesson.status == 'done':
        rate_obj = TeacherRate.objects.filter(
            teacher=lesson.teacher, subject=lesson.subject
        ).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        User.objects.filter(id=lesson.student.id).update(
            balance=models.F('balance') + price
        )

    lesson.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect('calendar')


@login_required
def chat_view(request, user_id):
    other_user = get_object_or_404(User, id=user_id)

    Message.objects.filter(
        sender_id=user_id, receiver=request.user, is_read=False
    ).update(is_read=True)

    messages = Message.objects.filter(
        (models.Q(sender=request.user) & models.Q(receiver=other_user)) |
        (models.Q(sender=other_user) & models.Q(receiver=request.user))
    ).order_by('created_at')

    if request.method == 'POST':
        text = request.POST.get('text')
        if text:
            Message.objects.create(
                sender=request.user,
                receiver=other_user,
                text=text
            )
            return redirect('chat', user_id=user_id)

    return render(request, 'core/chat.html', {
        'other_user': other_user,
        'chat_messages': messages
    })


@login_required
@user_passes_test(is_teacher_or_admin)
def update_lesson_status(request, lesson_id, status):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    rate_obj = TeacherRate.objects.filter(
        teacher=lesson.teacher, subject=lesson.subject
    ).first()
    price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson

    if lesson.status == 'done' and status != 'done':
        User.objects.filter(id=lesson.student.id).update(
            balance=models.F('balance') + price
        )
    elif lesson.status != 'done' and status == 'done':
        User.objects.filter(id=lesson.student.id).update(
            balance=models.F('balance') - price
        )

    lesson.status = status
    lesson.save()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect('calendar')


@login_required
def profile_view(request):
    if request.user.role == 'student':
        return redirect('calendar')

    selected_month = None
    teacher_stats = []
    my_salary = Decimal('0.00')
    my_total_lessons = 0

    if request.user.role == 'teacher':
        selected_month = request.GET.get('month')
        if selected_month:
            try:
                year, month = map(int, selected_month.split('-'))
                done_lessons = Lesson.objects.filter(
                    teacher=request.user, status='done',
                    date_time__year=year, date_time__month=month
                ).select_related('subject', 'student')
            except (ValueError, AttributeError):
                selected_month = None
                done_lessons = Lesson.objects.filter(
                    teacher=request.user, status='done'
                ).select_related('subject', 'student')
        else:
            done_lessons = Lesson.objects.filter(
                teacher=request.user, status='done'
            ).select_related('subject', 'student')

        my_total_lessons = done_lessons.count()

        summary_data = done_lessons.values(
            'student__username',
            'student__first_name',
            'subject__id',
            'subject__name'
        ).annotate(lesson_count=Count('id'))

        for item in summary_data:
            rate_obj = TeacherRate.objects.filter(
                teacher=request.user,
                subject_id=item['subject__id']
            ).first()
            current_rate = rate_obj.rate if rate_obj else Decimal('0.00')
            subtotal = current_rate * item['lesson_count']
            my_salary += subtotal
            teacher_stats.append({
                'student__username': item['student__first_name'] or item['student__username'],
                'subject__name': item['subject__name'],
                'lesson_count': item['lesson_count'],
                'rate': current_rate,
                'subtotal': subtotal,
            })

    all_teachers_data = []
    total_revenue = Decimal('0.00')
    students_list = None

    if request.user.role == 'admin':
        if request.method == 'POST' and 'recharge_balance' in request.POST:
            s_id = request.POST.get('student_id')
            amount = request.POST.get('amount')
            if s_id and amount:
                try:
                    User.objects.filter(id=s_id).update(
                        balance=models.F('balance') + Decimal(amount)
                    )
                except Exception:
                    pass
                return redirect('profile')

        teachers = User.objects.filter(role='teacher')
        for t in teachers:
            t_lessons = Lesson.objects.filter(
                teacher=t, status='done'
            ).select_related('subject')
            t_salary = Decimal('0.00')
            for lesson in t_lessons:
                r = TeacherRate.objects.filter(
                    teacher=t, subject=lesson.subject
                ).first()
                t_salary += r.rate if r else Decimal('0.00')

            all_teachers_data.append({
                'user': t,
                'count': t_lessons.count(),
                'salary': t_salary
            })

        done_lessons_global = Lesson.objects.select_related('subject').filter(status='done')
        for lesson in done_lessons_global:
            total_revenue += lesson.subject.price_per_lesson

        students_list = User.objects.filter(role='student')

    return render(request, 'core/profile.html', {
        'my_count': my_total_lessons,
        'my_salary': my_salary,
        'teacher_stats': teacher_stats,
        'all_teachers': all_teachers_data,
        'total_lessons_global': Lesson.objects.filter(status='done').count(),
        'total_revenue': total_revenue,
        'students': students_list,
        'selected_month': selected_month,
    })


@login_required
@user_passes_test(is_admin)
def admin_panel_view(request):
    # БАГ 5: возвращаем JSON для AJAX-запросов
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        if 'assign_student' in request.POST:
            student_id = request.POST.get('student_id')
            teacher_ids = request.POST.getlist('teacher_ids')
            TeacherStudent.objects.filter(student_id=student_id).delete()
            for tid in teacher_ids:
                TeacherStudent.objects.create(teacher_id=tid, student_id=student_id)
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'assign_student'})
            return redirect('admin_panel')

        elif 'create_student' in request.POST:
            username = request.POST.get('username')
            password = request.POST.get('password')
            full_name = request.POST.get('student_fullname', '')
            if username and password:
                student = User.objects.create_user(username=username, password=password, role='student')
                if full_name:
                    student.first_name = full_name
                    student.save()
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'create_student',
                                     'id': student.id, 'username': username, 'full_name': full_name})
            return redirect('admin_panel')

        elif 'create_teacher' in request.POST:
            username = request.POST.get('teacher_username')
            password = request.POST.get('teacher_password')
            full_name = request.POST.get('teacher_fullname', '')
            if username and password:
                teacher = User.objects.create_user(
                    username=username, password=password, role='teacher'
                )
                if full_name:
                    teacher.first_name = full_name
                    teacher.save()
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'create_teacher',
                                     'id': teacher.id, 'username': username, 'full_name': full_name})
            return redirect('admin_panel')

        elif 'delete_user' in request.POST:
            user_id = request.POST.get('user_id')
            User.objects.filter(id=user_id).delete()
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'delete_user', 'user_id': user_id})
            return redirect('admin_panel')

        elif 'create_subject' in request.POST:
            name = request.POST.get('name', '').strip()
            if name:
                if Subject.objects.filter(name__iexact=name).exists():
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': f'Направление "{name}" уже существует'})
                    return redirect('admin_panel')
                subj = Subject.objects.create(
                    name=name,
                    is_universal=request.POST.get('is_universal') == 'on'
                )
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'create_subject',
                                     'id': subj.id, 'name': name})
            return redirect('admin_panel')

        elif 'delete_subject' in request.POST:
            subject_id = request.POST.get('subject_id')
            Subject.objects.filter(id=subject_id).delete()
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'delete_subject', 'subject_id': subject_id})
            return redirect('admin_panel')

        elif 'update_price' in request.POST:
            subject_id = request.POST.get('subject_id')
            new_price = request.POST.get('new_price', '').strip()
            # Запрет пустого значения и нуля
            if subject_id and new_price:
                try:
                    price_decimal = Decimal(new_price)
                    if price_decimal <= 0:
                        if is_ajax:
                            return JsonResponse({'status': 'error', 'message': 'Цена должна быть больше нуля'})
                        return redirect('admin_panel')
                    Subject.objects.filter(id=subject_id).update(price_per_lesson=price_decimal)
                    formatted = f"{price_decimal:.2f}"
                except Exception:
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': 'Некорректная цена'})
                    return redirect('admin_panel')
            else:
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': 'Введите цену'})
                return redirect('admin_panel')
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'update_price',
                                     'subject_id': subject_id, 'new_price': formatted})
            return redirect('admin_panel')

        elif 'update_color' in request.POST:
            subject_id = request.POST.get('subject_id')
            new_color = request.POST.get('new_color')
            if subject_id and new_color:
                Subject.objects.filter(id=subject_id).update(color=new_color)
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'update_color'})
            return redirect('admin_panel')

        elif 'set_rate' in request.POST:
            teacher_id = request.POST.get('teacher_id')
            subject_id = request.POST.get('subject_id')
            rate = request.POST.get('rate')
            if teacher_id and subject_id and rate:
                TeacherRate.objects.update_or_create(
                    teacher_id=teacher_id,
                    subject_id=subject_id,
                    defaults={'rate': rate}
                )
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'set_rate'})
            return redirect('admin_panel')

        # БАГ 4: обновление профиля администратора
        elif 'update_admin_profile' in request.POST:
            full_name = request.POST.get('admin_fullname', '').strip()
            if full_name:
                request.user.first_name = full_name
                request.user.save()
            if is_ajax:
                return JsonResponse({'status': 'ok', 'action': 'update_admin_profile',
                                     'full_name': full_name})
            return redirect('admin_panel')

        if is_ajax:
            return JsonResponse({'status': 'ok'})
        return redirect('admin_panel')

    return render(request, 'core/admin_panel.html', {
        'subjects': Subject.objects.all().order_by('price_per_lesson'),
        'students': User.objects.filter(role='student'),
        'teachers': User.objects.filter(role='teacher'),
        'rates': TeacherRate.objects.all(),
        'teacher_students': TeacherStudent.objects.select_related('teacher', 'student').all(),
    })


@login_required
@user_passes_test(is_teacher_or_admin)
def materials_view(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        file = request.FILES.get('file')
        if title and content:
            Material.objects.create(
                title=title,
                content=content,
                author=request.user,
                file=file
            )
            return redirect('materials')

    return render(request, 'core/materials.html', {
        'materials': Material.objects.all().order_by('-created_at')
    })


@login_required
def messages_list_view(request):
    if request.user.role == 'admin':
        users = User.objects.exclude(id=request.user.id)
    elif request.user.role == 'teacher':
        colleagues = User.objects.filter(
            role__in=['teacher', 'admin']
        ).exclude(id=request.user.id)
        student_ids = Lesson.objects.filter(
            teacher=request.user
        ).values_list('student_id', flat=True)
        users = (colleagues | User.objects.filter(id__in=student_ids)).distinct()
    else:
        teacher_ids = Lesson.objects.filter(
            student=request.user
        ).values_list('teacher_id', flat=True)
        users = User.objects.filter(id__in=teacher_ids).distinct()

    # Расширенная информация для каждого контакта
    users_with_info = []
    for u in users:
        last_msg = Message.objects.filter(
            models.Q(sender=request.user, receiver=u) |
            models.Q(sender=u, receiver=request.user)
        ).order_by('-created_at').first()

        unread = Message.objects.filter(
            sender=u, receiver=request.user, is_read=False
        ).count()

        last_time = ''
        if last_msg:
            now = timezone.now()
            delta = now - last_msg.created_at
            if delta.days == 0:
                last_time = last_msg.created_at.strftime('%H:%M')
            elif delta.days == 1:
                last_time = 'вчера'
            elif delta.days < 7:
                last_time = f'{delta.days} дн.'
            else:
                last_time = last_msg.created_at.strftime('%d.%m')

        users_with_info.append({
            'user': u,
            'last_message': last_msg,
            'last_time': last_time,
            'unread_count': unread,
        })

    users_with_info.sort(
        key=lambda x: (
            0 if x['unread_count'] > 0 else 1,
            -(x['last_message'].created_at.timestamp() if x['last_message'] else 0)
        )
    )

    return render(request, 'core/messages_list.html', {
        'users': users,
        'users_with_info': users_with_info,
    })


@login_required
@user_passes_test(is_teacher_or_admin)
def reschedule_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    if request.user == lesson.teacher or request.user.role == 'admin':
        if request.method == 'POST':
            new_date_str = request.POST.get('new_date')
            if new_date_str:
                new_date = parse_datetime(new_date_str)
                if new_date is None:
                    from datetime import datetime as dt
                    new_date = dt.fromisoformat(new_date_str)
                if timezone.is_naive(new_date):
                    new_date = timezone.make_aware(new_date)

                if not lesson.original_date_time:
                    lesson.original_date_time = lesson.date_time

                old_date = lesson.date_time.strftime('%d.%m.%Y %H:%M')
                lesson.date_time = new_date
                lesson.save()

                new_date_fmt = new_date.strftime('%d.%m.%Y %H:%M')

                Notification.objects.create(
                    user=lesson.student,
                    text=f'Занятие "{lesson.subject.name}" перенесено '
                         f'с {old_date} на {new_date_fmt}. '
                         f'Учитель: {lesson.teacher.get_display_name()}'
                )

                admins = User.objects.filter(role='admin')
                for admin in admins:
                    Notification.objects.create(
                        user=admin,
                        text=f'Учитель {lesson.teacher.get_display_name()} перенёс занятие '
                             f'"{lesson.subject.name}" '
                             f'(ученик: {lesson.student.get_display_name()}) '
                             f'с {old_date} на {new_date_fmt}'
                    )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'status': 'ok',
                        'new_date_fmt': new_date_fmt,
                        'original_date': old_date,  # всегда строка вида "28.02.2026 17:00"
                    })
                return redirect('calendar')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'original_date': ''})
    return redirect('calendar')


@login_required
def export_lessons_csv(request):
    if request.user.role != 'admin':
        return HttpResponse("Отказано в доступе", status=403)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="itishnik_report.csv"'
    response.write(u'\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Дата и время', 'Учитель', 'Ученик', 'Предмет', 'Статус', 'Доход школы'])

    lessons = Lesson.objects.all().select_related(
        'teacher', 'student', 'subject'
    ).order_by('date_time')

    teacher_id = request.GET.get('teacher_filter')
    if teacher_id:
        lessons = lessons.filter(teacher_id=teacher_id)

    for lesson in lessons:
        writer.writerow([
            lesson.date_time.strftime('%d.%m.%Y %H:%M'),
            lesson.teacher.get_display_name(),
            lesson.student.get_display_name(),
            lesson.subject.name,
            lesson.get_status_display(),
            lesson.subject.price_per_lesson if lesson.status == 'done' else 0
        ])

    return response


@login_required
def reports_page(request):
    if request.user.role != 'admin':
        return redirect('calendar')

    from django.db.models import Count, Sum, Q
    from django.utils import timezone
    from datetime import timedelta

    tab    = request.GET.get('tab', 'finance')
    period = request.GET.get('period', 'month')

    now = timezone.now()
    if period == 'week':
        date_from = now - timedelta(days=7)
    elif period == 'year':
        date_from = now - timedelta(days=365)
    else:
        date_from = now - timedelta(days=30)

    lessons_period = Lesson.objects.filter(date_time__gte=date_from)
    done_period    = lessons_period.filter(status='done')
    cancel_period  = lessons_period.filter(status='canceled')

    context = {'tab': tab, 'period': period}

    if tab == 'finance':
        report_data = []
        for lesson in done_period.select_related('teacher', 'subject', 'student').order_by('-date_time'):
            rate = TeacherRate.objects.filter(
                teacher=lesson.teacher, subject=lesson.subject
            ).first()
            revenue = float(lesson.subject.price_per_lesson)
            salary  = float(rate.rate) if rate else 0
            profit  = revenue - salary
            report_data.append({
                'date':    lesson.date_time,
                'teacher': lesson.teacher.get_display_name(),
                'subject': lesson.subject.name,
                'revenue': int(revenue),
                'salary':  int(salary),
                'profit':  int(profit),
            })

        total_revenue  = sum(r['revenue'] for r in report_data)
        total_salaries = sum(r['salary']  for r in report_data)
        net_profit     = total_revenue - total_salaries

        context.update({
            'report_data':    report_data,
            'total_revenue':  total_revenue,
            'total_salaries': total_salaries,
            'net_profit':     net_profit,
        })

    elif tab == 'workload':
        teachers = User.objects.filter(role='teacher')
        teacher_workload = []
        max_total = 0

        for t in teachers:
            done  = lessons_period.filter(teacher=t, status='done').count()
            sched = lessons_period.filter(teacher=t, status='scheduled').count()
            total = done + sched
            if total > 0:
                max_total = max(max_total, total)
                teacher_workload.append({
                    'name': t.get_display_name(), 'done': done,
                    'scheduled': sched, 'total': total, 'pct': 0,
                })

        for t in teacher_workload:
            t['pct'] = round(t['total'] / max_total * 100) if max_total else 0
        teacher_workload.sort(key=lambda x: -x['total'])

        subject_qs = (
            lessons_period.filter(status='done')
            .values('subject__name').annotate(cnt=Count('id')).order_by('-cnt')
        )
        total_done = sum(s['cnt'] for s in subject_qs)
        subject_workload = [
            {
                'name': s['subject__name'],
                'count': s['cnt'],
                'pct': round(s['cnt'] / total_done * 100) if total_done else 0,
            }
            for s in subject_qs
        ]

        context.update({
            'teacher_workload':    teacher_workload,
            'subject_workload':    subject_workload,
            'workload_total':      lessons_period.count(),
            'workload_done_total': done_period.count(),
            'workload_sched_total': lessons_period.filter(status='scheduled').count(),
        })

    elif tab == 'cancels':
        total_all     = lessons_period.count()
        total_cancels = cancel_period.count()
        cancel_rate   = round(total_cancels / total_all * 100) if total_all else 0

        cancel_revenue_loss = int(
            cancel_period.aggregate(
                s=Sum('subject__price_per_lesson')
            )['s'] or 0
        )

        teacher_cancels = []
        for t in User.objects.filter(role='teacher'):
            total   = lessons_period.filter(teacher=t).count()
            cancels = cancel_period.filter(teacher=t).count()
            if total > 0:
                teacher_cancels.append({
                    'name': t.get_display_name(),
                    'cancels': cancels,
                    'total': total,
                    'rate': round(cancels / total * 100),
                })
        teacher_cancels.sort(key=lambda x: -x['cancels'])

        student_cancels = []
        for s in User.objects.filter(role='student'):
            total   = lessons_period.filter(student=s).count()
            cancels = cancel_period.filter(student=s).count()
            if total > 0:
                student_cancels.append({
                    'name': s.get_display_name(),
                    'cancels': cancels,
                    'total': total,
                    'rate': round(cancels / total * 100),
                })
        student_cancels.sort(key=lambda x: -x['cancels'])

        context.update({
            'total_cancels':       total_cancels,
            'cancel_rate':         cancel_rate,
            'cancel_revenue_loss': cancel_revenue_loss,
            'teacher_cancels':     teacher_cancels,
            'student_cancels':     student_cancels,
        })

    return render(request, 'core/reports.html', context)


@login_required
def export_detailed_report(request):
    if request.user.role != 'admin':
        return HttpResponse("Доступ запрещен", status=403)

    period = request.GET.get('period', 'month')
    now = timezone.now()

    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:
        start_date = now - timedelta(days=30)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="itishnik_financial_report_{period}.csv"'
    response.write(u'\ufeff'.encode('utf8'))

    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Дата и время', 'Учитель', 'Ученик', 'Предмет',
        'Выручка (руб)', 'Зарплата (руб)', 'Прибыль (руб)'
    ])

    lessons = Lesson.objects.filter(
        status='done',
        date_time__gte=start_date
    ).select_related('subject', 'teacher', 'student').order_by('date_time')

    total_rev = Decimal('0.00')
    total_sal = Decimal('0.00')

    for lesson in lessons:
        revenue = lesson.subject.price_per_lesson
        rate_obj = TeacherRate.objects.filter(
            teacher=lesson.teacher, subject=lesson.subject
        ).first()
        salary = rate_obj.rate if rate_obj else Decimal('0.00')
        profit = revenue - salary

        total_rev += revenue
        total_sal += salary

        writer.writerow([
            lesson.date_time.strftime('%d.%m.%Y %H:%M'),
            lesson.teacher.get_display_name(),
            lesson.student.get_display_name(),
            lesson.subject.name,
            revenue,
            salary,
            profit
        ])

    writer.writerow([])
    writer.writerow([
        'ИТОГО ЗА ПЕРИОД', '', '', '',
        total_rev, total_sal, total_rev - total_sal
    ])

    return response


@login_required
def dashboard_view(request):
    if request.user.role != 'admin':
        return HttpResponseForbidden()

    from django.utils import timezone
    from django.db.models import Count, Sum
    import json

    now = timezone.now()

    total_students = User.objects.filter(role='student').count()
    total_teachers = User.objects.filter(role='teacher').count()
    done_lessons   = Lesson.objects.filter(status='done').count()
    sched_lessons  = Lesson.objects.filter(status='scheduled').count()
    cancel_lessons = Lesson.objects.filter(status='canceled').count()

    revenue_total = Lesson.objects.filter(status='done').aggregate(
        total=Sum('subject__price_per_lesson')
    )['total'] or 0

    months_labels  = []
    months_data    = []
    revenue_labels = []
    revenue_data   = []

    RU_MONTHS = ['Янв','Фев','Мар','Апр','Май','Июн',
                 'Июл','Авг','Сен','Окт','Ноя','Дек']

    for i in range(5, -1, -1):
        month = now.month - i
        year  = now.year
        while month <= 0:
            month += 12
            year  -= 1

        label = f"{RU_MONTHS[month - 1]} {year}"
        count = Lesson.objects.filter(
            status='done',
            date_time__year=year,
            date_time__month=month,
        ).count()
        rev = Lesson.objects.filter(
            status='done',
            date_time__year=year,
            date_time__month=month,
        ).aggregate(s=Sum('subject__price_per_lesson'))['s'] or 0

        months_labels.append(label)
        months_data.append(count)
        revenue_labels.append(label)
        revenue_data.append(float(rev))

    subject_qs = (
        Lesson.objects.filter(status='done')
        .values('subject__name')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')
    )
    subject_labels = [s['subject__name'] for s in subject_qs]
    subject_data   = [s['cnt'] for s in subject_qs]

    teacher_qs = (
        Lesson.objects.filter(status='done')
        .values('teacher__username', 'teacher__first_name')
        .annotate(cnt=Count('id'))
        .order_by('-cnt')[:5]
    )
    teacher_labels = [t['teacher__first_name'] or t['teacher__username'] for t in teacher_qs]
    teacher_data   = [t['cnt'] for t in teacher_qs]

    return render(request, 'core/dashboard.html', {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_lessons':  done_lessons,
        'total_revenue':  int(revenue_total),  # int чтобы floatformat:0 не давал пустоту на Decimal
        'done_lessons':   done_lessons,
        'sched_lessons':  sched_lessons,
        'cancel_lessons': cancel_lessons,
        'status_counts': {
            'done':      done_lessons,
            'scheduled': sched_lessons,
            'canceled':  cancel_lessons,
        },
        'months_labels':  json.dumps(months_labels,  ensure_ascii=False),
        'months_data':    json.dumps(months_data),
        'revenue_labels': json.dumps(revenue_labels, ensure_ascii=False),
        'revenue_data':   json.dumps(revenue_data),
        'subject_labels': json.dumps(subject_labels, ensure_ascii=False),
        'subject_data':   json.dumps(subject_data),
        'teacher_labels': json.dumps(teacher_labels, ensure_ascii=False),
        'teacher_data':   json.dumps(teacher_data),
    })


@login_required
def notifications_view(request):
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:50]
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, 'core/notifications.html', {'notifications': notifications})


@login_required
def mark_notification_read(request, notif_id):
    Notification.objects.filter(id=notif_id, user=request.user).update(is_read=True)
    return redirect('notifications')


@login_required
def homework_view(request):
    if request.user.role == 'teacher':
        homeworks = Homework.objects.filter(
            teacher=request.user
        ).select_related('student', 'subject', 'lesson').order_by('-created_at')
        student_ids = TeacherStudent.objects.filter(
            teacher=request.user
        ).values_list('student', flat=True)
        students_list = User.objects.filter(id__in=student_ids)
        subject_ids = TeacherRate.objects.filter(
            teacher=request.user
        ).values_list('subject', flat=True)
        subjects_list = Subject.objects.filter(id__in=subject_ids)

    elif request.user.role == 'admin':
        homeworks = Homework.objects.all().select_related(
            'student', 'teacher', 'subject'
        ).order_by('-created_at')
        students_list = User.objects.filter(role='student')
        subjects_list = Subject.objects.all()

    else:
        homeworks = Homework.objects.filter(
            student=request.user
        ).select_related('teacher', 'subject').order_by('-created_at')
        students_list = []
        subjects_list = []

    homeworks_list = list(homeworks)
    total = len(homeworks_list)
    done_count = sum(1 for h in homeworks_list if h.status in ['done', 'checked'])
    pending_count = sum(1 for h in homeworks_list if h.status == 'assigned')

    return render(request, 'core/homework.html', {
        'homeworks': homeworks_list,
        'students_list': students_list,
        'subjects_list': subjects_list,
        'total': total,
        'done_count': done_count,
        'pending_count': pending_count,
    })


@login_required
@user_passes_test(is_teacher_or_admin)
def create_homework(request):
    if request.method == 'POST':
        student_id = request.POST.get('student')
        subject_id = request.POST.get('subject')
        title = request.POST.get('title')
        description = request.POST.get('description')
        due_date = request.POST.get('due_date') or None

        if student_id and subject_id and title and description:
            hw = Homework.objects.create(
                teacher=request.user,
                student_id=student_id,
                subject_id=subject_id,
                title=title,
                description=description,
                due_date=due_date,
            )
            Notification.objects.create(
                user=hw.student,
                text=f'Новое домашнее задание: "{title}" по предмету {hw.subject.name}. '
                     f'Учитель: {request.user.get_display_name()}'
                     + (f'. Срок: {due_date[:10].replace("-", ".")}' if due_date else '')
            )
    return redirect('homework')


@login_required
def mark_homework_done(request, hw_id):
    hw = get_object_or_404(Homework, id=hw_id, student=request.user)
    hw.status = 'done'
    hw.save()
    Notification.objects.create(
        user=hw.teacher,
        text=f'Ученик {request.user.get_display_name()} выполнил задание "{hw.title}"'
    )
    return redirect('homework')


@login_required
@user_passes_test(is_teacher_or_admin)
def check_homework(request, hw_id):
    hw = get_object_or_404(Homework, id=hw_id)
    if request.user.role == 'teacher' and hw.teacher != request.user:
        raise PermissionDenied
    if request.method == 'POST':
        comment = request.POST.get('comment', '')
        hw.status = 'checked'
        hw.teacher_comment = comment
        hw.save()
        Notification.objects.create(
            user=hw.student,
            text=f'Учитель проверил задание "{hw.title}"'
                 + (f': {comment}' if comment else '')
        )
    return redirect('homework')


@login_required
@user_passes_test(is_teacher_or_admin)
def delete_homework(request, hw_id):
    hw = get_object_or_404(Homework, id=hw_id)
    if request.user.role == 'teacher' and hw.teacher != request.user:
        raise PermissionDenied
    hw.delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect('homework')


@login_required
@user_passes_test(is_teacher_or_admin)
def update_homework_status(request, hw_id, status):
    hw = get_object_or_404(Homework, id=hw_id)
    if status in ['assigned', 'done', 'checked']:
        hw.status = status
        hw.save()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect('homework')


@login_required
def chat_poll(request, user_id):
    after_id = int(request.GET.get('after', 0))
    new_msgs = Message.objects.filter(
        models.Q(sender_id=user_id, receiver=request.user) |
        models.Q(sender=request.user, receiver_id=user_id),
        id__gt=after_id
    ).order_by('created_at')
    new_msgs.filter(sender_id=user_id).update(is_read=True)

    return JsonResponse({
        'messages': [
            {
                'id': m.id,
                'text': m.text,
                'sender_id': m.sender_id,
                'created_at': m.created_at.isoformat(),
            }
            for m in new_msgs
        ]
    })


@login_required
def chat_send(request, user_id):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        text = data.get('text', '').strip()
        if text:
            other_user = get_object_or_404(User, id=user_id)
            msg = Message.objects.create(
                sender=request.user,
                receiver=other_user,
                text=text
            )
            return JsonResponse({
                'message': {
                    'id': msg.id,
                    'text': msg.text,
                    'sender_id': msg.sender_id,
                    'created_at': msg.created_at.isoformat(),
                }
            })
    return JsonResponse({'error': 'bad request'}, status=400)


@login_required
@user_passes_test(is_teacher_or_admin)
def save_student_note(request):
    """Сохранить/обновить личную пометку об ученике (видна только автору)."""
    if request.method == 'POST':
        target_id = request.POST.get('target_id')
        text = request.POST.get('text', '').strip()
        if target_id:
            if text:
                UserNote.objects.update_or_create(
                    author=request.user,
                    target_id=target_id,
                    defaults={'text': text}
                )
            else:
                # Пустой текст = удалить пометку
                UserNote.objects.filter(
                    author=request.user, target_id=target_id
                ).delete()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'ok', 'text': text})
    return redirect('calendar')


@login_required
def archive_view(request):
    if request.user.role == 'student':
        return redirect('calendar')

    archive_date = timezone.now() - timedelta(days=3)

    if request.user.role == 'teacher':
        lessons = Lesson.objects.filter(
            teacher=request.user,
            date_time__lt=archive_date
        )
    else:  # admin
        lessons = Lesson.objects.all().filter(date_time__lt=archive_date)
        teacher_filter = request.GET.get('teacher_filter')
        if teacher_filter:
            lessons = lessons.filter(teacher_id=teacher_filter)

    month_filter = request.GET.get('month')
    if month_filter:
        try:
            year, month = map(int, month_filter.split('-'))
            lessons = lessons.filter(
                date_time__year=year,
                date_time__month=month
            )
        except ValueError:
            pass

    lessons = lessons.select_related(
        'teacher', 'student', 'subject'
    ).order_by('-date_time')

    # Пагинация в архиве тоже
    from django.core.paginator import Paginator
    paginator = Paginator(lessons, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'core/calendar.html', {
        'lessons': page_obj,
        'page_obj': page_obj,
        'paginator': paginator,
        'teachers': User.objects.filter(role='teacher'),
        'period_filter': 'all',
        'is_archive': True,
        'month_filter': month_filter or '',
    })