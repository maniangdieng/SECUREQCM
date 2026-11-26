"""
Passage d'un examen par l'étudiant.

Règles conservées de la version d'origine :
- chronomètre contrôlé côté serveur (échéance globale + échéance par question) ;
- temps par question = durée totale ÷ nombre de questions (secondes réparties exactement) ;
- passage séquentiel sans retour en arrière, réponse blanche à l'expiration ;
- 1re violation (changement d'onglet / sortie du plein écran) = avertissement,
  2e violation = clôture TERMINATED_SECURITY définitive pour cet examen.

Ajouts :
- #1 : les réponses sont envoyées en fetch() (endpoint JSON) pour rester en plein écran ;
- #2 : une 2e violation arrivée moins de VIOLATION_DEBOUNCE_SECONDS après la précédente
       est un doublon de la même action (onglet + plein écran) : journalisée, non comptée ;
- #3 : l'enseignant peut rouvrir une tentative clôturée pour sécurité (temps restant rendu,
       compteur de violations remis à zéro, trace dans le journal).
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Exam, ExamEnrollment, Question, Option, Attempt, Response, SecurityEvent
from ..permissions import role, can_authorize_resume
from ..services import calculate_score, exam_max_score

SECURITY_EVENTS = {"TAB_SWITCH", "FULLSCREEN_EXIT"}
MAX_VIOLATIONS = 2
VIOLATION_DEBOUNCE_SECONDS = 3
RESUME_EVENT = "RESUME_AUTHORIZED"
IGNORED_EVENT = "VIOLATION_IGNORED"


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
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


def counted_violations(attempt):
    """Violations qui comptent : celles postérieures à la dernière reprise autorisée."""
    events = SecurityEvent.objects.filter(attempt=attempt)
    qs = events.filter(event_type__in=SECURITY_EVENTS)
    last_resume = events.filter(event_type=RESUME_EVENT).order_by("-created_at").first()
    if last_resume:
        qs = qs.filter(created_at__gt=last_resume.created_at)
    return qs


def finished_score_context(attempt):
    """Score conservé à la clôture, rapporté au maximum de toutes les questions."""
    score = calculate_score(attempt)
    max_score = exam_max_score(attempt.exam)
    percentage = (score / max_score) * Decimal("100") if max_score else Decimal("0")
    return {"attempt": attempt, "score": score, "max_score": max_score,
            "percentage": percentage.quantize(Decimal("0.1"))}


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


def apply_deadlines(attempt):
    """Applique les échéances serveur : clôture si le temps global est écoulé, réponses blanches
    pour chaque question dont le temps est écoulé. Ne fait rien si la tentative est close."""
    while attempt.status == Attempt.IN_PROGRESS:
        now = timezone.now()
        if now >= attempt.global_deadline:
            close_attempt(attempt, Attempt.TIME_EXPIRED)
        elif now >= attempt.question_deadline:
            advance(attempt)
        else:
            break
    return attempt


def attempt_state(attempt):
    """État sérialisable de la tentative, consommé par le JavaScript de take_exam.html."""
    if attempt.status != Attempt.IN_PROGRESS:
        return {"status": attempt.status, "redirect": reverse("take_exam", args=[attempt.id])}
    now = timezone.now()
    q = _question_for(attempt)
    order = attempt.option_orders.get(str(q.id), [])
    by_id = {o.id: o for o in Option.objects.filter(id__in=order)}
    return {
        "status": attempt.status,
        "index": attempt.current_index + 1,
        "total": len(attempt.question_order),
        "question": {
            "id": q.id,
            "text": q.text,
            "multiple": q.question_type == Question.MULTIPLE,
            "type_label": q.get_question_type_display(),
            "points": str(q.points.normalize()),
            "options": [{"id": i, "text": by_id[i].text} for i in order if i in by_id],
        },
        "question_remaining": max(0, int((attempt.question_deadline - now).total_seconds())),
        "global_remaining": max(0, int((attempt.global_deadline - now).total_seconds())),
        "violations": counted_violations(attempt).count(),
    }


def _record_answer(request, attempt):
    """
    Enregistre la réponse à la question courante puis avance.
    Retourne None si tout va bien, ou une HttpResponse d'erreur.
    Le temps est contrôlé côté serveur : une réponse arrivée après l'échéance est enregistrée blanche.
    """
    q = _question_for(attempt)
    # Garde-fou : la réponse doit porter sur la question courante (double clic, onglet ancien,
    # nouvel essai réseau d'une réponse déjà enregistrée…). On n'enregistre rien.
    posted_question = request.POST.get("question_id", "")
    if posted_question and posted_question != str(q.id):
        return None
    now = timezone.now()
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
    else:
        advance(attempt)
    return None


# --------------------------------------------------------------------------- #
# Vues étudiant
# --------------------------------------------------------------------------- #
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

    questions = list(exam.questions.prefetch_related("options").all())
    if not questions:
        messages.error(request, "Aucune question disponible.")
        return redirect("student_dashboard")
    if exam.shuffle_questions:
        random.shuffle(questions)
    now = timezone.now()
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
    apply_deadlines(attempt)
    if attempt.status != Attempt.IN_PROGRESS:
        return render(request, "qcm/finished.html", finished_score_context(attempt))
    return render(request, "qcm/take_exam.html", {"attempt": attempt, "state": attempt_state(attempt)})


@login_required
@require_POST
def submit_answer(request, attempt_id):
    """Soumission classique (formulaire) : conservée pour compatibilité, redirige vers la page d'examen."""
    attempt = get_object_or_404(Attempt.objects.select_related("exam"), pk=attempt_id, student=request.user)
    if attempt.status != Attempt.IN_PROGRESS:
        return JsonResponse({"error": "Tentative clôturée"}, status=409)
    error = _record_answer(request, attempt)
    return error or redirect("take_exam", attempt_id=attempt.id)


@login_required
@require_POST
def submit_answer_api(request, attempt_id):
    """
    Soumission en fetch() (issue #1) : enregistre la réponse et renvoie l'état suivant en JSON,
    sans rechargement de page, donc sans sortie du plein écran.
    """
    with transaction.atomic():
        attempt = get_object_or_404(Attempt.objects.select_for_update().select_related("exam"),
                                    pk=attempt_id, student=request.user)
        if attempt.status != Attempt.IN_PROGRESS:
            return JsonResponse(attempt_state(attempt), status=409)
        apply_deadlines(attempt)
        if attempt.status == Attempt.IN_PROGRESS:
            error = _record_answer(request, attempt)
            if error is not None:
                return error
    return JsonResponse(attempt_state(attempt))


@login_required
@require_POST
def security_event(request, attempt_id):
    event = request.POST.get("event", "")
    with transaction.atomic():
        # Verrou sur la tentative : deux événements quasi simultanés (onglet + plein écran)
        # sont traités l'un après l'autre, ce qui rend l'anti-doublon fiable.
        attempt = get_object_or_404(Attempt.objects.select_for_update(), pk=attempt_id, student=request.user)
        if attempt.status != Attempt.IN_PROGRESS or event not in SECURITY_EVENTS:
            return JsonResponse({"status": attempt.status})
        violations = counted_violations(attempt)
        previous = violations.order_by("-created_at").first()
        if previous and (timezone.now() - previous.created_at).total_seconds() < VIOLATION_DEBOUNCE_SECONDS:
            SecurityEvent.objects.create(attempt=attempt, event_type=IGNORED_EVENT, details={
                "source": "browser-client", "event": event, "reason": "doublon de la violation précédente"})
            return JsonResponse({"status": Attempt.IN_PROGRESS, "duplicate": True, "count": violations.count()})
        SecurityEvent.objects.create(attempt=attempt, event_type=event, details={"source": "browser-client"})
        count = violations.count()
        if count >= MAX_VIOLATIONS:
            close_attempt(attempt, Attempt.TERMINATED_SECURITY)
            return JsonResponse({"status": "TERMINATED_SECURITY",
                                 "message": "Deux violations détectées : votre examen est clôturé.",
                                 "redirect": reverse("student_dashboard")})
        return JsonResponse({"status": "IN_PROGRESS", "warning": True, "count": count})


# --------------------------------------------------------------------------- #
# Vue enseignant : reprise après clôture de sécurité (issue #3)
# --------------------------------------------------------------------------- #
@login_required
@require_POST
def authorize_resume(request, attempt_id):
    attempt = get_object_or_404(Attempt.objects.select_related("exam", "student"), pk=attempt_id)
    if not can_authorize_resume(request.user, attempt):
        return HttpResponseForbidden("Action réservée à l'enseignant de l'examen ou à l'administration.")
    back = redirect("attempt_result_detail", attempt_id=attempt.id)
    reason = request.POST.get("reason", "").strip()[:500]
    if attempt.status != Attempt.TERMINATED_SECURITY:
        messages.error(request, "Seule une tentative clôturée pour sécurité peut être rouverte.")
        return back
    if attempt.exam.is_archived:
        messages.error(request, "L'examen est archivé : la reprise n'est plus possible.")
        return back
    if not reason:
        messages.error(request, "Indiquez le motif de la reprise : il est conservé dans le journal de sécurité.")
        return back

    # Temps qui restait au moment de la clôture : il est rendu tel quel à l'étudiant.
    closed_at = attempt.ended_at or timezone.now()
    global_left = attempt.global_deadline - closed_at
    if global_left.total_seconds() <= 0:
        messages.error(request, "Le temps de l'examen était déjà écoulé au moment de la clôture : rien à reprendre.")
        return back
    question_left = max(attempt.question_deadline - closed_at, timedelta(0))

    now = timezone.now()
    with transaction.atomic():
        attempt.status = Attempt.IN_PROGRESS
        attempt.ended_at = None
        attempt.global_deadline = now + global_left
        attempt.question_started_at = now
        attempt.question_deadline = min(attempt.global_deadline, now + question_left)
        attempt.save(update_fields=["status", "ended_at", "global_deadline", "question_started_at", "question_deadline"])
        SecurityEvent.objects.create(attempt=attempt, event_type=RESUME_EVENT, details={
            "by_id": request.user.id,
            "by": request.user.get_full_name() or request.user.username,
            "reason": reason,
            "closed_at": closed_at.isoformat(),
            "seconds_restored": int(global_left.total_seconds()),
        })
    minutes, seconds = divmod(int(global_left.total_seconds()), 60)
    messages.success(request, f"Reprise autorisée : {attempt.student.get_full_name() or attempt.student.username} "
                              f"dispose de {minutes} min {seconds:02d} s. Le compteur de violations repart à zéro.")
    return back
