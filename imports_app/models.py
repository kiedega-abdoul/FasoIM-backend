from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ImportOfficiel(models.Model):
    """Dossier d'import d'une liste officielle pour une session FasoIM.

    L'import officiel ne crée pas directement les immergés. Il conserve le
    fichier, les colonnes détectées, l'état du traitement et les statistiques.
    Les lignes validées seront transformées plus tard par le module immerges.
    """

    class TypeSource(models.TextChoices):
        BEPC = "BEPC", "BEPC"
        BAC = "BAC", "BAC"
        CONCOURS = "CONCOURS", "Concours"
        SELECTIONNES = "SELECTIONNES", "Sélectionnés"
        VOLONTAIRES_ACCEPTES = "VOLONTAIRES_ACCEPTES", "Volontaires acceptés"

    class TypeFichier(models.TextChoices):
        EXCEL = "EXCEL", "Excel"
        CSV = "CSV", "CSV"

    class Statut(models.TextChoices):
        RECU = "RECU", "Reçu"
        LECTURE_COLONNES_EN_COURS = "LECTURE_COLONNES_EN_COURS", "Lecture des colonnes en cours"
        CORRESPONDANCE_REQUISE = "CORRESPONDANCE_REQUISE", "Correspondance requise"
        CORRESPONDANCE_VALIDEE = "CORRESPONDANCE_VALIDEE", "Correspondance validée"
        VALIDATION_EN_COURS = "VALIDATION_EN_COURS", "Validation en cours"
        VALIDE = "VALIDE", "Valide"
        VALIDE_AVEC_ERREURS = "VALIDE_AVEC_ERREURS", "Valide avec erreurs"
        CONFIRMATION_EN_COURS = "CONFIRMATION_EN_COURS", "Confirmation en cours"
        TERMINE = "TERMINE", "Terminé"
        ECHEC = "ECHEC", "Échec"
        ANNULE = "ANNULE", "Annulé"

    session = models.ForeignKey(
        "sessions_app.SessionImmersion",
        on_delete=models.PROTECT,
        related_name="imports_officiels",
    )
    type_source = models.CharField(max_length=40, choices=TypeSource.choices, db_index=True)
    type_fichier = models.CharField(max_length=20, choices=TypeFichier.choices, default=TypeFichier.EXCEL)
    fichier = models.FileField(upload_to="imports/officiels/%Y/%m/", max_length=500)
    nom_fichier_original = models.CharField(max_length=255)
    taille_fichier = models.PositiveBigIntegerField(default=0)
    hash_fichier = models.CharField(max_length=128, blank=True, default="", db_index=True)

    statut = models.CharField(max_length=40, choices=Statut.choices, default=Statut.RECU, db_index=True)
    colonnes_detectees = models.JSONField(default=list, blank=True)
    apercu_lignes = models.JSONField(default=list, blank=True)
    message_erreur = models.TextField(blank=True, default="")
    commentaire = models.TextField(blank=True, default="")

    total_lignes = models.PositiveIntegerField(default=0)
    lignes_valides = models.PositiveIntegerField(default=0)
    lignes_erreur = models.PositiveIntegerField(default=0)
    lignes_ignorees = models.PositiveIntegerField(default=0)
    lignes_importees = models.PositiveIntegerField(default=0)

    importe_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="imports_officiels_crees",
        blank=True,
        null=True,
    )
    correspondance_confirmee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="imports_correspondances_confirmees",
        blank=True,
        null=True,
    )
    confirme_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="imports_confirmes",
        blank=True,
        null=True,
    )

    date_import = models.DateTimeField(default=timezone.now)
    date_lecture_colonnes = models.DateTimeField(blank=True, null=True)
    date_correspondance = models.DateTimeField(blank=True, null=True)
    date_validation = models.DateTimeField(blank=True, null=True)
    date_confirmation = models.DateTimeField(blank=True, null=True)
    date_fin_traitement = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["-date_import", "-id"]
        indexes = [
            models.Index(fields=["session", "type_source", "statut"]),
            models.Index(fields=["statut", "date_import"]),
            models.Index(fields=["deleted_at", "statut"]),
        ]
        verbose_name = "Import officiel"
        verbose_name_plural = "Imports officiels"

    def __str__(self):
        return f"{self.type_source} - {self.nom_fichier_original}"

    def clean(self):
        erreurs = {}

        compteurs = [
            self.total_lignes,
            self.lignes_valides,
            self.lignes_erreur,
            self.lignes_ignorees,
            self.lignes_importees,
        ]
        if any(valeur is not None and valeur < 0 for valeur in compteurs):
            erreurs["total_lignes"] = "Les compteurs d'import ne peuvent pas être négatifs."

        if self.statut == self.Statut.CORRESPONDANCE_REQUISE and not self.colonnes_detectees:
            erreurs["colonnes_detectees"] = "Les colonnes détectées sont obligatoires quand la correspondance est requise."

        if self.statut == self.Statut.ECHEC and not self.message_erreur:
            erreurs["message_erreur"] = "Le message d'erreur est obligatoire pour un import en échec."

        if erreurs:
            raise ValidationError(erreurs)

    @property
    def est_supprime(self):
        return self.deleted_at is not None

    @property
    def attend_correspondance(self):
        return self.statut == self.Statut.CORRESPONDANCE_REQUISE

    @property
    def peut_recevoir_correspondance(self):
        return self.statut in {
            self.Statut.CORRESPONDANCE_REQUISE,
            self.Statut.CORRESPONDANCE_VALIDEE,
            self.Statut.VALIDE_AVEC_ERREURS,
        }

    @property
    def peut_etre_confirme(self):
        return self.statut in {self.Statut.VALIDE, self.Statut.VALIDE_AVEC_ERREURS}


class CorrespondanceColonneImport(models.Model):
    """Correspondance validée entre un champ attendu par FasoIM et une colonne du fichier."""

    import_officiel = models.ForeignKey(
        ImportOfficiel,
        on_delete=models.CASCADE,
        related_name="correspondances",
    )
    champ_cible = models.CharField(max_length=120, db_index=True)
    libelle_champ_cible = models.CharField(max_length=180, blank=True, default="")
    colonne_source = models.CharField(max_length=255)
    obligatoire = models.BooleanField(default=False)
    confirmee = models.BooleanField(default=False)
    ordre = models.PositiveIntegerField(default=0)
    transformation = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["ordre", "champ_cible"]
        constraints = [
            models.UniqueConstraint(
                fields=["import_officiel", "champ_cible"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_correspondance_import_champ_actif",
            ),
            models.UniqueConstraint(
                fields=["import_officiel", "colonne_source"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_correspondance_import_colonne_active",
            ),
        ]
        indexes = [
            models.Index(fields=["import_officiel", "champ_cible"]),
            models.Index(fields=["import_officiel", "colonne_source"]),
            models.Index(fields=["deleted_at", "confirmee"]),
        ]
        verbose_name = "Correspondance de colonne"
        verbose_name_plural = "Correspondances de colonnes"

    def __str__(self):
        return f"{self.champ_cible} ← {self.colonne_source}"

    def clean(self):
        erreurs = {}
        if not self.champ_cible:
            erreurs["champ_cible"] = "Le champ cible est obligatoire."
        if not self.colonne_source:
            erreurs["colonne_source"] = "La colonne source est obligatoire."
        if self.import_officiel_id and self.colonne_source:
            colonnes = self.import_officiel.colonnes_detectees or []
            if colonnes and self.colonne_source not in colonnes:
                erreurs["colonne_source"] = "La colonne source n'existe pas dans les colonnes détectées du fichier."
        if erreurs:
            raise ValidationError(erreurs)

    @property
    def est_supprimee(self):
        return self.deleted_at is not None


class LigneImport(models.Model):
    """Ligne lue dans un import après validation de la correspondance des colonnes."""

    class Statut(models.TextChoices):
        EN_ATTENTE = "EN_ATTENTE", "En attente"
        VALIDE = "VALIDE", "Valide"
        ERREUR = "ERREUR", "Erreur"
        IGNOREE = "IGNOREE", "Ignorée"
        IMPORTEE = "IMPORTEE", "Importée"

    import_officiel = models.ForeignKey(
        ImportOfficiel,
        on_delete=models.CASCADE,
        related_name="lignes",
    )
    numero_ligne = models.PositiveIntegerField()
    donnees_brutes = models.JSONField(default=dict, blank=True)
    donnees_normalisees = models.JSONField(default=dict, blank=True)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE, db_index=True)
    message_statut = models.TextField(blank=True, default="")
    hash_ligne = models.CharField(max_length=128, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["import_officiel", "numero_ligne"]
        constraints = [
            models.UniqueConstraint(
                fields=["import_officiel", "numero_ligne"],
                condition=Q(deleted_at__isnull=True),
                name="uniq_ligne_import_numero_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["import_officiel", "statut"]),
            models.Index(fields=["import_officiel", "numero_ligne"]),
            models.Index(fields=["deleted_at", "statut"]),
        ]
        verbose_name = "Ligne d'import"
        verbose_name_plural = "Lignes d'import"

    def __str__(self):
        return f"{self.import_officiel_id} - ligne {self.numero_ligne}"

    def clean(self):
        erreurs = {}
        if self.numero_ligne <= 0:
            erreurs["numero_ligne"] = "Le numéro de ligne doit être supérieur à zéro."
        if self.statut == self.Statut.ERREUR and not self.message_statut:
            erreurs["message_statut"] = "Le message de statut est recommandé pour une ligne en erreur."
        if erreurs:
            raise ValidationError(erreurs)

    @property
    def est_supprimee(self):
        return self.deleted_at is not None

    @property
    def a_erreurs_bloquantes(self):
        return self.erreurs.filter(
            deleted_at__isnull=True,
            gravite=ErreurImport.Gravite.BLOQUANTE,
        ).exists()


class ErreurImport(models.Model):
    """Erreur ou avertissement détecté sur une ligne d'import."""

    class Gravite(models.TextChoices):
        BLOQUANTE = "BLOQUANTE", "Bloquante"
        AVERTISSEMENT = "AVERTISSEMENT", "Avertissement"

    class TypeErreur(models.TextChoices):
        CHAMP_OBLIGATOIRE = "CHAMP_OBLIGATOIRE", "Champ obligatoire"
        FORMAT_INVALIDE = "FORMAT_INVALIDE", "Format invalide"
        VALEUR_INVALIDE = "VALEUR_INVALIDE", "Valeur invalide"
        DOUBLON_FICHIER = "DOUBLON_FICHIER", "Doublon dans le fichier"
        DOUBLON_BASE = "DOUBLON_BASE", "Doublon dans la base"
        INCOHERENCE = "INCOHERENCE", "Incohérence"
        SYSTEME = "SYSTEME", "Erreur système"

    import_officiel = models.ForeignKey(
        ImportOfficiel,
        on_delete=models.CASCADE,
        related_name="erreurs",
    )
    ligne_import = models.ForeignKey(
        LigneImport,
        on_delete=models.CASCADE,
        related_name="erreurs",
    )
    champ_cible = models.CharField(max_length=120, blank=True, default="", db_index=True)
    colonne_source = models.CharField(max_length=255, blank=True, default="")
    type_erreur = models.CharField(max_length=40, choices=TypeErreur.choices, db_index=True)
    gravite = models.CharField(max_length=20, choices=Gravite.choices, default=Gravite.BLOQUANTE, db_index=True)
    message = models.TextField()
    valeur_recue = models.TextField(blank=True, default="")
    code_erreur = models.CharField(max_length=120, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["ligne_import__numero_ligne", "champ_cible", "id"]
        indexes = [
            models.Index(fields=["import_officiel", "gravite"]),
            models.Index(fields=["import_officiel", "type_erreur"]),
            models.Index(fields=["ligne_import", "gravite"]),
            models.Index(fields=["deleted_at", "gravite"]),
        ]
        verbose_name = "Erreur d'import"
        verbose_name_plural = "Erreurs d'import"

    def __str__(self):
        champ = self.champ_cible or self.colonne_source or "ligne"
        return f"{champ} - {self.type_erreur}"

    def clean(self):
        erreurs = {}
        if self.ligne_import_id and self.import_officiel_id:
            if self.ligne_import.import_officiel_id != self.import_officiel_id:
                erreurs["import_officiel"] = "L'erreur doit appartenir au même import que la ligne."
        if not self.message:
            erreurs["message"] = "Le message d'erreur est obligatoire."
        if erreurs:
            raise ValidationError(erreurs)

    @property
    def est_bloquante(self):
        return self.gravite == self.Gravite.BLOQUANTE
