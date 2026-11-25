from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("qcm", "0002_exam_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="study_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("L1", "Licence 1"),
                    ("L2", "Licence 2"),
                    ("L3", "Licence 3"),
                    ("M1", "Master 1"),
                    ("M2", "Master 2"),
                    ("DOCTORAT", "Doctorat"),
                    ("AUTRE", "Autre"),
                ],
                default="",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="exam",
            name="target_level",
            field=models.CharField(
                blank=True,
                choices=[
                    ("L1", "Licence 1"),
                    ("L2", "Licence 2"),
                    ("L3", "Licence 3"),
                    ("M1", "Master 1"),
                    ("M2", "Master 2"),
                    ("DOCTORAT", "Doctorat"),
                    ("AUTRE", "Autre"),
                ],
                default="",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="exam",
            name="audience_mode",
            field=models.CharField(
                choices=[
                    ("LEVEL", "Tous les étudiants du niveau"),
                    ("LIST", "Étudiants sélectionnés / liste CSV"),
                ],
                default="LEVEL",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="examenrollment",
            name="code_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="examenrollment",
            name="source",
            field=models.CharField(
                choices=[
                    ("LIST", "Liste enseignant"),
                    ("CODE", "Code examen"),
                    ("LEVEL", "Niveau d'études"),
                ],
                default="LIST",
                max_length=12,
            ),
        ),
    ]
