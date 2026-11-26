from decimal import Decimal
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect

from ..importers import (InvalidQuestions, apply_answer_key, check_questions, extract_text,
                         parse_answer_key_xlsx, parse_uploaded_questions)
from ..models import Profile, Exam, Question, Option, Classroom
from ..permissions import is_teacher_or_admin, can_manage_classroom
from .teacher import manageable_classrooms

MAX_UPLOAD = 15 * 1024 * 1024


@login_required
def import_qcm(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponseForbidden("Accès réservé aux enseignants.")
    classrooms = manageable_classrooms(request.user).filter(is_archived=False)
    errors = []
    if request.method == "POST":
        uploaded = request.FILES.get("subject_file")
        mode = request.POST.get("answer_mode", "integrated")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        try:
            if not uploaded:
                raise ValueError("Sélectionnez un fichier contenant les questions.")
            if uploaded.size > MAX_UPLOAD:
                raise ValueError("Le fichier dépasse la limite de 15 Mo.")
            classroom_id = request.POST.get("classroom_id", "").strip()
            classroom = None
            if classroom_id:
                classroom = Classroom.objects.filter(pk=classroom_id).first() if classroom_id.isdigit() else None
                if classroom is None or not can_manage_classroom(request.user, classroom):
                    raise ValueError("Classe invalide.")
            target_level = request.POST.get("target_level", "").strip()
            audience_mode = request.POST.get("audience_mode", "CLASS" if classroom else "LEVEL")
            if audience_mode not in dict(Exam.AUDIENCE_CHOICES):
                raise ValueError("Sélectionnez un mode d'affectation valide.")
            if audience_mode == "CLASS" and not classroom:
                raise ValueError("Le mode « toute la classe » nécessite de choisir une classe.")
            if target_level and target_level not in dict(Profile.LEVEL_CHOICES):
                raise ValueError("Niveau d'études invalide.")
            if audience_mode == "LEVEL" and not target_level:
                raise ValueError("Sélectionnez le niveau d'études ciblé.")
            duration = int(request.POST.get("duration", 60))
            questions = parse_uploaded_questions(uploaded)
            if mode == "separate":
                key_file = request.FILES.get("answer_file")
                if not key_file:
                    raise ValueError("Ajoutez le fichier de corrigé séparé.")
                if key_file.size > MAX_UPLOAD:
                    raise ValueError("Le corrigé dépasse la limite de 15 Mo.")
                if key_file.name.lower().endswith((".xlsx", ".xlsm")):
                    key = parse_answer_key_xlsx(key_file)
                    for q in questions:
                        q["correct"] = key.get(q["number"], [])
                else:
                    apply_answer_key(questions, extract_text(key_file))
            elif mode == "manual":
                for q in questions:
                    q["correct"] = []
            elif mode != "integrated":
                raise ValueError("Mode de correction inconnu.")
            check_questions(questions)
            request.session["qcm_import_preview"] = {
                "title": title or Path(uploaded.name).stem[:190],
                "description": description,
                "duration": max(1, min(180, duration)),
                "target_level": target_level or (classroom.study_level if classroom else ""),
                "audience_mode": audience_mode,
                "classroom_id": classroom.id if classroom else None,
                "classroom_name": str(classroom) if classroom else "",
                "mode": mode,
                "questions": questions,
            }
            return redirect("import_qcm_preview")
        except InvalidQuestions as exc:
            errors = exc.errors
        except (ValueError, OSError, TypeError) as exc:
            messages.error(request, str(exc))
    return render(request, "qcm/import_qcm.html", {
        "classrooms": classrooms,
        "import_errors": errors,
        "levels": Profile.LEVEL_CHOICES,
        "selected_classroom": request.GET.get("classe", ""),
    })


@login_required
def import_qcm_preview(request):
    if not is_teacher_or_admin(request.user):
        return HttpResponseForbidden()
    payload = request.session.get("qcm_import_preview")
    if not payload:
        messages.error(request, "Aucun import à prévisualiser. Sélectionnez vos fichiers.")
        return redirect("import_qcm")

    if request.method == "POST":
        original_questions = payload["questions"]
        removed_indexes = {int(v) for v in request.POST.getlist("remove_question") if v.isdigit()}
        questions = [(i, q) for i, q in enumerate(original_questions) if i not in removed_indexes]

        if not questions:
            messages.error(request, "Vous ne pouvez pas supprimer toutes les questions. Conservez au moins une question.")
            return render(request, "qcm/import_preview.html", {"payload": payload})

        # Les indices restent ceux de la prévisualisation initiale, même si
        # certaines questions sont supprimées dans cette même soumission.
        for display_index, (original_index, q) in enumerate(questions, 1):
            raw_values = request.POST.getlist(f"correct_{original_index}")
            valid_letters = [option["letter"] for option in q["options"]]
            q["correct"] = [value for value in raw_values if value in valid_letters]
            if not q["correct"]:
                messages.error(request, f"Veuillez indiquer au moins une bonne réponse à la question conservée n°{display_index}.")
                return render(request, "qcm/import_preview.html", {"payload": payload})
            declared = q.get("type")  # fourni par le JSON uniquement
            if declared == "SINGLE" and len(q["correct"]) > 1:
                messages.error(request, f"La question conservée n°{display_index} est à réponse unique : cochez une seule bonne réponse.")
                return render(request, "qcm/import_preview.html", {"payload": payload})
            q["final_type"] = declared or ("MULTIPLE" if len(q["correct"]) > 1 else "SINGLE")

        classroom = None
        if payload.get("classroom_id"):
            classroom = Classroom.objects.filter(pk=payload["classroom_id"]).first()
            if classroom is None or not can_manage_classroom(request.user, classroom):
                messages.error(request, "La classe choisie n'est plus accessible.")
                return redirect("import_qcm")
        try:
            with transaction.atomic():
                exam = Exam.objects.create(
                    title=payload["title"] or "QCM importé",
                    description=payload.get("description", ""),
                    teacher=request.user,
                    classroom=classroom,
                    duration_minutes=payload["duration"],
                    published=False,
                    shuffle_questions=True,
                    shuffle_answers=True,
                    target_level=payload.get("target_level", ""),
                    audience_mode=payload.get("audience_mode", "LEVEL"),
                )
                for position, (_, qdata) in enumerate(questions, 1):
                    question = Question.objects.create(
                        exam=exam, text=qdata["text"], question_type=qdata["final_type"],
                        duration_seconds=0, points=Decimal(qdata.get("points", "1")), position=position,
                    )
                    for option_position, option in enumerate(qdata["options"], 1):
                        Option.objects.create(
                            question=question, text=option["text"],
                            is_correct=option["letter"] in qdata["correct"], position=option_position,
                        )
            request.session.pop("qcm_import_preview", None)
            messages.success(request, f"Import réussi : {len(questions)} question(s) conservée(s). L'examen est enregistré en brouillon.")
            return redirect("teacher_exam", exam_id=exam.id)
        except Exception as exc:  # noqa: BLE001 - message affiché à l'enseignant
            messages.error(request, f"Import non effectué : {exc}")

    return render(request, "qcm/import_preview.html", {"payload": payload})
