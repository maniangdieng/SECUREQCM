"""
Règles d'accès centralisées.

Hiérarchie des rôles :
- Super-administrateur : compte Django `is_superuser` (créé avec `createsuperuser`).
  Il peut tout faire, y compris nommer d'autres administrateurs.
- Administrateur : compte `is_staff` ou profil ADMIN. Il gère les comptes
  (enseignant/étudiant), les classes et le cycle de vie des examens.
- Enseignant : crée ses classes et ses examens, gère uniquement ce qui lui appartient
  ou les classes dont il est co-enseignant.
- Étudiant : rejoint des classes par code, passe les examens auxquels il est affecté.
"""
from .models import Profile, ClassroomMembership


def role(user):
    """
    Détermine le rôle applicatif de manière cohérente.
    - Superutilisateur ou membre du staff Django : accès administrateur.
    - Profil explicitement TEACHER / ADMIN : rôle du profil.
    - Les autres comptes restent étudiants par défaut.
    """
    if not getattr(user, "is_authenticated", False):
        return "STUDENT"
    if user.is_superuser or user.is_staff:
        return "ADMIN"
    try:
        profile_role = user.profile.role
    except Profile.DoesNotExist:
        profile, _ = Profile.objects.get_or_create(user=user)
        profile_role = profile.role
    if profile_role in ("ADMIN", "TEACHER", "STUDENT"):
        return profile_role
    return "STUDENT"


def is_admin(user):
    return role(user) == "ADMIN"


def is_superadmin(user):
    return getattr(user, "is_authenticated", False) and user.is_superuser


def is_teacher_or_admin(user):
    return role(user) in ("TEACHER", "ADMIN")


def is_classroom_teacher(user, classroom):
    if classroom is None or not getattr(user, "is_authenticated", False):
        return False
    if classroom.owner_id == user.id:
        return True
    return ClassroomMembership.objects.filter(
        classroom=classroom, user=user, role=ClassroomMembership.TEACHER
    ).exists()


def is_classroom_student(user, classroom):
    return ClassroomMembership.objects.filter(
        classroom=classroom, user=user, role=ClassroomMembership.STUDENT
    ).exists()


def can_manage_classroom(user, classroom):
    return is_admin(user) or is_classroom_teacher(user, classroom)


def can_manage_exam(user, exam):
    """Auteur de l'examen, enseignant de la classe de l'examen, ou administrateur."""
    if is_admin(user):
        return True
    if exam.teacher_id == user.id:
        return True
    return is_classroom_teacher(user, exam.classroom)
