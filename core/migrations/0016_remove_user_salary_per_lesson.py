from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_user_is_finished'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='salary_per_lesson',
        ),
    ]
