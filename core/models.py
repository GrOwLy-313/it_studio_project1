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

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender} -> {self.receiver}: {self.text[:20]}"
    
class Material(models.Model):
    title = models.CharField(max_length=200, verbose_name="Название материала")
    content = models.TextField(verbose_name="Описание или ссылка")
    author = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Кто добавил")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
    
class Subject(models.Model):
    name = models.CharField(max_length=100)
    price_per_lesson = models.DecimalField(max_digits=10, decimal_places=2, default=500.00)
    is_universal = models.BooleanField(default=False, verbose_name="Доступно всем учителям")

    def __str__(self):
        return self.name

# Обновляем модель Lesson
class Lesson(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Запланирован'),
        ('done', 'Проведен'),
        ('canceled', 'Отменен'),
    ]
    # Теперь это связь, а не просто текст
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
        unique_together = ('teacher', 'student')  # нет дублей

    def __str__(self):
        return f"{self.teacher.username} → {self.student.username}"

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    text = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"→ {self.user.username}: {self.text[:40]}"