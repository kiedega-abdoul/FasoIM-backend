from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ArticleKit(models.Model):
    """Article officiel à apporter ou à remettre pendant une session."""

    class TypeKit(models.TextChoices):
        A_APPORTER = "A_APPORTER", "À apporter"
        A_REMETTRE = "A_REMETTRE", "À remettre"

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        INACTIF = "INACTIF", "Inactif"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="articles_kit",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="articles_kit",
        help_text=(
            "Laisser vide pour un article valable dans tous les centres "
            "de la session."
        ),
    )

    designation = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    type_kit = models.CharField(
        max_length=20,
        choices=TypeKit.choices,
        db_index=True,
    )
    quantite = models.PositiveIntegerField(
        default=1,
        help_text="Quantité prévue par immergé.",
    )
    unite = models.CharField(
        max_length=50,
        default="unité",
    )
    obligatoire = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIF,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "articles_kit"
        verbose_name = "Article de kit"
        verbose_name_plural = "Articles de kit"
        ordering = [
            "session_id",
            "centre_id",
            "ordre",
            "designation",
        ]
        indexes = [
            models.Index(
                fields=["session", "type_kit", "statut"],
                name="kit_art_sess_type_stat",
            ),
            models.Index(
                fields=["centre", "type_kit", "statut"],
                name="kit_art_ctr_type_stat",
            ),
            models.Index(
                fields=["deleted_at", "statut"],
                name="kit_art_del_stat",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite__gte=1),
                name="kit_art_qte_gt_zero",
            ),
            models.UniqueConstraint(
                fields=[
                    "session",
                    "designation",
                    "type_kit",
                ],
                condition=models.Q(
                    centre__isnull=True,
                    deleted_at__isnull=True,
                ),
                name="uniq_kit_art_global",
            ),
            models.UniqueConstraint(
                fields=[
                    "session",
                    "centre",
                    "designation",
                    "type_kit",
                ],
                condition=models.Q(
                    centre__isnull=False,
                    deleted_at__isnull=True,
                ),
                name="uniq_kit_art_centre",
            ),
        ]

    def __str__(self):
        portee = self.centre.nom if self.centre_id else "Tous les centres"
        return (
            f"{self.designation} - "
            f"{self.get_type_kit_display()} - {portee}"
        )

    @property
    def est_actif(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.ACTIF
        )

    @property
    def est_a_apporter(self):
        return self.type_kit == self.TypeKit.A_APPORTER

    @property
    def est_a_remettre(self):
        return self.type_kit == self.TypeKit.A_REMETTRE

    def applicable_au_centre(self, centre_id):
        return (
            self.centre_id is None
            or self.centre_id == centre_id
        )

    def clean(self):
        erreurs = {}

        self.designation = (self.designation or "").strip()
        self.unite = (self.unite or "").strip()

        if not self.designation:
            erreurs["designation"] = (
                "La désignation de l'article est obligatoire."
            )

        if not self.unite:
            erreurs["unite"] = "L'unité est obligatoire."

        if self.quantite is not None and self.quantite < 1:
            erreurs["quantite"] = (
                "La quantité doit être supérieure ou égale à 1."
            )

        if (
            self.session_id
            and self.statut == self.Statut.ACTIF
            and not self.session.est_active
        ):
            erreurs["session"] = (
                "Un article actif exige une session active."
            )

        if (
            self.centre_id
            and self.statut == self.Statut.ACTIF
            and not self.centre.est_actif
        ):
            erreurs["centre"] = (
                "Un article actif exige un centre actif."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def desactiver(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.INACTIF
        self.save(
            update_fields=[
                "statut",
                "updated_at",
            ]
        )
        return self

    def reactiver(self):
        if self.deleted_at is not None:
            raise ValidationError(
                "Un article supprimé ne peut pas être réactivé."
            )

        self.statut = self.Statut.ACTIF
        self.save(
            update_fields=[
                "statut",
                "updated_at",
            ]
        )
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.INACTIF
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "deleted_at",
                "updated_at",
            ]
        )
        return self


class RemiseKit(models.Model):
    """Trace un article réellement remis à un immergé."""

    class StatutRemise(models.TextChoices):
        REMIS = "REMIS", "Remis"
        PARTIEL = "PARTIEL", "Partiel"
        NON_REMIS = "NON_REMIS", "Non remis"
        REMPLACE = "REMPLACE", "Remplacé"
        DISPENSE = "DISPENSE", "Dispensé"

    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="remises_kit",
    )
    article_kit = models.ForeignKey(
        ArticleKit,
        on_delete=models.PROTECT,
        related_name="remises",
    )

    quantite_prevue = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Copie de la quantité prévue au moment de la remise."
        ),
    )
    quantite_remise = models.PositiveIntegerField(default=0)
    statut_remise = models.CharField(
        max_length=20,
        choices=StatutRemise.choices,
        default=StatutRemise.NON_REMIS,
        db_index=True,
    )
    observations = models.TextField(blank=True)

    remis_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="remises_kit_effectuees",
    )
    date_remise = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "remises_kit"
        verbose_name = "Remise de kit"
        verbose_name_plural = "Remises de kits"
        ordering = ["-date_remise", "-id"]
        indexes = [
            models.Index(
                fields=[
                    "affectation_centre",
                    "statut_remise",
                ],
                name="kit_rem_aff_stat",
            ),
            models.Index(
                fields=["article_kit", "statut_remise"],
                name="kit_rem_art_stat",
            ),
            models.Index(
                fields=["date_remise", "deleted_at"],
                name="kit_rem_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "affectation_centre",
                    "article_kit",
                ],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_remise_kit_active",
            ),
            models.CheckConstraint(
                condition=models.Q(quantite_prevue__gte=1),
                name="kit_rem_qte_prev_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    quantite_remise__lte=models.F(
                        "quantite_prevue"
                    )
                ),
                name="kit_rem_qte_lte_prev",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        statut_remise="REMIS",
                        quantite_remise=models.F(
                            "quantite_prevue"
                        ),
                    )
                    | models.Q(
                        statut_remise="PARTIEL",
                        quantite_remise__gt=0,
                        quantite_remise__lt=models.F(
                            "quantite_prevue"
                        ),
                    )
                    | models.Q(
                        statut_remise="NON_REMIS",
                        quantite_remise=0,
                    )
                    | models.Q(
                        statut_remise="DISPENSE",
                        quantite_remise=0,
                    )
                    | models.Q(
                        statut_remise="REMPLACE",
                        quantite_remise__gt=0,
                        quantite_remise__lte=models.F(
                            "quantite_prevue"
                        ),
                    )
                ),
                name="kit_rem_stat_qte_ok",
            ),
        ]

    def __str__(self):
        immerge = self.affectation_centre.immerge
        code = (
            getattr(immerge, "code_fasoim", None)
            or str(immerge.id)
        )
        return (
            f"{code} - {self.article_kit.designation} - "
            f"{self.get_statut_remise_display()}"
        )

    @property
    def est_active(self):
        return self.deleted_at is None

    @property
    def est_complete(self):
        return (
            self.deleted_at is None
            and self.statut_remise
            in {
                self.StatutRemise.REMIS,
                self.StatutRemise.REMPLACE,
                self.StatutRemise.DISPENSE,
            }
        )

    def clean(self):
        erreurs = {}

        if self.affectation_centre_id and self.deleted_at is None:
            affectation = self.affectation_centre

            if not affectation.est_active:
                erreurs["affectation_centre"] = (
                    "La remise exige une affectation centre active."
                )

        if self.article_kit_id and self.deleted_at is None:
            article = self.article_kit

            if not article.est_actif:
                erreurs["article_kit"] = (
                    "La remise exige un article actif."
                )

            if not article.est_a_remettre:
                erreurs["article_kit"] = (
                    "Seuls les articles de type À REMETTRE "
                    "peuvent être distribués."
                )

        if self.affectation_centre_id and self.article_kit_id:
            affectation = self.affectation_centre
            article = self.article_kit

            if affectation.session_id != article.session_id:
                erreurs["article_kit"] = (
                    "L'article et l'affectation doivent appartenir "
                    "à la même session."
                )

            if (
                article.centre_id is not None
                and article.centre_id != affectation.centre_id
            ):
                erreurs["article_kit"] = (
                    "Cet article est réservé à un autre centre."
                )

        if (
            self.quantite_prevue is not None
            and self.quantite_prevue < 1
        ):
            erreurs["quantite_prevue"] = (
                "La quantité prévue doit être supérieure "
                "ou égale à 1."
            )

        if (
            self.quantite_prevue is not None
            and self.quantite_remise is not None
            and self.quantite_remise > self.quantite_prevue
        ):
            erreurs["quantite_remise"] = (
                "La quantité remise ne peut pas dépasser "
                "la quantité prévue."
            )

        if self.statut_remise == self.StatutRemise.REMIS:
            if self.quantite_remise != self.quantite_prevue:
                erreurs["quantite_remise"] = (
                    "Une remise complète exige la totalité "
                    "de la quantité prévue."
                )

        elif self.statut_remise == self.StatutRemise.PARTIEL:
            if not (
                0 < self.quantite_remise < self.quantite_prevue
            ):
                erreurs["quantite_remise"] = (
                    "Une remise partielle exige une quantité "
                    "strictement comprise entre 0 et la quantité prévue."
                )

        elif self.statut_remise in {
            self.StatutRemise.NON_REMIS,
            self.StatutRemise.DISPENSE,
        }:
            if self.quantite_remise != 0:
                erreurs["quantite_remise"] = (
                    "Ce statut exige une quantité remise égale à 0."
                )

        elif self.statut_remise == self.StatutRemise.REMPLACE:
            if not (
                0 < self.quantite_remise <= self.quantite_prevue
            ):
                erreurs["quantite_remise"] = (
                    "Un remplacement exige une quantité positive "
                    "ne dépassant pas la quantité prévue."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if (
            self.article_kit_id
            and not self.quantite_prevue
        ):
            self.quantite_prevue = self.article_kit.quantite

        self.observations = (self.observations or "").strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def enregistrer_quantite(
        self,
        quantite,
        *,
        acteur=None,
        observations="",
    ):
        quantite = int(quantite)

        if quantite < 0:
            raise ValidationError(
                "La quantité remise ne peut pas être négative."
            )

        if quantite > self.quantite_prevue:
            raise ValidationError(
                "La quantité remise dépasse la quantité prévue."
            )

        self.quantite_remise = quantite
        self.remis_par = acteur or self.remis_par
        self.observations = observations or self.observations
        self.date_remise = timezone.now()

        if quantite == 0:
            self.statut_remise = self.StatutRemise.NON_REMIS
        elif quantite < self.quantite_prevue:
            self.statut_remise = self.StatutRemise.PARTIEL
        else:
            self.statut_remise = self.StatutRemise.REMIS

        self.save()
        return self

    def marquer_remplace(
        self,
        quantite,
        *,
        acteur=None,
        observations="",
    ):
        self.quantite_remise = int(quantite)
        self.statut_remise = self.StatutRemise.REMPLACE
        self.remis_par = acteur or self.remis_par
        self.observations = observations or self.observations
        self.date_remise = timezone.now()
        self.save()
        return self

    def marquer_dispense(
        self,
        *,
        acteur=None,
        observations="",
    ):
        self.quantite_remise = 0
        self.statut_remise = self.StatutRemise.DISPENSE
        self.remis_par = acteur or self.remis_par
        self.observations = observations or self.observations
        self.date_remise = timezone.now()
        self.save()
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "deleted_at",
                "updated_at",
            ]
        )
        return self
