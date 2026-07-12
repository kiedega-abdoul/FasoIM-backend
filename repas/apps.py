from django.apps import AppConfig


class RepasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "repas"

    def ready(self):
        from . import signals  # noqa: F401
