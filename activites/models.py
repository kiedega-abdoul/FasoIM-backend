from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class ModuleActivite(models.Model):
    """Catalogue réutilisable des activités FasoIM."""

    class Categorie(models.TextChoices):
        FORMATION = "FORMATION", "Formation"
        SENSIBILISATION = "SENSIBILISATION", "Sensibilisation"
        SPORT = "SPORT", "Sport"
        CIVISME = "CIVISME", "Civisme"
        DISCIPLINE = "DISCIPLINE", "Discipline"
        ORIENTATION = "ORIENTATION", "Orientation"
        CULTURE = "CULTURE", "Culture"
        AUTRE = "AUTRE", "Autre"

    class Statut(models.TextChoices):
        ACTIF = "ACTIF", "Actif"
        INACTIF = "INACTIF", "Inactif"

    titre = models.CharField(max_length=180)
    code = models.CharField(max_length=60)
    description = models.TextField(blank=True)
    categorie = models.CharField(
        max_length=30,
        choices=Categorie.choices,
        db_index=True,
    )
    duree_prevue = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Durée indicative de l'activité en minutes.",
    )
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
        db_table = "modules_activite"
        verbose_name = "Module d'activité"
        verbose_name_plural = "Modules d'activité"
        ordering = ["ordre", "categorie", "titre", "id"]
        indexes = [
            models.Index(
                fields=["categorie", "statut"],
                name="act_mod_cat_stat",
            ),
            models.Index(
                fields=["ordre", "statut"],
                name="act_mod_ordre_stat",
            ),
            models.Index(
                fields=["deleted_at", "statut"],
                name="act_mod_del_stat",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_module_activite_code_actif",
            ),
            models.UniqueConstraint(
                fields=["titre", "categorie"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_module_activite_titre_cat",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.titre}"

    @property
    def est_actif(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.ACTIF
        )

    def clean(self):
        erreurs = {}

        self.titre = (self.titre or "").strip()
        self.code = (self.code or "").strip().upper()
        self.description = (self.description or "").strip()

        if not self.titre:
            erreurs["titre"] = "Le titre du module est obligatoire."

        if not self.code:
            erreurs["code"] = "Le code du module est obligatoire."

        if (
            self.duree_prevue is not None
            and self.duree_prevue < 1
        ):
            erreurs["duree_prevue"] = (
                "La durée prévue doit être supérieure à zéro."
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
        self.save(update_fields=["statut", "updated_at"])
        return self

    def reactiver(self):
        if self.deleted_at is not None:
            raise ValidationError(
                "Un module supprimé ne peut pas être réactivé."
            )

        self.statut = self.Statut.ACTIF
        self.save(update_fields=["statut", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        suffixe = uuid4().hex[:10].upper()
        longueur_originale = max(1, 60 - len(suffixe) - 5)
        self.code = (
            f"{self.code[:longueur_originale]}-DEL-{suffixe}"
        )
        self.statut = self.Statut.INACTIF
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "code",
                "statut",
                "deleted_at",
                "updated_at",
            ]
        )
        return self


class Seance(models.Model):
    """Planification d'un module d'activité dans une session."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        PLANIFIEE = "PLANIFIEE", "Planifiée"
        EN_COURS = "EN_COURS", "En cours"
        TERMINEE = "TERMINEE", "Terminée"
        REPORTEE = "REPORTEE", "Reportée"
        ANNULEE = "ANNULEE", "Annulée"

    class StatutFeuillePresence(models.TextChoices):
        NON_OUVERTE = "NON_OUVERTE", "Non ouverte"
        OUVERTE = "OUVERTE", "Ouverte"
        VALIDEE = "VALIDEE", "Validée"
        CLOTUREE = "CLOTUREE", "Clôturée"

    module_activite = models.ForeignKey(
        ModuleActivite,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seances",
    )
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="seances_activite",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="seances_activite",
    )
    section = models.ForeignKey(
        "organisation.Section",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seances_activite",
    )
    groupe = models.ForeignKey(
        "organisation.Groupe",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seances_activite",
    )
    formateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="seances_animees",
    )

    titre = models.CharField(
        max_length=180,
        blank=True,
        default="",
    )
    date_seance = models.DateField(db_index=True)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    lieu = models.CharField(max_length=180)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    observations = models.TextField(blank=True)

    statut_feuille_presence = models.CharField(
        max_length=20,
        choices=StatutFeuillePresence.choices,
        default=StatutFeuillePresence.NON_OUVERTE,
        db_index=True,
    )
    date_ouverture_presence = models.DateTimeField(
        null=True,
        blank=True,
    )
    date_validation_presence = models.DateTimeField(
        null=True,
        blank=True,
    )
    date_cloture_presence = models.DateTimeField(
        null=True,
        blank=True,
    )
    presences_validees_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="feuilles_presence_validees",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "seances_activite"
        verbose_name = "Séance d'activité"
        verbose_name_plural = "Séances d'activité"
        ordering = [
            "date_seance",
            "heure_debut",
            "centre_id",
            "id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "session",
                    "centre",
                    "date_seance",
                    "statut",
                ],
                name="act_sea_sess_ctr_date",
            ),
            models.Index(
                fields=["formateur", "date_seance"],
                name="act_sea_form_date",
            ),
            models.Index(
                fields=["groupe", "date_seance"],
                name="act_sea_grp_date",
            ),
            models.Index(
                fields=["section", "date_seance"],
                name="act_sea_sec_date",
            ),
            models.Index(
                fields=["statut_feuille_presence", "date_seance"],
                name="act_sea_feuille_date",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    heure_fin__gt=models.F("heure_debut")
                ),
                name="act_seance_heure_fin_apres_debut",
            ),
        ]

    def __str__(self):
        titre = self.titre or (self.module_activite.titre if self.module_activite_id else "Séance")
        return (
            f"{titre} - "
            f"{self.date_seance} {self.heure_debut}"
        )

    @property
    def est_active(self):
        return (
            self.deleted_at is None
            and self.statut != self.Statut.ANNULEE
        )

    @property
    def niveau_cible(self):
        if self.groupe_id:
            return "GROUPE"
        if self.section_id:
            return "SECTION"
        return "CENTRE"

    @property
    def feuille_presence_modifiable(self):
        return self.statut_feuille_presence in {
            self.StatutFeuillePresence.NON_OUVERTE,
            self.StatutFeuillePresence.OUVERTE,
        }

    def clean(self):
        erreurs = {}

        self.titre = (self.titre or "").strip()
        self.lieu = (self.lieu or "").strip()
        self.observations = (self.observations or "").strip()

        if not self.lieu:
            erreurs["lieu"] = "Le lieu de la séance est obligatoire."

        if (
            self.heure_debut
            and self.heure_fin
            and self.heure_fin <= self.heure_debut
        ):
            erreurs["heure_fin"] = (
                "L'heure de fin doit être postérieure "
                "à l'heure de début."
            )

        if self.module_activite_id and not self.module_activite.est_actif:
            erreurs["module_activite"] = (
                "Le module d'activité doit être actif."
            )

        if self.session_id and self.deleted_at is None:
            try:
                parametres = self.session.parametres
            except Exception:
                parametres = None

            if (
                parametres is not None
                and not parametres.activites_active
            ):
                erreurs["session"] = (
                    "Le module activités est désactivé "
                    "pour cette session."
                )

        if self.section_id:
            if self.section.centre_id != self.centre_id:
                erreurs["section"] = (
                    "La section doit appartenir au centre "
                    "de la séance."
                )
            if self.section.session_id != self.session_id:
                erreurs["section"] = (
                    "La section doit appartenir à la session "
                    "de la séance."
                )

        if self.groupe_id:
            if self.groupe.section.centre_id != self.centre_id:
                erreurs["groupe"] = (
                    "Le groupe doit appartenir au centre "
                    "de la séance."
                )
            if self.groupe.section.session_id != self.session_id:
                erreurs["groupe"] = (
                    "Le groupe doit appartenir à la session "
                    "de la séance."
                )
            if (
                self.section_id
                and self.groupe.section_id != self.section_id
            ):
                erreurs["groupe"] = (
                    "Le groupe doit appartenir à la section "
                    "sélectionnée."
                )

        if (
            self.date_validation_presence
            and not self.date_ouverture_presence
        ):
            erreurs["date_validation_presence"] = (
                "La feuille doit être ouverte avant sa validation."
            )

        if (
            self.date_cloture_presence
            and not self.date_validation_presence
        ):
            erreurs["date_cloture_presence"] = (
                "La feuille doit être validée avant sa clôture."
            )

        if (
            self.date_ouverture_presence
            and self.date_validation_presence
            and self.date_validation_presence
            < self.date_ouverture_presence
        ):
            erreurs["date_validation_presence"] = (
                "La validation ne peut pas précéder l'ouverture."
            )

        if (
            self.date_validation_presence
            and self.date_cloture_presence
            and self.date_cloture_presence
            < self.date_validation_presence
        ):
            erreurs["date_cloture_presence"] = (
                "La clôture ne peut pas précéder la validation."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if not (self.titre or "").strip() and self.module_activite_id:
            self.titre = self.module_activite.titre

        self.full_clean()
        super().save(*args, **kwargs)

    def annuler(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.ANNULEE
        self.save(update_fields=["statut", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.ANNULEE
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "deleted_at",
                "updated_at",
            ]
        )
        return self


class Presence(models.Model):
    """Présence d'un immergé à une séance."""

    class StatutPresence(models.TextChoices):
        PRESENT = "PRESENT", "Présent"
        ABSENT = "ABSENT", "Absent"
        RETARD = "RETARD", "Retard"
        EXCUSE = "EXCUSE", "Excusé"
        DISPENSE = "DISPENSE", "Dispensé"

    seance = models.ForeignKey(
        Seance,
        on_delete=models.PROTECT,
        related_name="presences",
    )
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="presences_activite",
    )
    statut_presence = models.CharField(
        max_length=20,
        choices=StatutPresence.choices,
        db_index=True,
    )
    heure_arrivee = models.TimeField(null=True, blank=True)
    observations = models.TextField(blank=True)
    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="presences_activite_saisies",
    )
    date_saisie = models.DateTimeField(
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
        db_table = "presences_activite"
        verbose_name = "Présence à une activité"
        verbose_name_plural = "Présences aux activités"
        ordering = ["seance_id", "affectation_centre_id"]
        indexes = [
            models.Index(
                fields=["seance", "statut_presence"],
                name="act_pre_sea_stat",
            ),
            models.Index(
                fields=[
                    "affectation_centre",
                    "statut_presence",
                ],
                name="act_pre_aff_stat",
            ),
            models.Index(
                fields=["date_saisie"],
                name="act_pre_date_saisie",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["seance", "affectation_centre"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_presence_active_seance_immerge",
            ),
        ]

    def __str__(self):
        return (
            f"{self.affectation_centre.immerge.code_fasoim} - "
            f"{self.seance_id} - "
            f"{self.get_statut_presence_display()}"
        )

    @property
    def est_active(self):
        return self.deleted_at is None

    @property
    def compte_comme_present(self):
        return self.statut_presence in {
            self.StatutPresence.PRESENT,
            self.StatutPresence.RETARD,
            self.StatutPresence.EXCUSE,
            self.StatutPresence.DISPENSE,
        }

    def clean(self):
        erreurs = {}

        self.observations = (self.observations or "").strip()

        if self.seance_id and self.affectation_centre_id:
            if (
                self.seance.session_id
                != self.affectation_centre.session_id
            ):
                erreurs["affectation_centre"] = (
                    "L'affectation et la séance doivent appartenir "
                    "à la même session."
                )

            if (
                self.seance.centre_id
                != self.affectation_centre.centre_id
            ):
                erreurs["affectation_centre"] = (
                    "L'affectation et la séance doivent appartenir "
                    "au même centre."
                )

            if not self.affectation_centre.est_active:
                erreurs["affectation_centre"] = (
                    "L'affectation centre doit être active."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.deleted_at = timezone.now()
        self.save(
            update_fields=["deleted_at", "updated_at"]
        )
        return self


class Evaluation(models.Model):
    """Évaluation planifiée dans une session et un centre."""

    class TypeEvaluation(models.TextChoices):
        QUIZ = "QUIZ", "Quiz"
        TEST = "TEST", "Test"
        PRATIQUE = "PRATIQUE", "Pratique"
        COMPORTEMENT = "COMPORTEMENT", "Comportement"
        PARTICIPATION = "PARTICIPATION", "Participation"
        FINALE = "FINALE", "Finale"
        AUTRE = "AUTRE", "Autre"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        OUVERTE = "OUVERTE", "Ouverte"
        CLOTUREE = "CLOTUREE", "Clôturée"
        ANNULEE = "ANNULEE", "Annulée"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="evaluations_activite",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="evaluations_activite",
    )
    seance = models.ForeignKey(
        Seance,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )

    titre = models.CharField(max_length=180)
    type_evaluation = models.CharField(
        max_length=30,
        choices=TypeEvaluation.choices,
        db_index=True,
    )
    bareme = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    coefficient = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date_evaluation = models.DateTimeField(db_index=True)
    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evaluations_activite_creees",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "evaluations_activite"
        verbose_name = "Évaluation d'activité"
        verbose_name_plural = "Évaluations d'activités"
        ordering = ["date_evaluation", "centre_id", "id"]
        indexes = [
            models.Index(
                fields=[
                    "session",
                    "centre",
                    "date_evaluation",
                    "statut",
                ],
                name="act_eval_sess_ctr_dt",
            ),
            models.Index(
                fields=["type_evaluation", "statut"],
                name="act_eval_type_stat",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(bareme__gt=0),
                name="act_eval_bareme_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(coefficient__gt=0),
                name="act_eval_coef_gt_zero",
            ),
        ]

    def __str__(self):
        return f"{self.titre} / {self.bareme}"

    @property
    def est_active(self):
        return (
            self.deleted_at is None
            and self.statut != self.Statut.ANNULEE
        )

    @property
    def module_activite(self):
        return (
            self.seance.module_activite
            if self.seance_id
            else None
        )

    def clean(self):
        erreurs = {}

        self.titre = (self.titre or "").strip()

        if not self.titre:
            erreurs["titre"] = (
                "Le titre de l'évaluation est obligatoire."
            )

        if self.bareme is not None and self.bareme <= 0:
            erreurs["bareme"] = (
                "Le barème doit être strictement positif."
            )

        if self.coefficient is not None and self.coefficient <= 0:
            erreurs["coefficient"] = (
                "Le coefficient doit être strictement positif."
            )

        if self.session_id and self.deleted_at is None:
            try:
                parametres = self.session.parametres
            except Exception:
                parametres = None

            if (
                parametres is not None
                and not parametres.evaluation_active
            ):
                erreurs["session"] = (
                    "Les évaluations sont désactivées "
                    "pour cette session."
                )

        if self.seance_id:
            if self.seance.session_id != self.session_id:
                erreurs["seance"] = (
                    "La séance et l'évaluation doivent appartenir "
                    "à la même session."
                )
            if self.seance.centre_id != self.centre_id:
                erreurs["seance"] = (
                    "La séance et l'évaluation doivent appartenir "
                    "au même centre."
                )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def annuler(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.ANNULEE
        self.save(update_fields=["statut", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.ANNULEE
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut",
                "deleted_at",
                "updated_at",
            ]
        )
        return self


class Note(models.Model):
    """Résultat d'un immergé pour une évaluation."""

    class StatutNote(models.TextChoices):
        NOTEE = "NOTEE", "Notée"
        ABSENT = "ABSENT", "Absent"
        DISPENSE = "DISPENSE", "Dispensée"
        ANNULEE = "ANNULEE", "Annulée"

    Statut = StatutNote

    evaluation = models.ForeignKey(
        Evaluation,
        on_delete=models.PROTECT,
        related_name="notes",
    )
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="notes_activite",
    )
    valeur = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )
    appreciation = models.TextField(blank=True)
    statut_note = models.CharField(
        max_length=20,
        choices=StatutNote.choices,
        default=StatutNote.NOTEE,
        db_index=True,
    )
    observations = models.TextField(blank=True)
    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notes_activite_saisies",
    )
    date_saisie = models.DateTimeField(
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
        db_table = "notes_activite"
        verbose_name = "Note d'activité"
        verbose_name_plural = "Notes d'activités"
        ordering = ["evaluation_id", "affectation_centre_id"]
        indexes = [
            models.Index(
                fields=["evaluation", "statut_note"],
                name="act_note_eval_stat",
            ),
            models.Index(
                fields=["affectation_centre", "statut_note"],
                name="act_note_aff_stat",
            ),
            models.Index(
                fields=["date_saisie"],
                name="act_note_date_saisie",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "affectation_centre"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_note_active_eval_immerge",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        statut_note="NOTEE",
                        valeur__isnull=False,
                        valeur__gte=0,
                    )
                    | models.Q(
                        statut_note__in=["ABSENT", "DISPENSE"],
                        valeur__isnull=True,
                    )
                    | models.Q(statut_note="ANNULEE")
                ),
                name="act_note_statut_valeur_ok",
            ),
        ]

    def __str__(self):
        valeur = (
            self.valeur
            if self.valeur is not None
            else self.get_statut_note_display()
        )
        return (
            f"{self.affectation_centre.immerge.code_fasoim} - "
            f"{self.evaluation.titre}: {valeur}"
        )

    @property
    def est_active(self):
        return self.deleted_at is None

    @property
    def est_notee(self):
        return self.statut_note == self.StatutNote.NOTEE

    def clean(self):
        erreurs = {}

        self.appreciation = (self.appreciation or "").strip()
        self.observations = (self.observations or "").strip()

        if self.evaluation_id and self.affectation_centre_id:
            if (
                self.evaluation.session_id
                != self.affectation_centre.session_id
            ):
                erreurs["affectation_centre"] = (
                    "L'affectation et l'évaluation doivent "
                    "appartenir à la même session."
                )
            if (
                self.evaluation.centre_id
                != self.affectation_centre.centre_id
            ):
                erreurs["affectation_centre"] = (
                    "L'affectation et l'évaluation doivent "
                    "appartenir au même centre."
                )

        if self.statut_note in {
            self.StatutNote.ABSENT,
            self.StatutNote.DISPENSE,
        }:
            if self.valeur is not None:
                erreurs["valeur"] = (
                    "Une absence ou une dispense ne doit contenir "
                    "aucune note."
                )

        elif self.statut_note == self.StatutNote.NOTEE:
            if self.valeur is None:
                erreurs["valeur"] = (
                    "Le statut NOTÉE exige une valeur."
                )
            elif self.evaluation_id:
                if self.valeur < 0:
                    erreurs["valeur"] = (
                        "La note ne peut pas être négative."
                    )
                elif self.valeur > self.evaluation.bareme:
                    erreurs["valeur"] = (
                        "La note ne peut pas dépasser le barème."
                    )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def marquer_absent(self):
        self.valeur = None
        self.statut_note = self.StatutNote.ABSENT
        self.save(
            update_fields=[
                "valeur",
                "statut_note",
                "updated_at",
            ]
        )
        return self

    def marquer_dispense(self):
        self.valeur = None
        self.statut_note = self.StatutNote.DISPENSE
        self.save(
            update_fields=[
                "valeur",
                "statut_note",
                "updated_at",
            ]
        )
        return self

    def annuler(self):
        self.statut_note = self.StatutNote.ANNULEE
        self.save(update_fields=["statut_note", "updated_at"])
        return self

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self

        self.statut_note = self.StatutNote.ANNULEE
        self.deleted_at = timezone.now()
        self.save(
            update_fields=[
                "statut_note",
                "deleted_at",
                "updated_at",
            ]
        )
        return self
