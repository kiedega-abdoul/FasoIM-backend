from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


ANNEE_PREMIERE_PROMOTION = 2025
NUMERO_PREMIERE_PROMOTION = 1


def annee_courante():
    return timezone.localdate().year


def calculer_numero_promotion(annee):
    """
    Règle retenue :
    - 2025 correspond à la promotion 1 ;
    - 2026 correspond à la promotion 2 ;
    - 2027 correspond à la promotion 3.

    Le numéro est calculé automatiquement à partir de l'année.
    """
    if annee >= ANNEE_PREMIERE_PROMOTION:
        return NUMERO_PREMIERE_PROMOTION + (annee - ANNEE_PREMIERE_PROMOTION)

    return NUMERO_PREMIERE_PROMOTION


def numero_promotion_par_defaut():
    return calculer_numero_promotion(annee_courante())


class SessionImmersion(models.Model):
    class TypeSession(models.TextChoices):
        EXAMEN = "examen", "Examen"
        CONCOURS = "concours", "Concours"
        SELECTIONNE = "selectionne", "Sélectionné"
        VOLONTAIRE = "volontaire", "Volontaire"
        MIXTE = "mixte", "Mixte"

    class PublicCible(models.TextChoices):
        BEPC = "BEPC", "BEPC"
        BAC = "BAC", "BAC"
        CONCOURS = "CONCOURS", "Concours"
        SELECTIONNE = "SELECTIONNE", "Sélectionné"
        VOLONTAIRE = "VOLONTAIRE", "Volontaire"
        MIXTE = "MIXTE", "Mixte"

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        OUVERTE = "ouverte", "Ouverte"
        EN_PREPARATION = "en_preparation", "En préparation"
        EN_COURS = "en_cours", "En cours"
        TERMINEE = "terminee", "Terminée"
        ARCHIVEE = "archivee", "Archivée"
        ANNULEE = "annulee", "Annulée"

    nom = models.CharField(max_length=255)

    # Code technique de la session, généré par le système.
    # Ce champ n'est pas le code FasoIM individuel des immergés.
    code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        editable=False,
        db_index=True,
    )

    annee = models.PositiveIntegerField(
        default=annee_courante,
        validators=[
            MinValueValidator(2025),
            MaxValueValidator(2100),
        ],
    )
    numero_promotion = models.PositiveIntegerField(
        default=numero_promotion_par_defaut,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(99),
        ],
        help_text="Par défaut : 2025 = promotion 1, 2026 = promotion 2, etc.",
    )

    type_session = models.CharField(
        max_length=30,
        choices=TypeSession.choices,
    )
    public_cible = models.CharField(
        max_length=30,
        choices=PublicCible.choices,
    )

    date_debut = models.DateField()
    date_fin = models.DateField()
    date_ouverture_inscription = models.DateField(null=True, blank=True)
    date_fermeture_inscription = models.DateField(null=True, blank=True)

    statut = models.CharField(
        max_length=30,
        choices=Statut.choices,
        default=Statut.BROUILLON,
        db_index=True,
    )
    description = models.TextField(blank=True)
    motif_annulation = models.TextField(blank=True)
    date_annulation = models.DateTimeField(null=True, blank=True)
    cloture_proposee_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cloture_proposee_blocages = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "sessions_immersion"
        ordering = ["-created_at"]
        verbose_name = "Session d'immersion"
        verbose_name_plural = "Sessions d'immersion"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(annee__gte=2025) & models.Q(annee__lte=2100),
                name="sessions_immersion_annee_2025_2100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(numero_promotion__gte=1)
                    & models.Q(numero_promotion__lte=99)
                ),
                name="sessions_immersion_promotion_1_99",
            ),
        ]

    def __str__(self):
        if self.code:
            return f"{self.code} - {self.nom}"
        return self.nom

    @property
    def est_active(self):
        return self.deleted_at is None and self.statut != self.Statut.ANNULEE

    @property
    def est_modifiable(self):
        return self.statut not in [
            self.Statut.TERMINEE,
            self.Statut.ARCHIVEE,
            self.Statut.ANNULEE,
        ]

    @property
    def accepte_import(self):
        if not hasattr(self, "parametres"):
            return False

        return self.parametres.mode_entree in [
            ParametreSession.ModeEntree.IMPORT,
            ParametreSession.ModeEntree.MIXTE,
        ]

    @property
    def accepte_inscription_volontaire(self):
        if not hasattr(self, "parametres"):
            return False

        return self.parametres.mode_entree in [
            ParametreSession.ModeEntree.INSCRIPTION,
            ParametreSession.ModeEntree.MIXTE,
        ]

    def generer_code_session(self):
        """
        Génère un code technique de session.

        Exemple :
        SES-2026-02-MIXTE-A1B2C3

        Le code FasoIM individuel sera généré plus tard dans le module immerges :
        IP{annee}{type}{numero_promotion}{sequence_5_chiffres}
        """
        suffixe = uuid4().hex[:6].upper()
        type_code = (self.type_session or "SESSION").upper()
        return f"SES-{self.annee}-{self.numero_promotion:02d}-{type_code}-{suffixe}"

    def clean(self):
        super().clean()

        if self.annee is not None:
            self.numero_promotion = calculer_numero_promotion(self.annee)

        correspondances = {
            self.TypeSession.EXAMEN: {self.PublicCible.BEPC, self.PublicCible.BAC},
            self.TypeSession.CONCOURS: {self.PublicCible.CONCOURS},
            self.TypeSession.SELECTIONNE: {self.PublicCible.SELECTIONNE},
            self.TypeSession.VOLONTAIRE: {self.PublicCible.VOLONTAIRE},
            self.TypeSession.MIXTE: {self.PublicCible.MIXTE},
        }
        if self.type_session and self.public_cible:
            if self.public_cible not in correspondances.get(self.type_session, set()):
                raise ValidationError({
                    "public_cible": "Le public cible n'est pas cohérent avec le type de session."
                })

        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError({
                "date_fin": "La date de fin ne peut pas être antérieure à la date de début."
            })

        if (
            self.date_ouverture_inscription
            and self.date_fermeture_inscription
            and self.date_fermeture_inscription < self.date_ouverture_inscription
        ):
            raise ValidationError({
                "date_fermeture_inscription": (
                    "La date de fermeture ne peut pas être antérieure à la date d'ouverture."
                )
            })

    def save(self, *args, **kwargs):
        if self.annee is not None:
            self.numero_promotion = calculer_numero_promotion(self.annee)

        if not self.code:
            self.code = self.generer_code_session()

        self.full_clean()
        super().save(*args, **kwargs)


class ParametreSession(models.Model):
    class ModeEntree(models.TextChoices):
        IMPORT = "import", "Import"
        INSCRIPTION = "inscription", "Inscription"
        MIXTE = "mixte", "Mixte"

    class ModeVisiteMedicale(models.TextChoices):
        ARRIVEE = "arrivee", "À l'arrivée"

    session = models.OneToOneField(
        SessionImmersion,
        on_delete=models.CASCADE,
        related_name="parametres",
    )

    mode_entree = models.CharField(
        max_length=30,
        choices=ModeEntree.choices,
        default=ModeEntree.IMPORT,
    )

    hebergement_active = models.BooleanField(default=True)
    repas_active = models.BooleanField(default=True)

    visite_medicale_active = models.BooleanField(default=False)
    mode_visite_medicale = models.CharField(
        max_length=30,
        choices=ModeVisiteMedicale.choices,
        default=ModeVisiteMedicale.ARRIVEE,
    )

    activites_active = models.BooleanField(default=True)
    evaluation_active = models.BooleanField(default=False)
    attestation_active = models.BooleanField(default=True)
    consultation_publique_active = models.BooleanField(default=True)

    taux_presence_minimum_attestation = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )

    moyenne_minimum_attestation = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("20.00")),
        ],
        help_text=(
            "Moyenne minimale sur 20 lorsque les évaluations sont activées."
        ),
    )

    directives_generales = models.TextField(blank=True)
    consignes_generales = models.TextField(blank=True)
    documents_exiges = models.JSONField(default=list, blank=True)
    centres_accueil = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Photographie des centres retenus pour la session : "
            "centre_id, centre_code et centre_nom."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "parametres_session"
        verbose_name = "Paramètre de session"
        verbose_name_plural = "Paramètres de session"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(taux_presence_minimum_attestation__gte=0)
                    & models.Q(taux_presence_minimum_attestation__lte=100)
                ),
                name="parametres_session_taux_presence_0_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(moyenne_minimum_attestation__gte=0)
                    & models.Q(moyenne_minimum_attestation__lte=20)
                ),
                name="parametres_session_moyenne_0_20",
            ),
        ]

    def __str__(self):
        return f"Paramètres - {self.session.code}"

    @property
    def utilise_import(self):
        return self.mode_entree in [
            self.ModeEntree.IMPORT,
            self.ModeEntree.MIXTE,
        ]

    @property
    def utilise_inscription_volontaire(self):
        return self.mode_entree in [
            self.ModeEntree.INSCRIPTION,
            self.ModeEntree.MIXTE,
        ]

    def clean(self):
        super().clean()

        if (
            self.taux_presence_minimum_attestation < Decimal("0.00")
            or self.taux_presence_minimum_attestation > Decimal("100.00")
        ):
            raise ValidationError({
                "taux_presence_minimum_attestation": (
                    "Le taux minimum de présence doit être compris entre 0 et 100."
                )
            })

        if (
            self.moyenne_minimum_attestation < Decimal("0.00")
            or self.moyenne_minimum_attestation > Decimal("20.00")
        ):
            raise ValidationError({
                "moyenne_minimum_attestation": (
                    "La moyenne minimale doit être comprise entre 0 et 20."
                )
            })

        if not isinstance(self.documents_exiges, list):
            raise ValidationError({
                "documents_exiges": "La liste des documents exigés doit être un tableau JSON."
            })

        if not self.visite_medicale_active:
            self.mode_visite_medicale = self.ModeVisiteMedicale.ARRIVEE

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
