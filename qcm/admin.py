from django.contrib import admin
from .models import (Profile, Classroom, ClassroomMembership, Exam, ExamEnrollment, Question, Option,
                     Attempt, Response, SecurityEvent)


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
    list_display = ("title", "teacher", "classroom", "target_level", "audience_mode", "published",
                    "results_published", "opens_at", "closes_at", "is_archived", "duration_minutes", "created_at")
    list_filter = ("published", "results_published", "is_archived", "target_level", "audience_mode")
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


admin.site.register([ClassroomMembership, Option, Response, SecurityEvent, ExamEnrollment])
