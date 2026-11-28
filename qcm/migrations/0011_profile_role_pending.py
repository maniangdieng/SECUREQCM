from django.db import migrations, models


class Migration(migrations.Migration):
    """Choix supplémentaire seulement : aucune colonne ni donnée modifiée."""

    dependencies = [("qcm", "0010_exam_window_results")]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="role",
            field=models.CharField(choices=[("ADMIN", "Administrateur"), ("TEACHER", "Enseignant"), ("STUDENT", "Étudiant"),
                                            ("PENDING", "Enseignant en attente")], default="STUDENT", max_length=12),
        ),
    ]
