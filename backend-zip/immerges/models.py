from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class SourceImporteeBase(models.Model):
    """Champs communs aux listes officielles importées."""

    class Sexe(models.TextChoices):
        MASCULIN = "M", "Masculin"
        FEMININ = "F", "Féminin"
        AUTRE = "AUTRE", "Autre"
        NON_PRECISE = "NON_PRECISE", "Non précisé"

    class StatutValidation(models.TextChoices):
        VALIDE = "VALIDE", "Valide"
        INCOMPLET = "INCOMPLET", "Incomplet"
        REJETE = "REJETE", "Rejeté"
        SUSPECT = "SUSPECT", "Suspect"

    import_officiel = models.ForeignKey(
        "imports_app.ImportOfficiel",
        on_delete=models.PROTECT,
        related_name="%(class)ss",
    )
    numero_ligne_import = models.PositiveIntegerField(db_index=True)

    nom = models.CharField(max_length=150, blank=True, default="")
    prenoms = models.CharField(max_length=220, blank=True, default="")
    nom_et_prenoms = models.CharField(max_length=300, blank=True, default="")
    sexe = models.CharField(max_length=20, choices=Sexe.choices, blank=True, default="")
    date_naissance = models.DateField(blank=True, null=True)
    lieu_naissance = models.CharField(max_length=180, blank=True, default="")
    nationalite = models.CharField(max_length=120, blank=True, default="")
    numero_cnib = models.CharField(max_length=80, blank=True, default="", db_index=True)
    telephone = models.CharField(max_length=40, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    contact_urgence = models.CharField(max_length=40, blank=True, default="")
    nom_contact_urgence = models.CharField(max_length=180, blank=True, default="")

    statut_validation = models.CharField(
        max_length=20,
        choices=StatutValidation.choices,
        default=StatutValidation.INCOMPLET,
        db_index=True,
    )
    donnees_brutes = models.JSONField(default=dict, blank=True)
    donnees_normalisees = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        abstract = True

    @property
    def est_supprime(self):
        return self.deleted_at is not None

    @property
    def identite_affichable(self):
        if self.nom_et_prenoms:
            return self.nom_et_prenoms
        return " ".join(partie for partie in [self.nom, self.prenoms] if partie).strip()

    def clean(self):
        erreurs = {}
        if not self.numero_ligne_import:
            erreurs["numero_ligne_import"] = "Le numéro de ligne importée est obligatoire."
        if not self.nom_et_prenoms and not (self.nom or self.prenoms):
            erreurs["nom_et_prenoms"] = "L'identité doit être renseignée au moins dans nom_et_prenoms ou nom/prenoms."
        if erreurs:
            raise ValidationError(erreurs)


class ImmergeExamen(SourceImporteeBase):
    """Source des immergés issus des examens officiels."""

    class TypeExamen(models.TextChoices):
        BEPC = "BEPC", "BEPC"
        BAC = "BAC", "BAC"
        AUTRE = "AUTRE", "Autre"

    numero_pv = models.CharField(max_length=80, db_index=True)
    type_examen = models.CharField(max_length=20, choices=TypeExamen.choices, db_index=True)
    serie = models.CharField(max_length=80, blank=True, default="")
    annee_obtention = models.PositiveIntegerField(blank=True, null=True, db_index=True)
    statut = models.CharField(max_length=80, blank=True, default="")
    centre_examen = models.CharField(max_length=180, blank=True, default="")
    etablissement_origine = models.CharField(max_length=220, blank=True, default="")
    region_examen = models.CharField(max_length=120, blank=True, default="", db_index=True)
    province_examen = models.CharField(max_length=120, blank=True, default="", db_index=True)

    class Meta:
        db_table = "immerges_examens"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["import_officiel", "numero_pv"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_immerge_examen_import_pv_actif",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "numero_ligne_import"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_immerge_examen_ligne_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["import_officiel", "statut_validation"]),
            models.Index(fields=["type_examen", "annee_obtention"]),
            models.Index(fields=["deleted_at", "statut_validation"]),
        ]
        verbose_name = "Immergé examen"
        verbose_name_plural = "Immergés examens"

    def __str__(self):
        return f"{self.type_examen} - {self.numero_pv} - {self.identite_affichable}"

    def clean(self):
        super().clean()
        erreurs = {}
        if not self.numero_pv:
            erreurs["numero_pv"] = "Le numéro PV est obligatoire pour les examens."
        if not self.type_examen:
            erreurs["type_examen"] = "Le type d'examen est obligatoire."
        if erreurs:
            raise ValidationError(erreurs)


class ImmergeConcours(SourceImporteeBase):
    """Source des immergés issus des concours officiels."""

    numero_recepisse = models.CharField(max_length=100, db_index=True)
    specialite = models.CharField(max_length=180, blank=True, default="")
    centre_composition = models.CharField(max_length=180, blank=True, default="")
    region_composition = models.CharField(max_length=120, blank=True, default="", db_index=True)
    province_composition = models.CharField(max_length=120, blank=True, default="", db_index=True)

    class Meta:
        db_table = "immerges_concours"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["import_officiel", "numero_recepisse"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_immerge_concours_import_recepisse_actif",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "numero_ligne_import"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_immerge_concours_ligne_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["import_officiel", "statut_validation"]),
            models.Index(fields=["region_composition", "province_composition"]),
            models.Index(fields=["deleted_at", "statut_validation"]),
        ]
        verbose_name = "Immergé concours"
        verbose_name_plural = "Immergés concours"

    def __str__(self):
        return f"Concours - {self.numero_recepisse} - {self.identite_affichable}"

    def clean(self):
        super().clean()
        if not self.numero_recepisse:
            raise ValidationError({"numero_recepisse": "Le numéro de récépissé est obligatoire pour les concours."})


class ImmergeSelectionne(SourceImporteeBase):
    """Source des personnes sélectionnées par décision ou liste officielle."""

    matricule = models.CharField(max_length=100, blank=True, default="", db_index=True)
    reference_selection = models.CharField(max_length=140, blank=True, default="", db_index=True)
    structure_origine = models.CharField(max_length=220, blank=True, default="")
    motif_selection = models.TextField(blank=True, default="")
    region_structure = models.CharField(max_length=120, blank=True, default="", db_index=True)
    province_structure = models.CharField(max_length=120, blank=True, default="", db_index=True)

    class Meta:
        db_table = "immerges_selectionnes"
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                check=Q(matricule__gt="") | Q(reference_selection__gt=""),
                name="chk_selectionne_matricule_ou_reference",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "matricule"],
                condition=Q(deleted_at__isnull=True) & ~Q(matricule=""),
                name="uniq_selectionne_import_matricule_actif",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "reference_selection"],
                condition=Q(deleted_at__isnull=True) & ~Q(reference_selection=""),
                name="uniq_selectionne_import_reference_actif",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "numero_ligne_import"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_selectionne_ligne_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["import_officiel", "statut_validation"]),
            models.Index(fields=["region_structure", "province_structure"]),
            models.Index(fields=["deleted_at", "statut_validation"]),
        ]
        verbose_name = "Immergé sélectionné"
        verbose_name_plural = "Immergés sélectionnés"

    def __str__(self):
        reference = self.matricule or self.reference_selection
        return f"Sélectionné - {reference} - {self.identite_affichable}"

    def clean(self):
        super().clean()
        if not self.matricule and not self.reference_selection:
            raise ValidationError({"reference_selection": "Le matricule ou la référence de sélection est obligatoire."})


class InscriptionVolontaire(models.Model):
    """Demande volontaire avant création éventuelle d'un immergé central."""

    class Sexe(models.TextChoices):
        MASCULIN = "M", "Masculin"
        FEMININ = "F", "Féminin"
        AUTRE = "AUTRE", "Autre"
        NON_PRECISE = "NON_PRECISE", "Non précisé"

    class StatutDemande(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        ACCEPTEE = "ACCEPTEE", "Acceptée"
        REJETEE = "REJETEE", "Rejetée"
        ANNULEE = "ANNULEE", "Annulée"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="inscriptions_volontaires",
    )
    code_suivi = models.CharField(max_length=80, blank=True, default="", db_index=True)
    nom = models.CharField(max_length=150)
    prenoms = models.CharField(max_length=220, blank=True, default="")
    nom_et_prenoms = models.CharField(max_length=300, blank=True, default="")
    sexe = models.CharField(max_length=20, choices=Sexe.choices, blank=True, default="")
    date_naissance = models.DateField(blank=True, null=True)
    lieu_naissance = models.CharField(max_length=180, blank=True, default="")
    nationalite = models.CharField(max_length=120, blank=True, default="Burkinabè")
    numero_cnib = models.CharField(max_length=80, blank=True, default="", db_index=True)
    telephone = models.CharField(max_length=40)
    email = models.EmailField(blank=True, default="")
    contact_urgence = models.CharField(max_length=40, blank=True, default="")
    nom_contact_urgence = models.CharField(max_length=180, blank=True, default="")
    region_residence = models.CharField(max_length=120, blank=True, default="", db_index=True)
    province_residence = models.CharField(max_length=120, blank=True, default="", db_index=True)
    commune_residence = models.CharField(max_length=120, blank=True, default="")
    adresse_residence = models.TextField(blank=True, default="")
    niveau_etude = models.CharField(max_length=180, blank=True, default="")
    profession = models.CharField(max_length=180, blank=True, default="")
    motivation = models.TextField(blank=True, default="")
    statut_demande = models.CharField(
        max_length=20,
        choices=StatutDemande.choices,
        default=StatutDemande.EN_ATTENTE,
        db_index=True,
    )
    date_soumission = models.DateTimeField(default=timezone.now)
    date_decision = models.DateTimeField(blank=True, null=True)
    motif_decision = models.TextField(blank=True, default="")
    donnees_brutes = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "inscriptions_volontaires"
        ordering = ["-date_soumission", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["code_suivi"],
                condition=Q(deleted_at__isnull=True) & ~Q(code_suivi=""),
                name="uniq_inscription_volontaire_code_suivi_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "statut_demande"]),
            models.Index(fields=["telephone", "statut_demande"]),
            models.Index(fields=["deleted_at", "statut_demande"]),
        ]
        verbose_name = "Inscription volontaire"
        verbose_name_plural = "Inscriptions volontaires"

    def __str__(self):
        return f"{self.code_suivi or 'VOL'} - {self.identite_affichable}"

    @property
    def est_supprimee(self):
        return self.deleted_at is not None

    @property
    def identite_affichable(self):
        if self.nom_et_prenoms:
            return self.nom_et_prenoms
        return " ".join(partie for partie in [self.nom, self.prenoms] if partie).strip()

    @property
    def est_acceptee(self):
        return self.statut_demande == self.StatutDemande.ACCEPTEE

    def clean(self):
        erreurs = {}
        if not self.nom_et_prenoms and not (self.nom or self.prenoms):
            erreurs["nom_et_prenoms"] = "L'identité du volontaire est obligatoire."
        if not self.telephone and not self.email:
            erreurs["telephone"] = "Le téléphone ou l'email est obligatoire pour suivre une demande volontaire."
        if self.statut_demande in {self.StatutDemande.REJETEE, self.StatutDemande.ANNULEE} and not self.motif_decision:
            erreurs["motif_decision"] = "Le motif est obligatoire pour une demande rejetée ou annulée."
        if erreurs:
            raise ValidationError(erreurs)


class Immerge(models.Model):
    """Table centrale des immergés, sans duplication des données personnelles."""

    class TypeImmerge(models.TextChoices):
        BEPC = "BEPC", "BEPC"
        BAC = "BAC", "BAC"
        CONCOURS = "CONCOURS", "Concours"
        SELECTIONNE = "SELECTIONNE", "Sélectionné"
        VOLONTAIRE = "VOLONTAIRE", "Volontaire"

    class Statut(models.TextChoices):
        CREE = "CREE", "Créé"
        CODE_GENERE = "CODE_GENERE", "Code généré"
        AFFECTE_REGION = "AFFECTE_REGION", "Affecté à une région"
        AFFECTE_CENTRE = "AFFECTE_CENTRE", "Affecté à un centre"
        EN_IMMERSION = "EN_IMMERSION", "En immersion"
        LIBERE = "LIBERE", "Libéré"
        ANNULE = "ANNULE", "Annulé"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="immerges",
    )
    type_immerge = models.CharField(max_length=30, choices=TypeImmerge.choices, db_index=True)
    origine_id = models.PositiveBigIntegerField(db_index=True)
    code_fasoim = models.CharField(max_length=80, blank=True, default="", db_index=True)
    qr_code = models.CharField(max_length=255, blank=True, default="", db_index=True)
    statut = models.CharField(max_length=30, choices=Statut.choices, default=Statut.CREE, db_index=True)
    date_creation_code = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        db_table = "immerges"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "type_immerge", "origine_id"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_immerge_session_type_origine_actif",
            ),
            models.UniqueConstraint(
                fields=["code_fasoim"],
                condition=Q(deleted_at__isnull=True) & ~Q(code_fasoim=""),
                name="uniq_immerge_code_fasoim_actif",
            ),
            models.UniqueConstraint(
                fields=["qr_code"],
                condition=Q(deleted_at__isnull=True) & ~Q(qr_code=""),
                name="uniq_immerge_qr_code_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "type_immerge", "statut"]),
            models.Index(fields=["session", "statut"]),
            models.Index(fields=["deleted_at", "statut"]),
        ]
        verbose_name = "Immergé central"
        verbose_name_plural = "Immergés centraux"

    def __str__(self):
        return f"{self.code_fasoim or self.type_immerge} - origine {self.origine_id}"

    @property
    def est_supprime(self):
        return self.deleted_at is not None

    def clean(self):
        erreurs = {}
        if not self.type_immerge:
            erreurs["type_immerge"] = "Le type d'immergé est obligatoire."
        if not self.origine_id:
            erreurs["origine_id"] = "L'origine de l'immergé est obligatoire."
        if erreurs:
            raise ValidationError(erreurs)
