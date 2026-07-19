from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ResultatFinal(models.Model):
    """Décision officielle d'éligibilité d'un immergé à l'attestation.

    Le modèle fige les résultats utilisés au moment de la certification. Les
    données détaillées restent dans activites, sante et incidents ; documents
    conserve uniquement les compteurs et décisions nécessaires à la preuve.
    """

    class Decision(models.TextChoices):
        A_VERIFIER = "A_VERIFIER", "À vérifier"
        ELIGIBLE = "ELIGIBLE", "Éligible"
        NON_ELIGIBLE = "NON_ELIGIBLE", "Non éligible"

    class Statut(models.TextChoices):
        CALCULE = "CALCULE", "Calculé"
        VALIDE_CENTRE = "VALIDE_CENTRE", "Validé par le centre"
        SOUMIS_REGION = "SOUMIS_REGION", "Soumis à la région"
        VALIDE_REGION = "VALIDE_REGION", "Validé par la région"
        PUBLIE = "PUBLIE", "Publié"
        ANNULE = "ANNULE", "Annulé"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="resultats_finaux",
    )
    region = models.ForeignKey(
        "affectations.RegionImmersion",
        on_delete=models.PROTECT,
        related_name="resultats_finaux",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        related_name="resultats_finaux",
    )
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        related_name="resultats_finaux",
    )
    immerge = models.ForeignKey(
        "immerges.Immerge",
        on_delete=models.PROTECT,
        related_name="resultats_finaux",
    )

    total_seances = models.PositiveIntegerField(default=0)
    total_eligible_presence = models.PositiveIntegerField(default=0)
    presences_favorables = models.PositiveIntegerField(default=0)
    presents = models.PositiveIntegerField(default=0)
    retards = models.PositiveIntegerField(default=0)
    absences = models.PositiveIntegerField(default=0)
    excuses = models.PositiveIntegerField(default=0)
    dispenses_presence = models.PositiveIntegerField(default=0)
    taux_presence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    seuil_presence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )

    evaluation_active = models.BooleanField(default=False)
    evaluations_applicables = models.PositiveIntegerField(default=0)
    evaluations_cloturees = models.PositiveIntegerField(default=0)
    notes_comptees = models.PositiveIntegerField(default=0)
    absences_evaluation = models.PositiveIntegerField(default=0)
    dispenses_evaluation = models.PositiveIntegerField(default=0)
    somme_coefficients = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    moyenne_sur_20 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("20.00"))],
    )
    seuil_moyenne_sur_20 = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("20.00"))],
    )

    visite_medicale_active = models.BooleanField(default=False)
    statut_medical_administratif = models.CharField(max_length=40, blank=True)
    participation_medicale_autorisee = models.BooleanField(default=True)
    incident_bloquant = models.BooleanField(default=False)

    decision = models.CharField(
        max_length=20,
        choices=Decision.choices,
        default=Decision.A_VERIFIER,
        db_index=True,
    )
    motifs = models.JSONField(default=list, blank=True)
    details_calcul = models.JSONField(default=dict, blank=True)
    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.CALCULE,
        db_index=True,
    )
    version = models.PositiveIntegerField(default=1)

    calcule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resultats_finaux_calcules",
    )
    valide_centre_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resultats_finaux_valides_centre",
    )
    valide_region_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resultats_finaux_valides_region",
    )
    date_calcul = models.DateTimeField(default=timezone.now)
    date_validation_centre = models.DateTimeField(null=True, blank=True)
    date_validation_region = models.DateTimeField(null=True, blank=True)
    date_publication = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "resultats_finaux"
        verbose_name = "résultat final"
        verbose_name_plural = "résultats finaux"
        ordering = ["session_id", "centre_id", "immerge__code_fasoim"]
        indexes = [
            models.Index(fields=["session", "centre", "decision", "statut"], name="doc_res_ses_ctr_dec"),
            models.Index(fields=["session", "region", "statut"], name="doc_res_ses_reg_stat"),
            models.Index(fields=["immerge", "statut"], name="doc_res_imm_stat"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "affectation_centre"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_resultat_final_affectation_active",
            ),
            models.CheckConstraint(
                condition=Q(taux_presence__gte=0) & Q(taux_presence__lte=100),
                name="doc_resultat_taux_presence_0_100",
            ),
            models.CheckConstraint(
                condition=Q(moyenne_sur_20__isnull=True) | (Q(moyenne_sur_20__gte=0) & Q(moyenne_sur_20__lte=20)),
                name="doc_resultat_moyenne_0_20",
            ),
        ]

    def __str__(self):
        return f"{self.immerge.code_fasoim} - {self.get_decision_display()}"

    @property
    def est_final(self):
        return self.decision in {self.Decision.ELIGIBLE, self.Decision.NON_ELIGIBLE}

    def clean(self):
        erreurs = {}
        if self.affectation_centre_id:
            if self.session_id != self.affectation_centre.session_id:
                erreurs["session"] = "La session doit correspondre à l'affectation centre."
            if self.centre_id != self.affectation_centre.centre_id:
                erreurs["centre"] = "Le centre doit correspondre à l'affectation centre."
            if self.region_id != self.affectation_centre.centre.region_id:
                erreurs["region"] = "La région doit correspondre au centre."
            if self.immerge_id != self.affectation_centre.immerge_id:
                erreurs["immerge"] = "L'immergé doit correspondre à l'affectation centre."
        if self.evaluation_active and self.moyenne_sur_20 is None and self.decision == self.Decision.ELIGIBLE:
            erreurs["moyenne_sur_20"] = "Une moyenne est obligatoire pour un résultat éligible lorsque les évaluations sont actives."
        if not isinstance(self.motifs, list):
            erreurs["motifs"] = "Les motifs doivent être une liste."
        if not isinstance(self.details_calcul, dict):
            erreurs["details_calcul"] = "Les détails de calcul doivent être un objet JSON."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PublicationOfficielle(models.Model):
    """Workflow de validation et de publication par centre, région et DGAS."""

    class TypePublication(models.TextChoices):
        INFORMATIONS_ARRIVEE = "INFORMATIONS_ARRIVEE", "Informations avant l'arrivée"
        ATTESTATIONS = "ATTESTATIONS", "Attestations"

    class Perimetre(models.TextChoices):
        CENTRE = "CENTRE", "Centre"
        REGION = "REGION", "Région"
        NATIONAL = "NATIONAL", "National"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        SOUMISE_REGION = "SOUMISE_REGION", "Soumise à la région"
        A_CORRIGER = "A_CORRIGER", "À corriger"
        VALIDEE_REGION = "VALIDEE_REGION", "Validée par la région"
        PRETE_DGAS = "PRETE_DGAS", "Prête pour la DGAS"
        PUBLIEE = "PUBLIEE", "Publiée"
        DEPUBLIEE = "DEPUBLIEE", "Dépubliée"
        REMPLACEE = "REMPLACEE", "Remplacée"
        ANNULEE = "ANNULEE", "Annulée"

    uuid_publication = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    type_publication = models.CharField(max_length=40, choices=TypePublication.choices, db_index=True)
    perimetre = models.CharField(max_length=20, choices=Perimetre.choices, default=Perimetre.CENTRE, db_index=True)
    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="publications_officielles",
    )
    region = models.ForeignKey(
        "affectations.RegionImmersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publications_officielles",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publications_officielles",
    )
    version = models.PositiveIntegerField(default=1)
    reference = models.CharField(max_length=140, unique=True, editable=False, db_index=True)
    statut = models.CharField(max_length=30, choices=Statut.choices, default=Statut.BROUILLON, db_index=True)
    resume = models.JSONField(default=dict, blank=True)
    commentaire = models.TextField(blank=True)
    motif_correction = models.TextField(blank=True)

    preparee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications_preparees",
    )
    soumise_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications_soumises",
    )
    validee_region_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications_validees_region",
    )
    publiee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications_publiees",
    )
    date_soumission = models.DateTimeField(null=True, blank=True)
    date_validation_region = models.DateTimeField(null=True, blank=True)
    date_publication = models.DateTimeField(null=True, blank=True)
    date_depublication = models.DateTimeField(null=True, blank=True)

    remplace_publication = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="versions_suivantes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "publications_officielles"
        verbose_name = "publication officielle"
        verbose_name_plural = "publications officielles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "type_publication", "statut"], name="doc_pub_ses_type_stat"),
            models.Index(fields=["session", "region", "statut"], name="doc_pub_ses_reg_stat"),
            models.Index(fields=["session", "centre", "statut"], name="doc_pub_ses_ctr_stat"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "type_publication", "perimetre", "centre", "version"],
                condition=Q(centre__isnull=False, deleted_at__isnull=True),
                name="uniq_publication_centre_version",
            ),
            models.UniqueConstraint(
                fields=["session", "type_publication", "perimetre", "region", "version"],
                condition=Q(centre__isnull=True, region__isnull=False, deleted_at__isnull=True),
                name="uniq_publication_region_version",
            ),
            models.UniqueConstraint(
                fields=["session", "type_publication", "perimetre", "version"],
                condition=Q(centre__isnull=True, region__isnull=True, deleted_at__isnull=True),
                name="uniq_publication_nationale_version",
            ),
        ]

    def __str__(self):
        return self.reference or f"{self.type_publication} - {self.session.code}"

    def clean(self):
        erreurs = {}
        if self.centre_id and self.region_id and self.centre.region_id != self.region_id:
            erreurs["region"] = "La région doit correspondre à celle du centre."
        if self.perimetre == self.Perimetre.CENTRE and not self.centre_id:
            erreurs["centre"] = "Le centre est obligatoire pour une publication de centre."
        if self.perimetre == self.Perimetre.REGION and not self.region_id:
            erreurs["region"] = "La région est obligatoire pour une publication régionale."
        if self.perimetre == self.Perimetre.NATIONAL and (self.region_id or self.centre_id):
            erreurs["perimetre"] = "Une publication nationale ne doit pas porter de région ni de centre."
        if not isinstance(self.resume, dict):
            erreurs["resume"] = "Le résumé doit être un objet JSON."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if self.centre_id and not self.region_id:
            self.region_id = self.centre.region_id
        if not self.reference:
            portee = self.centre.code if self.centre_id else (self.region.code if self.region_id else "NAT")
            self.reference = f"PUB-{self.type_publication}-{self.session.code}-{portee}-V{self.version}"
        self.full_clean()
        return super().save(*args, **kwargs)


class DocumentGenere(models.Model):
    """Fichier produit par FasoIM, avec intégrité, version et visibilité."""

    class TypeDocument(models.TextChoices):
        FICHE_ARRIVEE = "FICHE_ARRIVEE", "Fiche d'arrivée"
        CONSIGNES_ARRIVEE = "CONSIGNES_ARRIVEE", "Consignes avant l'arrivée"
        LISTE_IMMERGES = "LISTE_IMMERGES", "Liste des immergés"
        FEUILLE_PRESENCE = "FEUILLE_PRESENCE", "Feuille de présence"
        RAPPORT_IMPORT = "RAPPORT_IMPORT", "Rapport d'import"
        RAPPORT_CENTRE = "RAPPORT_CENTRE", "Rapport de centre"
        RAPPORT_REGIONAL = "RAPPORT_REGIONAL", "Rapport régional"
        RAPPORT_NATIONAL = "RAPPORT_NATIONAL", "Rapport national"
        RAPPORT_PRESENCES = "RAPPORT_PRESENCES", "Rapport des présences"
        RAPPORT_EVALUATIONS = "RAPPORT_EVALUATIONS", "Rapport des évaluations"
        RAPPORT_KITS = "RAPPORT_KITS", "Rapport des kits"
        RAPPORT_REPAS = "RAPPORT_REPAS", "Rapport des repas"
        RAPPORT_INCIDENTS = "RAPPORT_INCIDENTS", "Rapport des incidents"
        RAPPORT_ATTESTATIONS = "RAPPORT_ATTESTATIONS", "Rapport des attestations"
        SYNTHESE_MEDICALE = "SYNTHESE_MEDICALE", "Synthèse médicale administrative"
        ATTESTATION = "ATTESTATION", "Attestation"

    class Format(models.TextChoices):
        PDF = "PDF", "PDF"
        XLSX = "XLSX", "Excel"
        CSV = "CSV", "CSV"

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        EN_GENERATION = "EN_GENERATION", "En génération"
        GENERE = "GENERE", "Généré"
        SIGNE = "SIGNE", "Signé"
        PUBLIE = "PUBLIE", "Publié"
        ECHEC = "ECHEC", "Échec"
        ANNULE = "ANNULE", "Annulé"
        REMPLACE = "REMPLACE", "Remplacé"
        ARCHIVE = "ARCHIVE", "Archivé"

    class Visibilite(models.TextChoices):
        INTERNE = "INTERNE", "Interne"
        IMMERGE_CONCERNE = "IMMERGE_CONCERNE", "Immergé concerné"
        PERIMETRE_INTERNE = "PERIMETRE_INTERNE", "Acteurs du périmètre"
        PUBLIC_VERIFICATION = "PUBLIC_VERIFICATION", "Vérification publique"

    uuid_document = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    type_document = models.CharField(max_length=40, choices=TypeDocument.choices, db_index=True)
    format_fichier = models.CharField(max_length=10, choices=Format.choices, default=Format.PDF, db_index=True)
    titre = models.CharField(max_length=255)
    numero_document = models.CharField(max_length=140, unique=True, blank=True, editable=False, db_index=True)
    cle_generation = models.CharField(max_length=255, blank=True, db_index=True)

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="documents_generes",
    )
    region = models.ForeignKey(
        "affectations.RegionImmersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents_generes",
    )
    centre = models.ForeignKey(
        "affectations.CentreImmersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents_generes",
    )
    immerge = models.ForeignKey(
        "immerges.Immerge",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents_generes",
    )
    affectation_centre = models.ForeignKey(
        "affectations.AffectationCentre",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents_generes",
    )
    resultat_final = models.ForeignKey(
        ResultatFinal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents",
    )
    publication = models.ForeignKey(
        PublicationOfficielle,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents",
    )

    fichier = models.FileField(upload_to="documents/generes/%Y/%m/", max_length=500, blank=True)
    nom_fichier = models.CharField(max_length=255, blank=True)
    type_mime = models.CharField(max_length=120, blank=True)
    taille_octets = models.PositiveBigIntegerField(default=0)
    hash_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    code_verification = models.CharField(max_length=80, unique=True, blank=True, editable=False, db_index=True)
    qr_code_image = models.ImageField(upload_to="documents/qrcodes/%Y/%m/", max_length=500, blank=True)

    version = models.PositiveIntegerField(default=1)
    statut = models.CharField(max_length=30, choices=Statut.choices, default=Statut.EN_ATTENTE, db_index=True)
    visibilite = models.CharField(max_length=30, choices=Visibilite.choices, default=Visibilite.INTERNE, db_index=True)
    parametres_generation = models.JSONField(default=dict, blank=True)
    resume_generation = models.JSONField(default=dict, blank=True)
    donnees_figees = models.JSONField(default=dict, blank=True)
    message_erreur = models.TextField(blank=True)

    genere_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_generes_par_acteur",
    )
    signataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents_signes",
    )
    nom_signataire_snapshot = models.CharField(max_length=255, blank=True)
    fonction_signataire_snapshot = models.CharField(max_length=200, blank=True)
    organisation_signataire_snapshot = models.CharField(max_length=255, blank=True)
    signature_appliquee = models.BooleanField(default=False)
    cachet_applique = models.BooleanField(default=False)

    date_generation = models.DateTimeField(null=True, blank=True)
    date_signature = models.DateTimeField(null=True, blank=True)
    date_publication = models.DateTimeField(null=True, blank=True)
    remplace_document = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="versions_suivantes",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "documents_generes"
        verbose_name = "document généré"
        verbose_name_plural = "documents générés"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "type_document", "statut"], name="doc_gen_ses_type_stat"),
            models.Index(fields=["session", "centre", "type_document"], name="doc_gen_ses_ctr_type"),
            models.Index(fields=["immerge", "type_document", "statut"], name="doc_gen_imm_type_stat"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cle_generation"],
                condition=Q(deleted_at__isnull=True) & ~Q(cle_generation="") & ~Q(statut="ECHEC"),
                name="uniq_document_generation_reussie",
            ),
            models.UniqueConstraint(
                fields=["resultat_final"],
                condition=Q(type_document="ATTESTATION", resultat_final__isnull=False, deleted_at__isnull=True) & ~Q(statut__in=["ANNULE", "REMPLACE", "ECHEC"]),
                name="uniq_attestation_active_resultat",
            ),
        ]

    def __str__(self):
        return self.numero_document or self.titre

    @property
    def est_telechargeable(self):
        return bool(self.fichier and self.statut in {self.Statut.GENERE, self.Statut.SIGNE, self.Statut.PUBLIE})

    def clean(self):
        erreurs = {}
        for champ in ("parametres_generation", "resume_generation", "donnees_figees"):
            if not isinstance(getattr(self, champ), dict):
                erreurs[champ] = "Un objet JSON est attendu."
        if self.type_document == self.TypeDocument.ATTESTATION:
            if not self.immerge_id or not self.resultat_final_id:
                erreurs["resultat_final"] = "Une attestation doit être liée à un résultat final et à un immergé."
        if self.centre_id and self.region_id and self.centre.region_id != self.region_id:
            erreurs["region"] = "La région doit correspondre au centre."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        if self.centre_id and not self.region_id:
            self.region_id = self.centre.region_id
        if not self.numero_document:
            prefixe = "ATT" if self.type_document == self.TypeDocument.ATTESTATION else "DOC"
            self.numero_document = f"FASOIM-{prefixe}-{self.session.annee}-{uuid.uuid4().hex[:12].upper()}"
        if not self.code_verification:
            self.code_verification = uuid.uuid4().hex.upper()
        self.full_clean()
        return super().save(*args, **kwargs)
