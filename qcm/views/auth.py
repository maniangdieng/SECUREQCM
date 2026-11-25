from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.urls import reverse

from ..models import Profile, Exam, ExamEnrollment
from ..permissions import role

DASHBOARD_BY_ROLE = {"ADMIN": "admin_dashboard", "TEACHER": "teacher_dashboard", "STUDENT": "student_dashboard"}


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
    form_data = {}
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip()
        student_number = request.POST.get("student_number", "").strip()
        study_level = request.POST.get("study_level", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        form_data = {"first_name": first_name, "last_name": last_name, "email": email,
                     "student_number": student_number, "study_level": study_level, "username": username}
        errors = []
        if not all([first_name, last_name, student_number, study_level, username, password]):
            errors.append("Tous les champs obligatoires doivent être remplis.")
        if study_level not in dict(Profile.LEVEL_CHOICES):
            errors.append("Sélectionnez un niveau d'études valide.")
        if User.objects.filter(username__iexact=username).exists():
            errors.append("Cet identifiant est déjà utilisé.")
        if Profile.objects.filter(student_number=student_number).exclude(student_number="").exists():
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
            profile = Profile.objects.get(user=user)
            profile.role = "STUDENT"
            profile.student_number = student_number
            profile.study_level = study_level
            profile.save()
            # Les examens publiés pour ce niveau apparaissent automatiquement au nouvel étudiant.
            for exam in Exam.objects.filter(published=True, is_archived=False, audience_mode="LEVEL", target_level=study_level):
                ExamEnrollment.objects.get_or_create(exam=exam, student=user, defaults={"source": "LEVEL"})
            login(request, user)
            messages.success(request, "Votre compte étudiant a été créé. Rejoignez maintenant vos classes avec le code donné par votre enseignant.")
            return redirect("student_dashboard")
    return render(request, "registration/register.html", {"levels": Profile.LEVEL_CHOICES, "form_data": form_data})
