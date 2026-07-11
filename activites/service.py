from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import time
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.service import ControleAccesService
from affectations.models import CentreImmersion
from organisation.models import Groupe, Section
from sessions_app.models import SessionImmersion
from sante.service import ImpactMedicalService

from .models import (
    Evaluation,
    ModuleActivite,
    Note,
    Presence,
    Seance,
)
from .repository import (
    CandidatActiviteRepository,
    EvaluationRepository,
    ModuleActiviteRepository,
    NoteRepository,
    PresenceRepository,
    SeanceRepository,
)


class ValidationActiviteErreur(ValidationError):
    """Erreur métier du bloc activités, présences et évaluations."""


@dataclass
class ResultatTraitementMasse:
    demandes: int = 0
    traites: int = 0
    crees: int = 0
    mis_a_jour: int = 0
    dispenses: int = 0
    bloques_medicaux: int = 0
    ignores: int = 0
    erreurs: int = 0
    identifiants_ignores: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def en_dict(self):
        return asdict(self)


class ControleAccesActivitesService:
    """Contrôle métier des permissions et des périmètres."""

    @staticmethod
    def exiger(
        acteur,
        code_permission,
        *,
        session_id=None,
        centre_id=None,
    ):
        if acteur is None:
            raise ValidationActiviteErreur(
                "Un acteur authentifié est obligatoire."
            )

        if getattr(acteur, "is_superuser", False):
            return None

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=session_id,
            centre_id=centre_id,
        )
        if not resultat.autorise:
            raise ValidationActiviteErreur(
                resultat.motif
                or "Permission absente ou hors périmètre."
            )

        return resultat.affectation


class ServiceActiviteBase:
    """Outils communs aux services du bloc."""

    @staticmethod
    def _session(session_id):
        try:
            return SessionImmersion.objects.select_related(
                "parametres"
            ).get(
                id=session_id,
                deleted_at__isnull=True,
            )
        except SessionImmersion.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "La session est introuvable."
            ) from exc

    @staticmethod
    def _centre(centre_id):
        try:
            return CentreImmersion.objects.select_related(
                "region"
            ).get(
                id=centre_id,
                deleted_at__isnull=True,
            )
        except CentreImmersion.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "Le centre est introuvable."
            ) from exc

    @staticmethod
    def _acteur(acteur_id):
        if acteur_id in (None, ""):
            return None

        acteur = get_user_model().objects.filter(
            id=acteur_id,
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if acteur is None:
            raise ValidationActiviteErreur(
                "L'acteur demandé est introuvable ou inactif."
            )
        return acteur

    @staticmethod
    def _section(section_id):
        if not section_id:
            return None

        try:
            return Section.objects.select_related(
                "session",
                "centre",
            ).get(
                id=section_id,
                deleted_at__isnull=True,
            )
        except Section.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "La section est introuvable."
            ) from exc

    @staticmethod
    def _groupe(groupe_id):
        if not groupe_id:
            return None

        try:
            return Groupe.objects.select_related(
                "section",
                "section__session",
                "section__centre",
            ).get(
                id=groupe_id,
                deleted_at__isnull=True,
            )
        except Groupe.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "Le groupe est introuvable."
            ) from exc

    @staticmethod
    def _exiger_session_modifiable(session):
        if not session.est_modifiable:
            raise ValidationActiviteErreur(
                "La session terminée, archivée ou annulée "
                "n'est plus modifiable."
            )

    @staticmethod
    def _exiger_activites_actives(session):
        parametres = getattr(session, "parametres", None)
        if not parametres or not parametres.activites_active:
            raise ValidationActiviteErreur(
                "Le module activités est désactivé "
                "pour cette session."
            )

    @staticmethod
    def _exiger_evaluations_actives(session):
        parametres = getattr(session, "parametres", None)
        if not parametres or not parametres.evaluation_active:
            raise ValidationActiviteErreur(
                "Les évaluations sont désactivées "
                "pour cette session."
            )

    @staticmethod
    def _exiger_date_dans_session(session, date_reference):
        if not date_reference:
            return

        date_valeur = (
            date_reference.date()
            if hasattr(date_reference, "date")
            else date_reference
        )
        if not (
            session.date_debut
            <= date_valeur
            <= session.date_fin
        ):
            raise ValidationActiviteErreur(
                "La date doit appartenir à la période de la session."
            )

    @staticmethod
    def _normaliser_decimal(valeur, champ):
        try:
            return Decimal(str(valeur))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationActiviteErreur(
                {champ: "Valeur numérique invalide."}
            ) from exc

    @staticmethod
    def _normaliser_heure(valeur, champ="heure_arrivee"):
        if valeur in (None, ""):
            return None
        if isinstance(valeur, time):
            return valeur
        try:
            return time.fromisoformat(str(valeur))
        except ValueError as exc:
            raise ValidationActiviteErreur(
                {champ: "Heure invalide."}
            ) from exc


class ActiviteService(ServiceActiviteBase):
    """CRUD métier du catalogue permanent des activités."""

    PERMISSION_CREER = "creer_activite"
    PERMISSION_MODIFIER = "modifier_activite"
    PERMISSION_DESACTIVER = "desactiver_activite"

    CHAMPS_MODIFIABLES = {
        "code",
        "titre",
        "description",
        "categorie",
        "duree_prevue",
        "ordre",
        "statut",
    }

    @classmethod
    @transaction.atomic
    def creer_activite(
        cls,
        *,
        acteur,
        code,
        titre,
        categorie,
        description="",
        duree_prevue=None,
        ordre=0,
        statut=ModuleActivite.Statut.ACTIF,
    ):
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_CREER,
        )

        if ModuleActiviteRepository.existe_doublon(
            code=code,
            titre=titre,
            categorie=categorie,
        ):
            raise ValidationActiviteErreur(
                "Un module portant ce code ou ce titre "
                "dans cette catégorie existe déjà."
            )

        return ModuleActiviteRepository.creer(
            code=code,
            titre=titre,
            description=description,
            categorie=categorie,
            duree_prevue=duree_prevue,
            ordre=ordre,
            statut=statut,
        )

    @classmethod
    @transaction.atomic
    def modifier_activite(
        cls,
        module_id,
        *,
        acteur,
        **donnees,
    ):
        module = ModuleActiviteRepository.get_by_id_pour_update(
            module_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_MODIFIER,
        )

        donnees = {
            champ: valeur
            for champ, valeur in donnees.items()
            if champ in cls.CHAMPS_MODIFIABLES
        }
        if not donnees:
            return module

        code = donnees.get("code", module.code)
        titre = donnees.get("titre", module.titre)
        categorie = donnees.get(
            "categorie",
            module.categorie,
        )

        if ModuleActiviteRepository.existe_doublon(
            code=code,
            titre=titre,
            categorie=categorie,
            exclure_id=module.id,
        ):
            raise ValidationActiviteErreur(
                "Un module portant ce code ou ce titre "
                "dans cette catégorie existe déjà."
            )

        for champ, valeur in donnees.items():
            setattr(module, champ, valeur)

        champs = list(donnees)
        champs.append("updated_at")
        return ModuleActiviteRepository.sauvegarder(
            module,
            update_fields=list(dict.fromkeys(champs)),
        )

    @classmethod
    @transaction.atomic
    def desactiver_activite(cls, module_id, *, acteur):
        module = ModuleActiviteRepository.get_by_id_pour_update(
            module_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_DESACTIVER,
        )
        return module.desactiver()

    @classmethod
    @transaction.atomic
    def reactiver_activite(cls, module_id, *, acteur):
        module = ModuleActiviteRepository.get_by_id_pour_update(
            module_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_DESACTIVER,
        )
        return module.reactiver()

    @classmethod
    @transaction.atomic
    def supprimer_activite_logiquement(
        cls,
        module_id,
        *,
        acteur,
    ):
        module = ModuleActiviteRepository.get_by_id_pour_update(
            module_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_DESACTIVER,
        )
        return module.supprimer_logiquement()

    @staticmethod
    def lister_activites(**filtres):
        return ModuleActiviteRepository.filtrer(**filtres)


class SeanceService(ServiceActiviteBase):
    """Planification et cycle de vie des séances."""

    PERMISSION_PLANIFIER = "planifier_seance"
    PERMISSION_MODIFIER = "modifier_seance"
    PERMISSION_ANNULER = "annuler_seance"
    PERMISSION_REPORTER = "reporter_seance"
    PERMISSION_AFFECTER_FORMATEUR = (
        "affecter_formateur_seance"
    )

    @staticmethod
    def _module(module_activite_id):
        try:
            return ModuleActiviteRepository.actifs().get(
                id=module_activite_id
            )
        except ModuleActivite.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "Le module d'activité actif est introuvable."
            ) from exc

    @classmethod
    def _valider_cible(
        cls,
        *,
        session,
        centre,
        section,
        groupe,
    ):
        if not centre.est_actif:
            raise ValidationActiviteErreur(
                "Le centre doit être actif."
            )

        if section:
            if not section.est_active:
                raise ValidationActiviteErreur(
                    "La section doit être active."
                )
            if section.session_id != session.id:
                raise ValidationActiviteErreur(
                    "La section n'appartient pas à la session."
                )
            if section.centre_id != centre.id:
                raise ValidationActiviteErreur(
                    "La section n'appartient pas au centre."
                )

        if groupe:
            if not groupe.est_actif:
                raise ValidationActiviteErreur(
                    "Le groupe doit être actif."
                )
            if groupe.section.session_id != session.id:
                raise ValidationActiviteErreur(
                    "Le groupe n'appartient pas à la session."
                )
            if groupe.section.centre_id != centre.id:
                raise ValidationActiviteErreur(
                    "Le groupe n'appartient pas au centre."
                )
            if section and groupe.section_id != section.id:
                raise ValidationActiviteErreur(
                    "Le groupe n'appartient pas à la section."
                )

    @classmethod
    def _verifier_chevauchements(
        cls,
        *,
        session_id,
        centre_id,
        date_seance,
        heure_debut,
        heure_fin,
        section=None,
        groupe=None,
        formateur=None,
        exclure_id=None,
    ):
        conflit_formateur = (
            SeanceRepository.chevauchement_formateur(
                formateur_id=(
                    formateur.id if formateur else None
                ),
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                exclure_id=exclure_id,
            )
        )
        if conflit_formateur:
            raise ValidationActiviteErreur(
                {
                    "formateur_id": (
                        "Le formateur anime déjà la séance "
                        f"« {conflit_formateur} » sur cet horaire."
                    )
                }
            )

        conflit_cible = SeanceRepository.chevauchement_cible(
            session_id=session_id,
            centre_id=centre_id,
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            section_id=section.id if section else None,
            groupe_id=groupe.id if groupe else None,
            groupe_section_id=(
                groupe.section_id if groupe else None
            ),
            exclure_id=exclure_id,
        )
        if conflit_cible:
            raise ValidationActiviteErreur(
                {
                    "heure_debut": (
                        "La cible de la séance est déjà occupée "
                        f"par « {conflit_cible} »."
                    )
                }
            )

    @classmethod
    @transaction.atomic
    def planifier_seance(
        cls,
        *,
        acteur,
        module_activite_id,
        session_id,
        centre_id,
        date_seance,
        heure_debut,
        heure_fin,
        lieu,
        titre="",
        section_id=None,
        groupe_id=None,
        formateur_id=None,
        statut=Seance.Statut.PLANIFIEE,
        observations="",
        verifier_acces=True,
    ):
        session = cls._session(session_id)
        centre = cls._centre(centre_id)
        module = cls._module(module_activite_id)
        section = cls._section(section_id)
        groupe = cls._groupe(groupe_id)
        formateur = cls._acteur(formateur_id)

        cls._exiger_session_modifiable(session)
        cls._exiger_activites_actives(session)
        cls._exiger_date_dans_session(session, date_seance)
        cls._valider_cible(
            session=session,
            centre=centre,
            section=section,
            groupe=groupe,
        )

        if statut not in {
            Seance.Statut.BROUILLON,
            Seance.Statut.PLANIFIEE,
        }:
            raise ValidationActiviteErreur(
                {"statut": "Statut initial de séance invalide."}
            )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_PLANIFIER,
                session_id=session.id,
                centre_id=centre.id,
            )

        cls._verifier_chevauchements(
            session_id=session.id,
            centre_id=centre.id,
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            section=section,
            groupe=groupe,
            formateur=formateur,
        )

        try:
            return SeanceRepository.creer(
                module_activite=module,
                session=session,
                centre=centre,
                section=section,
                groupe=groupe,
                formateur=formateur,
                titre=titre,
                date_seance=date_seance,
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                lieu=lieu,
                statut=statut,
                observations=observations,
            )
        except IntegrityError as exc:
            raise ValidationActiviteErreur(
                "La séance entre en conflit avec une donnée existante."
            ) from exc

    @classmethod
    @transaction.atomic
    def modifier_seance(
        cls,
        seance_id,
        *,
        acteur,
        **donnees,
    ):
        seance = SeanceRepository.get_by_id_pour_update(
            seance_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_MODIFIER,
            session_id=seance.session_id,
            centre_id=seance.centre_id,
        )

        if seance.statut in {
            Seance.Statut.TERMINEE,
            Seance.Statut.ANNULEE,
            Seance.Statut.REPORTEE,
        }:
            raise ValidationActiviteErreur(
                "Cette séance ne peut plus être modifiée."
            )

        if not seance.feuille_presence_modifiable:
            raise ValidationActiviteErreur(
                "Une séance dont la feuille de présence est "
                "validée ou clôturée ne peut plus être modifiée."
            )

        session = cls._session(
            donnees.get("session_id", seance.session_id)
        )
        centre = cls._centre(
            donnees.get("centre_id", seance.centre_id)
        )
        module = cls._module(
            donnees.get(
                "module_activite_id",
                seance.module_activite_id,
            )
        )
        section = cls._section(
            donnees.get("section_id", seance.section_id)
        )
        groupe = cls._groupe(
            donnees.get("groupe_id", seance.groupe_id)
        )
        formateur = cls._acteur(
            donnees.get("formateur_id", seance.formateur_id)
        )
        date_seance = donnees.get(
            "date_seance",
            seance.date_seance,
        )
        heure_debut = donnees.get(
            "heure_debut",
            seance.heure_debut,
        )
        heure_fin = donnees.get(
            "heure_fin",
            seance.heure_fin,
        )

        cls._exiger_session_modifiable(session)
        cls._exiger_activites_actives(session)
        cls._exiger_date_dans_session(session, date_seance)
        cls._valider_cible(
            session=session,
            centre=centre,
            section=section,
            groupe=groupe,
        )
        cls._verifier_chevauchements(
            session_id=session.id,
            centre_id=centre.id,
            date_seance=date_seance,
            heure_debut=heure_debut,
            heure_fin=heure_fin,
            section=section,
            groupe=groupe,
            formateur=formateur,
            exclure_id=seance.id,
        )

        correspondances = {
            "module_activite_id": ("module_activite", module),
            "session_id": ("session", session),
            "centre_id": ("centre", centre),
            "section_id": ("section", section),
            "groupe_id": ("groupe", groupe),
            "formateur_id": ("formateur", formateur),
        }
        champs = []

        for cle, (champ, valeur) in correspondances.items():
            if cle in donnees:
                setattr(seance, champ, valeur)
                champs.append(champ)

        for champ in {
            "titre",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "lieu",
            "statut",
            "observations",
        }:
            if champ in donnees:
                setattr(seance, champ, donnees[champ])
                champs.append(champ)

        champs.append("updated_at")
        return SeanceRepository.sauvegarder(
            seance,
            update_fields=list(dict.fromkeys(champs)),
        )

    @classmethod
    @transaction.atomic
    def annuler_seance(
        cls,
        seance_id,
        *,
        acteur,
        observations="",
    ):
        seance = SeanceRepository.get_by_id_pour_update(
            seance_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_ANNULER,
            session_id=seance.session_id,
            centre_id=seance.centre_id,
        )

        if (
            seance.statut_feuille_presence
            == Seance.StatutFeuillePresence.CLOTUREE
        ):
            raise ValidationActiviteErreur(
                "Une séance dont la feuille est clôturée "
                "ne peut pas être annulée."
            )

        seance.observations = (
            observations or seance.observations
        )
        seance.statut = Seance.Statut.ANNULEE
        return SeanceRepository.sauvegarder(
            seance,
            update_fields=[
                "observations",
                "statut",
                "updated_at",
            ],
        )

    @classmethod
    @transaction.atomic
    def reporter_seance(
        cls,
        seance_id,
        *,
        acteur,
        nouvelle_date,
        nouvelle_heure_debut=None,
        nouvelle_heure_fin=None,
        observations="",
    ):
        ancienne = SeanceRepository.get_by_id_pour_update(
            seance_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_REPORTER,
            session_id=ancienne.session_id,
            centre_id=ancienne.centre_id,
        )

        if ancienne.statut in {
            Seance.Statut.TERMINEE,
            Seance.Statut.ANNULEE,
            Seance.Statut.REPORTEE,
        }:
            raise ValidationActiviteErreur(
                "Cette séance ne peut pas être reportée."
            )

        if (
            ancienne.statut_feuille_presence
            != Seance.StatutFeuillePresence.NON_OUVERTE
        ):
            raise ValidationActiviteErreur(
                "La feuille de présence doit être non ouverte "
                "pour reporter la séance."
            )

        ancienne.statut = Seance.Statut.REPORTEE
        ancienne.observations = (
            observations or ancienne.observations
        )
        SeanceRepository.sauvegarder(
            ancienne,
            update_fields=[
                "statut",
                "observations",
                "updated_at",
            ],
        )

        nouvelle = cls.planifier_seance(
            acteur=acteur,
            module_activite_id=ancienne.module_activite_id,
            session_id=ancienne.session_id,
            centre_id=ancienne.centre_id,
            section_id=ancienne.section_id,
            groupe_id=ancienne.groupe_id,
            formateur_id=ancienne.formateur_id,
            titre=ancienne.titre,
            date_seance=nouvelle_date,
            heure_debut=(
                nouvelle_heure_debut
                or ancienne.heure_debut
            ),
            heure_fin=(
                nouvelle_heure_fin
                or ancienne.heure_fin
            ),
            lieu=ancienne.lieu,
            statut=Seance.Statut.PLANIFIEE,
            observations=(
                observations
                or f"Report de la séance #{ancienne.id}."
            ),
            verifier_acces=False,
        )
        return {
            "ancienne_seance": ancienne,
            "nouvelle_seance": nouvelle,
        }

    @classmethod
    @transaction.atomic
    def affecter_formateur(
        cls,
        seance_id,
        *,
        acteur,
        formateur_id,
    ):
        seance = SeanceRepository.get_by_id_pour_update(
            seance_id
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_AFFECTER_FORMATEUR,
            session_id=seance.session_id,
            centre_id=seance.centre_id,
        )
        formateur = cls._acteur(formateur_id)

        cls._verifier_chevauchements(
            session_id=seance.session_id,
            centre_id=seance.centre_id,
            date_seance=seance.date_seance,
            heure_debut=seance.heure_debut,
            heure_fin=seance.heure_fin,
            section=seance.section,
            groupe=seance.groupe,
            formateur=formateur,
            exclure_id=seance.id,
        )

        seance.formateur = formateur
        return SeanceRepository.sauvegarder(
            seance,
            update_fields=["formateur", "updated_at"],
        )

    @staticmethod
    def consulter_planning(**filtres):
        return SeanceRepository.filtrer(**filtres)


class PresenceService(ServiceActiviteBase):
    """Feuilles de présence, saisie et calcul des taux."""

    PERMISSION_OUVRIR = "ouvrir_feuille_presence"
    PERMISSION_SAISIR = "saisir_presence"
    PERMISSION_MODIFIER = "modifier_presence"
    PERMISSION_VALIDER = "valider_presence"
    PERMISSION_CLOTURER = "cloturer_feuille_presence"
    PERMISSION_CALCULER = "calculer_taux_presence"

    @staticmethod
    def _seance(seance_id, *, verrou=False):
        try:
            if verrou:
                return SeanceRepository.get_by_id_pour_update(
                    seance_id
                )
            return SeanceRepository.get_by_id(seance_id)
        except Seance.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "La séance est introuvable."
            ) from exc

    @staticmethod
    def _decision_participation(
        affectation_centre_id,
        *,
        date_reference,
    ):
        decision_activite = (
            ImpactMedicalService.decision_pour_module(
                affectation_centre_id=affectation_centre_id,
                module="ACTIVITES",
                date_reference=date_reference,
            )
        )
        decision_presence = (
            ImpactMedicalService.decision_pour_module(
                affectation_centre_id=affectation_centre_id,
                module="PRESENCES",
                date_reference=date_reference,
            )
        )

        dispense = bool(
            decision_activite.get("dispense")
            or decision_presence.get("dispense")
        )
        autorise = bool(
            decision_activite.get("autorise")
            and decision_presence.get("autorise")
        )
        return {
            "autorise": autorise,
            "dispense": dispense,
            "necessite_adaptation": bool(
                decision_activite.get(
                    "necessite_adaptation"
                )
                or decision_presence.get(
                    "necessite_adaptation"
                )
            ),
            "consignes": [
                *decision_activite.get("consignes", []),
                *decision_presence.get("consignes", []),
            ],
            "etat_activite": decision_activite.get("etat"),
            "etat_presence": decision_presence.get("etat"),
        }

    @classmethod
    def _exiger_candidat(cls, seance, affectation_centre_id):
        if not CandidatActiviteRepository.appartient_a_seance(
            seance=seance,
            affectation_centre_id=affectation_centre_id,
        ):
            raise ValidationActiviteErreur(
                "L'immergé n'appartient pas à la cible "
                "de cette séance."
            )

    @classmethod
    @transaction.atomic
    def ouvrir_feuille_presence(
        cls,
        seance_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id, verrou=True)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_OUVRIR,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        cls._exiger_activites_actives(seance.session)

        if seance.statut in {
            Seance.Statut.BROUILLON,
            Seance.Statut.ANNULEE,
            Seance.Statut.REPORTEE,
        }:
            raise ValidationActiviteErreur(
                "La séance doit être planifiée, en cours "
                "ou terminée pour ouvrir la feuille."
            )

        if (
            seance.statut_feuille_presence
            == Seance.StatutFeuillePresence.CLOTUREE
        ):
            raise ValidationActiviteErreur(
                "La feuille de présence est déjà clôturée."
            )

        if (
            seance.statut_feuille_presence
            == Seance.StatutFeuillePresence.NON_OUVERTE
        ):
            seance.statut_feuille_presence = (
                Seance.StatutFeuillePresence.OUVERTE
            )
            seance.date_ouverture_presence = timezone.now()
            seance.save(
                update_fields=[
                    "statut_feuille_presence",
                    "date_ouverture_presence",
                    "updated_at",
                ]
            )

        return seance

    @classmethod
    @transaction.atomic
    def preparer_feuille_pour_affectations(
        cls,
        *,
        seance_id,
        affectation_centre_ids,
        acteur,
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_OUVRIR,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        if (
            seance.statut_feuille_presence
            != Seance.StatutFeuillePresence.OUVERTE
        ):
            raise ValidationActiviteErreur(
                "La feuille de présence doit être ouverte."
            )

        resultat = ResultatTraitementMasse(
            demandes=len(affectation_centre_ids),
        )
        existantes = PresenceRepository.paires_existantes(
            seance_id=seance.id,
            affectation_centre_ids=affectation_centre_ids,
        )
        maintenant = timezone.now()
        nouvelles = []

        candidats = {
            affectation.id: affectation
            for affectation in (
                CandidatActiviteRepository.pour_seance(seance)
                .filter(id__in=affectation_centre_ids)
            )
        }

        for affectation_id in affectation_centre_ids:
            resultat.traites += 1
            affectation = candidats.get(affectation_id)
            if affectation is None:
                resultat.ignores += 1
                resultat.identifiants_ignores.append(
                    affectation_id
                )
                continue

            if (seance.id, affectation_id) in existantes:
                resultat.ignores += 1
                continue

            try:
                decision = cls._decision_participation(
                    affectation_id,
                    date_reference=seance.date_seance,
                )
            except ValidationError:
                resultat.erreurs += 1
                resultat.identifiants_ignores.append(
                    affectation_id
                )
                continue

            if decision["dispense"]:
                statut = Presence.StatutPresence.DISPENSE
                resultat.dispenses += 1
            elif not decision["autorise"]:
                resultat.bloques_medicaux += 1
                resultat.identifiants_ignores.append(
                    affectation_id
                )
                continue
            else:
                statut = Presence.StatutPresence.ABSENT

            nouvelles.append(
                Presence(
                    seance=seance,
                    affectation_centre=affectation,
                    statut_presence=statut,
                    heure_arrivee=None,
                    observations="",
                    saisie_par=acteur,
                    date_saisie=maintenant,
                )
            )

        PresenceRepository.creer_en_masse(nouvelles)
        resultat.crees = len(nouvelles)
        return resultat

    @classmethod
    def preparer_feuille_complete(
        cls,
        *,
        seance_id,
        acteur,
    ):
        seance = cls.ouvrir_feuille_presence(
            seance_id,
            acteur=acteur,
        )
        ids = CandidatActiviteRepository.ids_pour_seance(
            seance
        )
        return cls.preparer_feuille_pour_affectations(
            seance_id=seance.id,
            affectation_centre_ids=ids,
            acteur=acteur,
            verifier_acces=False,
        )

    @classmethod
    @transaction.atomic
    def saisir_presence(
        cls,
        *,
        seance_id,
        affectation_centre_id,
        statut_presence,
        acteur,
        heure_arrivee=None,
        observations="",
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_SAISIR,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        if (
            seance.statut_feuille_presence
            != Seance.StatutFeuillePresence.OUVERTE
        ):
            raise ValidationActiviteErreur(
                "La feuille doit être ouverte pour saisir "
                "une présence."
            )

        cls._exiger_candidat(seance, affectation_centre_id)
        decision = cls._decision_participation(
            affectation_centre_id,
            date_reference=seance.date_seance,
        )

        if decision["dispense"]:
            statut_presence = Presence.StatutPresence.DISPENSE
        elif not decision["autorise"]:
            raise ValidationActiviteErreur(
                "La participation est bloquée par la décision "
                "médicale."
            )

        if statut_presence not in {
            valeur
            for valeur, _ in Presence.StatutPresence.choices
        }:
            raise ValidationActiviteErreur(
                {"statut_presence": "Statut de présence invalide."}
            )

        heure_arrivee = cls._normaliser_heure(
            heure_arrivee
        )
        if (
            statut_presence == Presence.StatutPresence.RETARD
            and heure_arrivee is None
        ):
            raise ValidationActiviteErreur(
                {
                    "heure_arrivee": (
                        "L'heure d'arrivée est obligatoire "
                        "pour un retard."
                    )
                }
            )

        if statut_presence in {
            Presence.StatutPresence.ABSENT,
            Presence.StatutPresence.EXCUSE,
            Presence.StatutPresence.DISPENSE,
        }:
            heure_arrivee = None

        presence = (
            PresenceRepository
            .get_active_par_seance_affectation(
                seance_id=seance.id,
                affectation_centre_id=affectation_centre_id,
            )
        )
        maintenant = timezone.now()

        if presence is None:
            affectation = (
                CandidatActiviteRepository.base_queryset().get(
                    id=affectation_centre_id
                )
            )
            return PresenceRepository.creer(
                seance=seance,
                affectation_centre=affectation,
                statut_presence=statut_presence,
                heure_arrivee=heure_arrivee,
                observations=observations,
                saisie_par=acteur,
                date_saisie=maintenant,
            )

        presence.statut_presence = statut_presence
        presence.heure_arrivee = heure_arrivee
        presence.observations = observations
        presence.saisie_par = acteur
        presence.date_saisie = maintenant
        return PresenceRepository.sauvegarder(
            presence,
            update_fields=[
                "statut_presence",
                "heure_arrivee",
                "observations",
                "saisie_par",
                "date_saisie",
                "updated_at",
            ],
        )

    @classmethod
    def modifier_presence(
        cls,
        presence_id,
        *,
        acteur,
        statut_presence,
        heure_arrivee=None,
        observations="",
    ):
        presence = PresenceRepository.get_by_id(presence_id)
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_MODIFIER,
            session_id=presence.seance.session_id,
            centre_id=presence.seance.centre_id,
        )
        return cls.saisir_presence(
            seance_id=presence.seance_id,
            affectation_centre_id=(
                presence.affectation_centre_id
            ),
            statut_presence=statut_presence,
            acteur=acteur,
            heure_arrivee=heure_arrivee,
            observations=observations,
            verifier_acces=False,
        )

    @classmethod
    @transaction.atomic
    def valider_feuille_presence(
        cls,
        seance_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id, verrou=True)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_VALIDER,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        if (
            seance.statut_feuille_presence
            != Seance.StatutFeuillePresence.OUVERTE
        ):
            raise ValidationActiviteErreur(
                "Seule une feuille ouverte peut être validée."
            )

        candidats = list(
            CandidatActiviteRepository.pour_seance(seance)
        )
        presents = {
            presence.affectation_centre_id
            for presence in PresenceRepository.lister_par_seance(
                seance.id
            )
        }
        manquants = []

        for affectation in candidats:
            if affectation.id in presents:
                continue

            decision = cls._decision_participation(
                affectation.id,
                date_reference=seance.date_seance,
            )
            if decision["autorise"] or decision["dispense"]:
                manquants.append(affectation.id)

        if manquants:
            raise ValidationActiviteErreur(
                {
                    "presences": (
                        f"{len(manquants)} immergé(s) éligible(s) "
                        "n'ont aucune présence saisie."
                    )
                }
            )

        seance.statut_feuille_presence = (
            Seance.StatutFeuillePresence.VALIDEE
        )
        seance.date_validation_presence = timezone.now()
        seance.presences_validees_par = acteur
        seance.save(
            update_fields=[
                "statut_feuille_presence",
                "date_validation_presence",
                "presences_validees_par",
                "updated_at",
            ]
        )
        return seance

    @classmethod
    @transaction.atomic
    def cloturer_feuille_presence(
        cls,
        seance_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id, verrou=True)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_CLOTURER,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        if (
            seance.statut_feuille_presence
            != Seance.StatutFeuillePresence.VALIDEE
        ):
            raise ValidationActiviteErreur(
                "La feuille doit être validée avant sa clôture."
            )

        seance.statut_feuille_presence = (
            Seance.StatutFeuillePresence.CLOTUREE
        )
        seance.date_cloture_presence = timezone.now()
        seance.save(
            update_fields=[
                "statut_feuille_presence",
                "date_cloture_presence",
                "updated_at",
            ]
        )
        return seance

    @classmethod
    def saisir_presences_lot(
        cls,
        *,
        seance_id,
        lignes,
        acteur,
        verifier_acces=True,
    ):
        seance = cls._seance(seance_id)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_SAISIR,
                session_id=seance.session_id,
                centre_id=seance.centre_id,
            )

        resultat = ResultatTraitementMasse(
            demandes=len(lignes),
        )
        for ligne in lignes:
            affectation_id = ligne.get(
                "affectation_centre_id"
            )
            try:
                presence_avant = (
                    PresenceRepository
                    .get_active_par_seance_affectation(
                        seance_id=seance.id,
                        affectation_centre_id=affectation_id,
                    )
                )
                presence = cls.saisir_presence(
                    seance_id=seance.id,
                    affectation_centre_id=affectation_id,
                    statut_presence=ligne.get(
                        "statut_presence"
                    ),
                    heure_arrivee=ligne.get(
                        "heure_arrivee"
                    ),
                    observations=ligne.get(
                        "observations",
                        "",
                    ),
                    acteur=acteur,
                    verifier_acces=False,
                )
                resultat.traites += 1
                if presence.statut_presence == (
                    Presence.StatutPresence.DISPENSE
                ):
                    resultat.dispenses += 1
                if presence_avant is None:
                    resultat.crees += 1
                else:
                    resultat.mis_a_jour += 1
            except ValidationError as exc:
                resultat.traites += 1
                resultat.erreurs += 1
                if affectation_id:
                    resultat.identifiants_ignores.append(
                        affectation_id
                    )
                resultat.details[str(affectation_id)] = str(exc)

        return resultat

    @classmethod
    def calculer_taux_presence(
        cls,
        *,
        affectation_centre_id,
        session_id,
        acteur=None,
        date_debut=None,
        date_fin=None,
        verifier_acces=True,
    ):
        affectation = (
            CandidatActiviteRepository.base_queryset().filter(
                id=affectation_centre_id,
                session_id=session_id,
            ).first()
        )
        if affectation is None:
            raise ValidationActiviteErreur(
                "L'affectation centre active est introuvable."
            )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_CALCULER,
                session_id=session_id,
                centre_id=affectation.centre_id,
            )

        lignes = list(
            PresenceRepository.pour_taux(
                affectation_centre_id=affectation_centre_id,
                session_id=session_id,
                date_debut=date_debut,
                date_fin=date_fin,
            )
        )
        compteurs = {
            valeur: 0
            for valeur, _ in Presence.StatutPresence.choices
        }
        for presence in lignes:
            compteurs[presence.statut_presence] += 1

        dispenses = compteurs[
            Presence.StatutPresence.DISPENSE
        ]
        total_eligible = len(lignes) - dispenses
        favorables = (
            compteurs[Presence.StatutPresence.PRESENT]
            + compteurs[Presence.StatutPresence.RETARD]
            + compteurs[Presence.StatutPresence.EXCUSE]
        )

        if total_eligible == 0:
            taux = Decimal("100.00")
        else:
            taux = (
                Decimal(favorables)
                * Decimal("100")
                / Decimal(total_eligible)
            ).quantize(Decimal("0.01"))

        session = cls._session(session_id)
        seuil = session.parametres.taux_presence_minimum_attestation

        return {
            "affectation_centre_id": affectation_centre_id,
            "session_id": session_id,
            "total_seances": len(lignes),
            "total_eligible": total_eligible,
            "favorables": favorables,
            "presents": compteurs[
                Presence.StatutPresence.PRESENT
            ],
            "retards": compteurs[
                Presence.StatutPresence.RETARD
            ],
            "absences": compteurs[
                Presence.StatutPresence.ABSENT
            ],
            "excuses": compteurs[
                Presence.StatutPresence.EXCUSE
            ],
            "dispenses": dispenses,
            "taux_presence": taux,
            "seuil_attestation": seuil,
            "seuil_atteint": taux >= seuil,
        }


class EvaluationService(ServiceActiviteBase):
    """Création et cycle de saisie des évaluations."""

    PERMISSION_CREER = "creer_evaluation"
    PERMISSION_MODIFIER = "modifier_evaluation"
    PERMISSION_OUVRIR = "ouvrir_saisie_notes"
    PERMISSION_CLOTURER = "cloturer_evaluation"
    PERMISSION_ANNULER = "annuler_evaluation"
    PERMISSION_VALIDER_RESULTATS = "valider_resultats"

    @classmethod
    def _seance_optionnelle(
        cls,
        seance_id,
        *,
        session_id,
        centre_id,
    ):
        if not seance_id:
            return None

        try:
            seance = SeanceRepository.get_by_id(seance_id)
        except Seance.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "La séance est introuvable."
            ) from exc

        if seance.session_id != session_id:
            raise ValidationActiviteErreur(
                "La séance n'appartient pas à la session."
            )
        if seance.centre_id != centre_id:
            raise ValidationActiviteErreur(
                "La séance n'appartient pas au centre."
            )
        if seance.statut in {
            Seance.Statut.ANNULEE,
            Seance.Statut.REPORTEE,
        }:
            raise ValidationActiviteErreur(
                "Une séance annulée ou reportée ne peut pas "
                "porter une évaluation."
            )
        return seance

    @classmethod
    @transaction.atomic
    def creer_evaluation(
        cls,
        *,
        acteur,
        session_id,
        centre_id,
        titre,
        type_evaluation,
        bareme,
        coefficient,
        date_evaluation,
        seance_id=None,
        statut=Evaluation.Statut.BROUILLON,
    ):
        session = cls._session(session_id)
        centre = cls._centre(centre_id)
        cls._exiger_session_modifiable(session)
        cls._exiger_evaluations_actives(session)
        cls._exiger_date_dans_session(
            session,
            date_evaluation,
        )

        if not centre.est_actif:
            raise ValidationActiviteErreur(
                "Le centre doit être actif."
            )

        seance = cls._seance_optionnelle(
            seance_id,
            session_id=session.id,
            centre_id=centre.id,
        )
        if statut != Evaluation.Statut.BROUILLON:
            raise ValidationActiviteErreur(
                {
                    "statut": (
                        "Une évaluation doit être créée "
                        "en brouillon."
                    )
                }
            )

        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_CREER,
            session_id=session.id,
            centre_id=centre.id,
        )

        return EvaluationRepository.creer(
            session=session,
            centre=centre,
            seance=seance,
            titre=titre,
            type_evaluation=type_evaluation,
            bareme=cls._normaliser_decimal(
                bareme,
                "bareme",
            ),
            coefficient=cls._normaliser_decimal(
                coefficient,
                "coefficient",
            ),
            date_evaluation=date_evaluation,
            statut=statut,
            created_by=acteur,
        )

    @classmethod
    @transaction.atomic
    def modifier_evaluation(
        cls,
        evaluation_id,
        *,
        acteur,
        **donnees,
    ):
        evaluation = (
            EvaluationRepository.get_by_id_pour_update(
                evaluation_id
            )
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_MODIFIER,
            session_id=evaluation.session_id,
            centre_id=evaluation.centre_id,
        )

        if evaluation.statut != Evaluation.Statut.BROUILLON:
            raise ValidationActiviteErreur(
                "Seule une évaluation en brouillon "
                "peut être modifiée."
            )

        session = cls._session(
            donnees.get("session_id", evaluation.session_id)
        )
        centre = cls._centre(
            donnees.get("centre_id", evaluation.centre_id)
        )
        seance = cls._seance_optionnelle(
            donnees.get("seance_id", evaluation.seance_id),
            session_id=session.id,
            centre_id=centre.id,
        )
        date_evaluation = donnees.get(
            "date_evaluation",
            evaluation.date_evaluation,
        )

        cls._exiger_session_modifiable(session)
        cls._exiger_evaluations_actives(session)
        cls._exiger_date_dans_session(
            session,
            date_evaluation,
        )

        correspondances = {
            "session_id": ("session", session),
            "centre_id": ("centre", centre),
            "seance_id": ("seance", seance),
        }
        champs = []

        for cle, (champ, valeur) in correspondances.items():
            if cle in donnees:
                setattr(evaluation, champ, valeur)
                champs.append(champ)

        for champ in {
            "titre",
            "type_evaluation",
            "date_evaluation",
        }:
            if champ in donnees:
                setattr(evaluation, champ, donnees[champ])
                champs.append(champ)

        if "bareme" in donnees:
            evaluation.bareme = cls._normaliser_decimal(
                donnees["bareme"],
                "bareme",
            )
            champs.append("bareme")

        if "coefficient" in donnees:
            evaluation.coefficient = cls._normaliser_decimal(
                donnees["coefficient"],
                "coefficient",
            )
            champs.append("coefficient")

        champs.append("updated_at")
        return EvaluationRepository.sauvegarder(
            evaluation,
            update_fields=list(dict.fromkeys(champs)),
        )

    @classmethod
    @transaction.atomic
    def ouvrir_saisie_notes(
        cls,
        evaluation_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        evaluation = (
            EvaluationRepository.get_by_id_pour_update(
                evaluation_id
            )
        )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_OUVRIR,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
            )

        cls._exiger_evaluations_actives(evaluation.session)

        if evaluation.statut != Evaluation.Statut.BROUILLON:
            raise ValidationActiviteErreur(
                "Seule une évaluation en brouillon "
                "peut être ouverte."
            )

        evaluation.statut = Evaluation.Statut.OUVERTE
        return EvaluationRepository.sauvegarder(
            evaluation,
            update_fields=["statut", "updated_at"],
        )

    @classmethod
    @transaction.atomic
    def cloturer_evaluation(
        cls,
        evaluation_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        evaluation = (
            EvaluationRepository.get_by_id_pour_update(
                evaluation_id
            )
        )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_CLOTURER,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
            )

        if evaluation.statut != Evaluation.Statut.OUVERTE:
            raise ValidationActiviteErreur(
                "Seule une évaluation ouverte peut être clôturée."
            )

        evaluation.statut = Evaluation.Statut.CLOTUREE
        return EvaluationRepository.sauvegarder(
            evaluation,
            update_fields=["statut", "updated_at"],
        )

    @classmethod
    @transaction.atomic
    def valider_resultats(
        cls,
        evaluation_id,
        *,
        acteur,
        verifier_acces=True,
    ):
        evaluation = (
            EvaluationRepository.get_by_id_pour_update(
                evaluation_id
            )
        )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_VALIDER_RESULTATS,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
            )

        if evaluation.statut != Evaluation.Statut.OUVERTE:
            raise ValidationActiviteErreur(
                "L'évaluation doit être ouverte."
            )

        candidats = list(
            CandidatActiviteRepository.pour_evaluation(
                evaluation
            )
        )
        notes = {
            note.affectation_centre_id
            for note in NoteRepository.lister_par_evaluation(
                evaluation.id
            )
            if note.statut_note != Note.StatutNote.ANNULEE
        }
        manquants = []

        for affectation in candidats:
            if affectation.id in notes:
                continue

            decision = (
                ImpactMedicalService.decision_pour_module(
                    affectation_centre_id=affectation.id,
                    module="EVALUATIONS",
                    date_reference=(
                        evaluation.date_evaluation.date()
                    ),
                )
            )
            if decision.get("dispense"):
                NoteRepository.creer(
                    evaluation=evaluation,
                    affectation_centre=affectation,
                    valeur=None,
                    appreciation="",
                    statut_note=Note.StatutNote.DISPENSE,
                    observations="Dispense médicale.",
                    saisie_par=acteur,
                    date_saisie=timezone.now(),
                )
                continue

            if decision.get("autorise"):
                manquants.append(affectation.id)

        if manquants:
            raise ValidationActiviteErreur(
                {
                    "notes": (
                        f"{len(manquants)} immergé(s) éligible(s) "
                        "n'ont ni note, ni absence, ni dispense."
                    )
                }
            )

        evaluation.statut = Evaluation.Statut.CLOTUREE
        return EvaluationRepository.sauvegarder(
            evaluation,
            update_fields=["statut", "updated_at"],
        )

    @classmethod
    @transaction.atomic
    def annuler_evaluation(
        cls,
        evaluation_id,
        *,
        acteur,
    ):
        evaluation = (
            EvaluationRepository.get_by_id_pour_update(
                evaluation_id
            )
        )
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_ANNULER,
            session_id=evaluation.session_id,
            centre_id=evaluation.centre_id,
        )

        if evaluation.statut == Evaluation.Statut.CLOTUREE:
            raise ValidationActiviteErreur(
                "Une évaluation clôturée ne peut pas être annulée "
                "sans procédure de correction."
            )

        return evaluation.annuler()

    @staticmethod
    def consulter_resultats(evaluation_id):
        evaluation = EvaluationRepository.get_by_id(
            evaluation_id
        )
        return {
            "evaluation": evaluation,
            "notes": NoteRepository.lister_par_evaluation(
                evaluation.id
            ),
            "statistiques": list(
                NoteRepository.statistiques_evaluation(
                    evaluation.id
                )
            ),
        }


class NoteService(ServiceActiviteBase):
    """Saisie, modification et calcul des notes."""

    PERMISSION_SAISIR = "saisir_note"
    PERMISSION_MODIFIER = "modifier_note"
    PERMISSION_ABSENT = "marquer_absence_note"
    PERMISSION_DISPENSE = "marquer_dispense_note"
    PERMISSION_ANNULER = "annuler_note"
    PERMISSION_MOYENNE = "calculer_moyenne"

    @staticmethod
    def _evaluation(evaluation_id):
        try:
            return EvaluationRepository.get_by_id(evaluation_id)
        except Evaluation.DoesNotExist as exc:
            raise ValidationActiviteErreur(
                "L'évaluation est introuvable."
            ) from exc

    @staticmethod
    def _exiger_evaluation_ouverte(evaluation):
        if evaluation.statut != Evaluation.Statut.OUVERTE:
            raise ValidationActiviteErreur(
                "Les notes ne sont modifiables que lorsque "
                "l'évaluation est ouverte."
            )

    @classmethod
    def _exiger_candidat(
        cls,
        evaluation,
        affectation_centre_id,
    ):
        if not (
            CandidatActiviteRepository
            .appartient_a_evaluation(
                evaluation=evaluation,
                affectation_centre_id=affectation_centre_id,
            )
        ):
            raise ValidationActiviteErreur(
                "L'immergé n'appartient pas à la cible "
                "de cette évaluation."
            )

    @staticmethod
    def _decision_evaluation(evaluation, affectation_id):
        return ImpactMedicalService.decision_pour_module(
            affectation_centre_id=affectation_id,
            module="EVALUATIONS",
            date_reference=evaluation.date_evaluation.date(),
        )

    @classmethod
    @transaction.atomic
    def saisir_note(
        cls,
        *,
        evaluation_id,
        affectation_centre_id,
        acteur,
        valeur=None,
        statut_note=Note.StatutNote.NOTEE,
        appreciation="",
        observations="",
        verifier_acces=True,
    ):
        evaluation = cls._evaluation(evaluation_id)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_SAISIR,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
            )

        cls._exiger_evaluation_ouverte(evaluation)
        cls._exiger_candidat(
            evaluation,
            affectation_centre_id,
        )
        decision = cls._decision_evaluation(
            evaluation,
            affectation_centre_id,
        )

        if decision.get("dispense"):
            statut_note = Note.StatutNote.DISPENSE
            valeur = None
        elif not decision.get("autorise"):
            raise ValidationActiviteErreur(
                "La saisie est bloquée par la décision médicale."
            )

        statuts_saisissables = {
            Note.StatutNote.NOTEE,
            Note.StatutNote.ABSENT,
            Note.StatutNote.DISPENSE,
        }
        if statut_note not in statuts_saisissables:
            raise ValidationActiviteErreur(
                {
                    "statut_note": (
                        "Ce statut ne peut pas être utilisé "
                        "pendant la saisie."
                    )
                }
            )

        if statut_note == Note.StatutNote.NOTEE:
            valeur = cls._normaliser_decimal(
                valeur,
                "valeur",
            )
            if valeur < 0 or valeur > evaluation.bareme:
                raise ValidationActiviteErreur(
                    {
                        "valeur": (
                            "La note doit être comprise entre zéro "
                            "et le barème."
                        )
                    }
                )
        else:
            valeur = None

        note = (
            NoteRepository
            .get_active_par_evaluation_affectation(
                evaluation_id=evaluation.id,
                affectation_centre_id=affectation_centre_id,
            )
        )
        affectation = (
            CandidatActiviteRepository.base_queryset().get(
                id=affectation_centre_id
            )
        )
        maintenant = timezone.now()

        if note is None:
            return NoteRepository.creer(
                evaluation=evaluation,
                affectation_centre=affectation,
                valeur=valeur,
                appreciation=appreciation,
                statut_note=statut_note,
                observations=observations,
                saisie_par=acteur,
                date_saisie=maintenant,
            )

        note.valeur = valeur
        note.appreciation = appreciation
        note.statut_note = statut_note
        note.observations = observations
        note.saisie_par = acteur
        note.date_saisie = maintenant
        return NoteRepository.sauvegarder(
            note,
            update_fields=[
                "valeur",
                "appreciation",
                "statut_note",
                "observations",
                "saisie_par",
                "date_saisie",
                "updated_at",
            ],
        )

    @classmethod
    def modifier_note(
        cls,
        note_id,
        *,
        acteur,
        valeur=None,
        statut_note=Note.StatutNote.NOTEE,
        appreciation="",
        observations="",
    ):
        note = NoteRepository.get_by_id(note_id)
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_MODIFIER,
            session_id=note.evaluation.session_id,
            centre_id=note.evaluation.centre_id,
        )
        return cls.saisir_note(
            evaluation_id=note.evaluation_id,
            affectation_centre_id=(
                note.affectation_centre_id
            ),
            acteur=acteur,
            valeur=valeur,
            statut_note=statut_note,
            appreciation=appreciation,
            observations=observations,
            verifier_acces=False,
        )

    @classmethod
    def marquer_absent(cls, note_id, *, acteur):
        note = NoteRepository.get_by_id(note_id)
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_ABSENT,
            session_id=note.evaluation.session_id,
            centre_id=note.evaluation.centre_id,
        )
        return cls.saisir_note(
            evaluation_id=note.evaluation_id,
            affectation_centre_id=(
                note.affectation_centre_id
            ),
            acteur=acteur,
            statut_note=Note.StatutNote.ABSENT,
            verifier_acces=False,
        )

    @classmethod
    def marquer_dispense(cls, note_id, *, acteur):
        note = NoteRepository.get_by_id(note_id)
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_DISPENSE,
            session_id=note.evaluation.session_id,
            centre_id=note.evaluation.centre_id,
        )
        return cls.saisir_note(
            evaluation_id=note.evaluation_id,
            affectation_centre_id=(
                note.affectation_centre_id
            ),
            acteur=acteur,
            statut_note=Note.StatutNote.DISPENSE,
            verifier_acces=False,
        )

    @classmethod
    @transaction.atomic
    def annuler_note(cls, note_id, *, acteur):
        note = NoteRepository.get_by_id_pour_update(note_id)
        ControleAccesActivitesService.exiger(
            acteur,
            cls.PERMISSION_ANNULER,
            session_id=note.evaluation.session_id,
            centre_id=note.evaluation.centre_id,
        )
        cls._exiger_evaluation_ouverte(note.evaluation)
        return note.annuler()

    @classmethod
    def saisir_notes_lot(
        cls,
        *,
        evaluation_id,
        lignes,
        acteur,
        verifier_acces=True,
    ):
        evaluation = cls._evaluation(evaluation_id)

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_SAISIR,
                session_id=evaluation.session_id,
                centre_id=evaluation.centre_id,
            )

        resultat = ResultatTraitementMasse(
            demandes=len(lignes),
        )

        for ligne in lignes:
            affectation_id = ligne.get(
                "affectation_centre_id"
            )
            try:
                note_avant = (
                    NoteRepository
                    .get_active_par_evaluation_affectation(
                        evaluation_id=evaluation.id,
                        affectation_centre_id=affectation_id,
                    )
                )
                note = cls.saisir_note(
                    evaluation_id=evaluation.id,
                    affectation_centre_id=affectation_id,
                    acteur=acteur,
                    valeur=ligne.get("valeur"),
                    statut_note=ligne.get(
                        "statut_note",
                        Note.StatutNote.NOTEE,
                    ),
                    appreciation=ligne.get(
                        "appreciation",
                        "",
                    ),
                    observations=ligne.get(
                        "observations",
                        "",
                    ),
                    verifier_acces=False,
                )
                resultat.traites += 1
                if note.statut_note == Note.StatutNote.DISPENSE:
                    resultat.dispenses += 1
                if note_avant is None:
                    resultat.crees += 1
                else:
                    resultat.mis_a_jour += 1
            except ValidationError as exc:
                resultat.traites += 1
                resultat.erreurs += 1
                if affectation_id:
                    resultat.identifiants_ignores.append(
                        affectation_id
                    )
                resultat.details[str(affectation_id)] = str(exc)

        return resultat

    @classmethod
    def calculer_moyenne(
        cls,
        *,
        affectation_centre_id,
        session_id,
        acteur=None,
        verifier_acces=True,
    ):
        affectation = (
            CandidatActiviteRepository.base_queryset().filter(
                id=affectation_centre_id,
                session_id=session_id,
            ).first()
        )
        if affectation is None:
            raise ValidationActiviteErreur(
                "L'affectation centre active est introuvable."
            )

        if verifier_acces:
            ControleAccesActivitesService.exiger(
                acteur,
                cls.PERMISSION_MOYENNE,
                session_id=session_id,
                centre_id=affectation.centre_id,
            )

        notes = list(
            NoteRepository.pour_moyenne(
                affectation_centre_id=affectation_centre_id,
                session_id=session_id,
            )
        )
        somme_ponderee = Decimal("0")
        somme_coefficients = Decimal("0")
        notes_comptees = 0
        absences = 0
        dispenses = 0

        for note in notes:
            if note.statut_note == Note.StatutNote.DISPENSE:
                dispenses += 1
                continue

            coefficient = note.evaluation.coefficient
            somme_coefficients += coefficient
            notes_comptees += 1

            if note.statut_note == Note.StatutNote.ABSENT:
                absences += 1
                score_sur_20 = Decimal("0")
            else:
                score_sur_20 = (
                    note.valeur
                    * Decimal("20")
                    / note.evaluation.bareme
                )

            somme_ponderee += score_sur_20 * coefficient

        moyenne = (
            Decimal("0.00")
            if somme_coefficients == 0
            else (
                somme_ponderee / somme_coefficients
            ).quantize(Decimal("0.01"))
        )

        return {
            "affectation_centre_id": affectation_centre_id,
            "session_id": session_id,
            "moyenne_sur_20": moyenne,
            "somme_coefficients": somme_coefficients,
            "notes_comptees": notes_comptees,
            "absences": absences,
            "dispenses": dispenses,
        }
