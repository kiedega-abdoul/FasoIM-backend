from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class VisiteMedicale(models.Model):
    """Résultat d'une visite médicale réalisée dans un centre."""

    class Resultat(models.TextChoices):
        APTE = "APTE", "Apte"
        APTE_SOUS_RESERVE = (
            "APTE_SOUS_RESERVE",
            "Apte sous réserve",
        )
        INAPTE_TEMPORAIRE = (
            "INAPTE_TEMPORAIRE",
            "Inapte temporaire",
        )
        INAPTE_DEFINITIF = (
            "INAPTE_DEFINITIF",
            "Inapte définitif",
        )
        DISPENSE = "DISPENSE", "Dispensé"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        VALIDEE = "VALIDEE", "Validée"
        ANNULEE = "ANNULEE", "Annulée"

    class StatutApplication(models.TextChoices):
        NON_DEMARREE = "NON_DEMARREE", "Non démarrée"
        A_APPLIQUER = "A_APPLIQUER", "À appliquer"
        EN_COURS = "EN_COURS", "Application en cours"
        APPLIQUEE = "APPLIQUEE", "Appliquée"
        ECHEC = "ECHEC", "Échec"

    RESULTATS_AUTORISANT_IMMERSION = {
        Resultat.APTE,
        Resultat.APTE_SOUS_RESERVE,
        Resultat.DISPENSE,
    }

    RESULTATS_RETIRANT_ORGANISATION = {
        Resultat.INAPTE_TEMPORAIRE,
        Resultat.INAPTE_DEFINITIF,
    }

    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="visites_medicales",
    )

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="visites_medicales",
        editable=False,
    )

    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="visites_medicales",
        editable=False,
    )

    numero_visite = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Numéro chronologique de la visite ou contre-visite."
        ),
    )

    est_courante = models.BooleanField(
        default=True,
        db_index=True,
        help_text=(
            "Indique la visite actuellement applicable."
        ),
    )

    date_visite = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    resultat = models.CharField(
        max_length=30,
        choices=Resultat.choices,
        blank=True,
        default="",
        db_index=True,
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )

    observations_medicales = models.TextField(
        blank=True,
        help_text=(
            "Informations médicales confidentielles. "
            "Elles ne doivent jamais être exposées aux "
            "modules opérationnels."
        ),
    )

    consignes_operationnelles = models.TextField(
        blank=True,
        help_text=(
            "Consignes non médicales transmissibles aux "
            "responsables et aux modules concernés."
        ),
    )

    document_medical = models.FileField(
        upload_to="sante/documents/%Y/%m/",
        blank=True,
    )

    date_prochaine_visite = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Date recommandée pour une contre-visite, "
            "notamment en cas d'inaptitude temporaire."
        ),
    )

    agent_sante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="visites_medicales_saisies",
    )

    date_validation = models.DateTimeField(
        null=True,
        blank=True,
    )

    statut_application = models.CharField(
        max_length=20,
        choices=StatutApplication.choices,
        default=StatutApplication.NON_DEMARREE,
        db_index=True,
        help_text=(
            "État d'application du résultat dans les "
            "autres modules FasoIM."
        ),
    )

    date_application = models.DateTimeField(
        null=True,
        blank=True,
    )

    erreur_application = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "visites_medicales"
        verbose_name = "Visite médicale"
        verbose_name_plural = "Visites médicales"
        ordering = ["-date_visite", "-id"]

        indexes = [
            models.Index(
                fields=[
                    "session",
                    "centre",
                    "resultat",
                ],
                name="sante_vis_sess_ctr_res_idx",
            ),
            models.Index(
                fields=[
                    "centre",
                    "statut",
                    "est_courante",
                ],
                name="sante_vis_ctr_stat_idx",
            ),
            models.Index(
                fields=[
                    "statut_application",
                    "deleted_at",
                ],
                name="sante_vis_application_idx",
            ),
            models.Index(
                fields=[
                    "affectation_centre",
                    "est_courante",
                ],
                name="sante_vis_aff_cour_idx",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["affectation_centre"],
                condition=models.Q(
                    est_courante=True,
                    deleted_at__isnull=True,
                ),
                name="uniq_visite_courante_aff",
            ),
            models.UniqueConstraint(
                fields=[
                    "affectation_centre",
                    "numero_visite",
                ],
                condition=models.Q(
                    deleted_at__isnull=True,
                ),
                name="uniq_numero_visite_aff",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    numero_visite__gte=1,
                ),
                name="sante_vis_numero_gt_zero",
            ),
        ]

    def __str__(self):
        immerge = self.affectation_centre.immerge

        code = (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
            or str(immerge.id)
        )

        resultat = (
            self.get_resultat_display()
            if self.resultat
            else "Brouillon"
        )

        return f"{code} - {resultat}"

    @property
    def est_active(self):
        return (
            self.deleted_at is None
            and self.est_courante
            and self.statut != self.Statut.ANNULEE
        )

    @property
    def est_validee(self):
        return (
            self.deleted_at is None
            and self.est_courante
            and self.statut == self.Statut.VALIDEE
        )

    @property
    def autorise_immersion(self):
        return (
            self.est_validee
            and self.resultat
            in self.RESULTATS_AUTORISANT_IMMERSION
        )

    @property
    def necessite_reorganisation(self):
        return (
            self.est_validee
            and self.resultat
            == self.Resultat.APTE_SOUS_RESERVE
        )

    @property
    def necessite_retrait_organisation(self):
        return (
            self.est_validee
            and self.resultat
            in self.RESULTATS_RETIRANT_ORGANISATION
        )

    @property
    def consequences_appliquees(self):
        return (
            self.statut_application
            == self.StatutApplication.APPLIQUEE
        )

    def clean(self):
        erreurs = {}

        if self.affectation_centre_id:
            affectation = self.affectation_centre

            if (
                self.session_id
                and affectation.session_id != self.session_id
            ):
                erreurs["session"] = (
                    "La session doit correspondre à "
                    "l'affectation centre."
                )

            if (
                self.centre_id
                and affectation.centre_id != self.centre_id
            ):
                erreurs["centre"] = (
                    "Le centre doit correspondre à "
                    "l'affectation centre."
                )

            if (
                self.est_courante
                and self.statut != self.Statut.ANNULEE
            ):
                if not affectation.est_active:
                    erreurs["affectation_centre"] = (
                        "La visite courante exige une "
                        "affectation centre active."
                    )

                parametres = getattr(
                    affectation.session,
                    "parametres",
                    None,
                )

                if (
                    not parametres
                    or not parametres.visite_medicale_active
                ):
                    erreurs["affectation_centre"] = (
                        "La visite médicale n'est pas activée "
                        "pour cette session."
                    )

        if (
            self.statut == self.Statut.VALIDEE
            and not self.resultat
        ):
            erreurs["resultat"] = (
                "Le résultat est obligatoire pour "
                "valider la visite."
            )

        if (
            self.resultat
            != self.Resultat.INAPTE_TEMPORAIRE
            and self.date_prochaine_visite
        ):
            erreurs["date_prochaine_visite"] = (
                "Une prochaine visite ne peut être "
                "programmée que pour une inaptitude temporaire."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if self.affectation_centre_id:
            self.session_id = (
                self.affectation_centre.session_id
            )
            self.centre_id = (
                self.affectation_centre.centre_id
            )

        self.full_clean()
        super().save(*args, **kwargs)

    def valider(self, agent_sante=None):
        if self.deleted_at is not None:
            raise ValidationError(
                "Une visite supprimée ne peut pas être validée."
            )

        if not self.est_courante:
            raise ValidationError(
                "Seule la visite courante peut être validée."
            )

        if not self.resultat:
            raise ValidationError(
                {
                    "resultat": (
                        "Le résultat médical est obligatoire."
                    )
                }
            )

        self.statut = self.Statut.VALIDEE
        self.agent_sante = agent_sante or self.agent_sante
        self.date_validation = timezone.now()

        self.statut_application = (
            self.StatutApplication.A_APPLIQUER
        )

        self.date_application = None
        self.erreur_application = ""

        self.save(
            update_fields=[
                "session",
                "centre",
                "statut",
                "agent_sante",
                "date_validation",
                "statut_application",
                "date_application",
                "erreur_application",
                "updated_at",
            ]
        )

        return self

    def marquer_application_en_cours(self):
        if not self.est_validee:
            raise ValidationError(
                "La visite doit être validée avant "
                "l'application du résultat."
            )

        self.statut_application = (
            self.StatutApplication.EN_COURS
        )

        self.erreur_application = ""

        self.save(
            update_fields=[
                "session",
                "centre",
                "statut_application",
                "erreur_application",
                "updated_at",
            ]
        )

        return self

    def marquer_appliquee(self):
        if not self.est_validee:
            raise ValidationError(
                "La visite doit être validée avant "
                "l'application du résultat."
            )

        self.statut_application = (
            self.StatutApplication.APPLIQUEE
        )

        self.date_application = timezone.now()
        self.erreur_application = ""

        self.save(
            update_fields=[
                "session",
                "centre",
                "statut_application",
                "date_application",
                "erreur_application",
                "updated_at",
            ]
        )

        return self

    def marquer_echec_application(self, erreur):
        self.statut_application = (
            self.StatutApplication.ECHEC
        )

        self.erreur_application = str(erreur)

        self.save(
            update_fields=[
                "session",
                "centre",
                "statut_application",
                "erreur_application",
                "updated_at",
            ]
        )

        return self

    def annuler(self):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.ANNULEE
        self.est_courante = False

        self.statut_application = (
            self.StatutApplication.NON_DEMARREE
        )

        self.deleted_at = timezone.now()

        self.save(
            update_fields=[
                "session",
                "centre",
                "statut",
                "est_courante",
                "statut_application",
                "deleted_at",
                "updated_at",
            ]
        )

        return self


class RestrictionMedicale(models.Model):
    """Restriction médicale exploitable par les autres modules."""

    class TypeRestriction(models.TextChoices):
        DISPENSE = "DISPENSE", "Dispense"
        ADAPTATION = "ADAPTATION", "Adaptation"
        INTERDICTION = "INTERDICTION", "Interdiction"
        SURVEILLANCE = "SURVEILLANCE", "Surveillance"
        PRIORITE = "PRIORITE", "Priorité"
        AUTRE = "AUTRE", "Autre"

    class ModuleConcerne(models.TextChoices):
        ORGANISATION = (
            "ORGANISATION",
            "Organisation interne",
        )
        HEBERGEMENT = "HEBERGEMENT", "Hébergement"
        REPAS = "REPAS", "Repas"
        ACTIVITES = "ACTIVITES", "Activités"
        EVALUATIONS = "EVALUATIONS", "Évaluations"
        PRESENCES = "PRESENCES", "Présences"
        DEPLACEMENTS = "DEPLACEMENTS", "Déplacements"
        AUTRE = "AUTRE", "Autre"

    class NiveauSensibilite(models.TextChoices):
        OPERATIONNEL = (
            "OPERATIONNEL",
            "Opérationnel",
        )
        CONFIDENTIEL = (
            "CONFIDENTIEL",
            "Confidentiel",
        )
        STRICTEMENT_CONFIDENTIEL = (
            "STRICTEMENT_CONFIDENTIEL",
            "Strictement confidentiel",
        )

    class Statut(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDUE = "SUSPENDUE", "Suspendue"
        LEVEE = "LEVEE", "Levée"
        EXPIREE = "EXPIREE", "Expirée"
        ANNULEE = "ANNULEE", "Annulée"

    visite_medicale = models.ForeignKey(
        VisiteMedicale,
        on_delete=models.PROTECT,
        related_name="restrictions",
    )

    libelle = models.CharField(
        max_length=180,
    )

    type_restriction = models.CharField(
        max_length=20,
        choices=TypeRestriction.choices,
        default=TypeRestriction.ADAPTATION,
        db_index=True,
    )

    modules_concernes = models.JSONField(
        default=list,
        help_text=(
            "Liste des modules qui doivent appliquer la "
            "restriction, par exemple HEBERGEMENT, "
            "ACTIVITES ou EVALUATIONS."
        ),
    )

    description_medicale = models.TextField(
        blank=True,
        help_text=(
            "Détail médical confidentiel réservé "
            "aux acteurs de santé."
        ),
    )

    consigne_operationnelle = models.TextField(
        help_text=(
            "Consigne non médicale transmise "
            "aux modules concernés."
        ),
    )

    niveau_sensibilite = models.CharField(
        max_length=30,
        choices=NiveauSensibilite.choices,
        default=NiveauSensibilite.CONFIDENTIEL,
    )

    date_debut = models.DateField(
        default=timezone.localdate,
        db_index=True,
    )

    date_fin = models.DateField(
        null=True,
        blank=True,
        db_index=True,
    )

    statut = models.CharField(
        max_length=20,
        choices=Statut.choices,
        default=Statut.ACTIVE,
        db_index=True,
    )

    date_levee = models.DateTimeField(
        null=True,
        blank=True,
    )

    motif_levee = models.TextField(
        blank=True,
    )

    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="restrictions_medicales_saisies",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    class Meta:
        db_table = "restrictions_medicales"
        verbose_name = "Restriction médicale"
        verbose_name_plural = "Restrictions médicales"
        ordering = ["-date_debut", "-id"]

        indexes = [
            models.Index(
                fields=[
                    "visite_medicale",
                    "statut",
                ],
                name="sante_res_vis_stat_idx",
            ),
            models.Index(
                fields=[
                    "statut",
                    "date_debut",
                    "date_fin",
                ],
                name="sante_res_periode_idx",
            ),
            models.Index(
                fields=[
                    "deleted_at",
                    "statut",
                ],
                name="sante_res_del_stat_idx",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(date_fin__isnull=True)
                    | models.Q(
                        date_fin__gte=models.F("date_debut")
                    )
                ),
                name="sante_res_dates_ok",
            ),
        ]

    def __str__(self):
        immerge = (
            self.visite_medicale
            .affectation_centre
            .immerge
        )

        code = (
            getattr(immerge, "code_fasoim", None)
            or getattr(immerge, "matricule_fasoim", None)
            or str(immerge.id)
        )

        return f"{self.libelle} - {code}"

    @property
    def est_active(self):
        return (
            self.deleted_at is None
            and self.statut == self.Statut.ACTIVE
        )

    @property
    def est_applicable(self):
        aujourd_hui = timezone.localdate()

        return (
            self.est_active
            and self.visite_medicale.est_validee
            and self.date_debut <= aujourd_hui
            and (
                self.date_fin is None
                or self.date_fin >= aujourd_hui
            )
        )

    def concerne_module(self, module):
        return module in (self.modules_concernes or [])

    def clean(self):
        erreurs = {}

        if (
            self.visite_medicale_id
            and self.visite_medicale.deleted_at is not None
        ):
            erreurs["visite_medicale"] = (
                "Une restriction ne peut pas être ajoutée "
                "à une visite supprimée."
            )

        if not isinstance(self.modules_concernes, list):
            erreurs["modules_concernes"] = (
                "Les modules concernés doivent être "
                "fournis sous forme de liste."
            )
        else:
            modules_valides = {
                choix
                for choix, _ in self.ModuleConcerne.choices
            }

            modules_inconnus = sorted(
                set(self.modules_concernes) - modules_valides
            )

            if modules_inconnus:
                erreurs["modules_concernes"] = (
                    "Modules inconnus : "
                    + ", ".join(modules_inconnus)
                )

            elif not self.modules_concernes:
                erreurs["modules_concernes"] = (
                    "Au moins un module concerné "
                    "est obligatoire."
                )

        if (
            self.date_fin
            and self.date_fin < self.date_debut
        ):
            erreurs["date_fin"] = (
                "La date de fin ne peut pas précéder "
                "la date de début."
            )

        if not self.consigne_operationnelle.strip():
            erreurs["consigne_operationnelle"] = (
                "Une consigne opérationnelle "
                "non médicale est obligatoire."
            )

        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if isinstance(self.modules_concernes, list):
            self.modules_concernes = list(
                dict.fromkeys(self.modules_concernes)
            )

        self.full_clean()
        super().save(*args, **kwargs)

    def lever(self, motif="", levee_par=None):
        if self.deleted_at is not None:
            return self

        self.statut = self.Statut.LEVEE
        self.date_levee = timezone.now()
        self.motif_levee = motif or self.motif_levee
        self.saisie_par = levee_par or self.saisie_par

        self.save(
            update_fields=[
                "statut",
                "date_levee",
                "motif_levee",
                "saisie_par",
                "updated_at",
            ]
        )

        return self

    def expirer_si_necessaire(self):
        if (
            self.est_active
            and self.date_fin
            and self.date_fin < timezone.localdate()
        ):
            self.statut = self.Statut.EXPIREE

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