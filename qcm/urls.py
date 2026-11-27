from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),

    # Comptes
    path("accounts/register/", views.student_register, name="student_register"),
    path("accounts/profile/", views.profile, name="profile"),

    # Administration
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/admin/users/", views.admin_users, name="admin_users"),
    path("dashboard/admin/users/new/", views.admin_create_user, name="admin_create_user"),
    path("dashboard/admin/journal/", views.admin_journal, name="admin_journal"),
    path("dashboard/admin/users/<int:user_id>/role/", views.admin_set_role, name="admin_set_role"),
    path("dashboard/admin/users/<int:user_id>/toggle-active/", views.admin_toggle_active, name="admin_toggle_active"),
    path("dashboard/admin/exams/<int:exam_id>/archive/", views.archive_exam, name="admin_archive_exam"),
    path("dashboard/admin/exams/<int:exam_id>/delete/", views.admin_normal_delete_exam, name="admin_normal_delete_exam"),
    path("dashboard/admin/exams/<int:exam_id>/delete-permanently/", views.admin_delete_exam, name="admin_delete_exam"),

    # Classes
    path("classes/create/", views.create_classroom, name="create_classroom"),
    path("classes/join/", views.join_classroom, name="join_classroom"),
    path("classes/<int:classroom_id>/", views.classroom_detail, name="classroom_detail"),
    path("classes/<int:classroom_id>/update/", views.update_classroom, name="update_classroom"),
    path("classes/<int:classroom_id>/regenerate-code/", views.regenerate_class_code, name="regenerate_class_code"),
    path("classes/<int:classroom_id>/archive/", views.archive_classroom, name="archive_classroom"),
    path("classes/<int:classroom_id>/delete/", views.delete_classroom, name="delete_classroom"),
    path("classes/<int:classroom_id>/teachers/add/", views.add_coteacher, name="add_coteacher"),
    path("classes/<int:classroom_id>/students/add/", views.add_students_to_classroom, name="add_students_to_classroom"),
    path("classes/<int:classroom_id>/members/<int:membership_id>/remove/", views.remove_classroom_member, name="remove_classroom_member"),
    path("classes/<int:classroom_id>/leave/", views.leave_classroom, name="leave_classroom"),

    # Enseignant
    path("dashboard/teacher/", views.teacher_dashboard, name="teacher_dashboard"),
    path("teacher/exams/create/", views.create_exam, name="create_exam"),
    path("teacher/exams/<int:exam_id>/", views.teacher_exam, name="teacher_exam"),
    path("teacher/exams/<int:exam_id>/duration/", views.update_exam_duration, name="update_exam_duration"),
    path("teacher/exams/<int:exam_id>/delete/", views.delete_exam, name="delete_exam"),
    path("teacher/exams/<int:exam_id>/settings/", views.update_exam_settings, name="update_exam_settings"),
    path("teacher/exams/<int:exam_id>/close/", views.close_exam, name="close_exam"),
    path("teacher/exams/<int:exam_id>/archive/", views.archive_exam, name="archive_exam"),
    path("teacher/exams/<int:exam_id>/question/add/", views.add_question, name="add_question"),
    path("teacher/exams/<int:exam_id>/question/<int:question_id>/delete/", views.delete_question, name="delete_question"),
    path("teacher/exams/<int:exam_id>/publish/", views.publish_exam, name="publish_exam"),
    path("teacher/exams/<int:exam_id>/students/import/", views.import_exam_students, name="import_exam_students"),
    path("teacher/exams/<int:exam_id>/students/add/", views.add_exam_student, name="add_exam_student"),
    path("teacher/exams/<int:exam_id>/results/", views.exam_results, name="exam_results"),
    path("teacher/exams/<int:exam_id>/results/export/", views.export_exam_results, name="export_exam_results"),
    path("teacher/exams/<int:exam_id>/results/export.xlsx", views.export_exam_results, {"fmt": "xlsx"},
         name="export_exam_results_xlsx"),
    path("teacher/exams/<int:exam_id>/results/print/", views.print_exam_results, name="print_exam_results"),
    path("teacher/attempts/<int:attempt_id>/results/", views.attempt_result_detail, name="attempt_result_detail"),
    path("teacher/attempts/<int:attempt_id>/authorize-resume/", views.authorize_resume, name="authorize_resume"),
    path("teacher/import-qcm/", views.import_qcm, name="import_qcm"),
    path("teacher/import-qcm/preview/", views.import_qcm_preview, name="import_qcm_preview"),

    # Étudiant
    path("dashboard/student/", views.student_dashboard, name="student_dashboard"),
    path("student/join-exam/", views.join_exam_by_code, name="join_exam_by_code"),
    path("student/exams/<int:exam_id>/start/", views.start_exam, name="start_exam"),
    path("attempt/<int:attempt_id>/", views.take_exam, name="take_exam"),
    path("attempt/<int:attempt_id>/answer.json", views.submit_answer_api, name="submit_answer_api"),
    path("attempt/<int:attempt_id>/save.json", views.save_answer, name="save_answer"),
    path("attempt/<int:attempt_id>/event/", views.security_event, name="security_event"),
]
