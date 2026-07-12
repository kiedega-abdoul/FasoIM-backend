from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AlerteIncident(models.Model):
    """Alerte automatique ou incident signalé dans FasoIM.

    Le modèle conserve une seule table métier. Les détails techniques variables
    des détecteurs sont rangés dans ``contexte`` afin d'éviter une collection de
    colonnes rarement utilisées. Les utilisateurs ne remplissent jamais ces
    champs techniques.
    """

    class Type(models.TextChoices):
        ALERTE = "ALERTE", "Alerte"
        INCIDENT = "INCIDENT", "Incident"

    class Origine(models.TextChoices):
        AUTOMATIQUE = "AUTOMATIQUE", "Automatique"
        MANUELLE = "MANUELLE", "Manuelle"
        SYSTEME_SECURITE = "SYSTEME_SECURITE", "Système / sécurité"

    class TypeConcerne(models.TextChoices):
        IMMERGE = "IMMERGE", "Immergé"
        ACTEUR = "ACTEUR", "Acteur interne"
        CENTRE = "CENTRE", "Centre"
        SESSION = "SESSION", "Session"
        DONNEE = "DONNEE", "Donnée métier"
        SYSTEME = "SYSTEME", "Système"

    class Categorie(models.TextChoices):
        SECURITE_ACCES = "SECURITE_ACCES", "Sécurité et accès"
        AFFECTATION = "AFFECTATION", "Affectation"
        ORGANISATION = "ORGANISATION", "Organisation"
        IMPORT = "IMPORT", "Import"
        SANTE = "SANTE", "Santé / accident"
        DISCIPLINE = "DISCIPLINE", "Discipline"
        LOGISTIQUE = "LOGISTIQUE", "Logistique"
        KIT = "KIT", "Kit"
        ACTIVITE = "ACTIVITE", "Activité / présence"
        REPAS = "REPAS", "Repas"
        SESSION = "SESSION", "Session"
        SYSTEME = "SYSTEME", "Système"
        AUTRE = "AUTRE", "Autre"

    class NiveauGravite(models.TextChoices):
        FAIBLE = "FAIBLE", "Faible"
        MOYEN = "MOYEN", "Moyen"
        ELEVE = "ELEVE", "Élevé"
        CRITIQUE = "CRITIQUE", "Critique"

    class Statut(models.TextChoices):
        NOUVEAU = "NOUVEAU", "Nouveau"
        EN_COURS = "EN_COURS", "En cours"
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        RESOLU = "RESOLU", "Résolu"
        CLOTURE = "CLOTURE", "Clôturé"
        ANNULE = "ANNULE", "Annulé"

    class Confidentialite(models.TextChoices):
        NORMALE = "NORMALE", "Normale"
        RESTREINTE = "RESTREINTE", "Restreinte"
        MEDICALE = "MEDICALE", "Médicale"

    STATUTS_OUVERTS = (
        Statut.NOUVEAU,
        Statut.EN_COURS,
        Statut.EN_ATTENTE,
    )

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="alertes_incidents",
        null=True,
        blank=True,
    )
    region = models.ForeignKey(
        "affectations.RegionImmersion",
        on_delete=models.PROTECT,
        related_name="alertes_incidents",
        null=True,
        blank=True,
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="alertes_incidents",
        null=True,
        blank=True,
    )
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="alertes_incidents",
        null=True,
        blank=True,
    )
    acteur_concerne = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incidents_le_concernant",
        null=True,
        blank=True,
    )

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.ALERTE,
        db_index=True,
    )
    origine = models.CharField(
        max_length=30,
        choices=Origine.choices,
        default=Origine.MANUELLE,
        db_index=True,
    )
    type_concerne = models.CharField(
        max_length=20,
        choices=TypeConcerne.choices,
        default=TypeConcerne.DONNEE,
        db_index=True,
    )
    categorie = models.CharField(
        max_length=30,
        choices=Categorie.choices,
        default=Categorie.AUTRE,
        db_index=True,
    )

    titre = models.CharField(max_length=255)
    description = models.TextField()
    niveau_gravite = models.CharField(
        max_length=20,
        choices=NiveauGravite.choices,
        default=NiveauGravite.MOYEN,
        db_index=True,
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.NOUVEAU,
        db_index=True,
    )
    niveau_confidentialite = models.CharField(
        max_length=20,
        choices=Confidentialite.choices,
        default=Confidentialite.NORMALE,
        db_index=True,
    )

    code_detection = models.CharField(max_length=100, blank=True, db_index=True)
    module_source = models.CharField(max_length=80, blank=True, db_index=True)
    modele_source = models.CharField(max_length=100, blank=True)
    objet_source_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    cle_deduplication = models.CharField(max_length=255, blank=True, db_index=True)
    contexte = models.JSONField(default=dict, blank=True)

    est_bloquante = models.BooleanField(default=False, db_index=True)
    resolution_automatique = models.BooleanField(default=False)

    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="incidents_signales",
        null=True,
        blank=True,
    )
    traite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="incidents_traites",
        null=True,
        blank=True,
    )

    nombre_occurrences = models.PositiveIntegerField(default=1)
    niveau_escalade = models.PositiveSmallIntegerField(default=0)
    date_premiere_detection = models.DateTimeField(null=True, blank=True)
    date_derniere_detection = models.DateTimeField(null=True, blank=True, db_index=True)
    date_derniere_escalade = models.DateTimeField(null=True, blank=True)

    date_signalement = models.DateTimeField(default=timezone.now, db_index=True)
    date_prise_en_charge = models.DateTimeField(null=True, blank=True)
    date_resolution = models.DateTimeField(null=True, blank=True)
    date_cloture = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)
    observations = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "alertes_incidents"
        verbose_name = "alerte ou incident"
        verbose_name_plural = "alertes et incidents"
        ordering = ["-date_signalement", "-id"]
        indexes = [
            models.Index(fields=["session", "centre", "statut"], name="inc_ses_ctr_stat_idx"),
            models.Index(fields=["session", "region", "statut"], name="inc_ses_reg_stat_idx"),
            models.Index(fields=["categorie", "niveau_gravite", "statut"], name="inc_cat_grav_stat_idx"),
            models.Index(fields=["origine", "module_source", "statut"], name="inc_org_mod_stat_idx"),
            models.Index(fields=["cree_par", "date_signalement"], name="inc_createur_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cle_deduplication"],
                condition=(
                    Q(deleted_at__isnull=True)
                    & ~Q(cle_deduplication="")
                    & Q(statut__in=["NOUVEAU", "EN_COURS", "EN_ATTENTE"])
                ),
                name="uniq_incident_auto_ouvert_cle",
            ),
            models.CheckConstraint(
                condition=Q(nombre_occurrences__gte=1),
                name="incident_occurrences_positives",
            ),
        ]

    def __str__(self):
        return f"{self.get_niveau_gravite_display()} - {self.titre}"

    @property
    def est_ouvert(self):
        return self.deleted_at is None and self.statut in self.STATUTS_OUVERTS

    @property
    def est_automatique(self):
        return self.origine in {
            self.Origine.AUTOMATIQUE,
            self.Origine.SYSTEME_SECURITE,
        }

    def clean(self):
        erreurs = {}

        if self.centre_id and self.region_id and self.centre.region_id != self.region_id:
            erreurs["region"] = "La région doit correspondre à celle du centre."

        if self.affectation_centre_id:
            if self.session_id and self.affectation_centre.session_id != self.session_id:
                erreurs["session"] = "La session doit correspondre à l'affectation centre."
            if self.centre_id and self.affectation_centre.centre_id != self.centre_id:
                erreurs["centre"] = "Le centre doit correspondre à l'affectation centre."
            if self.region_id and self.affectation_centre.centre.region_id != self.region_id:
                erreurs["region"] = "La région doit correspondre à celle de l'affectation centre."

        if self.origine == self.Origine.MANUELLE:
            if not self.cree_par_id:
                erreurs["cree_par"] = "L'acteur qui signale est obligatoire."
            if not any(
                [
                    self.session_id,
                    self.centre_id,
                    self.affectation_centre_id,
                    self.acteur_concerne_id,
                ]
            ):
                erreurs["type_concerne"] = "Un élément concerné est obligatoire."
            if len((self.description or "").strip()) < 10:
                erreurs["description"] = "La raison doit contenir au moins 10 caractères."
            if self.niveau_confidentialite == self.Confidentialite.NORMALE:
                erreurs["niveau_confidentialite"] = (
                    "Un signalement manuel doit être au minimum restreint."
                )

        if self.est_automatique and not self.cle_deduplication:
            erreurs["cle_deduplication"] = (
                "Une alerte automatique doit avoir une clé de déduplication."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self
        etait_ouvert = self.statut in self.STATUTS_OUVERTS
        self.deleted_at = timezone.now()
        champs = ["deleted_at", "updated_at"]
        if etait_ouvert:
            self.statut = self.Statut.ANNULE
            champs.append("statut")
        self.save(update_fields=champs)
        return self
