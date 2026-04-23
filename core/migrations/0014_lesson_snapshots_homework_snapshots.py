# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_alter_homework_student_alter_homework_teacher_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='lesson',
            name='teacher_name_snapshot',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='lesson',
            name='student_name_snapshot',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='homework',
            name='teacher_name_snapshot',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='homework',
            name='student_name_snapshot',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
