from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Profile


class AccountForm(UserCreationForm):
    """Création d'un compte par l'administration. Aucun champ ne donne l'accès technique ou super-admin."""
    role = forms.ChoiceField(label="Rôle", initial="STUDENT")
    student_number = forms.CharField(label="Matricule", max_length=40, required=False)
    study_level = forms.ChoiceField(label="Niveau d'études", required=False,
                                    choices=[("", "Sélectionner…"), *Profile.LEVEL_CHOICES])

    class Meta(UserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, creator, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = self.fields["last_name"].required = True
        # Seul le super-administrateur peut nommer un administrateur.
        self.fields["role"].choices = [c for c in Profile.ROLE_CHOICES if c[0] != "ADMIN" or creator.is_superuser]

    def clean(self):
        data = super().clean()
        if data.get("role") == "STUDENT":
            number = data.get("student_number")
            if not number:
                self.add_error("student_number", "Le matricule est obligatoire pour un étudiant.")
            # ponytail: unicité vérifiée ici comme à l'inscription ; contrainte en base si des doublons apparaissent.
            elif Profile.objects.filter(student_number=number).exists():
                self.add_error("student_number", "Ce matricule est déjà associé à un compte.")
            if not data.get("study_level"):
                self.add_error("study_level", "Le niveau est obligatoire pour un étudiant.")
        return data

    def save(self, commit=True):
        user = super().save(commit)
        profile = user.profile
        profile.role = self.cleaned_data["role"]
        if profile.role == "STUDENT":
            profile.student_number = self.cleaned_data["student_number"]
            profile.study_level = self.cleaned_data["study_level"]
        profile.save()
        return user
