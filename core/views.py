from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Lesson, Message, User, Material, Subject, TeacherRate, TeacherStudent, Notification
from django.db import models
from django.db.models import Count, Sum
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal
from django.core.exceptions import PermissionDenied
import csv
from django.http import HttpResponse

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
    # --- 1. АВТОМАТИЧЕСКАЯ ПРОВЕРКА ПРОШЕДШИХ УРОКОВ ---
    now = timezone.now()
    past_lessons = Lesson.objects.filter(date_time__lt=now, status='scheduled')
    
    for lesson in past_lessons:
        # Списываем стоимость предмета с баланса ученика (как в твоем оригинале)
        price = lesson.subject.price_per_lesson
        
        lesson.status = 'done'
        lesson.student.balance -= price
        lesson.student.save()
        lesson.save()

    # --- 2. ФИЛЬТРАЦИЯ УРОКОВ ДЛЯ ОТОБРАЖЕНИЯ ---
    teacher_filter_id = request.GET.get('teacher_filter')
    period_filter = request.GET.get('period')  # 'week', 'month', 'all'

    if request.user.role == 'student':
        lessons = Lesson.objects.filter(student=request.user).order_by('date_time')
    elif request.user.role == 'teacher':
        lessons = Lesson.objects.filter(teacher=request.user).order_by('date_time')
    else:  # Админ
        lessons = Lesson.objects.all().order_by('date_time')
        if teacher_filter_id:
            lessons = lessons.filter(teacher_id=teacher_filter_id)

    # Фильтр по периоду
    now = timezone.now()
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

    # --- 3. ОБРАБОТКА СОЗДАНИЯ НОВОГО ЗАНЯТИЯ (ТВОЙ ОРИГИНАЛ + ПРАВКИ) ---
    if request.method == 'POST' and request.user.role in ['teacher', 'admin']:
        subject_id = request.POST.get('subject')
        student_id = request.POST.get('student')
        teacher_id = request.POST.get('teacher') # Используется только админом
        start_date_str = request.POST.get('date_time')
        repeat = request.POST.get('repeat') == 'on'

        if subject_id and student_id and start_date_str:
            subject = Subject.objects.get(id=subject_id)
            student = User.objects.get(id=student_id)
            
            if request.user.role == 'admin':
                teacher = User.objects.get(id=teacher_id)
            else:
                teacher = request.user

            start_date = timezone.datetime.fromisoformat(start_date_str)
            iterations = 4 if repeat else 1
            
            conflicts = []
            for i in range(iterations):
                lesson_time = start_date + timedelta(weeks=i)
                # Проверяем есть ли у этого учителя урок в промежутке ±1 час
                conflict = Lesson.objects.filter(
                    teacher=teacher,
                    status='scheduled',
                    date_time__gte=lesson_time - timedelta(hours=1),
                    date_time__lte=lesson_time + timedelta(hours=1),
                ).exists()
                if conflict:
                    conflicts.append(lesson_time.strftime('%d.%m.%Y %H:%M'))
            
            if conflicts:
                # Передаём ошибку в шаблон
                conflict_str = ', '.join(conflicts)
                # Нужно пересобрать контекст и вернуть с ошибкой
                if request.user.role == 'admin':
                    available_subjects = Subject.objects.all()
                    students = User.objects.filter(role='student')
                else:
                    assigned_ids = TeacherRate.objects.filter(teacher=request.user).values_list('subject_id', flat=True)
                    available_subjects = Subject.objects.filter(
                        models.Q(id__in=assigned_ids) | models.Q(is_universal=True)
                    )
                    student_ids = TeacherStudent.objects.filter(teacher=request.user).values_list('student_id', flat=True)
                    students = User.objects.filter(id__in=student_ids)
                
                return render(request, 'core/calendar.html', {
                    'lessons': lessons,
                    'subjects': available_subjects,
                    'students': students,
                    'teachers': User.objects.filter(role='teacher'),
                    'period_filter': period_filter or 'all',
                    'conflict_error': f'⚠ У учителя уже есть занятие в это время: {conflict_str}',
                })
            
            # Конфликтов нет — создаём
            for i in range(iterations):
                Lesson.objects.create(
                    subject=subject,
                    student=student,
                    teacher=teacher,
                    date_time=start_date + timedelta(weeks=i),
                    status='scheduled'
                )
            return redirect('calendar')

    # --- 4. ОГРАНИЧЕНИЕ ПРЕДМЕТОВ И СТУДЕНТОВ ДЛЯ ВЫБОРА ---
    if request.user.role == 'admin':
        available_subjects = Subject.objects.all()
        students = User.objects.filter(role='student')
    else:
        # Учитель видит только те направления, по которым у него есть ставка
        assigned_ids = TeacherRate.objects.filter(teacher=request.user).values_list('subject_id', flat=True)
        available_subjects = Subject.objects.filter(
            models.Q(id__in=assigned_ids) | models.Q(is_universal=True)
        )
        # Учитель видит только назначенных ему учеников
        student_ids = TeacherStudent.objects.filter(
            teacher=request.user
        ).values_list('student_id', flat=True)
        students = User.objects.filter(id__in=student_ids)

    return render(request, 'core/calendar.html', {
        'lessons': lessons,
        'subjects': available_subjects,
        'students': students,
        'teachers': User.objects.filter(role='teacher'),
        'period_filter': period_filter or 'all',
    })

@login_required
@user_passes_test(is_admin)
def delete_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    
    if lesson.status == 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        lesson.student.balance += price
        lesson.student.save()
        
    lesson.delete()
    
    # Если AJAX — возвращаем JSON, иначе редирект
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'ok'})
    return redirect('calendar')

@login_required
def chat_view(request, user_id):
    # Тот, с кем мы переписываемся
    other_user = get_object_or_404(User, id=user_id)
    
    # Помечаем сообщения как прочитанные
    Message.objects.filter(sender_id=user_id, receiver=request.user, is_read=False).update(is_read=True)
    
    # Получаем сообщения (используем названия полей из твоего ТЗ: text и created_at)
    messages = Message.objects.filter(
        (models.Q(sender=request.user) & models.Q(receiver=other_user)) |
        (models.Q(sender=other_user) & models.Q(receiver=request.user))
    ).order_by('created_at')

    if request.method == 'POST':
        text = request.POST.get('text') # Убедись, что в HTML name="text"
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
    
    if lesson.status == 'done' and status != 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        lesson.student.balance += price
        lesson.student.save()
    elif lesson.status != 'done' and status == 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        lesson.student.balance -= price
        lesson.student.save()

    lesson.status = status
    lesson.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({'status': 'ok'})
    return redirect('calendar')

@login_required
def profile_view(request):
    if request.user.role == 'student':
        return redirect('calendar')

    # --- ЛОГИКА ДЛЯ УЧИТЕЛЯ ---
    teacher_stats = []
    my_salary = Decimal('0.00')
    my_total_lessons = 0

    if request.user.role == 'teacher':
        # Получаем все проведенные уроки конкретного учителя
        # Фильтр по месяцу
        selected_month = request.GET.get('month')  # формат: "2025-03"
        if selected_month:
            try:
                year, month = map(int, selected_month.split('-'))
                done_lessons = Lesson.objects.filter(
                    teacher=request.user, status='done',
                    date_time__year=year, date_time__month=month
                ).select_related('subject', 'student')
            except:
                done_lessons = Lesson.objects.filter(teacher=request.user, status='done').select_related('subject', 'student')
        else:
            done_lessons = Lesson.objects.filter(teacher=request.user, status='done').select_related('subject', 'student')

        my_total_lessons = done_lessons.count()

        summary_data = done_lessons.values(
            'student__username',
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
                'student__username': item['student__username'],
                'subject__name': item['subject__name'],
                'lesson_count': item['lesson_count'],
                'rate': current_rate
            })

    # --- ЛОГИКА ДЛЯ АДМИНА ---
    all_teachers_data = []
    total_revenue = 0
    students_list = None

    if request.user.role == 'admin':
        # Обработка пополнения баланса ученика
        if request.method == 'POST' and 'recharge_balance' in request.POST:
            s_id = request.POST.get('student_id')
            amount = request.POST.get('amount')
            if s_id and amount:
                student_to_pay = get_object_or_404(User, id=s_id)
                student_to_pay.balance += Decimal(amount) 
                student_to_pay.save()
                return redirect('profile')

        # Сбор статистики по всем учителям для админ-панели
        teachers = User.objects.filter(role='teacher')
        for t in teachers:
            t_lessons = Lesson.objects.filter(teacher=t, status='done').select_related('subject')
            t_salary = Decimal('0.00')
            
            # Для каждого урока учителя ищем ставку, назначенную админом
            for lesson in t_lessons:
                r = TeacherRate.objects.filter(teacher=t, subject=lesson.subject).first()
                t_salary += r.rate if r else Decimal('0.00')
            
            all_teachers_data.append({
                'user': t,
                'count': t_lessons.count(),
                'salary': t_salary
            })
        
        # Общая выручка школы (сумма стоимостей всех проведенных занятий)
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
        'selected_month': selected_month if request.user.role == 'teacher' else None,  # НОВОЕ
    })

@login_required
@user_passes_test(is_admin)
def admin_panel_view(request):
    if request.user.role != 'admin':
        return redirect('calendar')

    if 'assign_student' in request.POST:
        student_id = request.POST.get('student_id')
        teacher_ids = request.POST.getlist('teacher_ids')  # getlist — т.к. несколько чекбоксов
        # Сначала удаляем старые связи этого ученика
        TeacherStudent.objects.filter(student_id=student_id).delete()
        # Создаём новые
        for tid in teacher_ids:
            TeacherStudent.objects.create(teacher_id=tid, student_id=student_id)
        return redirect('admin_panel')
    # 1. Создание ученика
    if 'create_student' in request.POST:
        User.objects.create_user(
            username=request.POST.get('username'), 
            password=request.POST.get('password'), 
            role='student'
        )
    
    # 2. Создание учителя
    if 'create_teacher' in request.POST:
        username = request.POST.get('teacher_username')
        password = request.POST.get('teacher_password')
        full_name = request.POST.get('teacher_fullname', '')
        if username and password:
            teacher = User.objects.create_user(
                username=username,
                password=password,
                role='teacher'
            )
            # Сохраняем полное имя если указано
            if full_name:
                teacher.first_name = full_name
                teacher.save()

    # 3. Удаление пользователя
    if 'delete_user' in request.POST:
        User.objects.filter(id=request.POST.get('user_id')).delete()

    # 4. Создание направления
    if 'create_subject' in request.POST:
        Subject.objects.create(
            name=request.POST.get('name'),
            is_universal=request.POST.get('is_universal') == 'on'
        )

    # 5. Удаление направления
    if 'delete_subject' in request.POST:
        Subject.objects.filter(id=request.POST.get('subject_id')).delete()

    # 6. Изменение цены направления
    if 'update_price' in request.POST:
        subject_id = request.POST.get('subject_id')
        new_price = request.POST.get('new_price')
        if subject_id and new_price:
            Subject.objects.filter(id=subject_id).update(
                price_per_lesson=Decimal(new_price)
            )

    # 6. Назначение ставки учителю
    if 'set_rate' in request.POST:
        TeacherRate.objects.update_or_create(
            teacher_id=request.POST.get('teacher_id'),
            subject_id=request.POST.get('subject_id'),
            defaults={'rate': request.POST.get('rate')}
        )

    return render(request, 'core/admin_panel.html', {
        'subjects': Subject.objects.all(),
        'students': User.objects.filter(role='student'),
        'teachers': User.objects.filter(role='teacher'),
        'rates': TeacherRate.objects.all(),
        'teacher_students': TeacherStudent.objects.select_related('teacher', 'student').all(),  # НОВОЕ
    })

@login_required
@user_passes_test(is_teacher_or_admin)
def materials_view(request):
    if request.user.role not in ['teacher', 'admin']:
        return redirect('calendar')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        if title and content:
            Material.objects.create(title=title, content=content, author=request.user)
            return redirect('materials')

    return render(request, 'core/materials.html', {'materials': Material.objects.all().order_by('-created_at')})

@login_required
def messages_list_view(request):
    if request.user.role == 'admin':
        users = User.objects.exclude(id=request.user.id)
    elif request.user.role == 'teacher':
        colleagues = User.objects.filter(role__in=['teacher', 'admin']).exclude(id=request.user.id)
        student_ids = Lesson.objects.filter(teacher=request.user).values_list('student_id', flat=True)
        users = (colleagues | User.objects.filter(id__in=student_ids)).distinct()
    else:
        teacher_ids = Lesson.objects.filter(student=request.user).values_list('teacher_id', flat=True)
        users = User.objects.filter(id__in=teacher_ids).distinct()

    return render(request, 'core/messages_list.html', {'users': users})

@login_required
@user_passes_test(is_teacher_or_admin)
def reschedule_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    if request.user == lesson.teacher or request.user.role == 'admin':
        if request.method == 'POST':
            new_date = request.POST.get('new_date')
            if new_date:
                if not lesson.original_date_time:
                    lesson.original_date_time = lesson.date_time

                old_date = lesson.date_time.strftime('%d.%m.%Y %H:%M')
                lesson.date_time = new_date
                lesson.save()

                # Уведомление ученику
                Notification.objects.create(
                    user=lesson.student,
                    text=f'Занятие "{lesson.subject.name}" перенесено '
                         f'с {old_date} на '
                         f'{lesson.date_time.strftime("%d.%m.%Y %H:%M")}. '
                         f'Учитель: {lesson.teacher.username}'
                )

                # Уведомление админу
                admins = User.objects.filter(role='admin')
                for admin in admins:
                    Notification.objects.create(
                        user=admin,
                        text=f'Учитель {lesson.teacher.username} перенёс занятие '
                             f'"{lesson.subject.name}" '
                             f'(ученик: {lesson.student.username}) '
                             f'с {old_date} на '
                             f'{lesson.date_time.strftime("%d.%m.%Y %H:%M")}'
                    )

    return redirect('calendar')

@login_required
def export_lessons_csv(request):
    if request.user.role != 'admin':
        return HttpResponse("Отказано в доступе", status=403)

    # Создаем HTTP-ответ с типом контента CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="itishnik_report.csv"'
    
    # Чтобы Excel понимал кириллицу
    response.write(u'\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')
    
    # Заголовки столбцов
    writer.writerow(['Дата и время', 'Учитель', 'Ученик', 'Предмет', 'Статус', 'Доход школы'])

    # Берем уроки (с учетом фильтра по учителю, если он есть)
    lessons = Lesson.objects.all().select_related('teacher', 'student', 'subject').order_by('date_time')
    
    teacher_id = request.GET.get('teacher_filter')
    if teacher_id:
        lessons = lessons.filter(teacher_id=teacher_id)

    # Записываем данные
    for lesson in lessons:
        writer.writerow([
            lesson.date_time.strftime('%d.%m.%Y %H:%M'),
            lesson.teacher.username,
            lesson.student.username,
            lesson.subject.name,
            lesson.get_status_display(),
            lesson.subject.price_per_lesson if lesson.status == 'done' else 0
        ])

    return response

@login_required
def reports_page(request):
    if request.user.role != 'admin':
        return redirect('calendar')

    # Фильтр по датам
    period = request.GET.get('period', 'month')
    now = timezone.now()
    
    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:  # month по умолчанию
        start_date = now - timedelta(days=30)

    # Получаем все завершенные уроки за период
    lessons = Lesson.objects.filter(
        status='done', 
        date_time__gte=start_date
    ).select_related('subject', 'teacher')

    total_revenue = 0  # Сколько заплатили ученики
    total_salaries = 0 # Сколько должны учителям
    
    report_data = []

    for lesson in lessons:
        revenue = lesson.subject.price_per_lesson
        # Ищем ставку учителя
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        salary = rate_obj.rate if rate_obj else 0
        
        total_revenue += revenue
        total_salaries += salary
        
        report_data.append({
            'date': lesson.date_time,
            'teacher': lesson.teacher.username,
            'subject': lesson.subject.name,
            'revenue': revenue,
            'salary': salary,
            'profit': revenue - salary
        })

    context = {
        'report_data': report_data,
        'total_revenue': total_revenue,
        'total_salaries': total_salaries,
        'net_profit': total_revenue - total_salaries,
        'period': period
    }
    return render(request, 'core/reports.html', context)

@login_required
def export_detailed_report(request):
    if request.user.role != 'admin':
        return HttpResponse("Доступ запрещен", status=403)

    # Логика фильтрации такая же, как на странице отчетов
    period = request.GET.get('period', 'month')
    now = timezone.now()
    
    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:
        start_date = now - timedelta(days=30)

    # Создаем объект ответа CSV
    response = HttpResponse(content_type='text/csv')
    # Название файла будет зависеть от периода
    response['Content-Disposition'] = f'attachment; filename="itishnik_financial_report_{period}.csv"'
    
    # Добавляем BOM для корректного отображения кириллицы в Excel
    response.write(u'\ufeff'.encode('utf8'))
    
    writer = csv.writer(response, delimiter=';')
    
    # Заголовки (как в твоем новом крутом отчете)
    writer.writerow(['Дата и время', 'Учитель', 'Ученик', 'Предмет', 'Выручка (руб)', 'Зарплата (руб)', 'Прибыль (руб)'])

    lessons = Lesson.objects.filter(
        status='done', 
        date_time__gte=start_date
    ).select_related('subject', 'teacher', 'student').order_by('date_time')

    total_rev = 0
    total_sal = 0

    for lesson in lessons:
        revenue = lesson.subject.price_per_lesson
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        salary = rate_obj.rate if rate_obj else 0
        profit = revenue - salary
        
        total_rev += revenue
        total_sal += salary

        writer.writerow([
            lesson.date_time.strftime('%d.%m.%Y %H:%M'),
            lesson.teacher.username,
            lesson.student.username,
            lesson.subject.name,
            revenue,
            salary,
            profit
        ])

    # В конце отчета добавим итоговую строку
    writer.writerow([]) # Пустая строка для красоты
    writer.writerow(['ИТОГО ЗА ПЕРИОД', '', '', '', total_rev, total_sal, total_rev - total_sal])

    return response

@login_required
@user_passes_test(is_admin)
def dashboard_view(request):
    from django.db.models.functions import TruncMonth, TruncWeek
    import json

    # --- Уроки по месяцам (последние 6 месяцев) ---
    lessons_by_month = (
        Lesson.objects
        .filter(status='done')
        .annotate(month=TruncMonth('date_time'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )[:6]

    # --- Выручка по месяцам ---
    revenue_by_month = {}
    for lesson in Lesson.objects.filter(status='done').select_related('subject'):
        key = lesson.date_time.strftime('%Y-%m')
        revenue_by_month[key] = revenue_by_month.get(key, 0) + float(lesson.subject.price_per_lesson)

    # --- Топ учителей по кол-ву уроков ---
    top_teachers = (
        Lesson.objects
        .filter(status='done')
        .values('teacher__username')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    # --- Распределение по предметам ---
    lessons_by_subject = (
        Lesson.objects
        .filter(status='done')
        .values('subject__name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # --- Статусы всех уроков ---
    status_counts = {
        'done': Lesson.objects.filter(status='done').count(),
        'scheduled': Lesson.objects.filter(status='scheduled').count(),
        'canceled': Lesson.objects.filter(status='canceled').count(),
    }

    # --- Общие цифры ---
    total_students = User.objects.filter(role='student').count()
    total_teachers = User.objects.filter(role='teacher').count()
    total_revenue = sum(
        float(l.subject.price_per_lesson)
        for l in Lesson.objects.filter(status='done').select_related('subject')
    )
    total_lessons = Lesson.objects.filter(status='done').count()

    # Формируем данные для графиков
    months_labels = [item['month'].strftime('%b %Y') for item in lessons_by_month]
    months_data = [item['count'] for item in lessons_by_month]

    revenue_labels = sorted(revenue_by_month.keys())[-6:]
    revenue_data = [revenue_by_month[k] for k in revenue_labels]

    teacher_labels = [item['teacher__username'] for item in top_teachers]
    teacher_data = [item['count'] for item in top_teachers]

    subject_labels = [item['subject__name'] for item in lessons_by_subject]
    subject_data = [item['count'] for item in lessons_by_subject]

    return render(request, 'core/dashboard.html', {
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_revenue': total_revenue,
        'total_lessons': total_lessons,
        'status_counts': status_counts,
        # JSON для Chart.js
        'months_labels': json.dumps(months_labels, ensure_ascii=False),
        'months_data': json.dumps(months_data),
        'revenue_labels': json.dumps(revenue_labels),
        'revenue_data': json.dumps(revenue_data),
        'teacher_labels': json.dumps(teacher_labels, ensure_ascii=False),
        'teacher_data': json.dumps(teacher_data),
        'subject_labels': json.dumps(subject_labels, ensure_ascii=False),
        'subject_data': json.dumps(subject_data),
    })

@login_required
def notifications_view(request):
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-created_at')[:50]
    
    # Помечаем все как прочитанные при открытии страницы
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    return render(request, 'core/notifications.html', {
        'notifications': notifications
    })

@login_required
def mark_notification_read(request, notif_id):
    Notification.objects.filter(id=notif_id, user=request.user).update(is_read=True)
    return redirect('notifications')