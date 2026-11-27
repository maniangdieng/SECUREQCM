import csv
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from ..models import Exam, Attempt
from ..permissions import can_manage_exam, can_authorize_resume
from ..services import close_expired_attempts, grade_summary, grading_of


def csv_safe(value):
    """
    Neutralise l'injection de formules (CSV injection) : un nom saisi par un étudiant
    comme « =HYPERLINK(...) » serait exécuté par Excel à l'ouverture de l'export.
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@login_required
def exam_results(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related("classroom"), pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden("Accès réservé à l'enseignant responsable.")
    close_expired_attempts(Attempt.objects.filter(exam=exam))
    attempts = (Attempt.objects.filter(exam=exam).select_related("student", "student__profile")
                # Seules les vraies violations comptent (pas les doublons ignorés ni les reprises).
                .annotate(violation_count=Count("security_events",
                                                filter=Q(security_events__event_type__in=["TAB_SWITCH", "FULLSCREEN_EXIT"])))
                .order_by("-started_at"))
    rows = [{"attempt": a, **grade_summary(a)} for a in attempts]
    finished = [r for r in rows if r["attempt"].status != Attempt.IN_PROGRESS]
    average = (sum(r["final_grade"] for r in finished) / len(finished)) if finished else None
    return render(request, "qcm/exam_results.html", {
        "exam": exam, "rows": rows,
        "completed_count": len(finished),
        "in_progress_count": len(rows) - len(finished),
        "average": average,
        "enrollment_count": exam.enrollments.count(),
    })


@login_required
def attempt_result_detail(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("exam", "student"), pk=attempt_id)
    if not can_manage_exam(request.user, attempt.exam):
        return HttpResponseForbidden()
    if close_expired_attempts(Attempt.objects.filter(pk=attempt.pk)):
        attempt.refresh_from_db()
    grading = grading_of(attempt)
    details = []
    response_map = {r.question_id: r for r in attempt.responses.all()}
    for q in attempt.exam.questions.prefetch_related("options").order_by("position"):
        response = response_map.get(q.id)
        selected = set(response.selected_option_ids) if response else set()
        options = list(q.options.all())
        correct = set(grading["questions"].get(str(q.id), {}).get("correct", []))
        details.append({"question": q, "options": options, "selected": selected, "correct": correct,
                        "response": response, "is_right": bool(correct) and selected == correct})
    return render(request, "qcm/attempt_result_detail.html", {
        "attempt": attempt, "details": details, **grade_summary(attempt, grading),
        "scoring_label": dict(Exam.SCORING_CHOICES)[grading["multiple_scoring"]],
        "events": attempt.security_events.order_by("created_at"),
        "can_resume": attempt.status == Attempt.TERMINATED_SECURITY and not attempt.exam.is_archived
                      and can_authorize_resume(request.user, attempt),
    })


@login_required
def export_exam_results(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    close_expired_attempts(Attempt.objects.filter(exam=exam))

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="resultats_examen_{exam.id}.csv"'
    response.write("﻿")  # BOM : Excel détecte l'UTF-8
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Identifiant", "Matricule", "Nom", "Prénom", "Statut", "Nature du score", "Motif de clôture",
                     "Début", "Fin", "Score obtenu", "Score maximal", "Pourcentage (%)", "Note finale (/20)"])

    attempts = (Attempt.objects.filter(exam=exam).select_related("student", "student__profile")
                .order_by("student__username", "-started_at"))
    for attempt in attempts:
        g = grade_summary(attempt)
        profile = getattr(attempt.student, "profile", None)
        writer.writerow([
            csv_safe(attempt.student.username),
            csv_safe(profile.student_number if profile else ""),
            csv_safe(attempt.student.last_name),
            csv_safe(attempt.student.first_name),
            attempt.get_status_display(),
            "Provisoire" if attempt.status == Attempt.IN_PROGRESS else "Définitif",
            "Violation des règles" if attempt.status == Attempt.TERMINATED_SECURITY else attempt.get_status_display(),
            timezone.localtime(attempt.started_at).strftime("%d/%m/%Y %H:%M"),
            timezone.localtime(attempt.ended_at).strftime("%d/%m/%Y %H:%M") if attempt.ended_at else "",
            str(g["score"].quantize(Decimal("0.01"))),
            str(g["max_score"].quantize(Decimal("0.01"))),
            str(g["percent"]),
            str(g["final_grade"]),
        ])
    return response
