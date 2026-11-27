import csv
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Exam, Attempt
from ..permissions import can_manage_exam, can_authorize_resume
from ..services import (PASS_MARK, RESULT_HEADER, audit, close_expired_attempts, grade_summary, graded_rows,
                        grading_of, question_stats, result_rows, results_summary)


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
    rows = list(graded_rows(exam, "-started_at"))
    return render(request, "qcm/exam_results.html", {
        "exam": exam, "rows": rows, "summary": results_summary(rows), "pass_mark": PASS_MARK,
        "enrollment_count": exam.enrollments.count(),
        "question_stats": question_stats(exam),
    })


@login_required
def print_exam_results(request, exam_id):
    """Page imprimable : l'export PDF passe par « Enregistrer en PDF » du navigateur."""
    exam = get_object_or_404(Exam.objects.select_related("classroom"), pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    close_expired_attempts(Attempt.objects.filter(exam=exam))
    rows = list(graded_rows(exam, "student__last_name", "student__first_name", "student__username", "started_at"))
    return render(request, "qcm/exam_results_print.html", {
        "exam": exam, "rows": rows, "summary": results_summary(rows), "pass_mark": PASS_MARK,
        "enrollment_count": exam.enrollments.count(), "printed_at": timezone.now(),
    })


@login_required
@require_POST
def publish_results(request, exam_id):
    """Les étudiants voient leur note (#12). Irréversible : refusé tant que des copies sont en cours."""
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden("Accès réservé à l'enseignant responsable.")
    close_expired_attempts(Attempt.objects.filter(exam=exam))
    running = Attempt.objects.filter(exam=exam, status=Attempt.IN_PROGRESS).count()
    if not exam.published:
        messages.error(request, "Publiez d'abord l'examen avant de publier les notes.")
        return redirect("teacher_exam", exam_id=exam.id)
    if exam.results_published:
        messages.info(request, "Les notes de cet examen sont déjà publiées.")
    elif running:
        messages.error(request, f"{running} étudiant(s) composent encore : publiez les notes quand toutes les "
                                "copies sont remises (la publication ne peut pas être annulée).")
    else:
        with transaction.atomic():
            exam.results_published = True
            exam.save(update_fields=["results_published"])
            audit(request.user, "Notes publiées", exam)
        messages.success(request, "Les notes sont désormais visibles par les étudiants.")
    return redirect("exam_results", exam_id=exam.id)


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


def _csv_cell(value):
    return value.strftime("%d/%m/%Y %H:%M") if isinstance(value, datetime) else csv_safe(value)


def _write_csv(response, rows):
    response.write("\ufeff")  # BOM : Excel détecte l'UTF-8
    writer = csv.writer(response, delimiter=";")
    writer.writerow(RESULT_HEADER)
    for row in rows:
        writer.writerow([_csv_cell(value) for value in row])


def _write_xlsx(response, rows):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.utils import get_column_letter

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Résultats")
    sheet.freeze_panes = "A2"
    for number in range(1, len(RESULT_HEADER) + 1):
        sheet.column_dimensions[get_column_letter(number)].width = 18

    def cell(value):
        if isinstance(value, str):
            # Type « texte » imposé : un nom commençant par « = » ne devient jamais une formule.
            text = WriteOnlyCell(sheet, ILLEGAL_CHARACTERS_RE.sub("", value))
            text.data_type = "s"
            return text
        if isinstance(value, datetime):
            date = WriteOnlyCell(sheet, value)
            date.number_format = "dd/mm/yyyy hh:mm"
            return date
        return value

    sheet.append(RESULT_HEADER)
    for row in rows:
        sheet.append([cell(value) for value in row])
    workbook.save(response)


EXPORT_FORMATS = {
    "csv": ("text/csv; charset=utf-8", _write_csv),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _write_xlsx),
}


@login_required
def export_exam_results(request, exam_id, fmt="csv"):
    exam = get_object_or_404(Exam, pk=exam_id)
    if not can_manage_exam(request.user, exam):
        return HttpResponseForbidden()
    close_expired_attempts(Attempt.objects.filter(exam=exam))
    content_type, write = EXPORT_FORMATS[fmt]
    response = HttpResponse(content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="resultats_examen_{exam.id}.{fmt}"'
    write(response, result_rows(exam))
    return response
