from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("qcm", "0003_exam_level_targeting"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="exam", name="is_archived",
            field=models.BooleanField(default=False, verbose_name="Archivé"),
        ),
        migrations.AddField(
            model_name="exam", name="archived_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Date d’archivage"),
        ),
        migrations.AddField(
            model_name="exam", name="archived_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="archived_exams", to=settings.AUTH_USER_MODEL, verbose_name="Archivé par"),
        ),
    ]
