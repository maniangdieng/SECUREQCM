from django.db import migrations, models
from django.utils import timezone


def interrupt_older_duplicates(apps, schema_editor):
    """La contrainte exige une seule tentative en cours : les plus anciennes sont conservées, interrompues."""
    Attempt = apps.get_model("qcm", "Attempt")
    seen = set()
    for attempt in Attempt.objects.filter(status="IN_PROGRESS").order_by("-started_at", "-pk"):
        key = (attempt.exam_id, attempt.student_id)
        if key in seen:
            Attempt.objects.filter(pk=attempt.pk).update(status="INTERRUPTED", ended_at=timezone.now())
        seen.add(key)


class Migration(migrations.Migration):

    dependencies = [("qcm", "0006_exam_teacher_protect")]

    operations = [
        migrations.RunPython(interrupt_older_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="attempt",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "IN_PROGRESS")), fields=("exam", "student"),
                                               name="uniq_attempt_in_progress"),
        ),
    ]
