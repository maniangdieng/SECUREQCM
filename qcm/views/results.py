import csv
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from ..models import Exam, Attempt
from ..permissions import can_manage_exam
from ..services import exam_max_score, grade_summary


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
    attempts = (Attempt.objects.filter(exam=exam).select_related("student", "student__profile")
                .annotate(violation_count=Count("security_events"))
                .order_by("-started_at"))
    max_score = exam_max_score(exam)
    rows = [{"attempt": a, **grade_summary(a, max_score)} for a in attempts]
    finished = [r for r in rows if r["attempt"].status != Attempt.IN_PROGRESS]
    average = (sum(r["final_grade"] for r in finished) / len(finished)) if finished else None
    return render(request, "qcm/exam_results.html", {
        "exam": exam, "rows": rows, "max_score": max_score,
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
    details = []
    response_map = {r.question_id: r for r in attempt.responses.all()}
    for q in attempt.exam.questions.prefetch_related("options").order_by("position"):
        response = response_map.get(q.id)
        selected = set(response.selected_option_ids) if response else set()
        options = list(q.options.all())
        correct = {o.id for o in options if o.is_correct}
        details.append({"question": q, "options": options, "selected": selected, "correct": correct,
                        "response": response, "is_right": bool(correct) and selected == correct})
    return render(request, "qcm/attempt_result_detail.html", {
        "attempt": attempt, "details": details, **grade_summary(attempt),
        "events": attempt.security_events.order_by("created_at"),
    })


@login_required
def export_exam_results(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="resultats_examen_{exam.id}.csv"'
    response.write("﻿")  # BOM : Excel détecte l'UTF-8
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Identifiant", "Matricule", "Nom", "Prénom", "Statut", "Nature du score", "Motif de clôture",
                     "Début", "Fin", "Score obtenu", "Score maximal", "Pourcentage (%)", "Note finale (/20)"])

    max_score = exam_max_score(exam)
    attempts = (Attempt.objects.filter(exam=exam).select_related("student", "student__profile")
                .order_by("student__username", "-started_at"))
    for attempt in attempts:
        g = grade_summary(attempt, max_score)
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
            str(max_score.quantize(Decimal("0.01"))),
            str(g["percent"]),
            str(g["final_grade"]),
        ])
    return response
