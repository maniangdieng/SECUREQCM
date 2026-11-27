import csv
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404

from ..models import Exam, Attempt
from ..permissions import can_manage_exam, can_authorize_resume
from ..services import (RESULT_HEADER, close_expired_attempts, exam_attempts, grade_summary, graded_attempts,
                        grading_of, result_rows)


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
    attempts = exam_attempts(exam).order_by("-started_at")
    rows = [{"attempt": a, **g} for a, g in graded_attempts(exam, attempts)]
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
