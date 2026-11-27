"""
Passage d'un examen par l'étudiant.

Règles conservées de la version d'origine :
- chronomètre contrôlé côté serveur (échéance globale + échéance par question) ;
- temps par question = durée totale ÷ nombre de questions (secondes réparties exactement) ;
- passage séquentiel sans retour en arrière, réponse blanche à l'expiration ;
- 1re violation (changement d'onglet / sortie du plein écran / fenêtre quittée) = avertissement,
  2e violation = clôture TERMINATED_SECURITY définitive pour cet examen.

Ajouts :
- #1 : les réponses sont envoyées en fetch() (endpoint JSON) pour rester en plein écran ;
- #2 : une 2e violation arrivée moins de VIOLATION_DEBOUNCE_SECONDS après la précédente
       est un doublon de la même action (onglet + plein écran) : journalisée, non comptée ;
- #3 : l'enseignant peut rouvrir une tentative clôturée pour sécurité (temps restant rendu,
       compteur de violations remis à zéro, trace dans le journal) ;
- #23 : consignes confirmées avant le démarrage, sauvegarde automatique de la sélection,
        et toute modification d'une tentative se fait sous verrou (services.locked_attempts) ;
- #24 : pertes de focus et redimensionnements journalisés sans être comptés ; chaque événement
        garde le compteur de violations au moment où il est écrit.
"""
import random
from datetime import timedelta
from functools import wraps
from contextlib import nullcontext

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from ..models import Exam, ExamEnrollment, Question, Option, Attempt, Response, SecurityEvent
from ..permissions import role, can_authorize_resume
from ..services import (RESUME_EVENT, VIOLATION_LABELS, audit, build_grading, exam_max_score, grade_summary,
                        locked_attempts, question_time_seconds, advance, close_attempt, apply_deadlines)

SECURITY_EVENTS = set(VIOLATION_LABELS)
INFO_EVENTS = {"FOCUS_LOSS", "WINDOW_RESIZE"}  # journalisés pour information, jamais comptés
MAX_VIOLATIONS = 2
VIOLATION_DEBOUNCE_SECONDS = 3
IGNORED_EVENT = "VIOLATION_IGNORED"


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def _question_for(attempt):
    qid = attempt.question_order[attempt.current_index]
    return get_object_or_404(Question, pk=qid)


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
    grade = grade_summary(attempt)
    return {"attempt": attempt, "score": grade["score"], "max_score": grade["max_score"],
            "percentage": grade["percent"]}


def attempt_state(attempt):
    """État sérialisable de la tentative, consommé par le JavaScript de take_exam.html."""
    if attempt.status != Attempt.IN_PROGRESS:
        return {"status": attempt.status, "redirect": reverse("take_exam", args=[attempt.id])}
    now = timezone.now()
    q = _question_for(attempt)
    order = attempt.option_orders.get(str(q.id), [])
    by_id = {o.id: o for o in Option.objects.filter(id__in=order)}
    draft = Response.objects.filter(attempt=attempt, question=q).first()
    rule = attempt.grading_snapshot.get("multiple_scoring", attempt.exam.multiple_scoring)
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
            "scoring_rule": Exam.SCORING_RULES[rule] if q.question_type == Question.MULTIPLE else "",
            "options": [{"id": i, "text": by_id[i].text} for i in order if i in by_id],
            "selected": draft.selected_option_ids if draft else [],
        },
        "question_remaining": max(0, int((attempt.question_deadline - now).total_seconds())),
        "global_remaining": max(0, int((attempt.global_deadline - now).total_seconds())),
        "violations": counted_violations(attempt).count(),
    }


def _is_current_question(request, attempt):
    return request.POST.get("question_id") == str(attempt.question_order[attempt.current_index])


def _store_selection(request, attempt):
    """
    Valide puis enregistre la sélection envoyée pour la question courante.
    Retourne None si tout va bien, ou une HttpResponse d'erreur.
    """
    q = _question_for(attempt)
    try:
        selected = [int(x) for x in request.POST.getlist("option")]
    except ValueError:
        return HttpResponseBadRequest("Réponse invalide.")
    if not set(selected).issubset(set(attempt.option_orders.get(str(q.id), []))):
        return HttpResponseForbidden("Réponse invalide.")
    if q.question_type == Question.SINGLE and len(selected) > 1:
        return HttpResponseForbidden("Une seule réponse est autorisée pour cette question.")
    Response.objects.update_or_create(
        attempt=attempt, question=q,
        defaults={"selected_option_ids": selected, "auto_submitted": False, "submitted_at": timezone.now()},
    )
    return None


def json_login_required(view):
    """Pour les routes appelées en fetch() : une session expirée répond 401, pas une page HTML."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "session_expired"}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


# --------------------------------------------------------------------------- #
# Vues étudiant
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def start_exam(request, exam_id):
    """GET : consignes. POST avec confirmation : crée la tentative et démarre le chronomètre."""
    exam = get_object_or_404(Exam, pk=exam_id, published=True, is_archived=False)
    if role(request.user) != "STUDENT":
        return HttpResponseForbidden()
    confirmed = request.method == "POST" and bool(request.POST.get("confirm"))
    # Au démarrage, l'affectation est verrouillée : deux requêtes simultanées passent l'une
    # après l'autre et la seconde retrouve la tentative créée par la première.
    with transaction.atomic() if confirmed else nullcontext():
        enrollments = ExamEnrollment.objects.filter(exam=exam, student=request.user)
        if confirmed:
            enrollments = enrollments.select_for_update()
        enrollment = enrollments.first()
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

        if exam.closed_at:
            messages.error(request, "Cet examen a été clôturé par l'enseignant : aucune nouvelle tentative n'est possible.")
            return redirect("student_dashboard")

        questions = list(exam.questions.prefetch_related("options").all())
        if not questions:
            messages.error(request, "Aucune question disponible.")
            return redirect("student_dashboard")
        if not confirmed:
            return render(request, "qcm/exam_instructions.html", {
                "exam": exam, "question_count": len(questions), "max_score": exam_max_score(exam),
                "confirmation_missing": request.method == "POST",
                "scoring_rule": Exam.SCORING_RULES[exam.multiple_scoring],
            })
        attempt = _create_attempt(exam, request.user, questions)
    return redirect("take_exam", attempt_id=attempt.id)


def _create_attempt(exam, student, questions):
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
    return Attempt.objects.create(exam=exam, student=student, question_order=order, option_orders=option_orders,
                                  global_deadline=global_deadline, question_started_at=now,
                                  question_deadline=first_question_deadline,
                                  grading_snapshot=build_grading(exam, questions))


@login_required
def take_exam(request, attempt_id):
    with transaction.atomic():
        attempt = get_object_or_404(locked_attempts(), pk=attempt_id, student=request.user)
        if attempt.status == Attempt.TERMINATED_SECURITY:
            messages.error(request, "Cette tentative a été clôturée après deux violations. La reprise de l'examen n'est pas autorisée.")
            return redirect("student_dashboard")
        apply_deadlines(attempt)
    if attempt.status != Attempt.IN_PROGRESS:
        return render(request, "qcm/finished.html", finished_score_context(attempt))
    return render(request, "qcm/take_exam.html", {"attempt": attempt, "state": attempt_state(attempt)})


@json_login_required
@require_POST
def submit_answer_api(request, attempt_id):
    """
    Soumission en fetch() (issue #1) : enregistre la réponse et renvoie l'état suivant en JSON,
    sans rechargement de page, donc sans sortie du plein écran.
    """
    with transaction.atomic():
        attempt = get_object_or_404(locked_attempts(), pk=attempt_id, student=request.user)
        if attempt.status != Attempt.IN_PROGRESS:
            return JsonResponse(attempt_state(attempt), status=409)
        apply_deadlines(attempt)
        # Réponse portant sur une autre question (double clic, onglet ancien, envoi arrivé après
        # l'échéance) : rien n'est enregistré, on renvoie simplement la question courante.
        if attempt.status == Attempt.IN_PROGRESS and _is_current_question(request, attempt):
            error = _store_selection(request, attempt)
            if error is not None:
                return error
            advance(attempt)
    return JsonResponse(attempt_state(attempt))


@json_login_required
@require_POST
def save_answer(request, attempt_id):
    """Sauvegarde automatique (#23) : enregistre la sélection en cours sans changer de question."""
    with transaction.atomic():
        attempt = get_object_or_404(locked_attempts(), pk=attempt_id, student=request.user)
        apply_deadlines(attempt)
        if attempt.status != Attempt.IN_PROGRESS or not _is_current_question(request, attempt):
            return JsonResponse(attempt_state(attempt), status=409)
        error = _store_selection(request, attempt)
        if error is not None:
            return error
    return JsonResponse({"status": attempt.status, "saved": True})


def _log_event(attempt, event_type, violation_count, **details):
    SecurityEvent.objects.create(attempt=attempt, event_type=event_type,
                                 details={**details, "violation_count": violation_count})


@json_login_required
@require_POST
def security_event(request, attempt_id):
    event = request.POST.get("event", "")
    with transaction.atomic():
        # Verrou sur la tentative : deux événements quasi simultanés (onglet + plein écran)
        # sont traités l'un après l'autre, ce qui rend l'anti-doublon fiable.
        attempt = get_object_or_404(locked_attempts(), pk=attempt_id, student=request.user)
        apply_deadlines(attempt)  # un événement reçu après la fin du temps ne change plus rien
        if attempt.status != Attempt.IN_PROGRESS or event not in SECURITY_EVENTS | INFO_EVENTS:
            return JsonResponse({"status": attempt.status})
        violations = counted_violations(attempt)
        if event in INFO_EVENTS:
            # ponytail: une ligne par type toutes les 3 s ; un client modifié peut insister,
            # plafonner par tentative si le journal grossit trop.
            since = timezone.now() - timedelta(seconds=VIOLATION_DEBOUNCE_SECONDS)
            if not attempt.security_events.filter(event_type=event, created_at__gt=since).exists():
                _log_event(attempt, event, violations.count(), source="browser-client")
            return JsonResponse({"status": Attempt.IN_PROGRESS})
        previous = violations.order_by("-created_at").first()
        if previous and (timezone.now() - previous.created_at).total_seconds() < VIOLATION_DEBOUNCE_SECONDS:
            _log_event(attempt, IGNORED_EVENT, violations.count(), source="browser-client",
                       event=event, reason="doublon de la violation précédente")
            return JsonResponse({"status": Attempt.IN_PROGRESS, "duplicate": True, "count": violations.count()})
        count = violations.count() + 1
        _log_event(attempt, event, count, source="browser-client")
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
@transaction.atomic
def authorize_resume(request, attempt_id):
    attempt = get_object_or_404(locked_attempts().select_related("student"), pk=attempt_id)
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
    if Attempt.objects.filter(exam=attempt.exam, student=attempt.student, status=Attempt.IN_PROGRESS).exists():
        messages.error(request, "Une autre tentative est déjà en cours pour cet étudiant : rien à reprendre.")
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
    attempt.status = Attempt.IN_PROGRESS
    attempt.ended_at = None
    attempt.global_deadline = now + global_left
    attempt.question_started_at = now
    attempt.question_deadline = min(attempt.global_deadline, now + question_left)
    attempt.save(update_fields=["status", "ended_at", "global_deadline", "question_started_at", "question_deadline"])
    audit(request.user, "Reprise autorisée", attempt, reason)
    _log_event(attempt, RESUME_EVENT, 0,  # le compteur repart à zéro
               by_id=request.user.id, by=request.user.get_full_name() or request.user.username, reason=reason,
               closed_at=closed_at.isoformat(), seconds_restored=int(global_left.total_seconds()))
    minutes, seconds = divmod(int(global_left.total_seconds()), 60)
    messages.success(request, f"Reprise autorisée : {attempt.student.get_full_name() or attempt.student.username} "
                              f"dispose de {minutes} min {seconds:02d} s. Le compteur de violations repart à zéro.")
    return back
