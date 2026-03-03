from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Lesson, Message, User, Material, Subject, TeacherRate
from django.db import models
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import PermissionDenied

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
    # --- АВТОМАТИЧЕСКАЯ ПРОВЕРКА ПРОШЕДШИХ УРОКОВ ---
    now = timezone.now()
    # Ищем уроки, время которых меньше текущего, а статус всё еще "Запланирован"
    past_lessons = Lesson.objects.filter(date_time__lt=now, status='scheduled')
    
    for lesson in past_lessons:
        # Ищем ставку учителя за этот предмет
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        
        # Списываем баланс и меняем статус
        lesson.status = 'done'
        lesson.student.balance -= price
        lesson.student.save()
        lesson.save()

    # --- ОТОБРАЖЕНИЕ (Твой оригинальный код) ---
    if request.user.role == 'student':
        lessons = Lesson.objects.filter(student=request.user).order_by('date_time')
    elif request.user.role == 'teacher':
        lessons = Lesson.objects.filter(teacher=request.user).order_by('date_time')
    else:  # Для админа показываем вообще все уроки
        lessons = Lesson.objects.all().order_by('date_time')

    # Обработка создания нового занятия
    if request.method == 'POST' and request.user.role in ['teacher', 'admin']:
        subject_id = request.POST.get('subject')
        student_id = request.POST.get('student')
        teacher_id = request.POST.get('teacher')
        start_date = request.POST.get('date_time')
        repeat = request.POST.get('repeat') == 'on'

        if subject_id and student_id and start_date:
            subject = Subject.objects.get(id=subject_id)
            student = User.objects.get(id=student_id)
            
            if request.user.role == 'admin':
                teacher = User.objects.get(id=teacher_id)
            else:
                teacher = request.user

            current_date = timezone.datetime.fromisoformat(start_date)
            iterations = 4 if repeat else 1
            
            for i in range(iterations):
                Lesson.objects.create(
                    subject=subject,
                    student=student,
                    teacher=teacher,
                    date_time=current_date + timedelta(weeks=i),
                    status='scheduled'
                )
            return redirect('calendar')

    return render(request, 'core/calendar.html', {
        'lessons': lessons,
        'subjects': Subject.objects.all(),
        'students': User.objects.filter(role='student'),
        'teachers': User.objects.filter(role='teacher'),
    })

@login_required
@user_passes_test(is_admin) # Учителя больше не могут удалять
def delete_lesson(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    
    # Если админ удаляет уже проведенный урок — возвращаем деньги ученику
    if lesson.status == 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        
        lesson.student.balance += price
        lesson.student.save()
        
    lesson.delete()
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
    
    # 1. Если статус меняется С "Проведено" на любой другой — возвращаем деньги
    if lesson.status == 'done' and status != 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        lesson.student.balance += price
        lesson.student.save()
        
    # 2. Если статус меняется НА "Проведено" с любого другого — списываем деньги
    elif lesson.status != 'done' and status == 'done':
        rate_obj = TeacherRate.objects.filter(teacher=lesson.teacher, subject=lesson.subject).first()
        price = rate_obj.rate if rate_obj else lesson.subject.price_per_lesson
        lesson.student.balance -= price
        lesson.student.save()

    # Сохраняем новый статус
    lesson.status = status
    lesson.save()
    return redirect('calendar')

@login_required
def profile_view(request):
    if request.user.role == 'student':
        return redirect('calendar')

    # --- ЛОГИКА ДЛЯ УЧИТЕЛЯ ---
    # Группируем выполненные уроки по ученику и предмету
    teacher_stats = Lesson.objects.filter(teacher=request.user, status='done') \
        .values('student__username', 'subject__name') \
        .annotate(lesson_count=Count('id'))

    my_count = Lesson.objects.filter(teacher=request.user, status='done').count()
    my_salary = my_count * getattr(request.user, 'salary_per_lesson', 0)

    # --- ЛОГИКА ДЛЯ АДМИНА ---
    all_teachers_data = []
    total_revenue = 0
    students = None

    if request.user.role == 'admin':
        if request.method == 'POST' and request.user.role == 'admin' and 'recharge_balance' in request.POST:
            s_id = request.POST.get('student_id')
            amount = request.POST.get('amount')
            if s_id and amount:
                student_to_pay = get_object_or_404(User, id=s_id)
                student_to_pay.balance += Decimal(amount) 
                student_to_pay.save()
                return redirect('profile')
            student_to_pay = User.objects.get(id=s_id)
            student_to_pay.balance += amount
            student_to_pay.save()
            return redirect('profile')

        teachers = User.objects.filter(role='teacher')
        for t in teachers:
            count = Lesson.objects.filter(teacher=t, status='done').count()
            all_teachers_data.append({
                'user': t,
                'count': count,
                'salary': count * getattr(t, 'salary_per_lesson', 0)
            })
        
        done_lessons = Lesson.objects.filter(status='done')
        for lesson in done_lessons:
            total_revenue += lesson.subject.price_per_lesson
            
        students = User.objects.filter(role='student')

    return render(request, 'core/profile.html', {
        'my_count': my_count,
        'my_salary': my_salary,
        'teacher_stats': teacher_stats, # Новая статистика
        'all_teachers': all_teachers_data,
        'total_lessons': Lesson.objects.filter(status='done').count(),
        'total_revenue': total_revenue,
        'students': students,
    })

@login_required
@user_passes_test(is_admin)
def admin_panel_view(request):
    if request.user.role != 'admin':
        return redirect('calendar')

    # 1. Создание ученика
    if 'create_student' in request.POST:
        User.objects.create_user(
            username=request.POST.get('username'), 
            password=request.POST.get('password'), 
            role='student'
        )
    
    # 2. Удаление пользователя
    if 'delete_user' in request.POST:
        User.objects.filter(id=request.POST.get('user_id')).delete()

    # 3. Создание направления
    if 'create_subject' in request.POST:
        Subject.objects.create(name=request.POST.get('name'))

    # 4. Удаление направления
    if 'delete_subject' in request.POST:
        Subject.objects.filter(id=request.POST.get('subject_id')).delete()

    # 5. Назначение ставки учителю
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
        'rates': TeacherRate.objects.all()
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
    
    # Только учитель этого урока или админ могут переносить
    if request.user == lesson.teacher or request.user.role == 'admin':
        if request.method == 'POST':
            new_date = request.POST.get('new_date')
            if new_date:
                # Если это первый перенос, сохраняем оригинал
                if not lesson.original_date_time:
                    lesson.original_date_time = lesson.date_time
                
                lesson.date_time = new_date
                lesson.save()
    return redirect('calendar')