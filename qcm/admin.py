from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (Profile, Classroom, ClassroomMembership, Exam, ExamEnrollment, Question, Option,
                     Attempt, Response, SecurityEvent, AuditLog)


class OptionInline(admin.TabularInline):
    model = Option
    extra = 2


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0


class MembershipInline(admin.TabularInline):
    model = ClassroomMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "student_number", "study_level")
    list_filter = ("role", "study_level")
    search_fields = ("user__username", "user__first_name", "user__last_name", "student_number")
    list_editable = ("role",)
    autocomplete_fields = ("user",)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "section", "subject", "owner", "join_code", "is_archived", "created_at")
    list_filter = ("is_archived", "study_level")
    search_fields = ("name", "section", "subject", "owner__username", "join_code")
    inlines = [MembershipInline]


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "teacher", "classroom", "target_level", "audience_mode", "published", "closed_at", "is_archived", "duration_minutes", "created_at")
    list_filter = ("published", "is_archived", "target_level", "audience_mode")
    search_fields = ("title", "teacher__username", "classroom__name")
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "exam", "question_type", "points")
    search_fields = ("text", "exam__title")
    inlines = [OptionInline]


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "status", "started_at", "ended_at")
    list_filter = ("status",)
    search_fields = ("student__username", "exam__title")


admin.site.register([ClassroomMembership, Option, ExamEnrollment])


class ReadOnlyAdmin(admin.ModelAdmin):
    """Consultation seule, y compris pour le super-administrateur : traces d'examen et journaux."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SecurityEvent)
class SecurityEventAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "attempt", "event_type", "details")
    list_filter = ("event_type",)
    search_fields = ("attempt__student__username", "attempt__exam__title")
    list_select_related = ("attempt__student", "attempt__exam")


admin.site.register(Response, ReadOnlyAdmin)


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Un enseignant qui possède des examens ou des classes ne peut pas être supprimé
    (Exam.teacher et Classroom.owner sont en PROTECT, issue #4). Django affiche déjà
    la liste des objets protégés ; on ajoute la marche à suivre.
    """

    def delete_view(self, request, object_id, extra_context=None):
        user = self.get_object(request, object_id)
        if user is not None and (user.created_exams.exists() or user.owned_classrooms.exists()):
            messages.warning(
                request,
                "Ce compte possède des examens ou des classes : sa suppression est bloquée pour protéger "
                "l'historique des notes. Désactivez plutôt le compte (Administration → Comptes → Désactiver).",
            )
        return super().delete_view(request, object_id, extra_context)


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "actor_name", "action", "target", "details")
    list_filter = ("action",)
    search_fields = ("actor_name", "target", "details")
