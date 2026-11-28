from django.apps import AppConfig
class QcmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "qcm"
    def ready(self):
        import qcm.signals  # noqa: F401  (enregistre les signaux)
        import qcm.google  # noqa: F401  (idem, connexion avec Google)
