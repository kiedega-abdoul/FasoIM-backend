from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class JournalAction(models.Model):
    """Trace immuable des actions importantes exécutées dans FasoIM.

    Les entrées sont créées uniquement par ``JournalActionService`` ou par le
    middleware d'audit. L'API du module est strictement en lecture seule.
    """

    class Origine(models.TextChoices):
        ACTEUR = "ACTEUR", "Acteur interne"
        IMMERGE = "IMMERGE", "Immergé"
        SYSTEME = "SYSTEME", "Système"
        CELERY = "CELERY", "Tâche Celery"
        API_PUBLIQUE = "API_PUBLIQUE", "API publique"
        ADMIN = "ADMIN", "Administration Django"

    class Resultat(models.TextChoices):
        TENTATIVE = "TENTATIVE", "Tentative"
        SUCCES = "SUCCES", "Succès"
        REFUS = "REFUS", "Refus"
        ECHEC = "ECHEC", "Échec"
        PARTIEL = "PARTIEL", "Partiel"
        ANNULE = "ANNULE", "Annulé"

    class Canal(models.TextChoices):
        API = "API", "API interne"
        PORTAIL_PUBLIC = "PORTAIL_PUBLIC", "Portail public"
        EMAIL = "EMAIL", "E-mail"
        SMS = "SMS", "SMS"
        CELERY = "CELERY", "Celery"
        ADMIN = "ADMIN", "Administration Django"
        SYSTEME = "SYSTEME", "Système"
        EXPORT = "EXPORT", "Export"

    uuid_evenement = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    origine = models.CharField(max_length=30, choices=Origine.choices, db_index=True)
    resultat = models.CharField(max_length=20, choices=Resultat.choices, db_index=True)
    canal = models.CharField(
        max_length=30,
        choices=Canal.choices,
        default=Canal.SYSTEME,
        db_index=True,
    )

    acteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="journaux_actions",
        null=True,
        blank=True,
    )
    immerge = models.ForeignKey(
        "immerges.Immerge",
        on_delete=models.PROTECT,
        related_name="journaux_actions",
        null=True,
        blank=True,
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="journaux_actions",
        null=True,
        blank=True,
    )
    region = models.ForeignKey(
        "affectations.RegionImmersion",
        on_delete=models.PROTECT,
        related_name="journaux_actions",
        null=True,
        blank=True,
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="journaux_actions",
        null=True,
        blank=True,
    )

    code_action = models.CharField(max_length=140, db_index=True)
    module_source = models.CharField(max_length=80, db_index=True)
    motif = models.TextField(blank=True)

    objet_type = models.CharField(max_length=120, blank=True, db_index=True)
    objet_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    objet_reference = models.CharField(max_length=180, blank=True)

    contexte = models.JSONField(default=dict, blank=True)

    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    methode_http = models.CharField(max_length=12, blank=True)
    chemin_api = models.CharField(max_length=500, blank=True)
    statut_http = models.PositiveSmallIntegerField(null=True, blank=True)
    duree_ms = models.PositiveIntegerField(null=True, blank=True)
    task_id = models.CharField(max_length=80, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "journaux_actions"
        verbose_name = "journal d'action"
        verbose_name_plural = "journaux d'actions"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["region", "created_at"]),
            models.Index(fields=["centre", "created_at"]),
            models.Index(fields=["acteur", "created_at"]),
            models.Index(fields=["immerge", "created_at"]),
            models.Index(fields=["module_source", "code_action", "created_at"]),
            models.Index(fields=["origine", "resultat", "created_at"]),
            models.Index(fields=["objet_type", "objet_id"]),
        ]

    def __str__(self):
        return f"{self.code_action} - {self.resultat} - {self.created_at:%Y-%m-%d %H:%M:%S}"

    def clean(self):
        if not self.code_action.strip():
            raise ValidationError({"code_action": "Le code de l'action est obligatoire."})
        if not self.module_source.strip():
            raise ValidationError({"module_source": "Le module source est obligatoire."})

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_autoriser_modification_interne", False):
            raise ValidationError("Un journal d'audit est immuable et ne peut pas être modifié.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Un journal d'audit ne peut pas être supprimé.")
