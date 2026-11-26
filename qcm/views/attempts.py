"""
Passage d'un examen par l'étudiant.

Règles conservées de la version d'origine :
- chronomètre contrôlé côté serveur (échéance globale + échéance par question) ;
- temps par question = durée totale ÷ nombre de questions (secondes réparties exactement) ;
- passage séquentiel sans retour en arrière, réponse blanche à l'expiration ;
- 1re violation (changement d'onglet / sortie du plein écran) = avertissement,
  2e violation = clôture TERMINATED_SECURITY définitive pour cet examen.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Exam, ExamEnrollment, Question, Option, Attempt, Response, SecurityEvent
from ..permissions import role
from ..services import calculate_score, exam_max_score, exam_window_message

SECURITY_EVENTS = {"TAB_SWITCH", "FULLSCREEN_EXIT"}
MAX_VIOLATIONS = 2


def _question_for(attempt):
    qid = attempt.question_order[attempt.current_index]
    return get_object_or_404(Question, pk=qid)


def question_time_seconds(attempt, index=None):
    """Répartit exactement la durée totale, en secondes entières, entre les questions."""
    count = len(attempt.question_order)
    if count <= 0:
        return 0
    if index is None:
        index = attempt.current_index
    total_seconds = int(attempt.exam.duration_minutes) * 60
    base_seconds, extra_seconds = divmod(total_seconds, count)
    # Les premières questions reçoivent chacune une seconde supplémentaire
    # lorsque la division ne tombe pas juste : la somme est exactement égale
    # à la durée totale de l'examen.
    return base_seconds + (1 if 0 <= index < extra_seconds else 0)


def finished_score_context(attempt):
    """Score conservé à la clôture, rapporté au maximum de toutes les questions."""
    score = calculate_score(attempt)
    max_score = exam_max_score(attempt.exam)
    percentage = (score / max_score) * Decimal("100") if max_score else Decimal("0")
    return {"attempt": attempt, "score": score, "max_score": max_score,
            "percentage": percentage.quantize(Decimal("0.1"))}


@login_required
@require_POST
def start_exam(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id, published=True, is_archived=False)
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden()
    enrollment = ExamEnrollment.objects.filter(exam=exam, student=request.user).first()
    if not enrollment:
        return HttpResponseForbidden("Vous n'êtes pas autorisé à accéder à cet examen.")
    if not enrollment.code_verified:
        messages.error(request, "Saisissez d'abord le code d'accès propre à cet examen.")
        return redirect("student_dashboard")
    # Une clôture pour violation est définitive pour cet étudiant et cet examen.
    # La vérification porte sur toutes les tentatives, pas seulement la dernière,
    # afin d'empêcher un redémarrage après déconnexion ou nouvelle tentative.
    if Attempt.objects.filter(exam=exam, student=request.user, status=Attempt.TERMINATED_SECURITY).exists():
        messages.error(request, "Accès refusé : votre examen a été clôturé après deux violations. "
                                "Vous ne pouvez ni le reprendre ni recommencer une nouvelle tentative.")
        return redirect("student_dashboard")

    # Reprendre une tentative en cours ; une tentative terminée affiche son résultat.
    existing = Attempt.objects.filter(exam=exam, student=request.user).order_by("-started_at").first()
    if existing and existing.status != Attempt.INTERRUPTED:
        return redirect("take_exam", attempt_id=existing.id)

    now = timezone.now()
    window_error = exam_window_message(exam, now)
    if window_error:
        messages.error(request, window_error)
        return redirect("student_dashboard")

    questions = list(exam.questions.prefetch_related("options").all())
    if not questions:
        messages.error(request, "Aucune question disponible.")
        return redirect("student_dashboard")
    if exam.shuffle_questions:
        random.shuffle(questions)
    order = [q.id for q in questions]
    global_deadline = now + timedelta(minutes=exam.duration_minutes)
    first_question_seconds, remainder = divmod(exam.duration_minutes * 60, len(order))
    first_question_seconds += 1 if remainder > 0 else 0
    first_question_deadline = min(global_deadline, now + timedelta(seconds=first_question_seconds))
    option_orders = {}
    for q in questions:
        opts = list(q.options.all())
        if exam.shuffle_answers:
            random.shuffle(opts)
        option_orders[str(q.id)] = [o.id for o in opts]
    attempt = Attempt.objects.create(exam=exam, student=request.user, question_order=order, option_orders=option_orders,
                                     global_deadline=global_deadline, question_started_at=now,
                                     question_deadline=first_question_deadline)
    return redirect("take_exam", attempt_id=attempt.id)


@login_required
def take_exam(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("exam"), pk=attempt_id, student=request.user)
    if attempt.status == Attempt.TERMINATED_SECURITY:
        messages.error(request, "Cette tentative a été clôturée après deux violations. La reprise de l'examen n'est pas autorisée.")
        return redirect("student_dashboard")
    if attempt.status != Attempt.IN_PROGRESS:
        return render(request, "qcm/finished.html", finished_score_context(attempt))
    now = timezone.now()
    if now >= attempt.global_deadline:
        close_attempt(attempt, Attempt.TIME_EXPIRED)
        return render(request, "qcm/finished.html", finished_score_context(attempt))
    if now >= attempt.question_deadline:
        advance(attempt)  # expiration : réponse blanche puis question suivante
        attempt.refresh_from_db()
        if attempt.status != Attempt.IN_PROGRESS:
            return render(request, "qcm/finished.html", finished_score_context(attempt))
        return redirect("take_exam", attempt_id=attempt.id)
    q = _question_for(attempt)
    order = attempt.option_orders.get(str(q.id), [])
    byid = {o.id: o for o in Option.objects.filter(id__in=order)}
    options = [byid[i] for i in order if i in byid]
    violations = SecurityEvent.objects.filter(attempt=attempt, event_type__in=SECURITY_EVENTS).count()
    return render(request, "qcm/take_exam.html", {
        "attempt": attempt, "question": q, "options": options,
        "global_remaining": max(0, int((attempt.global_deadline - now).total_seconds())),
        "question_remaining": max(0, int((attempt.question_deadline - now).total_seconds())),
        "violations": violations,
    })


@transaction.atomic
def advance(attempt):
    q = _question_for(attempt)
    if not Response.objects.filter(attempt=attempt, question=q).exists():
        Response.objects.create(attempt=attempt, question=q, selected_option_ids=[], auto_submitted=True)
    attempt.current_index += 1
    if attempt.current_index >= len(attempt.question_order):
        close_attempt(attempt, Attempt.COMPLETED)
        return
    now = timezone.now()
    attempt.question_started_at = now
    allotted = timedelta(seconds=question_time_seconds(attempt, attempt.current_index))
    attempt.question_deadline = min(attempt.global_deadline, now + allotted)
    attempt.save(update_fields=["current_index", "question_started_at", "question_deadline"])


def close_attempt(attempt, status):
    attempt.status = status
    attempt.ended_at = timezone.now()
    attempt.save(update_fields=["status", "ended_at"])


@login_required
@require_POST
def submit_answer(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("exam"), pk=attempt_id, student=request.user)
    if attempt.status != Attempt.IN_PROGRESS:
        return JsonResponse({"error": "Tentative clôturée"}, status=409)
    now = timezone.now()
    q = _question_for(attempt)
    # Garde-fou : la réponse doit porter sur la question courante (double clic, onglet ancien…).
    posted_question = request.POST.get("question_id", "")
    if posted_question and posted_question != str(q.id):
        return redirect("take_exam", attempt_id=attempt.id)
    # À l'expiration du temps de la question, les choix envoyés trop tard sont ignorés.
    question_expired = now >= attempt.question_deadline
    global_expired = now >= attempt.global_deadline
    try:
        selected = [] if question_expired or global_expired else [int(x) for x in request.POST.getlist("option")]
    except ValueError:
        return HttpResponseBadRequest("Réponse invalide.")
    if not set(selected).issubset(set(attempt.option_orders.get(str(q.id), []))):
        return HttpResponseForbidden("Réponse invalide.")
    if q.question_type == Question.SINGLE and len(selected) > 1:
        return HttpResponseForbidden("Une seule réponse est autorisée pour cette question.")
    Response.objects.update_or_create(
        attempt=attempt, question=q,
        defaults={"selected_option_ids": selected, "auto_submitted": question_expired or global_expired},
    )
    if global_expired:
        close_attempt(attempt, Attempt.TIME_EXPIRED)
        return redirect("take_exam", attempt_id=attempt.id)
    advance(attempt)
    return redirect("take_exam", attempt_id=attempt.id)


@login_required
@require_POST
def security_event(request, attempt_id):
    attempt = get_object_or_404(Attempt, pk=attempt_id, student=request.user)
    if attempt.status != Attempt.IN_PROGRESS:
        return JsonResponse({"status": attempt.status})
    event = request.POST.get("event", "")
    if event in SECURITY_EVENTS:
        SecurityEvent.objects.create(attempt=attempt, event_type=event, details={"source": "browser-client"})
        count = SecurityEvent.objects.filter(attempt=attempt, event_type__in=SECURITY_EVENTS).count()
        if count >= MAX_VIOLATIONS:
            close_attempt(attempt, Attempt.TERMINATED_SECURITY)
            return JsonResponse({"status": "TERMINATED_SECURITY",
                                 "message": "Deux violations détectées : votre examen est clôturé."})
        return JsonResponse({"status": "IN_PROGRESS", "warning": True, "count": count})
    return JsonResponse({"status": attempt.status})
