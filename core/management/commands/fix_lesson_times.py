from django.core.management.base import BaseCommand
from django.db.models import F, ExpressionWrapper, DateTimeField
from datetime import timedelta
from core.models import Lesson

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        count = Lesson.objects.count()
        self.stdout.write(f'Уроков найдено: {count}')
        
        Lesson.objects.update(
            date_time=ExpressionWrapper(
                F('date_time') - timedelta(hours=3),
                output_field=DateTimeField()
            )
        )
        Lesson.objects.filter(original_date_time__isnull=False).update(
            original_date_time=ExpressionWrapper(
                F('original_date_time') - timedelta(hours=3),
                output_field=DateTimeField()
            )
        )
        self.stdout.write('✅ Готово — вычли 3 часа из всех уроков')
```

Не забудь создать пустые `__init__.py` если их нет:
- `core/management/__init__.py`
- `core/management/commands/__init__.py`

Затем в `render.yaml` или в настройках Render в поле **Build Command** временно добавь в конец:
```
&& python manage.py fix_lesson_times