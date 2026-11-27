from decimal import Decimal
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from qcm.importers import check_questions, parse_json
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
            data, questions = parse_json(path.read_bytes())
            for q in questions:
                if not q["correct"]:  # pas de prévisualisation ici : le corrigé doit être complet
                    q.setdefault("errors", []).append("aucune bonne réponse")
            check_questions(questions)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc))
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
        title = str(opts["title"] or data.get("title") or "QCM importé")[:200]
        exam = Exam.objects.create(
            title=title,
            description=f"{data.get('instructions', '')}\nSource : {data.get('source', '')}",
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
                exam=exam, text=qdata["text"],
                question_type=qdata.get("type") or ("MULTIPLE" if len(qdata["correct"]) > 1 else "SINGLE"),
                duration_seconds=opts["seconds"], points=Decimal(qdata["points"]),
                position=qdata["number"],
            )
            for index, option in enumerate(qdata["options"], start=1):
                Option.objects.create(question=q, text=option["text"],
                                      is_correct=option["letter"] in qdata["correct"], position=index)
        if exam.published:
            enroll_audience(exam)
        self.stdout.write(self.style.SUCCESS(
            f"Examen importé : {exam.title} | {len(questions)} questions | "
            f"{opts['duration']} min | {opts['seconds']} s/question | "
            f"{'publié' if exam.published else 'brouillon'}"
        ))
        self.stdout.write(f"ID de l'examen : {exam.id}")
        self.stdout.write(f"URL de vérification : /teacher/exams/{exam.id}/")
