import qcm.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def populate_exam_access_codes(apps, schema_editor):
    Exam = apps.get_model("qcm", "Exam")
    db_alias = schema_editor.connection.alias
    used_codes = set(
        Exam.objects.using(db_alias)
        .exclude(access_code="")
        .values_list("access_code", flat=True)
    )
    for exam in Exam.objects.using(db_alias).filter(access_code="").iterator():
        code = qcm.models.generate_exam_code()
        while code in used_codes:
            code = qcm.models.generate_exam_code()
        exam.access_code = code
        exam.save(update_fields=["access_code"], using=db_alias)
        used_codes.add(code)


class Migration(migrations.Migration):
    dependencies = [
        ("qcm", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="access_code",
            field=models.CharField(default="", max_length=12),
        ),
        migrations.RunPython(populate_exam_access_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="exam",
            name="access_code",
            field=models.CharField(default=qcm.models.generate_exam_code, max_length=12, unique=True),
        ),
        migrations.CreateModel(
            name="ExamEnrollment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enrolled_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.CharField(choices=[("LIST", "Liste enseignant"), ("CODE", "Code examen")], default="LIST", max_length=12)),
                ("exam", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="enrollments", to="qcm.exam")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="exam_enrollments", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="examenrollment",
            constraint=models.UniqueConstraint(fields=("exam", "student"), name="unique_exam_student_enrollment"),
        ),
    ]
