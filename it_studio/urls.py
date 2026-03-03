from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from core import views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.calendar_view, name='calendar'),
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('chat/<int:user_id>/', views.chat_view, name='chat'),
    path('lesson/<int:lesson_id>/status/<str:status>/', views.update_lesson_status, name='update_status'),
    path('lesson/delete/<int:lesson_id>/', views.delete_lesson, name='delete_lesson'), # НОВОЕ
    path('profile/', views.profile_view, name='profile'),
    path('materials/', views.materials_view, name='materials'),
    path('messages/', views.messages_list_view, name='messages_list'),
    path('admin-panel/', views.admin_panel_view, name='admin_panel'),
    path('lesson/reschedule/<int:lesson_id>/', views.reschedule_lesson, name='reschedule_lesson'),
    path('export/lessons/', views.export_lessons_csv, name='export_lessons_csv'),
    path('reports/', views.reports_page, name='reports_page'),
    path('reports/export/', views.export_detailed_report, name='export_detailed_report'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/read/<int:notif_id>/', views.mark_notification_read, name='notif_read'),
    path('homework/', views.homework_view, name='homework'),
    path('homework/create/', views.create_homework, name='create_homework'),
    path('homework/<int:hw_id>/done/', views.mark_homework_done, name='homework_done'),
    path('homework/<int:hw_id>/check/', views.check_homework, name='homework_check'),
    path('homework/<int:hw_id>/delete/', views.delete_homework, name='homework_delete'),
    path('homework/<int:hw_id>/status/<str:status>/', views.update_homework_status, name='homework_status'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)