from __future__ import annotations

from rest_framework import serializers

from immerges.models import Immerge
from sessions_app.models import SessionImmersion

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)


def _nettoyer_liste_unique(valeurs, *, nom_champ: str) -> list:
    """Nettoie une liste reçue par l'API en conservant son ordre."""

    resultat = []
    deja_vus = set()

    for valeur in valeurs or []:
        if isinstance(valeur, str):
            valeur = valeur.strip()

        if valeur in ("", None):
            raise serializers.ValidationError(
                f"{nom_champ} ne peut pas contenir une valeur vide."
            )

        cle = str(valeur).upper()
        if cle in deja_vus:
            raise serializers.ValidationError(
                f"{nom_champ} ne peut pas contenir de doublons."
            )

        deja_vus.add(cle)
        resultat.append(valeur)

    return resultat


def _resume_acteur(acteur):
    """Expose seulement l'identifiant et le nom utile à l'écran."""

    if acteur is None:
        return None

    nom = getattr(acteur, "nom_complet", "")
    if callable(nom):
        nom = nom()

    if not nom and hasattr(acteur, "get_full_name"):
        nom = acteur.get_full_name()

    nom = str(nom or getattr(acteur, "username", "") or "").strip()

    return {
        "id": acteur.id,
        "nom": nom,
    }


class SessionAffectationResumeSerializer(serializers.ModelSerializer):
    """Résumé non sensible d'une session."""

    class Meta:
        model = SessionImmersion
        fields = [
            "id",
            "code",
            "nom",
            "statut",
        ]
        read_only_fields = fields


class ImmergeAffectationResumeSerializer(serializers.ModelSerializer):
    """Résumé central de l'immergé.

    Les informations personnelles détaillées restent dans les tables sources.
    Elles seront exposées séparément dans le profil d'affectation préparé par
    le service, afin d'éviter toute duplication dans le modèle central.
    """

    class Meta:
        model = Immerge
        fields = [
            "id",
            "code_fasoim",
            "type_immerge",
            "statut",
        ]
        read_only_fields = fields


class ProfilAffectationSerializer(serializers.Serializer):
    """Profil uniforme destiné à la vérification d'une proposition."""

    immerge_id = serializers.IntegerField(read_only=True)
    origine_id = serializers.IntegerField(read_only=True)
    type_immerge = serializers.CharField(read_only=True)
    sexe = serializers.CharField(read_only=True, allow_blank=True)
    date_naissance = serializers.DateField(read_only=True, allow_null=True)
    region_reference = serializers.CharField(read_only=True, allow_blank=True)
    province_reference = serializers.CharField(read_only=True, allow_blank=True)
    niveau_examen = serializers.CharField(read_only=True, allow_blank=True)
    serie_filiere = serializers.CharField(read_only=True, allow_blank=True)
    specialite = serializers.CharField(read_only=True, allow_blank=True)
    structure_origine = serializers.CharField(read_only=True, allow_blank=True)
    niveau_etude = serializers.CharField(read_only=True, allow_blank=True)
    profession = serializers.CharField(read_only=True, allow_blank=True)
    identifiant_source = serializers.CharField(read_only=True, allow_blank=True)
    source_valide = serializers.BooleanField(read_only=True)


class RegionImmersionResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegionImmersion
        fields = [
            "id",
            "code",
            "nom",
            "statut",
        ]
        read_only_fields = fields


class RegionImmersionDetailSerializer(serializers.ModelSerializer):
    est_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = RegionImmersion
        fields = [
            "id",
            "code",
            "nom",
            "description",
            "statut",
            "est_active",
        ]
        read_only_fields = fields


class RegionImmersionInputSerializer(serializers.Serializer):
    """Données acceptées pour créer ou modifier une région.

    Ce serializer ne fait aucune écriture. La vue transmet validated_data au
    service, lequel applique les règles et utilise le repository.
    """

    code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=150)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    statut = serializers.ChoiceField(
        choices=RegionImmersion.Statut.choices,
        required=False,
        default=RegionImmersion.Statut.ACTIVE,
    )

    def validate_code(self, value):
        value = value.strip().upper()
        return value

    def validate_nom(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le nom de la région est obligatoire.")
        return value


class RegionImmersionUpdateSerializer(RegionImmersionInputSerializer):
    code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    statut = serializers.ChoiceField(
        choices=RegionImmersion.Statut.choices,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni pour la modification."
            )
        return attrs


class CentreImmersionResumeSerializer(serializers.ModelSerializer):
    region = RegionImmersionResumeSerializer(read_only=True)

    class Meta:
        model = CentreImmersion
        fields = [
            "id",
            "region",
            "code",
            "nom",
            "province",
            "ville",
            "genre",
            "statut",
        ]
        read_only_fields = fields


class CentreImmersionDetailSerializer(serializers.ModelSerializer):
    region = RegionImmersionResumeSerializer(read_only=True)
    est_actif = serializers.BooleanField(read_only=True)

    class Meta:
        model = CentreImmersion
        fields = [
            "id",
            "region",
            "code",
            "nom",
            "province",
            "ville",
            "adresse",
            "genre",
            "publics_acceptes",
            "niveaux_acceptes",
            "statut",
            "est_actif",
        ]
        read_only_fields = fields


class CentreImmersionInputSerializer(serializers.Serializer):
    """Données reçues pour créer un centre.

    region_id reste un identifiant simple. Sa résolution et son verrouillage
    appartiennent au service, pas au serializer.
    """

    region_id = serializers.IntegerField(min_value=1)
    code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=200)
    province = serializers.CharField(max_length=150)
    ville = serializers.CharField(max_length=150)
    adresse = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    genre = serializers.ChoiceField(
        choices=CentreImmersion.Genre.choices,
        required=False,
        default=CentreImmersion.Genre.MIXTE,
    )
    publics_acceptes = serializers.ListField(
        child=serializers.ChoiceField(choices=Immerge.TypeImmerge.choices),
        required=False,
        allow_empty=True,
        default=list,
        max_length=20,
    )
    niveaux_acceptes = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        default=list,
        max_length=100,
    )
    statut = serializers.ChoiceField(
        choices=CentreImmersion.Statut.choices,
        required=False,
        default=CentreImmersion.Statut.ACTIF,
    )

    def validate_code(self, value):
        value = value.strip().upper()
        return value

    def validate_nom(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Le nom du centre est obligatoire.")
        return value

    def validate_province(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("La province est obligatoire.")
        return value

    def validate_ville(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("La ville est obligatoire.")
        return value

    def validate_publics_acceptes(self, value):
        return _nettoyer_liste_unique(
            value,
            nom_champ="La liste des publics acceptés",
        )

    def validate_niveaux_acceptes(self, value):
        return _nettoyer_liste_unique(
            value,
            nom_champ="La liste des niveaux acceptés",
        )


class CentreImmersionUpdateSerializer(CentreImmersionInputSerializer):
    region_id = serializers.IntegerField(min_value=1, required=False)
    code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    nom = serializers.CharField(max_length=200, required=False)
    province = serializers.CharField(max_length=150, required=False)
    ville = serializers.CharField(max_length=150, required=False)
    adresse = serializers.CharField(required=False, allow_blank=True)
    genre = serializers.ChoiceField(
        choices=CentreImmersion.Genre.choices,
        required=False,
    )
    publics_acceptes = serializers.ListField(
        child=serializers.ChoiceField(choices=Immerge.TypeImmerge.choices),
        required=False,
        allow_empty=True,
        max_length=20,
    )
    niveaux_acceptes = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
        allow_empty=True,
        max_length=100,
    )
    statut = serializers.ChoiceField(
        choices=CentreImmersion.Statut.choices,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni pour la modification."
            )
        return attrs


class AffectationRegionaleSerializer(serializers.ModelSerializer):
    immerge = ImmergeAffectationResumeSerializer(read_only=True)
    session = SessionAffectationResumeSerializer(read_only=True)
    region = RegionImmersionResumeSerializer(read_only=True)
    affecte_par = serializers.SerializerMethodField()
    est_proposee = serializers.BooleanField(read_only=True)
    est_active = serializers.BooleanField(read_only=True)
    est_ouverte = serializers.BooleanField(read_only=True)
    profil_source = serializers.SerializerMethodField()

    class Meta:
        model = AffectationRegionale
        fields = [
            "id",
            "immerge",
            "session",
            "region",
            "statut",
            "affecte_par",
            "date_affectation",
            "motif",
            "est_proposee",
            "est_active",
            "est_ouverte",
            "profil_source",
        ]
        read_only_fields = fields

    def get_affecte_par(self, obj):
        return _resume_acteur(obj.affecte_par)

    def get_profil_source(self, obj):
        """Lit un profil préchargé sans lancer de requête supplémentaire."""

        profil = getattr(obj, "_profil_affectation", None)
        if profil is None:
            return None
        return ProfilAffectationSerializer(profil).data


class AffectationCentreSerializer(serializers.ModelSerializer):
    immerge = ImmergeAffectationResumeSerializer(read_only=True)
    session = SessionAffectationResumeSerializer(read_only=True)
    affectation_regionale_id = serializers.IntegerField(read_only=True)
    centre = CentreImmersionResumeSerializer(read_only=True)
    affecte_par = serializers.SerializerMethodField()
    est_proposee = serializers.BooleanField(read_only=True)
    est_active = serializers.BooleanField(read_only=True)
    est_ouverte = serializers.BooleanField(read_only=True)
    profil_source = serializers.SerializerMethodField()

    class Meta:
        model = AffectationCentre
        fields = [
            "id",
            "immerge",
            "session",
            "affectation_regionale_id",
            "centre",
            "statut",
            "affecte_par",
            "date_affectation",
            "motif",
            "est_proposee",
            "est_active",
            "est_ouverte",
            "profil_source",
        ]
        read_only_fields = fields

    def get_affecte_par(self, obj):
        return _resume_acteur(obj.affecte_par)

    def get_profil_source(self, obj):
        profil = getattr(obj, "_profil_affectation", None)
        if profil is None:
            return None
        return ProfilAffectationSerializer(profil).data


class PropositionRegionaleLotInputSerializer(serializers.Serializer):
    """Demande de génération asynchrone d'un lot régional."""

    session_id = serializers.IntegerField(min_value=1)
    nombre = serializers.IntegerField(min_value=1, max_value=1000)
    forcer_reliquat = serializers.BooleanField(required=False, default=False)


class PropositionCentreLotInputSerializer(serializers.Serializer):
    """Demande de génération asynchrone d'un lot de centres."""

    session_id = serializers.IntegerField(min_value=1)
    region_id = serializers.IntegerField(min_value=1)
    nombre = serializers.IntegerField(min_value=1, max_value=1000)


class AffectationRegionaleManuelleInputSerializer(serializers.Serializer):
    immerge_id = serializers.IntegerField(min_value=1)
    region_id = serializers.IntegerField(min_value=1)
    motif = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        default="",
    )


class AffectationCentreManuelleInputSerializer(serializers.Serializer):
    immerge_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    motif = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        default="",
    )


class ActionAffectationsLotInputSerializer(serializers.Serializer):
    """Base commune aux validations et rejets en masse."""

    affectation_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        min_length=1,
        max_length=1000,
    )
    motif = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        default="",
    )

    def validate_affectation_ids(self, value):
        ids = list(dict.fromkeys(value))
        if len(ids) != len(value):
            raise serializers.ValidationError(
                "La liste des affectations contient des doublons."
            )
        return ids


class ValidationAffectationsLotInputSerializer(ActionAffectationsLotInputSerializer):
    pass


class RejetAffectationsLotInputSerializer(ActionAffectationsLotInputSerializer):
    motif = serializers.CharField(
        allow_blank=False,
        max_length=2000,
    )

    def validate_motif(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "Le motif du rejet est obligatoire."
            )
        return value


class AnnulationAffectationInputSerializer(serializers.Serializer):
    motif = serializers.CharField(
        allow_blank=False,
        max_length=2000,
    )

    def validate_motif(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "Le motif de l'annulation est obligatoire."
            )
        return value


class ResultatPropositionLotSerializer(serializers.Serializer):
    """Réponse métier retournée après l'exécution de la tâche Celery."""

    demandes = serializers.IntegerField(read_only=True)
    candidats_pris = serializers.IntegerField(read_only=True)
    propositions_creees = serializers.IntegerField(read_only=True)
    candidats_restants = serializers.IntegerField(read_only=True)
    sans_source = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
    )
    sans_destination = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
    )
    affectation_ids = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
    )
    details = serializers.DictField(read_only=True)


class TacheAffectationLanceeSerializer(serializers.Serializer):
    """Réponse immédiate de l'API avant le traitement Celery."""

    task_id = serializers.CharField(read_only=True)
    operation = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class ProgressionAffectationSerializer(serializers.Serializer):
    """État temporaire conservé dans Redis pour le frontend."""

    task_id = serializers.CharField(read_only=True)
    operation = serializers.CharField(read_only=True)
    statut = serializers.CharField(read_only=True)
    progression = serializers.IntegerField(
        read_only=True,
        min_value=0,
        max_value=100,
    )
    message = serializers.CharField(read_only=True, allow_blank=True)
    total = serializers.IntegerField(read_only=True, min_value=0)
    traites = serializers.IntegerField(read_only=True, min_value=0)
    proposes = serializers.IntegerField(read_only=True, min_value=0)
    restants = serializers.IntegerField(read_only=True, min_value=0)
    erreurs = serializers.IntegerField(read_only=True, min_value=0)
    resultat = ResultatPropositionLotSerializer(
        read_only=True,
        allow_null=True,
    )


class FiltreCentreImmersionSerializer(serializers.Serializer):
    region_id = serializers.IntegerField(required=False, min_value=1)
    region_code = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=50,
    )
    centre_id = serializers.IntegerField(required=False, min_value=1)
    statut = serializers.ChoiceField(
        choices=CentreImmersion.Statut.choices,
        required=False,
    )
    genre = serializers.ChoiceField(
        choices=CentreImmersion.Genre.choices,
        required=False,
    )
    type_immerge = serializers.ChoiceField(
        choices=Immerge.TypeImmerge.choices,
        required=False,
    )
    niveau_examen = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=100,
    )
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
    )


class FiltreAffectationRegionaleSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    region_id = serializers.IntegerField(required=False, min_value=1)
    statut = serializers.ChoiceField(
        choices=AffectationRegionale.Statut.choices,
        required=False,
    )
    type_immerge = serializers.ChoiceField(
        choices=Immerge.TypeImmerge.choices,
        required=False,
    )
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
    )


class FiltreAffectationCentreSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=False, min_value=1)
    region_id = serializers.IntegerField(required=False, min_value=1)
    centre_id = serializers.IntegerField(required=False, min_value=1)
    statut = serializers.ChoiceField(
        choices=AffectationCentre.Statut.choices,
        required=False,
    )
    type_immerge = serializers.ChoiceField(
        choices=Immerge.TypeImmerge.choices,
        required=False,
    )
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
    )
