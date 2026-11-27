"""
Données de démonstration (issue #7) : comptes fictifs, classes et examens.

    python manage.py seed_demo                  # 20 étudiants
    python manage.py seed_demo --students 200   # pour le test de charge (#8)
    python manage.py seed_demo --reset          # supprime puis recrée les données de démo

Tous les comptes créés commencent par « demo_ » et partagent le même mot de passe.
Aucune vraie donnée : noms, matricules et questions sont inventés.
"""
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, ProtectedError, Value
from django.db.models.functions import Concat

from qcm.models import Attempt, Classroom, ClassroomMembership, Exam, Option, Profile, Question
from qcm.services import enroll_audience

PREFIX = "demo_"
EMAIL_DOMAIN = "@demo.invalid"


def demo_users():
    """Comptes créés par seed_demo : identifiant « demo_… » ET e-mail « <identifiant>@demo.invalid ».

    Le préfixe seul ne suffit pas : n'importe qui peut s'inscrire avec un identifiant « demo_… ».
    """
    return User.objects.filter(username__startswith=PREFIX).filter(email=Concat(F("username"), Value(EMAIL_DOMAIN)))
DEFAULT_PASSWORD = "Demo-SecureQCM-2026"

FIRST_NAMES = ["Awa", "Moussa", "Fatou", "Ibrahima", "Aminata", "Ousmane", "Mariama", "Cheikh", "Khady", "Abdou",
               "Seynabou", "Mamadou", "Ndeye", "Lamine", "Coumba", "Pape", "Rokhaya", "Alioune", "Bineta", "Saliou"]
LAST_NAMES = ["Diallo", "Sow", "Ba", "Ndiaye", "Fall", "Sarr", "Diop", "Faye", "Gueye", "Mbaye",
              "Cisse", "Kane", "Thiam", "Sy", "Badji", "Diatta", "Sane", "Mendy", "Camara", "Coly"]

# (énoncé, type, [(proposition, correcte), ...])
GL_QUESTIONS = [
    ("Quel diagramme UML décrit les interactions entre objets dans le temps ?", "SINGLE",
     [("Diagramme de séquence", True), ("Diagramme de classes", False), ("Diagramme de déploiement", False),
      ("Diagramme de paquetages", False)]),
    ("Quelles pratiques font partie de Scrum ?", "MULTIPLE",
     [("Sprint planning", True), ("Daily scrum", True), ("Cycle en V", False), ("Rétrospective", True)]),
    ("Que signifie le « S » de SOLID ?", "SINGLE",
     [("Single responsibility", True), ("Simple design", False), ("Secure by default", False),
      ("Static typing", False)]),
    ("Quelle commande Git crée une nouvelle branche et s'y place ?", "SINGLE",
     [("git checkout -b", True), ("git branch -d", False), ("git merge", False), ("git stash", False)]),
    ("Quels tests vérifient une unité de code isolée ?", "SINGLE",
     [("Tests unitaires", True), ("Tests de charge", False), ("Tests d'acceptation", False),
      ("Tests de bout en bout", False)]),
    ("Quels éléments sont des patrons de conception du GoF ?", "MULTIPLE",
     [("Singleton", True), ("Observateur", True), ("MVC", False), ("Fabrique", True)]),
    ("Dans une architecture REST, quelle méthode HTTP est idempotente et sert à remplacer une ressource ?", "SINGLE",
     [("PUT", True), ("POST", False), ("PATCH", False), ("CONNECT", False)]),
    ("Quel est l'objectif principal de l'intégration continue ?", "SINGLE",
     [("Détecter tôt les erreurs en intégrant et testant souvent", True), ("Remplacer les tests manuels", False),
      ("Déployer sans tests", False), ("Supprimer les revues de code", False)]),
]
BD_QUESTIONS = [
    ("Quelle clause SQL filtre les groupes après un GROUP BY ?", "SINGLE",
     [("HAVING", True), ("WHERE", False), ("ORDER BY", False), ("LIMIT", False)]),
    ("Quelles propriétés font partie de ACID ?", "MULTIPLE",
     [("Atomicité", True), ("Cohérence", True), ("Disponibilité", False), ("Durabilité", True)]),
    ("Une clé étrangère sert à…", "SINGLE",
     [("Garantir l'intégrité référentielle entre deux tables", True), ("Accélérer toutes les requêtes", False),
      ("Chiffrer une colonne", False), ("Créer une vue", False)]),
    ("Quelle forme normale élimine les dépendances transitives ?", "SINGLE",
     [("3FN", True), ("1FN", False), ("2FN", False), ("Aucune", False)]),
    ("Quels SGBD sont orientés NoSQL ?", "MULTIPLE",
     [("Cassandra", True), ("MongoDB", True), ("PostgreSQL", False), ("Redis", True)]),
]


class Command(BaseCommand):
    help = "Crée des comptes, classes et examens fictifs pour les démonstrations et les tests de charge."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=20, help="Nombre d'étudiants fictifs (défaut : 20)")
        parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Mot de passe commun des comptes de démo")
        parser.add_argument("--reset", action="store_true", help="Supprime d'abord les données de démo existantes")
        parser.add_argument("--force", action="store_true",
                            help="Autorise l'exécution avec DJANGO_DEBUG=0 (déconseillé sur un vrai serveur)")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("DJANGO_DEBUG=0 : ces comptes ont un mot de passe connu. Ajoutez --force si c'est voulu.")
        if not 1 <= opts["students"] <= 2000:
            raise CommandError("--students doit être compris entre 1 et 2000.")
        with transaction.atomic():
            if opts["reset"]:
                self._reset()
            elif demo_users().exists():
                raise CommandError("Des données de démo existent déjà. Relancez avec --reset pour les recréer.")
            self._check_free_usernames(opts["students"])
            summary = self._create(opts["students"], opts["password"])
        self._print(summary, opts["password"])

    # ------------------------------------------------------------------ #
    def _check_free_usernames(self, n_students):
        wanted = [f"{PREFIX}admin", f"{PREFIX}prof1", f"{PREFIX}prof2"]
        wanted += [f"{PREFIX}etu{i:03d}" for i in range(1, n_students + 1)]
        taken = sorted(User.objects.filter(username__in=wanted).exclude(pk__in=demo_users()).values_list(
            "username", flat=True))
        if taken:
            raise CommandError(
                "Ces identifiants appartiennent à de vrais comptes (pas créés par seed_demo) : "
                f"{', '.join(taken[:10])}{'…' if len(taken) > 10 else ''}. Renommez-les avant de lancer la commande.")

    def _reset(self):
        users = demo_users()
        classrooms = Classroom.objects.filter(owner__in=users)
        foreign = Exam.objects.filter(classroom__in=classrooms).exclude(teacher__in=users)
        if foreign.exists():
            titles = ", ".join(f"« {e.title} » ({e.teacher.username})" for e in foreign.select_related("teacher")[:5])
            raise CommandError(
                "Impossible de supprimer les classes de démo : elles contiennent des examens créés par de vrais "
                f"enseignants : {titles}. Déplacez ou supprimez ces examens d'abord. Rien n'a été supprimé.")
        exams = Exam.objects.filter(teacher__in=users)
        try:
            Attempt.objects.filter(exam__in=exams).delete()  # Attempt.exam est en PROTECT
            Attempt.objects.filter(student__in=users).delete()
            exams.delete()
            classrooms.delete()
            count = users.count()
            users.delete()
        except ProtectedError as exc:
            blocking = ", ".join(sorted({f"{o._meta.verbose_name} #{o.pk}" for o in list(exc.protected_objects)[:5]}))
            raise CommandError(f"Suppression impossible, des données protégées en dépendent : {blocking}. "
                               "Rien n'a été supprimé.") from exc
        self.stdout.write(f"Données de démo supprimées ({count} comptes).")

    def _user(self, username, first, last, hashed, role="STUDENT", level="", number="", staff=False):
        user = User(username=username, first_name=first, last_name=last, password=hashed,
                    email=f"{username}{EMAIL_DOMAIN}", is_staff=staff)
        user.save()  # le signal post_save crée le Profile
        Profile.objects.filter(user=user).update(role=role, study_level=level, student_number=number)
        return user

    def _create(self, n_students, password):
        hashed = make_password(password)  # un seul hachage : rapide même pour 200 comptes
        admin = self._user(f"{PREFIX}admin", "Admin", "Démo", hashed, role="ADMIN")
        prof1 = self._user(f"{PREFIX}prof1", "Aissatou", "Sagna", hashed, role="TEACHER")
        prof2 = self._user(f"{PREFIX}prof2", "Babacar", "Senghor", hashed, role="TEACHER")

        students = []
        for i in range(1, n_students + 1):
            first = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
            last = LAST_NAMES[(i * 7) % len(LAST_NAMES)]
            level = "M1" if i % 2 else "L3"
            students.append(self._user(f"{PREFIX}etu{i:03d}", first, last, hashed, level=level,
                                       number=f"DEMO-{i:04d}"))

        gl = Classroom.objects.create(name="Génie logiciel", section="M1 – démo", subject="Génie logiciel",
                                      study_level="M1", owner=prof1, join_code="DEMOGLM", color="teal")
        bd = Classroom.objects.create(name="Bases de données", section="L3 – démo", subject="Bases de données",
                                      study_level="L3", owner=prof2, join_code="DEMOBDL", color="indigo")
        ClassroomMembership.objects.create(classroom=gl, user=prof1, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=gl, user=prof2, role=ClassroomMembership.TEACHER)
        ClassroomMembership.objects.create(classroom=bd, user=prof2, role=ClassroomMembership.TEACHER)
        # Tous les étudiants dans la classe de génie logiciel (pratique pour le test de charge),
        # les L3 aussi en bases de données.
        for s in students:
            ClassroomMembership.objects.create(classroom=gl, user=s, role=ClassroomMembership.STUDENT)
            if s.profile.study_level == "L3":
                ClassroomMembership.objects.create(classroom=bd, user=s, role=ClassroomMembership.STUDENT)

        exam_gl = self._exam(prof1, gl, "Démo – Génie logiciel", "DEMOGL01", GL_QUESTIONS, minutes=10, publish=True)
        exam_bd = self._exam(prof2, bd, "Démo – Bases de données", "DEMOBD01", BD_QUESTIONS, minutes=5, publish=True)
        self._exam(prof1, gl, "Démo – Brouillon à compléter", "DEMODRFT", GL_QUESTIONS[:3], minutes=5, publish=False)
        return {"admin": admin, "teachers": [prof1, prof2], "students": students,
                "classes": [gl, bd], "exams": [exam_gl, exam_bd]}

    def _exam(self, teacher, classroom, title, code, questions, minutes, publish):
        exam = Exam.objects.create(title=title, teacher=teacher, classroom=classroom, duration_minutes=minutes,
                                   access_code=code, audience_mode="CLASS", target_level=classroom.study_level,
                                   description="Examen fictif créé par seed_demo.")
        for position, (text, kind, options) in enumerate(questions, 1):
            q = Question.objects.create(exam=exam, text=text, question_type=kind, duration_seconds=0,
                                        points=1, position=position)
            for opt_pos, (opt_text, correct) in enumerate(options, 1):
                Option.objects.create(question=q, text=opt_text, is_correct=correct, position=opt_pos)
        if publish:
            exam.published = True
            exam.save(update_fields=["published"])
            enroll_audience(exam)
        return exam

    def _print(self, s, password):
        w = self.stdout.write
        w(self.style.SUCCESS("Données de démonstration créées."))
        w(f"  Mot de passe commun : {password}")
        w(self.style.WARNING("  Attention : demo_admin est administrateur avec un mot de passe connu. "
                             "Ne jamais laisser ces comptes sur le serveur d'un vrai examen (seed_demo --reset puis "
                             "suppression, ou base séparée)."))
        w(f"  Administrateur      : {s['admin'].username}")
        w(f"  Enseignants         : {', '.join(t.username for t in s['teachers'])}")
        w(f"  Étudiants           : {s['students'][0].username} … {s['students'][-1].username} ({len(s['students'])})")
        for c in s["classes"]:
            w(f"  Classe « {c.name} » : code {c.join_code}")
        for e in s["exams"]:
            w(f"  Examen « {e.title} » : code d'accès {e.access_code}, {e.questions.count()} questions")
