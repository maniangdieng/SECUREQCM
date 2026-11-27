"""
Vues de Secure QCM, découpées par espace fonctionnel :

- auth.py        connexion unifiée, inscription étudiant
- admin.py       espace (super-)administrateur
- classrooms.py  classes façon Google Classroom
- teacher.py     examens et questions côté enseignant
- imports.py     import de sujets PDF / Word / Excel
- student.py     tableau de bord étudiant, code d'examen
- attempts.py    passage de l'examen (chronomètre, sécurité)
- results.py     résultats, copies, export CSV
"""
from .auth import UnifiedLoginView, home, student_register  # noqa: F401
from .admin import (admin_dashboard, admin_users, admin_set_role, admin_toggle_active,  # noqa: F401
                    admin_delete_exam, admin_normal_delete_exam, admin_create_user, admin_journal)
from .classrooms import (create_classroom, classroom_detail, update_classroom, regenerate_class_code,  # noqa: F401
                         archive_classroom, delete_classroom, add_coteacher, add_students_to_classroom,
                         remove_classroom_member, join_classroom, leave_classroom)
from .teacher import (teacher_dashboard, create_exam, update_exam_duration, delete_exam, teacher_exam,  # noqa: F401
                      add_question, delete_question, publish_exam, import_exam_students,
                      update_exam_settings, close_exam, archive_exam, add_exam_student)
from .imports import import_qcm, import_qcm_preview  # noqa: F401
from .student import student_dashboard, join_exam_by_code  # noqa: F401
from .attempts import (start_exam, take_exam, submit_answer_api, save_answer, security_event,  # noqa: F401
                       authorize_resume, advance, close_attempt, finished_score_context)
from .results import exam_results, attempt_result_detail, export_exam_results, print_exam_results  # noqa: F401
from ..services import calculate_score, question_time_seconds  # noqa: F401  (compatibilité avec l'ancien import)
