from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


STATUTS_AFFECTATION_GROUPE_OUVERTS = (
    "PROPOSEE",
    "ACTIVE",
    "A_REORGANISER",
)

STATUTS_ATTRIBUTION_LIT_OUVERTS = (
    "PROPOSEE",
    "ACTIVE",
    "A_REORGANISER",
)


class RegleOrganisationCentre(models.Model):
    """Règles locales d'un centre pour une session d'immersion.

    Les options générales, comme l'activation de l'hébergement ou de la visite
    médicale, restent portées par ParametreSession. Le Responsable de centre
    précise ici leur application locale : seuils de découpage, accueil,
    hébergement, kits à apporter, repas, horaires, discipline et consignes.
    """

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        EN_COURS = "EN_COURS", "Organisation en cours"
        VALIDEE = "VALIDEE", "Organisation validée"
        PRETE_PUBLICATION = "PRETE_PUBLICATION", "Prête pour publication"
        ARCHIVEE = "ARCHIVEE", "Archivée"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="regles_organisation_centres",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="regles_organisation",
    )
    
    capacite_ouverte = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text=(
            "Nombre maximal de places mises à disposition par le centre "
            "pour cette session."
        ),
    )

    seuil_division_sections = models.PositiveIntegerField(
        validators=[MinValueValidator(2)],
        help_text=(
            "À partir de cet effectif total, le système peut proposer "
            "plusieurs sections. En dessous, il crée une seule section."
        ),
    )
    capacite_max_section = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Capacité maximale autorisée pour une section.",
    )
    seuil_division_groupes = models.PositiveIntegerField(
        validators=[MinValueValidator(2)],
        help_text=(
            "À partir de cet effectif dans une section, le système peut "
            "proposer plusieurs groupes. En dessous, il crée un seul groupe."
        ),
    )
    capacite_max_groupe = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Capacité maximale autorisée pour un groupe.",
    )

    repartition_sections_groupes_automatique = models.BooleanField(
        default=True,
        help_text=(
            "Autorise le système à proposer automatiquement les sections, "
            "groupes et affectations internes."
        ),
    )
    attribution_lits_automatique = models.BooleanField(
        default=True,
        help_text=(
            "Autorise le système à proposer automatiquement les dortoirs "
            "et lits lorsque l'hébergement est activé dans la session."
        ),
    )

    lieu_accueil = models.CharField(max_length=255, blank=True)
    heure_accueil = models.TimeField(null=True, blank=True)
    horaires_generaux = models.TextField(blank=True)

    consignes_accueil = models.TextField(blank=True)
    consignes_hebergement = models.TextField(blank=True)
    consignes_kits_a_apporter = models.TextField(blank=True)
    consignes_repas = models.TextField(blank=True)
    regles_discipline = models.TextField(blank=True)
    consignes_internes = models.TextField(blank=True)
    directives_locales = models.TextField(blank=True)

    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regles_organisation_validees",
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    date_pret_publication = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Règle d'organisation de centre"
        verbose_name_plural = "Règles d'organisation des centres"
        ordering = ["-session__annee", "centre__nom", "-id"]
        indexes = [
            models.Index(fields=["session", "centre", "statut"]),
            models.Index(fields=["centre", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "centre"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_regle_org_session_centre_active",
            ),
        ]

    def __str__(self):
        return f"{self.session} - {self.centre.nom}"

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut != self.Statut.ARCHIVEE

    @property
    def est_validee(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.VALIDEE,
            self.Statut.PRETE_PUBLICATION,
        }

    @property
    def hebergement_active(self):
        parametres = getattr(self.session, "parametres", None)
        return bool(parametres and parametres.hebergement_active)

    @property
    def visite_medicale_active(self):
        parametres = getattr(self.session, "parametres", None)
        return bool(parametres and parametres.visite_medicale_active)

    def clean(self):
        erreurs = {}

        if self.centre_id and not self.centre.est_actif:
            erreurs["centre"] = "Le centre sélectionné n'est pas actif."

        if (
            self.capacite_max_section
            and self.capacite_ouverte
            and self.capacite_max_section > self.capacite_ouverte
        ):
            erreurs["capacite_max_section"] = (
                "La capacité maximale d'une section ne peut pas dépasser "
                "la capacité ouverte du centre pour cette session."
            )

        if (
            self.capacite_max_groupe
            and self.capacite_max_section
            and self.capacite_max_groupe > self.capacite_max_section
        ):
            erreurs["capacite_max_groupe"] = (
                "La capacité maximale d'un groupe ne peut pas dépasser "
                "celle d'une section."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def demarrer_organisation(self):
        if self.deleted_at is not None:
            raise ValidationError(
                "Une règle d'organisation archivée ne peut pas être démarrée."
            )

        if self.statut == self.Statut.BROUILLON:
            self.statut = self.Statut.EN_COURS
            self.save(update_fields=["statut", "updated_at"])
        return self

    def valider_organisation(self, validee_par=None):
        if self.deleted_at is not None:
            raise ValidationError(
                "Une règle d'organisation archivée ne peut pas être validée."
            )

        if self.statut not in {
            self.Statut.BROUILLON,
            self.Statut.EN_COURS,
            self.Statut.VALIDEE,
        }:
            raise ValidationError(
                "Cette organisation ne peut pas être validée dans son état actuel."
            )

        self.statut = self.Statut.VALIDEE
        self.validee_par = validee_par or self.validee_par
        self.date_validation = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                "statut",
                "validee_par",
                "date_validation",
                "updated_at",
            ]
        )
        return self

    def marquer_prete_publication(self):
        if not self.est_validee:
            raise ValidationError(
                "L'organisation doit être validée avant sa publication."
            )

        self.statut = self.Statut.PRETE_PUBLICATION
        self.date_pret_publication = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "date_pret_publication",
                "updated_at",
            ]
        )
        return self

    def supprimer_logiquement(self):
        if self.deleted_at:
            return self

        self.statut = self.Statut.ARCHIVEE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class Section(models.Model):
    """Grande unité d'organisation des immergés dans un centre."""

    class Statut(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DESACTIVEE = "DESACTIVEE", "Désactivée"
        ARCHIVEE = "ARCHIVEE", "Archivée"

    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="sections",
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="sections",
    )
    nom = models.CharField(max_length=150)
    code = models.CharField(max_length=50)
    capacite_max = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Section"
        verbose_name_plural = "Sections"
        ordering = ["session", "centre__nom", "code"]
        indexes = [
            models.Index(fields=["session", "centre", "statut"]),
            models.Index(fields=["code"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "centre", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_section_session_centre_code_active",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.nom}"

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    def clean(self):
        erreurs = {}

        if self.centre_id and not self.centre.est_actif:
            erreurs["centre"] = "Le centre de la section n'est pas actif."

        if erreurs:
            raise ValidationError(erreurs)

    def supprimer_logiquement(self):
        if self.deleted_at:
            return self

        if self.groupes.filter(deleted_at__isnull=True).exists():
            raise ValidationError(
                "Une section contenant encore des groupes ne peut pas être supprimée."
            )

        self.statut = self.Statut.ARCHIVEE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class Groupe(models.Model):
    """Sous-unité d'une section utilisée pour les activités et présences."""

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        DESACTIVE = "DESACTIVE", "Désactivé"
        ARCHIVE = "ARCHIVE", "Archivé"

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="groupes",
    )
    nom = models.CharField(max_length=150)
    code = models.CharField(max_length=50)
    capacite_max = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Groupe"
        verbose_name_plural = "Groupes"
        ordering = ["section__code", "code"]
        indexes = [
            models.Index(fields=["section", "statut"]),
            models.Index(fields=["code"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_groupe_section_code_active",
            ),
        ]

    def __str__(self):
        return f"{self.section.code} / {self.code} - {self.nom}"

    @property
    def est_actif(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIF

    def clean(self):
        erreurs = {}

        if self.section_id and not self.section.est_active:
            erreurs["section"] = "La section du groupe n'est pas active."

        if (
            self.section_id
            and self.capacite_max
            and self.capacite_max > self.section.capacite_max
        ):
            erreurs["capacite_max"] = (
                "La capacité du groupe ne peut pas dépasser celle de la section."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def supprimer_logiquement(self):
        if self.deleted_at:
            return self

        if self.affectations.filter(
            statut__in=STATUTS_AFFECTATION_GROUPE_OUVERTS,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Un groupe contenant encore des immergés ne peut pas être supprimé."
            )

        self.statut = self.Statut.ARCHIVE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class AffectationGroupe(models.Model):
    """Affectation interne fondée sur une affectation centre active."""

    class Statut(models.TextChoices):
        PROPOSEE = "PROPOSEE", "Proposée"
        ACTIVE = "ACTIVE", "Active"
        A_REORGANISER = "A_REORGANISER", "À réorganiser"
        REJETEE = "REJETEE", "Rejetée"
        ANNULEE = "ANNULEE", "Annulée"
        TRANSFEREE = "TRANSFEREE", "Transférée"

    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="affectations_groupes",
    )
    groupe = models.ForeignKey(
        Groupe,
        on_delete=models.PROTECT,
        related_name="affectations",
    )
    statut = models.CharField(
        max_length=25,
        choices=Statut.choices,
        default=Statut.PROPOSEE,
        db_index=True,
    )
    affecte_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="affectations_groupes_effectuees",
    )
    date_affectation = models.DateTimeField(default=timezone.now)
    observations = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Affectation à un groupe"
        verbose_name_plural = "Affectations aux groupes"
        ordering = ["-date_affectation", "-id"]
        indexes = [
            models.Index(fields=["affectation_centre", "statut"]),
            models.Index(fields=["groupe", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["affectation_centre"],
                condition=models.Q(
                    statut__in=[
                        "PROPOSEE",
                        "ACTIVE",
                        "A_REORGANISER",
                    ],
                    deleted_at__isnull=True,
                ),
                name="uniq_affectation_groupe_ouverte_centre",
            ),
        ]

    def __str__(self):
        return f"{self.affectation_centre.immerge} → {self.groupe}"

    @property
    def est_proposee(self):
        return self.deleted_at is None and self.statut == self.Statut.PROPOSEE

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    @property
    def est_a_reorganiser(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.A_REORGANISER
        )

    @property
    def est_ouverte(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.PROPOSEE,
            self.Statut.ACTIVE,
            self.Statut.A_REORGANISER,
        }

    def clean(self):
        erreurs = {}

        if (
            self.affectation_centre_id
            and not self.affectation_centre.est_active
        ):
            erreurs["affectation_centre"] = (
                "L'affectation au centre doit être active."
            )

        if self.groupe_id and not self.groupe.est_actif:
            erreurs["groupe"] = "Le groupe sélectionné n'est pas actif."

        if self.affectation_centre_id and self.groupe_id:
            section = self.groupe.section
            if section.centre_id != self.affectation_centre.centre_id:
                erreurs["groupe"] = (
                    "Le groupe doit appartenir au centre de l'immergé."
                )
            if section.session_id != self.affectation_centre.session_id:
                erreurs["groupe"] = (
                    "Le groupe doit appartenir à la session de l'immergé."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def valider(self, validee_par=None, observations: str = ""):
        if self.deleted_at is not None or self.statut not in {
            self.Statut.PROPOSEE,
            self.Statut.A_REORGANISER,
        }:
            raise ValidationError(
                "Seule une proposition ouverte ou une organisation à revoir "
                "peut être validée."
            )

        self.statut = self.Statut.ACTIVE
        self.affecte_par = validee_par or self.affecte_par
        self.date_affectation = timezone.now()
        self.observations = observations or self.observations
        self.full_clean()
        self.save(
            update_fields=[
                "statut",
                "affecte_par",
                "date_affectation",
                "observations",
                "updated_at",
            ]
        )
        return self

    def marquer_a_reorganiser(self, observations: str = ""):
        if not self.est_active:
            raise ValidationError(
                "Seule une affectation groupe active peut être réorganisée."
            )

        self.statut = self.Statut.A_REORGANISER
        self.observations = observations or self.observations
        self.save(
            update_fields=[
                "statut",
                "observations",
                "updated_at",
            ]
        )
        return self

    def rejeter(self, observations: str = ""):
        if not self.est_proposee:
            raise ValidationError(
                "Seule une proposition de groupe peut être rejetée."
            )

        self.statut = self.Statut.REJETEE
        self.observations = observations or self.observations
        self.save(
            update_fields=["statut", "observations", "updated_at"]
        )
        return self

    def annuler(self, observations: str = ""):
        self.statut = self.Statut.ANNULEE
        self.observations = observations or self.observations
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "observations",
                "deleted_at",
                "updated_at",
            ]
        )
        return self

    def transferer(self, observations: str = ""):
        self.statut = self.Statut.TRANSFEREE
        self.observations = observations or self.observations
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "observations",
                "deleted_at",
                "updated_at",
            ]
        )
        return self

    def supprimer_logiquement(self):
        return self.annuler(
            self.observations
            or "Suppression logique de l'affectation au groupe."
        )


class Dortoir(models.Model):
    """Espace physique d'hébergement d'un centre."""

    class SexeDortoir(models.TextChoices):
        MASCULIN = "MASCULIN", "Masculin"
        FEMININ = "FEMININ", "Féminin"

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        HORS_SERVICE = "HORS_SERVICE", "Hors service"
        ARCHIVE = "ARCHIVE", "Archivé"

    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="dortoirs",
    )
    nom = models.CharField(max_length=150)
    capacite = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    sexe_dortoir = models.CharField(
        max_length=20,
        choices=SexeDortoir.choices,
    )
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Dortoir"
        verbose_name_plural = "Dortoirs"
        ordering = ["centre__nom", "nom"]
        indexes = [
            models.Index(fields=["centre", "sexe_dortoir", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["centre", "nom"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_dortoir_centre_nom_active",
            ),
        ]

    def __str__(self):
        return f"{self.nom} - {self.centre.nom}"

    @property
    def est_actif(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIF

    def clean(self):
        erreurs = {}

        if self.centre_id and not self.centre.est_actif:
            erreurs["centre"] = "Le centre du dortoir n'est pas actif."

        if erreurs:
            raise ValidationError(erreurs)

    def mettre_hors_service(self):
        if AttributionLit.objects.filter(
            lit__dortoir=self,
            statut__in=STATUTS_ATTRIBUTION_LIT_OUVERTS,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Un dortoir ayant des attributions de lits ouvertes ne peut pas être mis hors service."
            )

        self.statut = self.Statut.HORS_SERVICE
        self.save(update_fields=["statut", "updated_at"])
        return self

    def reactiver(self):
        if self.deleted_at is not None:
            raise ValidationError(
                "Un dortoir archivé ne peut pas être réactivé directement."
            )

        self.statut = self.Statut.ACTIF
        self.full_clean()
        self.save(update_fields=["statut", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at:
            return self

        if self.lits.filter(deleted_at__isnull=True).exists():
            raise ValidationError(
                "Un dortoir contenant encore des lits ne peut pas être archivé."
            )

        self.statut = self.Statut.ARCHIVE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class Lit(models.Model):
    """Lit physique d'un dortoir.

    L'occupation n'est pas stockée ici. Elle est déterminée par une
    AttributionLit ouverte, ce qui évite les états contradictoires.
    """

    class Statut(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        HORS_SERVICE = "HORS_SERVICE", "Hors service"
        ARCHIVE = "ARCHIVE", "Archivé"

    dortoir = models.ForeignKey(
        Dortoir,
        on_delete=models.PROTECT,
        related_name="lits",
    )
    numero_lit = models.CharField(max_length=50)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.DISPONIBLE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Lit"
        verbose_name_plural = "Lits"
        ordering = ["dortoir__nom", "numero_lit"]
        indexes = [
            models.Index(fields=["dortoir", "statut"]),
            models.Index(fields=["numero_lit"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["dortoir", "numero_lit"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_lit_dortoir_numero_active",
            ),
        ]

    def __str__(self):
        return f"{self.dortoir.nom} / Lit {self.numero_lit}"

    @property
    def est_utilisable(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.DISPONIBLE
            and self.dortoir.est_actif
        )

    def clean(self):
        erreurs = {}

        if self.dortoir_id and not self.dortoir.est_actif:
            erreurs["dortoir"] = "Le dortoir du lit doit être actif."

        if self.dortoir_id:
            lits_existants = self.dortoir.lits.filter(deleted_at__isnull=True)
            if self.pk:
                lits_existants = lits_existants.exclude(pk=self.pk)
            if lits_existants.count() >= self.dortoir.capacite:
                erreurs["dortoir"] = (
                    "La capacité maximale de ce dortoir est déjà atteinte."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def mettre_hors_service(self):
        if self.attributions.filter(
            statut__in=STATUTS_ATTRIBUTION_LIT_OUVERTS,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Un lit possédant une attribution ouverte ne peut pas être mis hors service."
            )
        self.statut = self.Statut.HORS_SERVICE
        self.save(update_fields=["statut", "updated_at"])
        return self

    def reactiver(self):
        if self.deleted_at is not None:
            raise ValidationError(
                "Un lit archivé ne peut pas être réactivé directement."
            )
        if not self.dortoir.est_actif:
            raise ValidationError(
                "Le dortoir doit être actif avant de réactiver le lit."
            )

        self.statut = self.Statut.DISPONIBLE
        self.save(update_fields=["statut", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at:
            return self

        if self.attributions.filter(
            statut__in=STATUTS_ATTRIBUTION_LIT_OUVERTS,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Un lit possédant une attribution ouverte ne peut pas être archivé."
            )

        self.statut = self.Statut.ARCHIVE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class AttributionLit(models.Model):
    """Attribution historique d'un lit à une affectation centre."""

    class Statut(models.TextChoices):
        PROPOSEE = "PROPOSEE", "Proposée"
        ACTIVE = "ACTIVE", "Active"
        A_REORGANISER = "A_REORGANISER", "À réorganiser"
        REJETEE = "REJETEE", "Rejetée"
        LIBEREE = "LIBEREE", "Libérée"
        ANNULEE = "ANNULEE", "Annulée"
        TRANSFEREE = "TRANSFEREE", "Transférée"

    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="attributions_lits",
    )
    lit = models.ForeignKey(
        Lit,
        on_delete=models.PROTECT,
        related_name="attributions",
    )
    statut = models.CharField(
        max_length=25,
        choices=Statut.choices,
        default=Statut.PROPOSEE,
        db_index=True,
    )
    date_attribution = models.DateTimeField(default=timezone.now)
    date_liberation = models.DateTimeField(null=True, blank=True)
    attribue_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attributions_lits_effectuees",
    )
    observations = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Attribution de lit"
        verbose_name_plural = "Attributions de lits"
        ordering = ["-date_attribution", "-id"]
        indexes = [
            models.Index(fields=["affectation_centre", "statut"]),
            models.Index(fields=["lit", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["affectation_centre"],
                condition=models.Q(
                    statut__in=[
                        "PROPOSEE",
                        "ACTIVE",
                        "A_REORGANISER",
                    ],
                    deleted_at__isnull=True,
                ),
                name="uniq_attribution_lit_ouverte_centre",
            ),
            models.UniqueConstraint(
                fields=["lit"],
                condition=models.Q(
                    statut__in=[
                        "PROPOSEE",
                        "ACTIVE",
                        "A_REORGANISER",
                    ],
                    deleted_at__isnull=True,
                ),
                name="uniq_attribution_lit_ouverte_lit",
            ),
        ]

    def __str__(self):
        return f"{self.affectation_centre.immerge} → {self.lit}"

    @property
    def est_proposee(self):
        return self.deleted_at is None and self.statut == self.Statut.PROPOSEE

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    @property
    def est_a_reorganiser(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.A_REORGANISER
        )

    @property
    def est_ouverte(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.PROPOSEE,
            self.Statut.ACTIVE,
            self.Statut.A_REORGANISER,
        }

    def clean(self):
        erreurs = {}

        if (
            self.affectation_centre_id
            and not self.affectation_centre.est_active
        ):
            erreurs["affectation_centre"] = (
                "L'affectation au centre doit être active."
            )

        if self.lit_id and self.est_ouverte and not self.lit.est_utilisable:
            erreurs["lit"] = (
                "Le lit doit être disponible et appartenir à un dortoir actif."
            )

        if self.affectation_centre_id and self.lit_id:
            if self.lit.dortoir.centre_id != self.affectation_centre.centre_id:
                erreurs["lit"] = (
                    "Le lit doit appartenir au centre de l'immergé."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def valider(self, validee_par=None, observations: str = ""):
        if self.deleted_at is not None or self.statut not in {
            self.Statut.PROPOSEE,
            self.Statut.A_REORGANISER,
        }:
            raise ValidationError(
                "Seule une proposition ouverte ou une attribution à revoir "
                "peut être validée."
            )

        self.statut = self.Statut.ACTIVE
        self.attribue_par = validee_par or self.attribue_par
        self.date_attribution = timezone.now()
        self.date_liberation = None
        self.observations = observations or self.observations
        self.full_clean()
        self.save(
            update_fields=[
                "statut",
                "attribue_par",
                "date_attribution",
                "date_liberation",
                "observations",
                "updated_at",
            ]
        )
        return self

    def marquer_a_reorganiser(self, observations: str = ""):
        if not self.est_active:
            raise ValidationError(
                "Seule une attribution de lit active peut être réorganisée."
            )

        self.statut = self.Statut.A_REORGANISER
        self.observations = observations or self.observations
        self.save(
            update_fields=[
                "statut",
                "observations",
                "updated_at",
            ]
        )
        return self

    def rejeter(self, observations: str = ""):
        if not self.est_proposee:
            raise ValidationError(
                "Seule une proposition de lit peut être rejetée."
            )

        self.statut = self.Statut.REJETEE
        self.observations = observations or self.observations
        self.save(
            update_fields=["statut", "observations", "updated_at"]
        )
        return self

    def liberer(self, observations: str = ""):
        self.statut = self.Statut.LIBEREE
        self.date_liberation = timezone.now()
        self.observations = observations or self.observations
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "date_liberation",
                "observations",
                "deleted_at",
                "updated_at",
            ]
        )
        return self

    def annuler(self, observations: str = ""):
        self.statut = self.Statut.ANNULEE
        self.date_liberation = timezone.now()
        self.observations = observations or self.observations
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "date_liberation",
                "observations",
                "deleted_at",
                "updated_at",
            ]
        )
        return self

    def transferer(self, observations: str = ""):
        self.statut = self.Statut.TRANSFEREE
        self.date_liberation = timezone.now()
        self.observations = observations or self.observations
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "date_liberation",
                "observations",
                "deleted_at",
                "updated_at",
            ]
        )
        return self

    def supprimer_logiquement(self):
        return self.annuler(
            self.observations
            or "Suppression logique de l'attribution de lit."
        )
