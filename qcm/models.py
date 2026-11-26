import uuid
import secrets
import string
from django.db import models
from django.contrib.auth.models import User


def _random_code(length):
    # Sans caractères ambigus (0/O, 1/I) pour faciliter la saisie au tableau.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_exam_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def generate_class_code():
    return _random_code(7)


class Profile(models.Model):
    LEVEL_CHOICES = [("L1", "Licence 1"), ("L2", "Licence 2"), ("L3", "Licence 3"), ("M1", "Master 1"), ("M2", "Master 2"), ("DOCTORAT", "Doctorat"), ("AUTRE", "Autre")]
    ROLE_CHOICES = [("ADMIN", "Administrateur"), ("TEACHER", "Enseignant"), ("STUDENT", "Étudiant")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default="STUDENT")
    student_number = models.CharField(max_length=40, blank=True)
    study_level = models.CharField(max_length=12, choices=LEVEL_CHOICES, blank=True, default="")

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class Classroom(models.Model):
    """
    Classe au sens Google Classroom : un enseignant propriétaire, éventuellement
    des co-enseignants, et des étudiants qui la rejoignent avec un code de classe.
    """
    COLOR_CHOICES = [
        ("teal", "Sarcelle"), ("indigo", "Indigo"), ("amber", "Ambre"),
        ("rose", "Rose"), ("green", "Vert"), ("slate", "Ardoise"),
    ]
    name = models.CharField("Nom de la classe", max_length=120)
    section = models.CharField("Section / groupe", max_length=120, blank=True)
    subject = models.CharField("Matière", max_length=120, blank=True)
    description = models.TextField(blank=True)
    study_level = models.CharField("Niveau", max_length=12, choices=Profile.LEVEL_CHOICES, blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_classrooms")
    join_code = models.CharField(max_length=12, unique=True, default=generate_class_code)
    join_enabled = models.BooleanField("Inscription par code autorisée", default=True)
    color = models.CharField(max_length=12, choices=COLOR_CHOICES, default="teal")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_archived", "-created_at"]

    def __str__(self):
        return f"{self.name} {self.section}".strip()

    def teachers(self):
        return User.objects.filter(classroom_memberships__classroom=self, classroom_memberships__role=ClassroomMembership.TEACHER)

    def students(self):
        return User.objects.filter(classroom_memberships__classroom=self, classroom_memberships__role=ClassroomMembership.STUDENT)


class ClassroomMembership(models.Model):
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    ROLE_CHOICES = [(TEACHER, "Enseignant"), (STUDENT, "Étudiant")]
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="classroom_memberships")
    role = models.CharField(max_length=8, choices=ROLE_CHOICES)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["classroom", "user"], name="unique_classroom_member")]

    def __str__(self):
        return f"{self.user} – {self.classroom} ({self.role})"


class Exam(models.Model):
    LEVEL_CHOICES = Profile.LEVEL_CHOICES
    AUDIENCE_CHOICES = [
        ("CLASS", "Tous les étudiants de la classe"),
        ("LEVEL", "Tous les étudiants du niveau"),
        ("LIST", "Étudiants sélectionnés / liste CSV"),
    ]
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # PROTECT : supprimer un enseignant ne doit jamais emporter ses examens (ni les copies
    # des étudiants, elles-mêmes protégées). L'admin désactive le compte à la place (issue #4).
    teacher = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_exams")
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, null=True, blank=True, related_name="exams")
    duration_minutes = models.PositiveIntegerField(default=60)
    published = models.BooleanField(default=False)
    shuffle_questions = models.BooleanField(default=True)
    shuffle_answers = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    access_code = models.CharField(max_length=12, unique=True, default=generate_exam_code)
    target_level = models.CharField(max_length=12, choices=LEVEL_CHOICES, blank=True, default="")
    audience_mode = models.CharField(max_length=8, choices=AUDIENCE_CHOICES, default="LEVEL")
    is_archived = models.BooleanField(default=False, verbose_name="Archivé")
    archived_at = models.DateTimeField(null=True, blank=True, verbose_name="Date d’archivage")
    archived_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="archived_exams", verbose_name="Archivé par")

    def __str__(self):
        return self.title

    @property
    def state_label(self):
        if self.is_archived:
            return "Archivé"
        return "Publié" if self.published else "Brouillon"


class ExamEnrollment(models.Model):
    SOURCE_CHOICES = [("LIST", "Liste enseignant"), ("CODE", "Code examen"), ("LEVEL", "Niveau d'études"), ("CLASS", "Membre de la classe")]
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="exam_enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default="LIST")
    code_verified = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam", "student"], name="unique_exam_student_enrollment")]

    def __str__(self):
        return f"{self.student} – {self.exam}"


class Question(models.Model):
    SINGLE = "SINGLE"
    MULTIPLE = "MULTIPLE"
    TYPE_CHOICES = [(SINGLE, "Réponse unique"), (MULTIPLE, "Réponses multiples")]
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    question_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=SINGLE)
    duration_seconds = models.PositiveIntegerField(default=20)
    points = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text[:70]


class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text[:70]


class Attempt(models.Model):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    TERMINATED_SECURITY = "TERMINATED_SECURITY"
    TIME_EXPIRED = "TIME_EXPIRED"
    INTERRUPTED = "INTERRUPTED"
    STATUS_CHOICES = [(IN_PROGRESS, "En cours"), (COMPLETED, "Terminée"), (TERMINATED_SECURITY, "Clôturée pour sécurité"), (TIME_EXPIRED, "Temps écoulé"), (INTERRUPTED, "Interrompue")]
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="attempts")
    student = models.ForeignKey(User, on_delete=models.PROTECT, related_name="attempts")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=IN_PROGRESS)
    question_order = models.JSONField(default=list)
    option_orders = models.JSONField(default=dict)
    current_index = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    global_deadline = models.DateTimeField()
    question_started_at = models.DateTimeField()
    question_deadline = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam", "student"], condition=models.Q(status="IN_PROGRESS"),
                                               name="uniq_attempt_in_progress")]

    def __str__(self):
        return f"{self.student} – {self.exam}"


class Response(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    selected_option_ids = models.JSONField(default=list)
    submitted_at = models.DateTimeField(auto_now_add=True)
    auto_submitted = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "question"], name="one_response_per_question")]


class SecurityEvent(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="security_events")
    event_type = models.CharField(max_length=60)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
