from __future__ import annotations

from rest_framework import serializers

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)


class SessionActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class CentreActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class SectionActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class GroupeActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    nom = serializers.CharField()


class ActeurActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
    )
    first_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    last_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class ImmergeActiviteResumeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code_fasoim = serializers.CharField()
    type_immerge = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )


class AffectationCentreActiviteResumeSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    session = SessionActiviteResumeSerializer()
    centre = CentreActiviteResumeSerializer()
    immerge = ImmergeActiviteResumeSerializer()
    statut = serializers.CharField()


class ModuleActiviteSerializer(serializers.ModelSerializer):
    categorie_libelle = serializers.CharField(
        source="get_categorie_display",
        read_only=True,
    )
    statut_libelle = serializers.CharField(
        source="get_statut_display",
        read_only=True,
    )
    est_actif = serializers.BooleanField(read_only=True)

    class Meta:
        model = ModuleActivite
        fields = [
            "id",
            "code",
            "titre",
            "description",
            "categorie",
            "categorie_libelle",
            "duree_prevue",
            "ordre",
            "statut",
            "statut_libelle",
            "est_actif",
        ]


class ModuleActiviteCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=60)
    titre = serializers.CharField(max_length=180)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    categorie = serializers.ChoiceField(
        choices=ModuleActivite.Categorie.choices,
    )
    duree_prevue = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    ordre = serializers.IntegerField(
        min_value=0,
        default=0,
    )
    statut = serializers.ChoiceField(
        choices=ModuleActivite.Statut.choices,
        default=ModuleActivite.Statut.ACTIF,
    )


class ModuleActiviteUpdateSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=60,
        required=False,
    )
    titre = serializers.CharField(
        max_length=180,
        required=False,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    categorie = serializers.ChoiceField(
        choices=ModuleActivite.Categorie.choices,
        required=False,
    )
    duree_prevue = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    ordre = serializers.IntegerField(
        min_value=0,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=ModuleActivite.Statut.choices,
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni."
            )
        return attrs


class FiltreModuleActiviteSerializer(serializers.Serializer):
    categorie = serializers.ChoiceField(
        choices=ModuleActivite.Categorie.choices,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=ModuleActivite.Statut.choices,
        required=False,
    )
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )


class SeanceResumeSerializer(serializers.ModelSerializer):
    module_code = serializers.CharField(
        source="module_activite.code",
        read_only=True,
    )
    module_titre = serializers.CharField(
        source="module_activite.titre",
        read_only=True,
    )
    niveau_cible = serializers.CharField(read_only=True)

    class Meta:
        model = Seance
        fields = [
            "id",
            "module_code",
            "module_titre",
            "titre",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "lieu",
            "statut",
            "niveau_cible",
        ]


class SeanceSerializer(serializers.ModelSerializer):
    module_activite = ModuleActiviteSerializer(read_only=True)
    session = SessionActiviteResumeSerializer(read_only=True)
    centre = CentreActiviteResumeSerializer(read_only=True)
    section = SectionActiviteResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    groupe = GroupeActiviteResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    formateur = ActeurActiviteResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    presences_validees_par = ActeurActiviteResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    statut_libelle = serializers.CharField(
        source="get_statut_display",
        read_only=True,
    )
    statut_feuille_presence_libelle = serializers.CharField(
        source="get_statut_feuille_presence_display",
        read_only=True,
    )
    niveau_cible = serializers.CharField(read_only=True)
    feuille_presence_modifiable = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = Seance
        fields = [
            "id",
            "module_activite",
            "session",
            "centre",
            "section",
            "groupe",
            "formateur",
            "titre",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "lieu",
            "statut",
            "statut_libelle",
            "observations",
            "niveau_cible",
            "statut_feuille_presence",
            "statut_feuille_presence_libelle",
            "date_ouverture_presence",
            "date_validation_presence",
            "date_cloture_presence",
            "presences_validees_par",
            "feuille_presence_modifiable",
        ]


class SeanceCreateSerializer(serializers.Serializer):
    module_activite_id = serializers.IntegerField(min_value=1)
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    section_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    groupe_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    formateur_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    titre = serializers.CharField(
        max_length=180,
        required=False,
        allow_blank=True,
        default="",
    )
    date_seance = serializers.DateField()
    heure_debut = serializers.TimeField()
    heure_fin = serializers.TimeField()
    lieu = serializers.CharField(max_length=180)
    statut = serializers.ChoiceField(
        choices=[
            Seance.Statut.BROUILLON,
            Seance.Statut.PLANIFIEE,
        ],
        default=Seance.Statut.PLANIFIEE,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if attrs["heure_fin"] <= attrs["heure_debut"]:
            raise serializers.ValidationError(
                {
                    "heure_fin": (
                        "L'heure de fin doit être postérieure "
                        "à l'heure de début."
                    )
                }
            )
        return attrs


class SeanceUpdateSerializer(serializers.Serializer):
    module_activite_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    section_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    groupe_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    formateur_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    titre = serializers.CharField(
        max_length=180,
        required=False,
        allow_blank=True,
    )
    date_seance = serializers.DateField(required=False)
    heure_debut = serializers.TimeField(required=False)
    heure_fin = serializers.TimeField(required=False)
    lieu = serializers.CharField(
        max_length=180,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=[
            Seance.Statut.BROUILLON,
            Seance.Statut.PLANIFIEE,
            Seance.Statut.EN_COURS,
            Seance.Statut.TERMINEE,
        ],
        required=False,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni."
            )

        debut = attrs.get("heure_debut")
        fin = attrs.get("heure_fin")
        if debut and fin and fin <= debut:
            raise serializers.ValidationError(
                {
                    "heure_fin": (
                        "L'heure de fin doit être postérieure "
                        "à l'heure de début."
                    )
                }
            )
        return attrs


class FiltreSeanceSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    section_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    groupe_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    module_activite_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    formateur_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=Seance.Statut.choices,
        required=False,
    )
    statut_feuille_presence = serializers.ChoiceField(
        choices=Seance.StatutFeuillePresence.choices,
        required=False,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "session_id",
                "centre_id",
                "section_id",
                "groupe_id",
                "module_activite_id",
                "formateur_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre de planning est obligatoire."
            )

        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class ReporterSeanceSerializer(serializers.Serializer):
    nouvelle_date = serializers.DateField()
    nouvelle_heure_debut = serializers.TimeField(
        required=False,
        allow_null=True,
    )
    nouvelle_heure_fin = serializers.TimeField(
        required=False,
        allow_null=True,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        debut = attrs.get("nouvelle_heure_debut")
        fin = attrs.get("nouvelle_heure_fin")
        if debut and fin and fin <= debut:
            raise serializers.ValidationError(
                {
                    "nouvelle_heure_fin": (
                        "L'heure de fin doit être postérieure "
                        "à l'heure de début."
                    )
                }
            )
        return attrs


class AffecterFormateurSerializer(serializers.Serializer):
    formateur_id = serializers.IntegerField(
        min_value=1,
        allow_null=True,
    )


class PresenceSerializer(serializers.ModelSerializer):
    seance = SeanceResumeSerializer(read_only=True)
    affectation_centre = (
        AffectationCentreActiviteResumeSerializer(read_only=True)
    )
    saisie_par = ActeurActiviteResumeSerializer(read_only=True)
    statut_presence_libelle = serializers.CharField(
        source="get_statut_presence_display",
        read_only=True,
    )
    compte_comme_present = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = Presence
        fields = [
            "id",
            "seance",
            "affectation_centre",
            "statut_presence",
            "statut_presence_libelle",
            "heure_arrivee",
            "observations",
            "saisie_par",
            "date_saisie",
            "compte_comme_present",
        ]


class PresenceCreateSerializer(serializers.Serializer):
    seance_id = serializers.IntegerField(min_value=1)
    affectation_centre_id = serializers.IntegerField(min_value=1)
    statut_presence = serializers.ChoiceField(
        choices=Presence.StatutPresence.choices,
    )
    heure_arrivee = serializers.TimeField(
        required=False,
        allow_null=True,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni."
            )

        if (
            attrs.get("statut_presence")
            == Presence.StatutPresence.RETARD
            and not attrs.get("heure_arrivee")
        ):
            raise serializers.ValidationError(
                {
                    "heure_arrivee": (
                        "L'heure d'arrivée est obligatoire "
                        "pour un retard."
                    )
                }
            )
        return attrs


class PresenceUpdateSerializer(serializers.Serializer):
    statut_presence = serializers.ChoiceField(
        choices=Presence.StatutPresence.choices,
        required=False,
    )
    heure_arrivee = serializers.TimeField(
        required=False,
        allow_null=True,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if (
            attrs["statut_presence"]
            == Presence.StatutPresence.RETARD
            and not attrs.get("heure_arrivee")
        ):
            raise serializers.ValidationError(
                {
                    "heure_arrivee": (
                        "L'heure d'arrivée est obligatoire "
                        "pour un retard."
                    )
                }
            )
        return attrs


class FiltrePresenceSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    seance_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    statut_presence = serializers.ChoiceField(
        choices=Presence.StatutPresence.choices,
        required=False,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "session_id",
                "centre_id",
                "seance_id",
                "affectation_centre_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre de présence est obligatoire."
            )

        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class SeanceIdSerializer(serializers.Serializer):
    seance_id = serializers.IntegerField(min_value=1)


class TauxPresenceQuerySerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    session_id = serializers.IntegerField(min_value=1)
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)

    def validate(self, attrs):
        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class TauxPresenceSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField()
    session_id = serializers.IntegerField()
    total_seances = serializers.IntegerField(min_value=0)
    total_eligible = serializers.IntegerField(min_value=0)
    favorables = serializers.IntegerField(min_value=0)
    presents = serializers.IntegerField(min_value=0)
    retards = serializers.IntegerField(min_value=0)
    absences = serializers.IntegerField(min_value=0)
    excuses = serializers.IntegerField(min_value=0)
    dispenses = serializers.IntegerField(min_value=0)
    taux_presence = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    seuil_attestation = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    seuil_atteint = serializers.BooleanField()


class EvaluationResumeSerializer(serializers.ModelSerializer):
    session_id = serializers.IntegerField(read_only=True)
    centre_id = serializers.IntegerField(read_only=True)
    seance_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "session_id",
            "centre_id",
            "seance_id",
            "titre",
            "type_evaluation",
            "bareme",
            "coefficient",
            "date_evaluation",
            "statut",
        ]


class EvaluationSerializer(serializers.ModelSerializer):
    session = SessionActiviteResumeSerializer(read_only=True)
    centre = CentreActiviteResumeSerializer(read_only=True)
    seance = SeanceResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    created_by = ActeurActiviteResumeSerializer(
        read_only=True,
        allow_null=True,
    )
    type_evaluation_libelle = serializers.CharField(
        source="get_type_evaluation_display",
        read_only=True,
    )
    statut_libelle = serializers.CharField(
        source="get_statut_display",
        read_only=True,
    )
    module_activite = serializers.SerializerMethodField()

    class Meta:
        model = Evaluation
        fields = [
            "id",
            "session",
            "centre",
            "seance",
            "module_activite",
            "titre",
            "type_evaluation",
            "type_evaluation_libelle",
            "bareme",
            "coefficient",
            "date_evaluation",
            "statut",
            "statut_libelle",
            "created_by",
        ]

    def get_module_activite(self, obj):
        if not obj.seance_id:
            return None
        return ModuleActiviteSerializer(
            obj.seance.module_activite
        ).data


class EvaluationCreateSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    centre_id = serializers.IntegerField(min_value=1)
    seance_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    titre = serializers.CharField(max_length=180)
    type_evaluation = serializers.ChoiceField(
        choices=Evaluation.TypeEvaluation.choices,
    )
    bareme = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0.01,
    )
    coefficient = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0.01,
        default="1.00",
    )
    date_evaluation = serializers.DateTimeField()
    statut = serializers.HiddenField(
        default=Evaluation.Statut.BROUILLON,
    )


class EvaluationUpdateSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    seance_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
    )
    titre = serializers.CharField(
        max_length=180,
        required=False,
    )
    type_evaluation = serializers.ChoiceField(
        choices=Evaluation.TypeEvaluation.choices,
        required=False,
    )
    bareme = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0.01,
        required=False,
    )
    coefficient = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0.01,
        required=False,
    )
    date_evaluation = serializers.DateTimeField(
        required=False,
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni."
            )
        return attrs


class FiltreEvaluationSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    seance_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    type_evaluation = serializers.ChoiceField(
        choices=Evaluation.TypeEvaluation.choices,
        required=False,
    )
    statut = serializers.ChoiceField(
        choices=Evaluation.Statut.choices,
        required=False,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "session_id",
                "centre_id",
                "seance_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre d'évaluation est obligatoire."
            )

        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class NoteSerializer(serializers.ModelSerializer):
    evaluation = EvaluationResumeSerializer(read_only=True)
    affectation_centre = (
        AffectationCentreActiviteResumeSerializer(read_only=True)
    )
    saisie_par = ActeurActiviteResumeSerializer(read_only=True)
    statut_note_libelle = serializers.CharField(
        source="get_statut_note_display",
        read_only=True,
    )

    class Meta:
        model = Note
        fields = [
            "id",
            "evaluation",
            "affectation_centre",
            "valeur",
            "appreciation",
            "statut_note",
            "statut_note_libelle",
            "observations",
            "saisie_par",
            "date_saisie",
        ]


class NoteCreateSerializer(serializers.Serializer):
    evaluation_id = serializers.IntegerField(min_value=1)
    affectation_centre_id = serializers.IntegerField(min_value=1)
    valeur = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    statut_note = serializers.ChoiceField(
        choices=[
            Note.StatutNote.NOTEE,
            Note.StatutNote.ABSENT,
            Note.StatutNote.DISPENSE,
        ],
        required=False,
    )
    appreciation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if (
            attrs["statut_note"] == Note.StatutNote.NOTEE
            and attrs.get("valeur") is None
        ):
            raise serializers.ValidationError(
                {
                    "valeur": (
                        "La valeur est obligatoire pour une note."
                    )
                }
            )
        if attrs["statut_note"] != Note.StatutNote.NOTEE:
            attrs["valeur"] = None
        return attrs


class NoteUpdateSerializer(serializers.Serializer):
    valeur = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    statut_note = serializers.ChoiceField(
        choices=[
            Note.StatutNote.NOTEE,
            Note.StatutNote.ABSENT,
            Note.StatutNote.DISPENSE,
        ],
        default=Note.StatutNote.NOTEE,
    )
    appreciation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Au moins un champ doit être fourni."
            )

        statut = attrs.get("statut_note")
        if (
            statut == Note.StatutNote.NOTEE
            and "valeur" in attrs
            and attrs.get("valeur") is None
        ):
            raise serializers.ValidationError(
                {
                    "valeur": (
                        "La valeur est obligatoire pour une note."
                    )
                }
            )
        if (
            statut is not None
            and statut != Note.StatutNote.NOTEE
        ):
            attrs["valeur"] = None
        return attrs


class MarquerNoteSerializer(serializers.Serializer):
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class FiltreNoteSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    evaluation_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    affectation_centre_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
    statut_note = serializers.ChoiceField(
        choices=Note.StatutNote.choices,
        required=False,
    )
    date_debut = serializers.DateField(required=False)
    date_fin = serializers.DateField(required=False)
    recherche = serializers.CharField(
        required=False,
        allow_blank=False,
    )

    def validate(self, attrs):
        if not any(
            attrs.get(champ)
            for champ in (
                "session_id",
                "centre_id",
                "evaluation_id",
                "affectation_centre_id",
            )
        ):
            raise serializers.ValidationError(
                "Un périmètre de note est obligatoire."
            )

        date_debut = attrs.get("date_debut")
        date_fin = attrs.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            raise serializers.ValidationError(
                {
                    "date_fin": (
                        "La date de fin ne peut pas précéder "
                        "la date de début."
                    )
                }
            )
        return attrs


class MoyenneQuerySerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    session_id = serializers.IntegerField(min_value=1)


class MoyenneSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField()
    session_id = serializers.IntegerField()
    moyenne_sur_20 = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    somme_coefficients = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    notes_comptees = serializers.IntegerField(min_value=0)
    absences = serializers.IntegerField(min_value=0)
    dispenses = serializers.IntegerField(min_value=0)


class LignePresenceMasseSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    statut_presence = serializers.ChoiceField(
        choices=Presence.StatutPresence.choices,
    )
    heure_arrivee = serializers.TimeField(
        required=False,
        allow_null=True,
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if (
            attrs["statut_presence"]
            == Presence.StatutPresence.RETARD
            and not attrs.get("heure_arrivee")
        ):
            raise serializers.ValidationError(
                {
                    "heure_arrivee": (
                        "L'heure d'arrivée est obligatoire "
                        "pour un retard."
                    )
                }
            )
        return attrs


class SaisiePresencesMasseSerializer(serializers.Serializer):
    seance_id = serializers.IntegerField(min_value=1)
    lignes = LignePresenceMasseSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_lignes(self, value):
        ids = [
            ligne["affectation_centre_id"]
            for ligne in value
        ]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "Une affectation ne peut apparaître qu'une fois."
            )
        return value


class ValidationFeuillesMasseSerializer(serializers.Serializer):
    seance_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    cloturer = serializers.BooleanField(default=False)

    def validate_seance_ids(self, value):
        return list(dict.fromkeys(value))


class LigneNoteMasseSerializer(serializers.Serializer):
    affectation_centre_id = serializers.IntegerField(min_value=1)
    valeur = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0,
        required=False,
        allow_null=True,
    )
    statut_note = serializers.ChoiceField(
        choices=[
            Note.StatutNote.NOTEE,
            Note.StatutNote.ABSENT,
            Note.StatutNote.DISPENSE,
        ],
        default=Note.StatutNote.NOTEE,
    )
    appreciation = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if (
            attrs["statut_note"] == Note.StatutNote.NOTEE
            and attrs.get("valeur") is None
        ):
            raise serializers.ValidationError(
                {
                    "valeur": (
                        "La valeur est obligatoire pour une note."
                    )
                }
            )
        if attrs["statut_note"] != Note.StatutNote.NOTEE:
            attrs["valeur"] = None
        return attrs


class SaisieNotesMasseSerializer(serializers.Serializer):
    evaluation_id = serializers.IntegerField(min_value=1)
    lignes = LigneNoteMasseSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_lignes(self, value):
        ids = [
            ligne["affectation_centre_id"]
            for ligne in value
        ]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "Une affectation ne peut apparaître qu'une fois."
            )
        return value


class ValidationResultatsMasseSerializer(serializers.Serializer):
    evaluation_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    def validate_evaluation_ids(self, value):
        return list(dict.fromkeys(value))


class RecalculIndicateursSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(min_value=1)
    affectation_centre_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

    def validate_affectation_centre_ids(self, value):
        return list(dict.fromkeys(value))


class TacheActiviteLanceeSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField()
    statut = serializers.CharField()
    message = serializers.CharField()


class ProgressionActiviteSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    operation = serializers.CharField(
        allow_blank=True,
        required=False,
    )
    statut = serializers.CharField()
    progression = serializers.IntegerField(
        min_value=0,
        max_value=100,
    )
    message = serializers.CharField(
        allow_blank=True,
        required=False,
    )
    total = serializers.IntegerField(min_value=0)
    traites = serializers.IntegerField(min_value=0)
    crees = serializers.IntegerField(min_value=0)
    mis_a_jour = serializers.IntegerField(min_value=0)
    dispenses = serializers.IntegerField(min_value=0)
    bloques_medicaux = serializers.IntegerField(min_value=0)
    ignores = serializers.IntegerField(min_value=0)
    erreurs = serializers.IntegerField(min_value=0)
    resultat = serializers.JSONField(
        required=False,
        allow_null=True,
    )
