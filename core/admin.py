from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Message, Lesson

class MyUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Дополнительная информация', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Дополнительная информация', {'fields': ('role',)}),
    )

admin.site.register(User, MyUserAdmin)
admin.site.register(Lesson)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'created_at')