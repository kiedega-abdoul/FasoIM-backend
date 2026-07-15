from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def brouiller_code_unique(code: str, prefixe: str = "SUPPRIME") -> str:
    """Brouille un code unique avant suppression logique.

    Le but est de libérer l'ancien code pour permettre une recréation future,
    sans supprimer physiquement la ligne historique.
    """

    base = (code or "CODE")[:25]
    suffixe = uuid4().hex[:10]
    return f"{base}__{prefixe}_{suffixe}"[:50]


class RegionImmersion(models.Model):
    """Référentiel des régions d'affectation des immergés."""

    class Statut(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DESACTIVEE = "DESACTIVEE", "Désactivée"

    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Code stable de la région, par exemple CENTRE ou HAUTS_BASSINS.",
    )
    nom = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Région d'immersion"
        verbose_name_plural = "Régions d'immersion"
        ordering = ["nom"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["statut", "deleted_at"]),
        ]

    def __str__(self):
        return f"{self.nom} ({self.code})"

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    def supprimer_logiquement(self):
        """Supprime logiquement une région seulement si elle n'est plus utilisée."""

        if self.deleted_at:
            return self

        if self.centres.filter(deleted_at__isnull=True).exists():
            raise ValidationError(
                "Une région contenant encore des centres ne peut pas être supprimée."
            )

        if self.affectations_regionales.filter(
            statut__in=["PROPOSEE", "ACTIVE"],
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Une région possédant des affectations ouvertes ne peut pas être supprimée."
            )

        self.code = brouiller_code_unique(self.code)
        self.statut = self.Statut.DESACTIVEE
        self.deleted_at = timezone.now()
        self.save(update_fields=["code", "statut", "deleted_at", "updated_at"])
        return self


class CentreImmersion(models.Model):
    """Référentiel des centres d'immersion rattachés à une région."""

    class Genre(models.TextChoices):
        MASCULIN = "MASCULIN", "Masculin"
        FEMININ = "FEMININ", "Féminin"
        MIXTE = "MIXTE", "Mixte"

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        DESACTIVE = "DESACTIVE", "Désactivé"
        ARCHIVE = "ARCHIVE", "Archivé"

    region = models.ForeignKey(
        RegionImmersion,
        on_delete=models.PROTECT,
        related_name="centres",
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Code unique du centre, par exemple CENTRE-001.",
    )
    nom = models.CharField(max_length=200)
    province = models.CharField(max_length=150)
    ville = models.CharField(max_length=150)
    adresse = models.TextField(blank=True)
    genre = models.CharField(
        max_length=20,
        choices=Genre.choices,
        default=Genre.MIXTE,
    )

    publics_acceptes = models.JSONField(
        default=list,
        blank=True,
        help_text="Liste des publics acceptés : BEPC, BAC, CONCOURS, SELECTIONNE, VOLONTAIRE.",
    )
    niveaux_acceptes = models.JSONField(
        default=list,
        blank=True,
        help_text="Liste des niveaux ou séries acceptés : BEPC, BAC, BAC_D, BAC_A, etc.",
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Centre d'immersion"
        verbose_name_plural = "Centres d'immersion"
        ordering = ["region__nom", "nom"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["region", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]

    def __str__(self):
        return f"{self.nom} - {self.region.nom}"

    @property
    def est_actif(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIF

    def clean(self):
        """Valide les champs JSON utilisés comme listes."""

        erreurs = {}

        if self.region_id and not self.region.est_active:
            erreurs["region"] = "Le centre doit appartenir à une région active."

        if self.publics_acceptes is not None and not isinstance(self.publics_acceptes, list):
            erreurs["publics_acceptes"] = "La valeur doit être une liste."

        if self.niveaux_acceptes is not None and not isinstance(self.niveaux_acceptes, list):
            erreurs["niveaux_acceptes"] = "La valeur doit être une liste."

        if erreurs:
            raise ValidationError(erreurs)

    def supprimer_logiquement(self):
        """Supprime logiquement le centre seulement si aucune dépendance ouverte ne subsiste."""

        if self.deleted_at:
            return self

        if self.affectations_centres.filter(
            statut__in=["PROPOSEE", "ACTIVE"],
            deleted_at__isnull=True,
        ).exists():
            raise ValidationError(
                "Un centre possédant des affectations ouvertes ne peut pas être supprimé."
            )

        if self.dortoirs.filter(deleted_at__isnull=True).exists():
            raise ValidationError(
                "Un centre contenant encore des dortoirs ne peut pas être supprimé."
            )

        self.code = brouiller_code_unique(self.code)
        self.statut = self.Statut.DESACTIVE
        self.deleted_at = timezone.now()
        self.save(update_fields=["code", "statut", "deleted_at", "updated_at"])
        return self


class AffectationRegionale(models.Model):
    """Affectation d'un immergé vers une région.

    Cette étape est normalement faite par la DGAS ou la coordination nationale.
    """

    class Statut(models.TextChoices):
        PROPOSEE = "PROPOSEE", "Proposée"
        ACTIVE = "ACTIVE", "Active"
        REJETEE = "REJETEE", "Rejetée"
        ANNULEE = "ANNULEE", "Annulée"
        TRANSFEREE = "TRANSFEREE", "Transférée"

    immerge = models.ForeignKey(
        "immerges.Immerge",
        on_delete=models.PROTECT,
        related_name="affectations_regionales",
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="affectations_regionales",
    )
    region = models.ForeignKey(
        RegionImmersion,
        on_delete=models.PROTECT,
        related_name="affectations_regionales",
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.PROPOSEE,
    )
    affecte_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="affectations_regionales_effectuees",
    )
    date_affectation = models.DateTimeField(default=timezone.now)
    motif = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Affectation régionale"
        verbose_name_plural = "Affectations régionales"
        ordering = ["-date_affectation", "-id"]
        indexes = [
            models.Index(fields=["session", "region", "statut"]),
            models.Index(fields=["immerge", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["immerge"],
                condition=models.Q(
                    statut__in=["PROPOSEE", "ACTIVE"],
                    deleted_at__isnull=True,
                ),
                name="unique_affectation_regionale_ouverte_par_immerge",
            ),
        ]

    def __str__(self):
        return f"{self.immerge} → {self.region.nom}"

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    @property
    def est_proposee(self):
        return self.deleted_at is None and self.statut == self.Statut.PROPOSEE

    @property
    def est_ouverte(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.PROPOSEE,
            self.Statut.ACTIVE,
        }

    def clean(self):
        """Vérifie que la session correspond à celle de l'immergé."""

        erreurs = {}

        if self.immerge_id and self.session_id and self.immerge.session_id != self.session_id:
            erreurs["session"] = "La session de l'affectation doit correspondre à la session de l'immergé."

        if self.region_id and not self.region.est_active:
            erreurs["region"] = "La région sélectionnée n'est pas active."

        if erreurs:
            raise ValidationError(erreurs)

    def valider(self, valide_par=None, motif: str = ""):
        """Transforme une proposition régionale en affectation active."""

        if self.statut == self.Statut.ACTIVE and self.deleted_at is None:
            return self

        if self.statut != self.Statut.PROPOSEE or self.deleted_at is not None:
            raise ValidationError(
                "Seule une proposition régionale ouverte peut être validée."
            )

        self.statut = self.Statut.ACTIVE
        self.affecte_par = valide_par or self.affecte_par
        self.date_affectation = timezone.now()
        self.motif = motif or self.motif
        self.full_clean()
        self.save(
            update_fields=[
                "statut",
                "affecte_par",
                "date_affectation",
                "motif",
                "updated_at",
            ]
        )
        return self

    def rejeter(self, motif: str = ""):
        """Rejette une proposition sans la supprimer de l'historique."""

        if self.statut == self.Statut.REJETEE and self.deleted_at is None:
            return self

        if self.statut != self.Statut.PROPOSEE or self.deleted_at is not None:
            raise ValidationError(
                "Seule une proposition régionale ouverte peut être rejetée."
            )

        self.statut = self.Statut.REJETEE
        self.motif = motif or self.motif
        self.save(update_fields=["statut", "motif", "updated_at"])
        return self

    def annuler(self, motif: str = ""):
        """Annule l'affectation régionale sans supprimer physiquement la ligne."""

        self.statut = self.Statut.ANNULEE
        self.motif = motif or self.motif
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "motif", "deleted_at", "updated_at"])
        return self

    def transferer(self, motif: str = ""):
        """Marque l'affectation comme transférée avant de créer une nouvelle affectation."""

        self.statut = self.Statut.TRANSFEREE
        self.motif = motif or self.motif
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "motif", "deleted_at", "updated_at"])
        return self

    def supprimer_logiquement(self):
        """Suppression logique simple depuis l'administration ou le service."""

        return self.annuler(motif=self.motif or "Suppression logique de l'affectation régionale.")


class AffectationCentre(models.Model):
    """Affectation d'un immergé vers un centre.

    Cette étape vient après l'affectation régionale.
    Le centre doit appartenir à la même région que l'affectation régionale.
    """

    class Statut(models.TextChoices):
        PROPOSEE = "PROPOSEE", "Proposée"
        ACTIVE = "ACTIVE", "Active"
        REJETEE = "REJETEE", "Rejetée"
        ANNULEE = "ANNULEE", "Annulée"
        TRANSFEREE = "TRANSFEREE", "Transférée"

    immerge = models.ForeignKey(
        "immerges.Immerge",
        on_delete=models.PROTECT,
        related_name="affectations_centres",
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="affectations_centres",
    )
    affectation_regionale = models.ForeignKey(
        AffectationRegionale,
        on_delete=models.PROTECT,
        related_name="affectations_centres",
    )
    centre = models.ForeignKey(
        CentreImmersion,
        on_delete=models.PROTECT,
        related_name="affectations_centres",
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.PROPOSEE,
    )
    affecte_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="affectations_centres_effectuees",
    )
    date_affectation = models.DateTimeField(default=timezone.now)
    motif = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Affectation centre"
        verbose_name_plural = "Affectations centres"
        ordering = ["-date_affectation", "-id"]
        indexes = [
            models.Index(fields=["session", "centre", "statut"]),
            models.Index(fields=["immerge", "statut"]),
            models.Index(fields=["deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["immerge"],
                condition=models.Q(
                    statut__in=["PROPOSEE", "ACTIVE"],
                    deleted_at__isnull=True,
                ),
                name="unique_affectation_centre_ouverte_par_immerge",
            ),
        ]

    def __str__(self):
        return f"{self.immerge} → {self.centre.nom}"

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut == self.Statut.ACTIVE

    @property
    def est_proposee(self):
        return self.deleted_at is None and self.statut == self.Statut.PROPOSEE

    @property
    def est_ouverte(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.PROPOSEE,
            self.Statut.ACTIVE,
        }

    def clean(self):
        """Vérifie la cohérence entre l'immergé, la session, la région et le centre."""

        erreurs = {}

        if self.immerge_id and self.session_id and self.immerge.session_id != self.session_id:
            erreurs["session"] = "La session de l'affectation centre doit correspondre à la session de l'immergé."

        if self.affectation_regionale_id:
            if self.affectation_regionale.immerge_id != self.immerge_id:
                erreurs["affectation_regionale"] = "L'affectation régionale ne correspond pas à cet immergé."

            if self.affectation_regionale.session_id != self.session_id:
                erreurs["affectation_regionale"] = "L'affectation régionale ne correspond pas à cette session."

            if self.affectation_regionale.statut != AffectationRegionale.Statut.ACTIVE:
                erreurs["affectation_regionale"] = "L'affectation régionale doit être active."

        if self.centre_id:
            if not self.centre.est_actif:
                erreurs["centre"] = "Le centre sélectionné n'est pas actif."

            if self.affectation_regionale_id and self.centre.region_id != self.affectation_regionale.region_id:
                erreurs["centre"] = "Le centre doit appartenir à la région de l'affectation régionale."

        if erreurs:
            raise ValidationError(erreurs)

    def valider(self, valide_par=None, motif: str = ""):
        """Transforme une proposition de centre en affectation active."""

        if self.statut == self.Statut.ACTIVE and self.deleted_at is None:
            return self

        if self.statut != self.Statut.PROPOSEE or self.deleted_at is not None:
            raise ValidationError(
                "Seule une proposition de centre ouverte peut être validée."
            )

        self.statut = self.Statut.ACTIVE
        self.affecte_par = valide_par or self.affecte_par
        self.date_affectation = timezone.now()
        self.motif = motif or self.motif
        self.full_clean()
        self.save(
            update_fields=[
                "statut",
                "affecte_par",
                "date_affectation",
                "motif",
                "updated_at",
            ]
        )
        return self

    def rejeter(self, motif: str = ""):
        """Rejette une proposition de centre sans la supprimer de l'historique."""

        if self.statut == self.Statut.REJETEE and self.deleted_at is None:
            return self

        if self.statut != self.Statut.PROPOSEE or self.deleted_at is not None:
            raise ValidationError(
                "Seule une proposition de centre ouverte peut être rejetée."
            )

        self.statut = self.Statut.REJETEE
        self.motif = motif or self.motif
        self.save(update_fields=["statut", "motif", "updated_at"])
        return self

    def annuler(self, motif: str = ""):
        """Annule l'affectation centre sans supprimer physiquement la ligne."""

        self.statut = self.Statut.ANNULEE
        self.motif = motif or self.motif
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "motif", "deleted_at", "updated_at"])
        return self

    def transferer(self, motif: str = ""):
        """Marque l'affectation comme transférée avant de créer une nouvelle affectation."""

        self.statut = self.Statut.TRANSFEREE
        self.motif = motif or self.motif
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "motif", "deleted_at", "updated_at"])
        return self

    def supprimer_logiquement(self):
        """Suppression logique simple depuis l'administration ou le service."""

        return self.annuler(motif=self.motif or "Suppression logique de l'affectation centre.")
