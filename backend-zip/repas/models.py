from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class DemandeRavitaillementCentre(models.Model):
    """Dossier des besoins en denrées d'un centre pour une session."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        SOUMISE = "SOUMISE", "Soumise"
        VALIDEE = "VALIDEE", "Validée"
        PARTIELLEMENT_RECUE = (
            "PARTIELLEMENT_RECUE",
            "Partiellement reçue",
        )
        RECUE = "RECUE", "Reçue"
        ANNULEE = "ANNULEE", "Annulée"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="demandes_ravitaillement",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="demandes_ravitaillement",
    )
    effectif_reference = models.PositiveIntegerField(default=0)
    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    observations = models.TextField(blank=True)
    soumis_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="demandes_ravitaillement_soumises",
    )
    date_soumission = models.DateTimeField(null=True, blank=True)
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="demandes_ravitaillement_validees",
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "demandes_ravitaillement_centres"
        verbose_name = "Demande de ravitaillement de centre"
        verbose_name_plural = "Demandes de ravitaillement des centres"
        ordering = ["-session__annee", "centre__nom", "-id"]
        indexes = [
            models.Index(
                fields=["session", "centre", "statut"],
                name="rep_dem_sess_ctr_stat",
            ),
            models.Index(
                fields=["deleted_at", "statut"],
                name="rep_dem_del_stat",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "centre"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_dem_ravit_sess_ctr_active",
            ),
        ]

    def __str__(self):
        return f"{self.session} - {self.centre.nom}"

    @property
    def est_modifiable(self):
        return self.deleted_at is None and self.statut == self.Statut.BROUILLON

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut != self.Statut.ANNULEE

    def clean(self):
        erreurs = {}
        if self.session_id and self.centre_id:
            if not self.centre.est_actif:
                erreurs["centre"] = "Le centre doit être actif."
        if self.session_id and not self.session.est_modifiable:
            if self._state.adding or self.statut == self.Statut.BROUILLON:
                erreurs["session"] = (
                    "La session est terminée, archivée ou annulée."
                )
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self
        self.statut = self.Statut.ANNULEE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class LigneBesoinDenree(models.Model):
    """Produit demandé, validé puis reçu pour un centre."""

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        VALIDEE = "VALIDEE", "Validée"
        PARTIELLEMENT_RECUE = (
            "PARTIELLEMENT_RECUE",
            "Partiellement reçue",
        )
        RECUE = "RECUE", "Reçue"
        ANNULEE = "ANNULEE", "Annulée"

    demande_ravitaillement = models.ForeignKey(
        DemandeRavitaillementCentre,
        on_delete=models.PROTECT,
        related_name="lignes_denrees",
    )
    code_denree = models.CharField(max_length=60)
    designation = models.CharField(max_length=180)
    conditionnement = models.CharField(max_length=80)
    contenance_conditionnement = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
    )
    unite_base = models.CharField(max_length=30)
    quantite_demandee = models.DecimalField(max_digits=14, decimal_places=3)
    quantite_validee = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
    )
    quantite_recue = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0"),
    )
    observations = models.TextField(blank=True)
    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "lignes_besoins_denrees"
        verbose_name = "Ligne de besoin en denrée"
        verbose_name_plural = "Lignes de besoins en denrées"
        ordering = ["designation", "id"]
        indexes = [
            models.Index(
                fields=["demande_ravitaillement", "statut"],
                name="rep_lig_dem_stat",
            ),
            models.Index(fields=["code_denree"], name="rep_lig_code"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["demande_ravitaillement", "code_denree"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_lig_denree_dem_code_active",
            ),
            models.CheckConstraint(
                condition=models.Q(quantite_demandee__gt=0),
                name="rep_lig_qte_dem_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(quantite_validee__gte=0),
                name="rep_lig_qte_val_pos",
            ),
            models.CheckConstraint(
                condition=models.Q(quantite_recue__gte=0),
                name="rep_lig_qte_rec_pos",
            ),
        ]

    def __str__(self):
        return f"{self.designation} - {self.demande_ravitaillement.centre}"

    def clean(self):
        erreurs = {}
        self.code_denree = (self.code_denree or "").strip().upper()
        self.designation = (self.designation or "").strip()
        self.conditionnement = (self.conditionnement or "").strip()
        self.unite_base = (self.unite_base or "").strip().upper()
        if not self.code_denree:
            erreurs["code_denree"] = "Le code de la denrée est obligatoire."
        if not self.designation:
            erreurs["designation"] = "La désignation est obligatoire."
        if not self.conditionnement:
            erreurs["conditionnement"] = "Le conditionnement est obligatoire."
        if not self.unite_base:
            erreurs["unite_base"] = "L'unité de base est obligatoire."
        if self.quantite_demandee is not None and self.quantite_demandee <= 0:
            erreurs["quantite_demandee"] = (
                "La quantité demandée doit être strictement positive."
            )
        if self.quantite_validee is not None and self.quantite_validee < 0:
            erreurs["quantite_validee"] = "La quantité validée est invalide."
        if self.quantite_recue is not None and self.quantite_recue < 0:
            erreurs["quantite_recue"] = "La quantité reçue est invalide."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def supprimer_logiquement(self):
        if self.deleted_at is not None:
            return self
        self.statut = self.Statut.ANNULEE
        self.deleted_at = timezone.now()
        self.save(update_fields=["statut", "deleted_at", "updated_at"])
        return self


class RepasJournalier(models.Model):
    """Planification et préparation réelle d'un repas d'un centre."""

    class TypeRepas(models.TextChoices):
        PETIT_DEJEUNER = "PETIT_DEJEUNER", "Petit déjeuner"
        DEJEUNER = "DEJEUNER", "Déjeuner"
        DINER = "DINER", "Dîner"
        COLLATION = "COLLATION", "Collation"

    class StatutControleSante(models.TextChoices):
        NON_VERIFIE = "NON_VERIFIE", "Non vérifié"
        A_JOUR = "A_JOUR", "À jour"
        A_REVOIR = "A_REVOIR", "À revoir"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        PLANIFIE = "PLANIFIE", "Planifié"
        VALIDE = "VALIDE", "Validé"
        EN_PREPARATION = "EN_PREPARATION", "En préparation"
        PREPARE = "PREPARE", "Préparé"
        DISTRIBUTION_OUVERTE = (
            "DISTRIBUTION_OUVERTE",
            "Distribution ouverte",
        )
        CLOTURE = "CLOTURE", "Clôturé"
        ANNULE = "ANNULE", "Annulé"

    demande_ravitaillement = models.ForeignKey(
        DemandeRavitaillementCentre,
        on_delete=models.PROTECT,
        related_name="repas_journaliers",
    )
    date_repas = models.DateField(db_index=True)
    type_repas = models.CharField(
        max_length=25,
        choices=TypeRepas.choices,
        db_index=True,
    )
    heure_prevue = models.TimeField(null=True, blank=True)

    menu_prevu = models.CharField(max_length=255)
    description_prevue = models.TextField(blank=True)
    denrees_prevues = models.JSONField(default=list, blank=True)
    nombre_standard_prevu = models.PositiveIntegerField(default=0)
    synthese_restrictions_alimentaires = models.JSONField(
        default=dict,
        blank=True,
        editable=False,
    )
    preparations_speciales_prevues = models.JSONField(default=dict, blank=True)

    menu_prepare = models.CharField(max_length=255, blank=True)
    description_preparation_reelle = models.TextField(blank=True)
    denrees_reellement_utilisees = models.JSONField(default=list, blank=True)
    nombre_standard_prepare = models.PositiveIntegerField(default=0)
    preparations_speciales_reelles = models.JSONField(default=dict, blank=True)
    heure_debut_preparation = models.DateTimeField(null=True, blank=True)
    heure_fin_preparation = models.DateTimeField(null=True, blank=True)
    observations_preparation = models.TextField(blank=True)

    statut_controle_sante = models.CharField(
        max_length=20,
        choices=StatutControleSante.choices,
        default=StatutControleSante.NON_VERIFIE,
        db_index=True,
    )
    date_verification_sante = models.DateTimeField(null=True, blank=True)
    empreinte_besoins_sante = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
    )
    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repas_journaliers_crees",
    )
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="repas_journaliers_valides",
    )
    date_validation = models.DateTimeField(null=True, blank=True)
    date_ouverture_distribution = models.DateTimeField(null=True, blank=True)
    date_cloture = models.DateTimeField(null=True, blank=True)
    motif_annulation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "repas_journaliers"
        verbose_name = "Repas journalier"
        verbose_name_plural = "Repas journaliers"
        ordering = ["-date_repas", "type_repas", "id"]
        indexes = [
            models.Index(
                fields=["date_repas", "type_repas", "statut"],
                name="rep_repas_date_type_stat",
            ),
            models.Index(
                fields=["demande_ravitaillement", "statut"],
                name="rep_repas_dem_stat",
            ),
            models.Index(
                fields=["statut_controle_sante", "date_repas"],
                name="rep_repas_sante_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["demande_ravitaillement", "date_repas", "type_repas"],
                condition=models.Q(deleted_at__isnull=True),
                name="uniq_repas_dem_date_type_active",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_type_repas_display()} du {self.date_repas} - "
            f"{self.demande_ravitaillement.centre.nom}"
        )

    @property
    def session_id(self):
        return self.demande_ravitaillement.session_id

    @property
    def centre_id(self):
        return self.demande_ravitaillement.centre_id

    @property
    def total_special_prevu(self):
        return sum(
            max(0, int(valeur or 0))
            for valeur in (self.synthese_restrictions_alimentaires or {}).values()
        )

    @property
    def total_prepare(self):
        special = 0
        for valeur in (self.preparations_speciales_reelles or {}).values():
            if isinstance(valeur, dict):
                valeur = valeur.get("quantite", 0)
            special += max(0, int(valeur or 0))
        return self.nombre_standard_prepare + special

    @property
    def est_modifiable(self):
        return self.deleted_at is None and self.statut in {
            self.Statut.BROUILLON,
            self.Statut.PLANIFIE,
            self.Statut.VALIDE,
        }

    def clean(self):
        erreurs = {}
        if self.demande_ravitaillement_id:
            demande = self.demande_ravitaillement
            if not demande.est_active:
                erreurs["demande_ravitaillement"] = (
                    "La demande de ravitaillement n'est pas active."
                )
            session = demande.session
            if self.date_repas and not (
                session.date_debut <= self.date_repas <= session.date_fin
            ):
                erreurs["date_repas"] = (
                    "La date du repas doit appartenir à la période de la session."
                )
        if not isinstance(self.denrees_prevues, list):
            erreurs["denrees_prevues"] = "Une liste est attendue."
        for champ in (
            "synthese_restrictions_alimentaires",
            "preparations_speciales_prevues",
            "preparations_speciales_reelles",
        ):
            if not isinstance(getattr(self, champ), dict):
                erreurs[champ] = "Un objet JSON est attendu."
        if not isinstance(self.denrees_reellement_utilisees, list):
            erreurs["denrees_reellement_utilisees"] = "Une liste est attendue."
        if (
            self.heure_debut_preparation
            and self.heure_fin_preparation
            and self.heure_fin_preparation < self.heure_debut_preparation
        ):
            erreurs["heure_fin_preparation"] = (
                "La fin de préparation doit suivre son début."
            )
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SuiviRepas(models.Model):
    """Comptage collectif ou suivi opérationnel d'un repas adapté."""

    class TypeSuivi(models.TextChoices):
        COMPTAGE = "COMPTAGE", "Comptage"
        MEDICAL = "MEDICAL", "Suivi alimentaire"

    class StatutService(models.TextChoices):
        A_SERVIR = "A_SERVIR", "À servir"
        SERVI_CONFORME = "SERVI_CONFORME", "Servi conformément"
        SERVI_NON_CONFORME = (
            "SERVI_NON_CONFORME",
            "Servi non conformément",
        )
        NON_SERVI = "NON_SERVI", "Non servi"
        ABSENT = "ABSENT", "Absent"
        REFUSE = "REFUSE", "Refusé"

    repas_journalier = models.ForeignKey(
        RepasJournalier,
        on_delete=models.PROTECT,
        related_name="suivis",
    )
    type_suivi = models.CharField(
        max_length=15,
        choices=TypeSuivi.choices,
        db_index=True,
    )
    groupe = models.ForeignKey(
        "organisation.Groupe",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="suivis_repas",
    )
    effectif_attendu = models.PositiveIntegerField(default=0)
    nombre_ayant_mange = models.PositiveIntegerField(default=0)
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="suivis_repas_medicaux",
    )
    categorie_alimentaire = models.CharField(max_length=255, blank=True)
    consigne_alimentaire = models.TextField(blank=True)
    preparation_speciale_prevue = models.TextField(blank=True)
    statut_service = models.CharField(
        max_length=25,
        choices=StatutService.choices,
        blank=True,
        default="",
        db_index=True,
    )
    observation_service = models.TextField(blank=True)
    observations = models.TextField(blank=True)
    saisi_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="suivis_repas_saisis",
    )
    date_saisie = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "suivis_repas"
        verbose_name = "Suivi de repas"
        verbose_name_plural = "Suivis de repas"
        ordering = ["repas_journalier_id", "type_suivi", "id"]
        indexes = [
            models.Index(
                fields=["repas_journalier", "type_suivi"],
                name="rep_suivi_repas_type",
            ),
            models.Index(
                fields=["statut_service", "deleted_at"],
                name="rep_suivi_serv_del",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["repas_journalier", "groupe"],
                condition=models.Q(
                    type_suivi="COMPTAGE",
                    groupe__isnull=False,
                    deleted_at__isnull=True,
                ),
                name="uniq_suivi_comptage_repas_groupe",
            ),
            models.UniqueConstraint(
                fields=["repas_journalier"],
                condition=models.Q(
                    type_suivi="COMPTAGE",
                    groupe__isnull=True,
                    deleted_at__isnull=True,
                ),
                name="uniq_suivi_comptage_repas_centre",
            ),
            models.UniqueConstraint(
                fields=["repas_journalier", "affectation_centre"],
                condition=models.Q(
                    type_suivi="MEDICAL",
                    deleted_at__isnull=True,
                ),
                name="uniq_suivi_med_repas_aff",
            ),
            models.CheckConstraint(
                condition=models.Q(nombre_ayant_mange__lte=models.F("effectif_attendu")),
                name="rep_suivi_mange_lte_attendu",
            ),
        ]

    def __str__(self):
        if self.type_suivi == self.TypeSuivi.COMPTAGE:
            cible = self.groupe.nom if self.groupe_id else "Centre"
            return f"Comptage {cible} - {self.repas_journalier}"
        return f"Repas adapté {self.affectation_centre_id} - {self.repas_journalier}"

    def clean(self):
        erreurs = {}
        if self.type_suivi == self.TypeSuivi.COMPTAGE:
            if self.affectation_centre_id:
                erreurs["affectation_centre"] = (
                    "Un comptage collectif ne cible pas un immergé."
                )
            if self.statut_service:
                erreurs["statut_service"] = (
                    "Le statut de service est réservé au suivi alimentaire."
                )
            if self.nombre_ayant_mange > self.effectif_attendu:
                erreurs["nombre_ayant_mange"] = (
                    "Le nombre servi ne peut pas dépasser l'effectif attendu."
                )
        elif self.type_suivi == self.TypeSuivi.MEDICAL:
            if not self.affectation_centre_id:
                erreurs["affectation_centre"] = (
                    "Le suivi alimentaire exige une affectation centre."
                )
            if self.groupe_id:
                erreurs["groupe"] = (
                    "Le groupe est retrouvé depuis l'affectation de l'immergé."
                )
            if not self.consigne_alimentaire.strip():
                erreurs["consigne_alimentaire"] = (
                    "La consigne alimentaire opérationnelle est obligatoire."
                )
            if not self.statut_service:
                erreurs["statut_service"] = "Le statut de service est obligatoire."
            if self.affectation_centre_id and self.repas_journalier_id:
                if self.affectation_centre.session_id != self.repas_journalier.session_id:
                    erreurs["affectation_centre"] = "La session ne correspond pas."
                if self.affectation_centre.centre_id != self.repas_journalier.centre_id:
                    erreurs["affectation_centre"] = "Le centre ne correspond pas."
        else:
            erreurs["type_suivi"] = "Type de suivi inconnu."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def supprimer_logiquement(self):
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])
        return self
