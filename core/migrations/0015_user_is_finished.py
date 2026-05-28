from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_lesson_snapshots_homework_snapshots'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_finished',
            field=models.BooleanField(default=False, verbose_name='Обучение завершено'),
        ),
    ]
