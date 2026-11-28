from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render, redirect
from django.urls import reverse

from ..models import Profile
from ..permissions import role
from ..services import audit, enroll_student_in_level_exams

DASHBOARD_BY_ROLE = {"ADMIN": "admin_dashboard", "TEACHER": "teacher_dashboard", "STUDENT": "student_dashboard",
                     "PENDING": "teacher_pending"}


class EmailForm(forms.ModelForm):
    """Seul l'e-mail est modifiable : nom et matricule identifient l'étudiant dans les résultats.
    Le mot de passe est redemandé, car cette adresse permet de réinitialiser le compte."""
    password = forms.CharField(label="Mot de passe actuel", strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    class Meta:
        model = User
        fields = ["email"]
        labels = {"email": "Adresse e-mail"}

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.instance.check_password(password):
            raise ValidationError("Mot de passe actuel incorrect.")
        return password


class UnifiedLoginView(LoginView):
    """Page de connexion unique avec redirection selon le rôle applicatif."""
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        # Ignore les URL de redirection fournies dans ?next= : chaque profil
        # arrive directement dans son propre espace.
        return reverse(DASHBOARD_BY_ROLE.get(role(self.request.user), "student_dashboard"))

    def get_default_redirect_url(self):
        return self.get_success_url()


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(DASHBOARD_BY_ROLE.get(role(request.user), "student_dashboard"))


def student_register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form_data = {"account_type": "TEACHER" if request.GET.get("type") == "teacher" else "STUDENT"}
    if request.method == "POST":
        # Comme Google Classroom : on choisit « Étudiant » ou « Enseignant » à l'inscription.
        # Un enseignant attend la validation de l'administration avant de créer des classes.
        is_teacher = request.POST.get("account_type") == "TEACHER"
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        student_number = request.POST.get("student_number", "").strip()
        study_level = request.POST.get("study_level", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        if is_teacher:
            student_number = study_level = ""
        form_data = {"first_name": first_name, "last_name": last_name, "email": email, "username": username,
                     "student_number": student_number, "study_level": study_level,
                     "account_type": "TEACHER" if is_teacher else "STUDENT"}
        errors = []
        required = [first_name, last_name, username, password] + ([email] if is_teacher else [student_number, study_level])
        if not all(required):
            errors.append("Tous les champs obligatoires doivent être remplis.")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append("Adresse e-mail invalide.")
        if not is_teacher and study_level not in dict(Profile.LEVEL_CHOICES):
            errors.append("Sélectionnez un niveau d'études valide.")
        if User.objects.filter(username__iexact=username).exists():
            errors.append("Cet identifiant est déjà utilisé.")
        if student_number and Profile.objects.filter(student_number=student_number).exists():
            errors.append("Ce matricule est déjà associé à un compte.")
        if password != password2:
            errors.append("Les deux mots de passe ne correspondent pas.")
        try:
            validate_password(password, user=User(username=username, first_name=first_name, last_name=last_name, email=email))
        except ValidationError as exc:
            errors.extend(exc.messages)
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            user = User.objects.create_user(username=username, password=password, email=email,
                                            first_name=first_name, last_name=last_name)
            profile = user.profile
            profile.role = "PENDING" if is_teacher else "STUDENT"
            profile.student_number = student_number
            profile.study_level = study_level
            profile.save()
            # Plusieurs backends sont configurés (django-axes) : préciser lequel a authentifié.
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if is_teacher:
                audit(user, "Demande de compte enseignant", user)
                return redirect("teacher_pending")
            # Les examens publiés pour ce niveau apparaissent automatiquement au nouvel étudiant.
            enroll_student_in_level_exams(user)
            messages.success(request, "Votre compte étudiant a été créé. Rejoignez maintenant vos classes avec le code donné par votre enseignant.")
            return redirect("student_dashboard")
    return render(request, "registration/register.html", {"levels": Profile.LEVEL_CHOICES, "form_data": form_data})


@login_required
def teacher_pending(request):
    """Page d'attente d'un enseignant inscrit, tant que l'administration n'a pas validé sa demande."""
    if role(request.user) != "PENDING":
        return redirect("home")
    return render(request, "registration/teacher_pending.html")


@login_required
def profile(request):
    form = EmailForm(request.POST or None, instance=User.objects.get(pk=request.user.pk))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre adresse e-mail a été enregistrée.")
        return redirect("profile")
    return render(request, "registration/profile.html", {"form": form})
