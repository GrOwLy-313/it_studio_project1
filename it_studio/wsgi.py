import os
import django
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'it_studio.settings')

django.setup()

# Применяем миграции автоматически при каждом старте
from django.core.management import call_command
call_command('migrate', '--run-syncdb')

application = get_wsgi_application()