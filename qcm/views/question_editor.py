"""Éditeur graphique des questions (façon Google Forms) : points d'accès JSON utilisés par
static/js/question_editor.js sur la page d'un examen en brouillon.

Mêmes règles que les formulaires classiques : `validate_question` (contenu) et `_questions_locked`
(questions figées après publication ou première tentative).
"""
import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import AuditLog, Exam, Question
from ..permissions import can_manage_exam
from ..services import audit
from .teacher import _questions_locked, validate_question, write_options

# Les modifications sont enregistrées automatiquement pendant la saisie : une seule ligne de journal
# par question et par auteur dans cette fenêtre, pour ne pas noyer le journal des opérations.
AUDIT_COALESCE = timedelta(minutes=10)


def question_data(question):
    """Représentation JSON d'une question (lue par l'éditeur)."""
    return {
        "id": question.pk,
        "text": question.text,
        "kind": question.question_type,
        "points": format(question.points.normalize(), "f"),
        "options": [{"text": o.text, "correct": o.is_correct} for o in question.options.all()],
    }


def editor_data(exam):
    return [question_data(q) for q in exam.questions.prefetch_related("options")]


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _order(exam):
    return list(exam.questions.order_by("position", "id").values_list("id", flat=True))


def _renumber(exam, ids=None):
    """Positions 1..n, dans l'ordre `ids` s'il est donné, sinon dans l'ordre actuel."""
    for position, qid in enumerate(ids or _order(exam), 1):
        Question.objects.filter(pk=qid, exam=exam).exclude(position=position).update(position=position)


def _editable(request, exam_id):
    """(examen, None) si l'auteur peut modifier ses questions, sinon (None, réponse d'erreur)."""
    exam = Exam.objects.filter(pk=exam_id).first()
    if exam is None:
        return None, _error("Examen introuvable.", 404)
    if not can_manage_exam(request.user, exam):
        return None, _error("Accès refusé.", 403)
    locked = _questions_locked(exam)
    if locked:
        return None, _error(locked, 409)
    return exam, None


def _body(request):
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _question(exam, raw_id):
    try:
        return exam.questions.filter(pk=int(raw_id)).first()
    except (TypeError, ValueError):
        return None


@login_required
@require_POST
def api_save_question(request, exam_id):
    """Crée (sans `id`, après la question `after` si donnée) ou met à jour une question."""
    exam, denied = _editable(request, exam_id)
    if denied:
        return denied
    data = _body(request)
    if data is None or not isinstance(data.get("options"), list):
        return _error("Requête invalide.")
    options = [(o.get("text", ""), o.get("correct") is True) for o in data["options"] if isinstance(o, dict)]
    payload, error = validate_question(data.get("text"), data.get("kind"), data.get("points"), options)
    if error:
        return _error(error)

    with transaction.atomic():
        if data.get("id") is not None:
            question = _question(exam, data["id"])
            if question is None:
                return _error("Question introuvable : rechargez la page.", 404)
            before = question_data(question)
            question.text, question.question_type, question.points = payload["text"], payload["kind"], payload["points"]
            question.save(update_fields=["text", "question_type", "points"])
            write_options(question, payload["options"])
            if question_data(question) != before:
                target = f"{exam} (#{exam.pk})"[:300]
                recent = AuditLog.objects.filter(actor=request.user, action="Question modifiée", target=target,
                                                 details=f"question #{question.pk}",
                                                 created_at__gte=timezone.now() - AUDIT_COALESCE)
                if not recent.exists():
                    audit(request.user, "Question modifiée", exam, f"question #{question.pk}")
        else:
            after = _question(exam, data.get("after")) if data.get("after") is not None else None
            if after is not None:
                position = after.position + 1
                exam.questions.filter(position__gte=position).update(position=F("position") + 1)
            else:
                position = (exam.questions.order_by("-position").values_list("position", flat=True).first() or 0) + 1
            question = Question.objects.create(exam=exam, text=payload["text"], question_type=payload["kind"],
                                               duration_seconds=0, points=payload["points"], position=position)
            write_options(question, payload["options"])
            _renumber(exam)
            audit(request.user, "Question ajoutée", exam, f"question #{question.pk}")
    return JsonResponse({"question": question_data(question), "order": _order(exam)})


@login_required
@require_POST
def api_duplicate_question(request, exam_id, question_id):
    exam, denied = _editable(request, exam_id)
    if denied:
        return denied
    source = _question(exam, question_id)
    if source is None:
        return _error("Question introuvable : rechargez la page.", 404)
    with transaction.atomic():
        exam.questions.filter(position__gt=source.position).update(position=F("position") + 1)
        copy = Question.objects.create(exam=exam, text=source.text, question_type=source.question_type,
                                       duration_seconds=source.duration_seconds, points=source.points,
                                       position=source.position + 1)
        write_options(copy, [(o.text, o.is_correct) for o in source.options.all()])
        _renumber(exam)
        audit(request.user, "Question dupliquée", exam, f"question #{source.pk} → #{copy.pk}")
    return JsonResponse({"question": question_data(copy), "order": _order(exam)})


@login_required
@require_POST
def api_delete_question(request, exam_id, question_id):
    exam, denied = _editable(request, exam_id)
    if denied:
        return denied
    question = _question(exam, question_id)
    if question is None:
        return JsonResponse({"order": _order(exam)})  # déjà supprimée (double clic, autre onglet)
    with transaction.atomic():
        audit(request.user, "Question supprimée", exam, f"question #{question.pk} : {question.text[:80]}")
        question.delete()
        _renumber(exam)
    return JsonResponse({"order": _order(exam)})


@login_required
@require_POST
def api_reorder_questions(request, exam_id):
    """`order` : tous les identifiants des questions de l'examen, dans le nouvel ordre."""
    exam, denied = _editable(request, exam_id)
    if denied:
        return denied
    data = _body(request)
    order = data.get("order") if data else None
    current = _order(exam)
    if (not isinstance(order, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in order)
            or len(order) != len(set(order)) or set(order) != set(current)):
        return _error("Ordre invalide : rechargez la page.", 409)
    if order != current:
        with transaction.atomic():
            _renumber(exam, order)
            audit(request.user, "Ordre des questions modifié", exam)
    return JsonResponse({"order": _order(exam)})
