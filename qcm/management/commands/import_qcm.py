import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from qcm.models import Exam, Question, Option, Classroom, Profile
from qcm.services import enroll_audience

class Command(BaseCommand):
    help = "Importe un QCM JSON dans Secure QCM en tant que brouillon."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Chemin du fichier JSON")
        parser.add_argument("--teacher", required=True, help="Nom d'utilisateur du compte enseignant/admin")
        parser.add_argument("--duration", type=int, default=60, help="Durée globale en minutes (défaut : 60)")
        parser.add_argument("--seconds", type=int, default=30, help="Temps par question en secondes (défaut : 30)")
        parser.add_argument("--title", default=None, help="Titre personnalisé de l'examen")
        parser.add_argument("--level", default="", help="Niveau ciblé (L1, L2, L3, M1, M2, DOCTORAT, AUTRE)")
        parser.add_argument("--classroom", type=int, default=None, help="ID de la classe : l'examen ciblera toute la classe")
        parser.add_argument("--publish", action="store_true", help="Publier immédiatement (déconseillé avant vérification)")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = Path(opts["file"]).expanduser().resolve()
        if not path.is_file():
            raise CommandError(f"Fichier introuvable : {path}")
        if not 1 <= opts["duration"] <= 180:
            raise CommandError("La durée globale doit être comprise entre 1 et 180 minutes.")
        if not 5 <= opts["seconds"] <= 300:
            raise CommandError("Le temps par question doit être compris entre 5 et 300 secondes.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(f"JSON illisible : {exc}")
        questions = data.get("questions", [])
        if not questions:
            raise CommandError("Le fichier ne contient aucune question.")
        for q in questions:
            if len(q.get("options", [])) != 4 or sum(1 for o in q["options"] if o.get("correct")) != 1:
                raise CommandError(f"Question {q.get('number')} : il faut 4 propositions et exactement une bonne réponse.")
        User = get_user_model()
        try:
            teacher = User.objects.get(username=opts["teacher"])
        except User.DoesNotExist:
            raise CommandError(f"Utilisateur enseignant introuvable : {opts['teacher']}")
        if opts["level"] and opts["level"] not in dict(Profile.LEVEL_CHOICES):
            raise CommandError("Niveau inconnu.")
        classroom = None
        if opts["classroom"]:
            classroom = Classroom.objects.filter(pk=opts["classroom"]).first()
            if not classroom:
                raise CommandError(f"Classe introuvable : {opts['classroom']}")
        if opts["publish"] and not classroom and not opts["level"]:
            raise CommandError("--publish exige --level ou --classroom pour savoir quels étudiants affecter.")
        title = opts["title"] or data.get("title", "QCM importé")
        exam = Exam.objects.create(
            title=title,
            description=data.get("instructions", "") + "\nSource : " + data.get("source", ""),
            teacher=teacher,
            duration_minutes=opts["duration"],
            published=bool(opts["publish"]),
            classroom=classroom,
            target_level=opts["level"] or (classroom.study_level if classroom else ""),
            audience_mode="CLASS" if classroom else "LEVEL",
            shuffle_questions=True,
            shuffle_answers=True,
        )
        for qdata in questions:
            q = Question.objects.create(
                exam=exam, text=qdata["text"], question_type="SINGLE",
                duration_seconds=opts["seconds"], points=qdata.get("points", 1),
                position=qdata["number"],
            )
            for index, option in enumerate(qdata["options"], start=1):
                Option.objects.create(question=q, text=option["text"],
                                      is_correct=bool(option["correct"]), position=index)
        if exam.published:
            enroll_audience(exam)
        self.stdout.write(self.style.SUCCESS(
            f"Examen importé : {exam.title} | {len(questions)} questions | "
            f"{opts['duration']} min | {opts['seconds']} s/question | "
            f"{'publié' if exam.published else 'brouillon'}"
        ))
        self.stdout.write(f"ID de l'examen : {exam.id}")
        self.stdout.write(f"URL de vérification : /teacher/exams/{exam.id}/")
