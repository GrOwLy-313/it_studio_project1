from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User, Message, Lesson, Subject, Material,
    Homework, Notification, TeacherRate, TeacherStudent, UserNote
)


@admin.register(User)
class MyUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'balance', 'is_finished')
    list_filter = ('role', 'is_finished')
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': ('role', 'balance', 'is_finished')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация', {'fields': ('role',)}),
    )


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('subject', 'teacher', 'student', 'date_time', 'status')
    list_filter = ('status', 'subject')
    search_fields = ('teacher__username', 'student__username')
    date_hierarchy = 'date_time'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'created_at', 'is_read')
    list_filter = ('is_read',)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_per_lesson', 'is_universal', 'color')
    list_filter = ('is_universal',)


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_at')
    search_fields = ('title', 'author__username')


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ('title', 'teacher', 'student', 'subject', 'status', 'created_at')
    list_filter = ('status', 'subject')
    search_fields = ('title', 'teacher__username', 'student__username')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'text', 'is_read', 'created_at')
    list_filter = ('is_read',)


@admin.register(TeacherRate)
class TeacherRateAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'subject', 'rate')


@admin.register(TeacherStudent)
class TeacherStudentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'student')


@admin.register(UserNote)
class UserNoteAdmin(admin.ModelAdmin):
    list_display = ('author', 'target', 'updated_at')