"""Issue #24 : filigrane, pertes de focus journalisées, journaux en lecture seule."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.utils import timezone

from .models import Attempt, Response, SecurityEvent
from .services import violation_detail
from .tests_examen_securite import ExamFixture
from .views.attempts import VIOLATION_DEBOUNCE_SECONDS


class LaterMixin:
    def violation_later(self, event, delay=VIOLATION_DEBOUNCE_SECONDS + 1):
        with mock.patch("django.utils.timezone.now", return_value=timezone.now() + timedelta(seconds=delay)):
            return self.violation(event)


class InformationEventTests(LaterMixin, ExamFixture):
    def test_focus_loss_and_resize_are_logged_but_never_counted(self):
        for event in ("FOCUS_LOSS", "WINDOW_RESIZE"):
            self.assertEqual(self.violation(event), {"status": "IN_PROGRESS"})
            self.assertEqual(self.violation_later(event), {"status": "IN_PROGRESS"})
            self.assertEqual(SecurityEvent.objects.filter(attempt=self.attempt, event_type=event).count(), 2)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, Attempt.IN_PROGRESS)
        # La première vraie violation reste un simple avertissement, même juste après.
        result = self.violation("TAB_SWITCH")
        self.assertTrue(result["warning"])
        self.assertEqual(result["count"], 1)

    def test_information_event_does_not_hide_a_following_violation(self):
        self.violation("TAB_SWITCH")
        with mock.patch("django.utils.timezone.now",
                        return_value=timezone.now() + timedelta(seconds=VIOLATION_DEBOUNCE_SECONDS + 1)):
            self.violation("FOCUS_LOSS")
            self.assertEqual(self.violation("TAB_SWITCH")["status"], "TERMINATED_SECURITY")

    def test_repeats_within_a_few_seconds_are_logged_once_per_type(self):
        for _ in range(5):
            self.violation("FOCUS_LOSS")
        self.violation("WINDOW_RESIZE")
        self.assertEqual(SecurityEvent.objects.filter(attempt=self.attempt, event_type="FOCUS_LOSS").count(), 1)
        self.assertEqual(SecurityEvent.objects.filter(attempt=self.attempt, event_type="WINDOW_RESIZE").count(), 1)

    def test_nothing_is_logged_once_the_attempt_is_over(self):
        Attempt.objects.filter(pk=self.attempt.pk).update(status=Attempt.COMPLETED)
        self.violation("FOCUS_LOSS")
        self.assertFalse(SecurityEvent.objects.exists())

    def test_teacher_sees_readable_labels(self):
        self.violation("FOCUS_LOSS")
        self.violation("WINDOW_RESIZE")
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/attempts/{self.attempt.id}/results/")
        self.assertContains(page, "Perte de focus de la fenêtre")
        self.assertContains(page, "Redimensionnement de la fenêtre")
        self.assertNotContains(page, "FOCUS_LOSS")


class ProlongedFocusLossTests(LaterMixin, ExamFixture):
    """Alt+Tab : la page signale FOCUS_AWAY quand la fenêtre reste sans focus."""

    def test_second_prolonged_focus_loss_closes_the_exam(self):
        result = self.violation("FOCUS_AWAY")
        self.assertTrue(result["warning"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.violation_later("FOCUS_AWAY")["status"], "TERMINATED_SECURITY")

    def test_same_gesture_as_a_fullscreen_exit_counts_once(self):
        self.violation("FULLSCREEN_EXIT")
        self.assertTrue(self.violation_later("FOCUS_AWAY", delay=2)["duplicate"])

    def test_teacher_sees_it_as_a_violation(self):
        self.violation("FOCUS_AWAY")
        self.client.force_login(self.teacher)
        page = self.client.get(f"/teacher/attempts/{self.attempt.id}/results/")
        self.assertContains(page, "Perte de focus prolongée")
        self.assertNotContains(page, "FOCUS_AWAY")
        self.assertEqual(violation_detail(self.attempt), "Perte de focus prolongée : 1")

    def test_rules_warn_the_student(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(page, "plus de 2 secondes")
        self.assertContains(page, "ou fenêtre quittée")  # texte de l'avertissement


class ViolationCounterTests(LaterMixin, ExamFixture):
    def counters(self):
        return [(e.event_type, e.details.get("violation_count"))
                for e in SecurityEvent.objects.filter(attempt=self.attempt).order_by("id")]

    def test_every_event_keeps_the_violation_counter(self):
        self.violation("FOCUS_LOSS")
        self.violation("TAB_SWITCH")
        self.violation("FULLSCREEN_EXIT")  # doublon ignoré
        self.violation_later("WINDOW_RESIZE")
        self.violation_later("TAB_SWITCH")
        self.client.force_login(self.teacher)
        self.client.post(f"/teacher/attempts/{self.attempt.id}/authorize-resume/", {"reason": "Panne"})
        self.assertEqual(self.counters(), [
            ("FOCUS_LOSS", 0), ("TAB_SWITCH", 1), ("VIOLATION_IGNORED", 1),
            ("WINDOW_RESIZE", 1), ("TAB_SWITCH", 2), ("RESUME_AUTHORIZED", 0),
        ])


class ExamPageDeterrentTests(ExamFixture):
    def test_watermark_carries_identity_number_and_exam(self):
        User.objects.filter(pk=self.student.pk).update(first_name="Awa", last_name='<Ndiaye "A">')
        self.student.profile.student_number = "MAT-024"
        self.student.profile.save()
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(
            page, 'data-text="Awa &lt;Ndiaye &quot;A&quot;&gt; · MAT-024&#10;Sécurité" aria-hidden="true"')

    def test_rules_announce_what_is_logged(self):
        page = self.client.get(f"/attempt/{self.attempt.id}/")
        self.assertContains(page, "pertes de focus")
        self.assertContains(page, "filigrane")


class ReadOnlyAdminTests(ExamFixture):
    def setUp(self):
        super().setUp()
        self.answer_json()
        self.violation("TAB_SWITCH")
        self.response = Response.objects.get(attempt=self.attempt)
        self.event = SecurityEvent.objects.get(attempt=self.attempt)
        self.client.force_login(User.objects.create_superuser("root", password="StrongPass123!"))

    def test_logs_and_answers_can_be_read(self):
        for url in (f"/admin/qcm/securityevent/{self.event.id}/change/",
                    f"/admin/qcm/response/{self.response.id}/change/",
                    "/admin/qcm/securityevent/", "/admin/qcm/response/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_logs_and_answers_cannot_be_added_changed_or_deleted(self):
        for model, obj in (("securityevent", self.event), ("response", self.response)):
            base = f"/admin/qcm/{model}/"
            self.assertEqual(self.client.get(base + "add/").status_code, 403)
            self.assertEqual(self.client.post(f"{base}{obj.id}/change/", {}).status_code, 403)
            self.assertEqual(self.client.post(f"{base}{obj.id}/delete/", {"post": "yes"}).status_code, 403)
            self.client.post(base, {"action": "delete_selected", "_selected_action": [obj.id], "post": "yes"})
            self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())

    def test_deleting_the_attempt_cannot_erase_them(self):
        self.client.post(f"/admin/qcm/attempt/{self.attempt.id}/delete/", {"post": "yes"})
        self.assertTrue(Attempt.objects.filter(pk=self.attempt.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(pk=self.event.pk).exists())
        self.assertTrue(Response.objects.filter(pk=self.response.pk).exists())
