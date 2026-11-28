from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Profile


class StudentFieldsForm(forms.Form):
    """Matricule et niveau : obligatoires pour un étudiant, matricule unique."""
    student_number = forms.CharField(label="Matricule", max_length=40, required=False)
    study_level = forms.ChoiceField(label="Niveau d'études", required=False,
                                    choices=[("", "Sélectionner…"), *Profile.LEVEL_CHOICES])
    number_taken = "Ce matricule est déjà associé à un compte."

    def check_student_fields(self, data, user=None):
        number = data.get("student_number")
        # Une erreur déjà posée sur le champ (trop long, niveau inconnu) suffit.
        if "student_number" not in self.errors and not self.fields["student_number"].disabled:
            if not number:
                self.add_error("student_number", "Le matricule est obligatoire pour un étudiant.")
            # Unicité vérifiée ici comme à l'inscription ; contrainte en base si des doublons apparaissent.
            elif Profile.objects.filter(student_number=number).exclude(user=user).exists():
                self.add_error("student_number", self.number_taken)
        if "study_level" not in self.errors and not data.get("study_level"):
            self.add_error("study_level", "Le niveau est obligatoire pour un étudiant.")


class AccountForm(StudentFieldsForm, UserCreationForm):
    """Création d'un compte par l'administration. Aucun champ ne donne l'accès technique ou super-admin."""
    role = forms.ChoiceField(label="Rôle", initial="STUDENT")
    field_order = ["username", "first_name", "last_name", "email", "password1", "password2",
                   "role", "student_number", "study_level"]

    class Meta(UserCreationForm.Meta):
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, creator, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = self.fields["last_name"].required = True
        # Seul le super-administrateur peut nommer un administrateur.
        self.fields["role"].choices = [c for c in Profile.ROLE_CHOICES
                                       if c[0] != "PENDING" and (c[0] != "ADMIN" or creator.is_superuser)]

    def clean(self):
        data = super().clean()
        if data.get("role") == "STUDENT":
            self.check_student_fields(data)
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


class GoogleSignupForm(StudentFieldsForm):
    """Première connexion avec Google. L'adresse e-mail vient de Google et n'est pas un champ."""
    account_type = forms.ChoiceField(choices=[("STUDENT", "Étudiant"), ("TEACHER", "Enseignant")])
    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    number_taken = ("Ce matricule est déjà associé à un compte. Connectez-vous avec votre identifiant "
                    "et votre mot de passe, puis liez Google depuis « Mon profil ».")

    def clean(self):
        data = super().clean()
        if data.get("account_type") == "STUDENT":
            self.check_student_fields(data)
        else:
            data["student_number"] = data["study_level"] = ""
        return data


class StudentCompletionForm(StudentFieldsForm):
    """Étudiant connecté avec Google dont le matricule ou le niveau manque."""

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        # Ce qui est déjà renseigné identifie l'étudiant dans les résultats : il ne se change pas ici.
        for name in ("student_number", "study_level"):
            if value := getattr(user.profile, name):
                self.fields[name].disabled = True
                self.initial[name] = value

    def clean(self):
        data = super().clean()
        self.check_student_fields(data, user=self.user)
        return data
