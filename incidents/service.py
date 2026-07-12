from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Acteur, AffectationActeur
from accounts.service import ControleAccesService
from affectations.models import AffectationCentre, CentreImmersion, RegionImmersion
from immerges.models import Immerge
from sessions_app.models import SessionImmersion

from .models import AlerteIncident
from .repository import AlerteIncidentRepository


class ValidationIncidentErreur(ValidationError):
    """Erreur métier du module incidents."""


@dataclass
class ResultatScan:
    module: str
    detectes: int = 0
    crees: int = 0
    actualises: int = 0
    resolus: int = 0
    echecs: int = 0
    non_crees_limite: int = 0

    def en_dict(self):
        return asdict(self)


class ControleAccesIncidentService:
    @staticmethod
    def exiger(
        acteur,
        code_permission,
        *,
        session_id=None,
        centre_id=None,
        region_code=None,
    ):
        if acteur is None or not getattr(acteur, "is_authenticated", False):
            raise ValidationIncidentErreur("Un acteur authentifié est obligatoire.")
        if not getattr(acteur, "est_actif_metier", False):
            raise ValidationIncidentErreur("L'acteur est inactif ou supprimé.")
        if getattr(acteur, "is_superuser", False):
            return None

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=session_id,
            centre_id=centre_id,
            region_code=region_code,
        )
        if not resultat.autorise:
            raise ValidationIncidentErreur(
                resultat.motif or "Permission absente ou hors périmètre."
            )
        return resultat.affectation


class AlerteIncidentService:
    GRAVITES = [
        AlerteIncident.NiveauGravite.FAIBLE,
        AlerteIncident.NiveauGravite.MOYEN,
        AlerteIncident.NiveauGravite.ELEVE,
        AlerteIncident.NiveauGravite.CRITIQUE,
    ]

    MOTS_CATEGORIES = (
        (
            AlerteIncident.Categorie.SANTE,
            {
                "malaise",
                "blessure",
                "accident",
                "malade",
                "sante",
                "santé",
                "evanoui",
                "évanoui",
                "urgence",
                "douleur",
            },
        ),
        (
            AlerteIncident.Categorie.DISCIPLINE,
            {"bagarre", "violence", "discipline", "menace", "agression", "insulte"},
        ),
        (
            AlerteIncident.Categorie.SECURITE_ACCES,
            {
                "permission",
                "role",
                "rôle",
                "compte",
                "connexion",
                "acces",
                "accès",
                "piratage",
                "intrusion",
                "vol",
            },
        ),
        (
            AlerteIncident.Categorie.LOGISTIQUE,
            {
                "panne",
                "eau",
                "electricite",
                "électricité",
                "incendie",
                "materiel",
                "matériel",
                "batiment",
                "bâtiment",
            },
        ),
        (AlerteIncident.Categorie.REPAS, {"repas", "nourriture", "aliment", "cuisine"}),
        (AlerteIncident.Categorie.KIT, {"kit", "tenue", "equipement", "équipement"}),
        (
            AlerteIncident.Categorie.ACTIVITE,
            {"activite", "activité", "seance", "séance", "presence", "présence", "retard"},
        ),
        (
            AlerteIncident.Categorie.AFFECTATION,
            {"affectation", "region", "région", "centre", "transfert"},
        ),
        (
            AlerteIncident.Categorie.ORGANISATION,
            {"lit", "dortoir", "groupe", "section", "hebergement", "hébergement"},
        ),
    )

    @staticmethod
    def _texte(value):
        return str(value or "").strip()

    @classmethod
    def classifier_categorie(cls, raison):
        texte = re.sub(r"[^a-zA-ZÀ-ÿ0-9]+", " ", cls._texte(raison).lower())
        mots = set(texte.split())
        for categorie, vocabulaire in cls.MOTS_CATEGORIES:
            if mots.intersection(vocabulaire):
                return categorie
        return AlerteIncident.Categorie.AUTRE

    @staticmethod
    def _affectations_actives_acteur(acteur_id):
        aujourd_hui = timezone.localdate()
        return (
            AffectationActeur.objects.filter(
                acteur_id=acteur_id,
                statut=AffectationActeur.Statut.ACTIVE,
                deleted_at__isnull=True,
                date_debut__lte=aujourd_hui,
            )
            .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=aujourd_hui))
            .select_related("session")
            .order_by("-centre_id", "-session_id", "id")
        )

    @classmethod
    def _resoudre_concerne(cls, *, type_concerne, concerne_id):
        try:
            concerne_id = int(concerne_id)
        except (TypeError, ValueError) as exc:
            raise ValidationIncidentErreur(
                {"concerne": "L'identifiant du concerné est invalide."}
            ) from exc

        if type_concerne == AlerteIncident.TypeConcerne.IMMERGE:
            immerge = Immerge.objects.select_related("session").filter(
                id=concerne_id,
                deleted_at__isnull=True,
            ).first()
            if not immerge:
                raise ValidationIncidentErreur({"concerne": "L'immergé est introuvable."})
            affectation = (
                AffectationCentre.objects.select_related("centre__region", "session")
                .filter(
                    immerge_id=immerge.id,
                    statut=AffectationCentre.Statut.ACTIVE,
                    deleted_at__isnull=True,
                )
                .first()
            )
            return {
                "type_concerne": type_concerne,
                "session": immerge.session,
                "centre": affectation.centre if affectation else None,
                "affectation_centre": affectation,
                "acteur_concerne": None,
                "modele_source": "Immerge",
                "objet_source_id": immerge.id,
                "libelle": str(immerge),
                "region": affectation.centre.region if affectation else None,
                "region_code": affectation.centre.region.code if affectation else None,
            }

        if type_concerne == AlerteIncident.TypeConcerne.ACTEUR:
            acteur = Acteur.objects.filter(id=concerne_id, deleted_at__isnull=True).first()
            if not acteur:
                raise ValidationIncidentErreur({"concerne": "L'acteur concerné est introuvable."})
            return {
                "type_concerne": type_concerne,
                "session": None,
                "centre": None,
                "affectation_centre": None,
                "acteur_concerne": acteur,
                "modele_source": "Acteur",
                "objet_source_id": acteur.id,
                "libelle": str(acteur),
                "region": None,
                "region_code": None,
                "affectations_cibles": list(cls._affectations_actives_acteur(acteur.id)),
            }

        if type_concerne == AlerteIncident.TypeConcerne.CENTRE:
            centre = CentreImmersion.objects.select_related("region").filter(
                id=concerne_id,
                deleted_at__isnull=True,
            ).first()
            if not centre:
                raise ValidationIncidentErreur({"concerne": "Le centre est introuvable."})
            return {
                "type_concerne": type_concerne,
                "session": None,
                "centre": centre,
                "affectation_centre": None,
                "acteur_concerne": None,
                "modele_source": "CentreImmersion",
                "objet_source_id": centre.id,
                "libelle": centre.nom,
                "region": centre.region,
                "region_code": centre.region.code,
            }

        if type_concerne == AlerteIncident.TypeConcerne.SESSION:
            session = SessionImmersion.objects.filter(
                id=concerne_id,
                deleted_at__isnull=True,
            ).first()
            if not session:
                raise ValidationIncidentErreur({"concerne": "La session est introuvable."})
            return {
                "type_concerne": type_concerne,
                "session": session,
                "centre": None,
                "affectation_centre": None,
                "acteur_concerne": None,
                "modele_source": "SessionImmersion",
                "objet_source_id": session.id,
                "libelle": str(session),
                "region": None,
                "region_code": None,
            }

        raise ValidationIncidentErreur(
            {"concerne": "Le type de concerné n'est pas autorisé pour un signalement manuel."}
        )

    @classmethod
    def _choisir_contexte_autorise(cls, acteur, cible, code_permission):
        if getattr(acteur, "is_superuser", False):
            return cible

        affectations_cibles = cible.pop("affectations_cibles", [])

        # Pour un centre, la session n'est pas demandée à l'utilisateur. Elle est
        # déduite de l'affectation active du déclarant lorsque celle-ci est liée à
        # une session. Le formulaire reste donc limité à trois champs.
        if cible.get("type_concerne") == AlerteIncident.TypeConcerne.CENTRE:
            centre = cible.get("centre")
            for affectation in cls._affectations_actives_acteur(acteur.id):
                if affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE:
                    if affectation.centre_id != getattr(centre, "id", None):
                        continue
                elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
                    if str(affectation.region_code).lower() != str(cible.get("region_code") or "").lower():
                        continue
                try:
                    cls._exiger_sur_contexte(
                        acteur,
                        code_permission,
                        session_id=affectation.session_id,
                        centre_id=getattr(centre, "id", None),
                        region_code=cible.get("region_code"),
                    )
                except ValidationIncidentErreur:
                    continue
                cible["session"] = affectation.session
                return cible

        if affectations_cibles:
            for affectation in affectations_cibles:
                try:
                    cls._exiger_sur_contexte(
                        acteur,
                        code_permission,
                        session_id=affectation.session_id,
                        centre_id=affectation.centre_id,
                        region_code=affectation.region_code or None,
                    )
                except ValidationIncidentErreur:
                    continue
                cible["session"] = affectation.session
                if affectation.centre_id:
                    centre = CentreImmersion.objects.select_related("region").filter(
                        id=affectation.centre_id,
                        deleted_at__isnull=True,
                    ).first()
                    cible["centre"] = centre
                    cible["region"] = centre.region if centre else None
                    cible["region_code"] = centre.region.code if centre else affectation.region_code
                else:
                    region = RegionImmersion.objects.filter(
                        code__iexact=affectation.region_code,
                        deleted_at__isnull=True,
                    ).first() if affectation.region_code else None
                    cible["region"] = region
                    cible["region_code"] = affectation.region_code or None
                return cible

        cls._exiger_sur_contexte(
            acteur,
            code_permission,
            session_id=getattr(cible.get("session"), "id", None),
            centre_id=getattr(cible.get("centre"), "id", None),
            region_code=cible.get("region_code"),
        )
        return cible

    @staticmethod
    def _exiger_sur_contexte(
        acteur,
        code_permission,
        *,
        session_id=None,
        centre_id=None,
        region_code=None,
    ):
        return ControleAccesIncidentService.exiger(
            acteur,
            code_permission,
            session_id=session_id,
            centre_id=centre_id,
            region_code=region_code,
        )

    @classmethod
    @transaction.atomic
    def signaler_manuellement(cls, *, acteur, niveau_gravite, concerne, raison):
        raison = cls._texte(raison)
        if len(raison) < 10:
            raise ValidationIncidentErreur(
                {"raison": "La raison doit contenir au moins 10 caractères."}
            )
        if len(raison) > 5000:
            raise ValidationIncidentErreur(
                {"raison": "La raison ne peut pas dépasser 5000 caractères."}
            )

        if niveau_gravite not in AlerteIncident.NiveauGravite.values:
            raise ValidationIncidentErreur({"niveau_gravite": "Niveau de gravité invalide."})

        type_concerne = (concerne or {}).get("type")
        concerne_id = (concerne or {}).get("id")
        if type_concerne not in {
            AlerteIncident.TypeConcerne.IMMERGE,
            AlerteIncident.TypeConcerne.ACTEUR,
            AlerteIncident.TypeConcerne.CENTRE,
            AlerteIncident.TypeConcerne.SESSION,
        }:
            raise ValidationIncidentErreur(
                {"concerne": "Choisissez un immergé, un acteur, un centre ou une session."}
            )

        cible = cls._resoudre_concerne(
            type_concerne=type_concerne,
            concerne_id=concerne_id,
        )
        cible = cls._choisir_contexte_autorise(
            acteur,
            cible,
            "signaler_incident",
        )

        categorie = cls.classifier_categorie(raison)
        titre = f"{AlerteIncident.Categorie(categorie).label} concernant {cible['libelle']}"
        confidentialite = (
            AlerteIncident.Confidentialite.MEDICALE
            if categorie == AlerteIncident.Categorie.SANTE
            else AlerteIncident.Confidentialite.RESTREINTE
        )
        incident = AlerteIncident(
            session=cible.get("session"),
            region=cible.get("region") or getattr(cible.get("centre"), "region", None),
            centre=cible.get("centre"),
            affectation_centre=cible.get("affectation_centre"),
            acteur_concerne=cible.get("acteur_concerne"),
            type=AlerteIncident.Type.INCIDENT,
            origine=AlerteIncident.Origine.MANUELLE,
            type_concerne=type_concerne,
            categorie=categorie,
            titre=titre[:255],
            description=raison,
            niveau_gravite=niveau_gravite,
            statut=AlerteIncident.Statut.NOUVEAU,
            niveau_confidentialite=confidentialite,
            module_source="incidents",
            modele_source=cible.get("modele_source", ""),
            objet_source_id=cible.get("objet_source_id"),
            est_bloquante=niveau_gravite == AlerteIncident.NiveauGravite.CRITIQUE,
            resolution_automatique=False,
            cree_par=acteur,
            contexte={"signalement_rapide": True},
        )
        incident.full_clean()
        incident.save()
        return incident

    @classmethod
    def _contexte_incident(cls, incident):
        region_code = incident.region.code if incident.region_id and incident.region else None
        if not region_code and incident.centre_id and incident.centre:
            region_code = incident.centre.region.code
        return {
            "session_id": incident.session_id,
            "centre_id": incident.centre_id,
            "region_code": region_code,
        }

    @classmethod
    def _exiger_incident(cls, acteur, code_permission, incident):
        return cls._exiger_sur_contexte(
            acteur,
            code_permission,
            **cls._contexte_incident(incident),
        )

    @classmethod
    @transaction.atomic
    def modifier_signalement(cls, incident_id, *, acteur, niveau_gravite=None, raison=None):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        if incident.origine != AlerteIncident.Origine.MANUELLE:
            raise ValidationIncidentErreur("Une alerte automatique ne se modifie pas manuellement.")
        if incident.statut != AlerteIncident.Statut.NOUVEAU:
            raise ValidationIncidentErreur("Seul un incident nouveau peut être corrigé.")

        if incident.cree_par_id != acteur.id:
            cls._exiger_incident(acteur, "modifier_incident", incident)

        champs = []
        if niveau_gravite is not None:
            if niveau_gravite not in AlerteIncident.NiveauGravite.values:
                raise ValidationIncidentErreur({"niveau_gravite": "Gravité invalide."})
            incident.niveau_gravite = niveau_gravite
            incident.est_bloquante = niveau_gravite == AlerteIncident.NiveauGravite.CRITIQUE
            champs.extend(["niveau_gravite", "est_bloquante"])
        if raison is not None:
            raison = cls._texte(raison)
            if len(raison) < 10:
                raise ValidationIncidentErreur({"raison": "La raison est trop courte."})
            incident.description = raison
            incident.categorie = cls.classifier_categorie(raison)
            if incident.categorie == AlerteIncident.Categorie.SANTE:
                incident.niveau_confidentialite = AlerteIncident.Confidentialite.MEDICALE
            elif incident.niveau_confidentialite == AlerteIncident.Confidentialite.NORMALE:
                incident.niveau_confidentialite = AlerteIncident.Confidentialite.RESTREINTE
            champs.extend(["description", "categorie", "niveau_confidentialite"])
        if champs:
            incident.save(update_fields=[*set(champs), "updated_at"])
        return incident

    @classmethod
    @transaction.atomic
    def prendre_en_charge(cls, incident_id, *, acteur, observation=""):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        cls._exiger_incident(acteur, "prendre_en_charge_incident", incident)
        if incident.statut not in {
            AlerteIncident.Statut.NOUVEAU,
            AlerteIncident.Statut.EN_ATTENTE,
        }:
            raise ValidationIncidentErreur("Cet incident ne peut pas être pris en charge.")
        incident.statut = AlerteIncident.Statut.EN_COURS
        incident.traite_par = acteur
        incident.date_prise_en_charge = incident.date_prise_en_charge or timezone.now()
        if observation:
            incident.observations = cls._ajouter_observation(incident.observations, observation)
        incident.save(
            update_fields=[
                "statut",
                "traite_par",
                "date_prise_en_charge",
                "observations",
                "updated_at",
            ]
        )
        return incident

    @classmethod
    @transaction.atomic
    def mettre_en_attente(cls, incident_id, *, acteur, motif):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        cls._exiger_incident(acteur, "mettre_incident_en_attente", incident)
        if incident.statut != AlerteIncident.Statut.EN_COURS:
            raise ValidationIncidentErreur("Seul un incident en cours peut être mis en attente.")
        motif = cls._texte(motif)
        if len(motif) < 5:
            raise ValidationIncidentErreur({"motif": "Le motif d'attente est obligatoire."})
        incident.statut = AlerteIncident.Statut.EN_ATTENTE
        incident.traite_par = acteur
        incident.observations = cls._ajouter_observation(
            incident.observations,
            f"Mise en attente : {motif}",
        )
        incident.save(update_fields=["statut", "traite_par", "observations", "updated_at"])
        return incident

    @classmethod
    @transaction.atomic
    def resoudre(cls, incident_id, *, acteur, resolution):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        cls._exiger_incident(acteur, "resoudre_incident", incident)
        if incident.statut not in AlerteIncident.STATUTS_OUVERTS:
            raise ValidationIncidentErreur("Seul un incident ouvert peut être résolu.")
        resolution = cls._texte(resolution)
        if len(resolution) < 10:
            raise ValidationIncidentErreur({"resolution": "La résolution est trop courte."})
        incident.statut = AlerteIncident.Statut.RESOLU
        incident.traite_par = acteur
        incident.resolution = resolution
        incident.date_resolution = timezone.now()
        incident.save(
            update_fields=[
                "statut",
                "traite_par",
                "resolution",
                "date_resolution",
                "updated_at",
            ]
        )
        return incident

    @classmethod
    @transaction.atomic
    def cloturer(cls, incident_id, *, acteur, observation=""):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        cls._exiger_incident(acteur, "cloturer_incident", incident)
        if incident.statut != AlerteIncident.Statut.RESOLU:
            raise ValidationIncidentErreur("Seul un incident résolu peut être clôturé.")
        incident.statut = AlerteIncident.Statut.CLOTURE
        incident.traite_par = acteur
        incident.date_cloture = timezone.now()
        if observation:
            incident.observations = cls._ajouter_observation(incident.observations, observation)
        incident.save(
            update_fields=[
                "statut",
                "traite_par",
                "date_cloture",
                "observations",
                "updated_at",
            ]
        )
        return incident

    @classmethod
    @transaction.atomic
    def annuler(cls, incident_id, *, acteur, motif):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        cls._exiger_incident(acteur, "annuler_incident", incident)
        if incident.statut in {
            AlerteIncident.Statut.CLOTURE,
            AlerteIncident.Statut.ANNULE,
        }:
            raise ValidationIncidentErreur("Cet incident est déjà clôturé ou annulé.")
        motif = cls._texte(motif)
        if len(motif) < 5:
            raise ValidationIncidentErreur({"motif": "Le motif d'annulation est obligatoire."})
        incident.statut = AlerteIncident.Statut.ANNULE
        incident.traite_par = acteur
        incident.resolution = f"Annulation : {motif}"
        incident.date_resolution = timezone.now()
        incident.save(
            update_fields=[
                "statut",
                "traite_par",
                "resolution",
                "date_resolution",
                "updated_at",
            ]
        )
        return incident

    @classmethod
    @transaction.atomic
    def escalader(cls, incident_id, *, acteur=None, motif="", automatique=False):
        incident = AlerteIncidentRepository.get_by_id_pour_update(incident_id)
        if not incident:
            raise ValidationIncidentErreur("Incident introuvable.")
        if not automatique:
            cls._exiger_incident(acteur, "escalader_incident", incident)
        if incident.statut not in AlerteIncident.STATUTS_OUVERTS:
            raise ValidationIncidentErreur("Seul un incident ouvert peut être escaladé.")

        indice = cls.GRAVITES.index(incident.niveau_gravite)
        if indice < len(cls.GRAVITES) - 1:
            incident.niveau_gravite = cls.GRAVITES[indice + 1]
        incident.est_bloquante = (
            incident.est_bloquante
            or incident.niveau_gravite == AlerteIncident.NiveauGravite.CRITIQUE
        )
        incident.niveau_escalade += 1
        incident.date_derniere_escalade = timezone.now()
        texte = motif or "Escalade automatique après dépassement du délai de prise en charge."
        incident.observations = cls._ajouter_observation(
            incident.observations,
            f"Escalade {incident.niveau_escalade} : {texte}",
        )
        incident.save(
            update_fields=[
                "niveau_gravite",
                "est_bloquante",
                "niveau_escalade",
                "date_derniere_escalade",
                "observations",
                "updated_at",
            ]
        )
        return incident

    @staticmethod
    def _ajouter_observation(ancien, nouveau):
        horodatage = timezone.localtime().strftime("%Y-%m-%d %H:%M")
        ligne = f"[{horodatage}] {str(nouveau).strip()}"
        return f"{ancien.strip()}\n{ligne}".strip() if ancien else ligne


class AlerteAutomatiqueService:
    """Transforme les anomalies lues dans les autres modules en alertes.

    Les détecteurs parcourent toutes les données par lots. La limite configurée
    porte uniquement sur les nouvelles alertes créées pendant un passage, jamais
    sur les objets contrôlés. La résolution automatique n'est lancée qu'après la
    fin complète du détecteur.
    """

    @staticmethod
    def _confidentialite_anomalie(anomalie):
        if anomalie.niveau_confidentialite:
            return anomalie.niveau_confidentialite
        if anomalie.categorie == AlerteIncident.Categorie.SANTE:
            return AlerteIncident.Confidentialite.MEDICALE
        return AlerteIncident.Confidentialite.NORMALE

    @classmethod
    @transaction.atomic
    def enregistrer_anomalie(cls, anomalie, *, autoriser_creation=True):
        maintenant = timezone.now()
        incident = AlerteIncidentRepository.get_ouvert_par_cle_pour_update(anomalie.cle)
        confidentialite = cls._confidentialite_anomalie(anomalie)
        if incident:
            incident.nombre_occurrences += 1
            incident.date_derniere_detection = maintenant
            incident.region_id = anomalie.region_id
            incident.titre = anomalie.titre[:255]
            incident.description = anomalie.description
            incident.niveau_gravite = anomalie.gravite
            incident.est_bloquante = anomalie.est_bloquante
            if (
                incident.niveau_confidentialite
                != AlerteIncident.Confidentialite.MEDICALE
            ):
                incident.niveau_confidentialite = confidentialite
            incident.contexte = anomalie.contexte or {}
            incident.save(
                update_fields=[
                    "nombre_occurrences",
                    "date_derniere_detection",
                    "region",
                    "titre",
                    "description",
                    "niveau_gravite",
                    "est_bloquante",
                    "niveau_confidentialite",
                    "contexte",
                    "updated_at",
                ]
            )
            return incident, False

        if not autoriser_creation:
            return None, False

        incident = AlerteIncident(
            session_id=anomalie.session_id,
            region_id=anomalie.region_id,
            centre_id=anomalie.centre_id,
            affectation_centre_id=anomalie.affectation_centre_id,
            acteur_concerne_id=anomalie.acteur_concerne_id,
            type=AlerteIncident.Type.ALERTE,
            origine=anomalie.origine,
            type_concerne=anomalie.type_concerne,
            categorie=anomalie.categorie,
            titre=anomalie.titre[:255],
            description=anomalie.description,
            niveau_gravite=anomalie.gravite,
            statut=AlerteIncident.Statut.NOUVEAU,
            niveau_confidentialite=confidentialite,
            code_detection=anomalie.code,
            module_source=anomalie.module_source,
            modele_source=anomalie.modele_source,
            objet_source_id=anomalie.objet_source_id,
            cle_deduplication=anomalie.cle[:255],
            contexte=anomalie.contexte or {},
            est_bloquante=anomalie.est_bloquante,
            resolution_automatique=anomalie.resolution_automatique,
            nombre_occurrences=1,
            date_premiere_detection=maintenant,
            date_derniere_detection=maintenant,
            date_signalement=maintenant,
        )
        incident.full_clean()
        try:
            with transaction.atomic():
                incident.save()
            return incident, True
        except IntegrityError:
            incident = AlerteIncidentRepository.get_ouvert_par_cle_pour_update(anomalie.cle)
            if not incident:
                raise
            incident.nombre_occurrences += 1
            incident.date_derniere_detection = maintenant
            incident.save(
                update_fields=["nombre_occurrences", "date_derniere_detection", "updated_at"]
            )
            return incident, False

    @classmethod
    @transaction.atomic
    def resoudre_absentes(cls, *, module, codes, debut_scan):
        qs = AlerteIncident.objects.select_for_update().filter(
            origine__in=[
                AlerteIncident.Origine.AUTOMATIQUE,
                AlerteIncident.Origine.SYSTEME_SECURITE,
            ],
            module_source=module,
            code_detection__in=list(codes),
            statut__in=AlerteIncident.STATUTS_OUVERTS,
            resolution_automatique=True,
            deleted_at__isnull=True,
        ).filter(
            Q(date_derniere_detection__lt=debut_scan)
            | Q(date_derniere_detection__isnull=True)
        )
        maintenant = timezone.now()
        return qs.update(
            statut=AlerteIncident.Statut.RESOLU,
            resolution="Anomalie disparue lors du contrôle automatique.",
            date_resolution=maintenant,
            updated_at=maintenant,
        )

    @staticmethod
    def _enrichir_regions(anomalies):
        centre_ids = {a.centre_id for a in anomalies if a.centre_id and not a.region_id}
        affectation_ids = {
            a.affectation_centre_id
            for a in anomalies
            if a.affectation_centre_id and not a.region_id and not a.centre_id
        }
        regions_centres = dict(
            CentreImmersion.objects.filter(id__in=centre_ids).values_list("id", "region_id")
        )
        regions_affectations = dict(
            AffectationCentre.objects.filter(id__in=affectation_ids).values_list(
                "id", "centre__region_id"
            )
        )
        resultat = []
        for anomalie in anomalies:
            region_id = anomalie.region_id
            if not region_id and anomalie.centre_id:
                region_id = regions_centres.get(anomalie.centre_id)
            if not region_id and anomalie.affectation_centre_id:
                region_id = regions_affectations.get(anomalie.affectation_centre_id)
            resultat.append(replace(anomalie, region_id=region_id))
        return resultat

    @classmethod
    def executer_detecteur(cls, detecteur):
        debut_scan = timezone.now()
        resultat = ResultatScan(module=detecteur.module)
        taille_lot = max(1, int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", 500)))
        maximum_creations = max(
            0,
            int(getattr(settings, "INCIDENTS_MAX_ALERTES_CREEES_PAR_REGLE", 500)),
        )
        creations_par_code = defaultdict(int)
        lot = []

        def traiter_lot(lignes):
            for anomalie in cls._enrichir_regions(lignes):
                autoriser_creation = creations_par_code[anomalie.code] < maximum_creations
                incident, cree = cls.enregistrer_anomalie(
                    anomalie,
                    autoriser_creation=autoriser_creation,
                )
                if cree:
                    creations_par_code[anomalie.code] += 1
                    resultat.crees += 1
                elif incident is not None:
                    resultat.actualises += 1
                else:
                    resultat.non_crees_limite += 1

        # Le générateur est entièrement consommé. Une exception interrompt la
        # méthode avant ``resoudre_absentes`` et empêche toute fausse résolution.
        for anomalie in detecteur.fonction():
            resultat.detectes += 1
            lot.append(anomalie)
            if len(lot) >= taille_lot:
                traiter_lot(lot)
                lot.clear()
        if lot:
            traiter_lot(lot)

        resultat.resolus = cls.resoudre_absentes(
            module=detecteur.module,
            codes=detecteur.codes,
            debut_scan=debut_scan,
        )
        return resultat

    @classmethod
    def escalader_retards(cls):
        maintenant = timezone.now()
        total = 0
        for incident in AlerteIncidentRepository.ouverts_a_escalader().iterator():
            delai_minimum = {
                AlerteIncident.NiveauGravite.CRITIQUE: timedelta(minutes=15),
                AlerteIncident.NiveauGravite.ELEVE: timedelta(minutes=30),
                AlerteIncident.NiveauGravite.MOYEN: timedelta(hours=2),
            }.get(incident.niveau_gravite)
            if not delai_minimum:
                continue
            if incident.date_derniere_escalade and (
                maintenant - incident.date_derniere_escalade < delai_minimum
            ):
                continue
            AlerteIncidentService.escalader(
                incident.id,
                automatique=True,
                motif="Délai de prise en charge ou de résolution dépassé.",
            )
            total += 1
        return total
