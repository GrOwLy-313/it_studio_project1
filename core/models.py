from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Администратор'),
        ('teacher', 'Учитель'),
        ('student', 'Ученик'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    salary_per_lesson = models.DecimalField(max_digits=10, decimal_places=2, default=500.00)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # БАГ 4: приватная подпись — видна только тому, кто её добавил (через отдельную модель)
    # first_name уже есть в AbstractUser — используем его как ФИО

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def get_display_name(self):
        """Возвращает ФИО если задано, иначе логин."""
        return self.first_name.strip() if self.first_name and self.first_name.strip() else self.username


class UserNote(models.Model):
    """
    Приватная подпись/описание пользователя.
    author — кто добавил подпись (учитель или админ)
    target — о ком подпись (ученик, другой учитель и т.д.)
    Видна только автору.
    """
    author = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='my_notes'
    )
    target = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='notes_about_me'
    )
    text = models.TextField(verbose_name='Подпись/описание')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('author', 'target')

    def __str__(self):
        return f"{self.author.username} → {self.target.username}: {self.text[:40]}"


class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender} -> {self.receiver}: {self.text[:20]}"


class Material(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='materials/', null=True, blank=True)

    def __str__(self):
        return self.title


class Subject(models.Model):
    name = models.CharField(max_length=100)
    price_per_lesson = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_universal = models.BooleanField(default=False)
    color = models.CharField(max_length=7, default='#3b82f6')

    def __str__(self):
        return self.name


class Lesson(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Запланирован'),
        ('done', 'Проведен'),
        ('canceled', 'Отменен'),
    ]
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="Направление")
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teacher_lessons')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_lessons')
    date_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    original_date_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.subject.name} - {self.student.username}"


class TeacherRate(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rates')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    rate = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Оплата за этот предмет")

    def __str__(self):
        return f"{self.teacher.username} - {self.subject.name} ({self.rate}₽)"


class TeacherStudent(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_students')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_teachers')

    class Meta:
        unique_together = ('teacher', 'student')

    def __str__(self):
        return f"{self.teacher.username} → {self.student.username}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    text = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"→ {self.user.username}: {self.text[:40]}"


class Homework(models.Model):
    STATUS_CHOICES = [
        ('assigned', 'Назначено'),
        ('done', 'Выполнено'),
        ('checked', 'Проверено'),
    ]
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='homeworks', null=True, blank=True)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_homeworks')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_homeworks')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    due_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    created_at = models.DateTimeField(auto_now_add=True)
    teacher_comment = models.TextField(blank=True)

    def __str__(self):
        return f'{self.title} → {self.student.username}'