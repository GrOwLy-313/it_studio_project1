from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Message

# Настраиваем отображение пользователей в админке
class MyUserAdmin(UserAdmin):
    # Добавляем поле 'role' в список отображаемых полей
    list_display = ('username', 'email', 'role', 'is_staff')
    # Добавляем возможность редактировать роль в самой карточке пользователя
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация', {'fields': ('role',)}),
    )

admin.site.register(User, MyUserAdmin)
from .models import Lesson # добавь Lesson в импорт сверху, если его нет
admin.site.register(Lesson)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'created_at')