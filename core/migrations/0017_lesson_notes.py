from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_remove_user_salary_per_lesson'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='notes',
            field=models.TextField(blank=True, default='', verbose_name='Заметка к занятию'),
        ),
    ]
