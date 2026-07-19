from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.service import ControleAccesService
from affectations.models import CentreImmersion
from sessions_app.models import SessionImmersion
from sante.service import ImpactMedicalService

from .models import (
    DemandeRavitaillementCentre,
    LigneBesoinDenree,
    RepasJournalier,
    SuiviRepas,
)
from .repository import (
    CandidatRepasRepository,
    DemandeRavitaillementRepository,
    LigneBesoinDenreeRepository,
    RepasJournalierRepository,
    SuiviRepasRepository,
)


class ValidationRepasErreur(ValidationError):
    """Erreur métier lisible par l'API et les tâches Celery."""


@dataclass
class ResultatPreparationSuivis:
    groupes_crees: int = 0
    suivis_medicaux_crees: int = 0
    suivis_medicaux_mis_a_jour: int = 0
    suivis_medicaux_retires: int = 0

    def en_dict(self):
        return asdict(self)


class ControleAccesRepasService:
    @staticmethod
    def exiger(acteur, code_permission, *, session_id, centre_id=None):
        if acteur is None:
            raise ValidationRepasErreur("Un acteur authentifié est obligatoire.")
        if getattr(acteur, "is_superuser", False):
            return None
        resultat = ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=session_id,
            centre_id=centre_id,
        )
        if not resultat.autorise:
            raise ValidationRepasErreur(
                resultat.motif or "Permission absente ou hors périmètre."
            )
        return resultat.affectation


class SocleRepasService:
    @staticmethod
    def session(session_id):
        try:
            return SessionImmersion.objects.select_related("parametres").get(
                id=session_id, deleted_at__isnull=True
            )
        except SessionImmersion.DoesNotExist as exc:
            raise ValidationRepasErreur("La session est introuvable.") from exc

    @staticmethod
    def centre(centre_id):
        try:
            return CentreImmersion.objects.select_related("region").get(
                id=centre_id, deleted_at__isnull=True
            )
        except CentreImmersion.DoesNotExist as exc:
            raise ValidationRepasErreur("Le centre est introuvable.") from exc

    @staticmethod
    def exiger_module_actif(session):
        parametres = getattr(session, "parametres", None)
        if not parametres or not parametres.repas_active:
            raise ValidationRepasErreur(
                "Le module repas est désactivé pour cette session."
            )

    @staticmethod
    def exiger_session_modifiable(session):
        if not session.est_modifiable:
            raise ValidationRepasErreur(
                "La session est terminée, archivée ou annulée."
            )


class RavitaillementService(SocleRepasService):
    @classmethod
    @transaction.atomic
    def creer_demande(
        cls,
        *,
        acteur,
        session_id,
        centre_id,
        observations="",
    ):
        session = cls.session(session_id)
        centre = cls.centre(centre_id)
        cls.exiger_module_actif(session)
        cls.exiger_session_modifiable(session)
        ControleAccesRepasService.exiger(
            acteur,
            "creer_demande_ravitaillement",
            session_id=session.id,
            centre_id=centre.id,
        )
        effectif = CandidatRepasRepository.effectif_actif(
            session_id=session.id, centre_id=centre.id
        )
        try:
            return DemandeRavitaillementRepository.creer(
                session=session,
                centre=centre,
                effectif_reference=effectif,
                observations=observations,
            )
        except ValidationError as exc:
            raise ValidationRepasErreur(exc) from exc

    @classmethod
    @transaction.atomic
    def modifier_demande(cls, demande_id, *, acteur, **donnees):
        demande = DemandeRavitaillementRepository.get_by_id_pour_update(
            demande_id
        )
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_demande_ravitaillement",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if not demande.est_modifiable:
            raise ValidationRepasErreur(
                "Seule une demande en brouillon peut être modifiée."
            )
        if "observations" in donnees:
            demande.observations = donnees["observations"]
        if donnees.get("recalculer_effectif"):
            demande.effectif_reference = CandidatRepasRepository.effectif_actif(
                session_id=demande.session_id, centre_id=demande.centre_id
            )
        demande.save()
        return demande

    @classmethod
    @transaction.atomic
    def ajouter_denree(cls, demande_id, *, acteur, **donnees):
        demande = DemandeRavitaillementRepository.get_by_id_pour_update(
            demande_id
        )
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_demande_ravitaillement",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if not demande.est_modifiable:
            raise ValidationRepasErreur(
                "Les denrées ne sont modifiables qu'au stade brouillon."
            )
        ligne = LigneBesoinDenree(
            demande_ravitaillement=demande,
            quantite_validee=Decimal("0"),
            quantite_recue=Decimal("0"),
            **donnees,
        )
        ligne.save()
        return ligne

    @classmethod
    @transaction.atomic
    def modifier_denree(cls, ligne_id, *, acteur, **donnees):
        ligne = LigneBesoinDenreeRepository.get_by_id_pour_update(ligne_id)
        demande = ligne.demande_ravitaillement
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_demande_ravitaillement",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if not demande.est_modifiable:
            raise ValidationRepasErreur(
                "Les denrées ne sont modifiables qu'au stade brouillon."
            )
        champs = {
            "code_denree",
            "designation",
            "conditionnement",
            "contenance_conditionnement",
            "unite_base",
            "quantite_demandee",
            "observations",
        }
        for champ, valeur in donnees.items():
            if champ in champs:
                setattr(ligne, champ, valeur)
        ligne.save()
        return ligne

    @classmethod
    @transaction.atomic
    def supprimer_denree(cls, ligne_id, *, acteur):
        ligne = LigneBesoinDenreeRepository.get_by_id_pour_update(ligne_id)
        demande = ligne.demande_ravitaillement
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_demande_ravitaillement",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if not demande.est_modifiable:
            raise ValidationRepasErreur(
                "La demande n'est plus modifiable."
            )
        return ligne.supprimer_logiquement()

    @classmethod
    @transaction.atomic
    def soumettre(cls, demande_id, *, acteur):
        demande = DemandeRavitaillementRepository.get_by_id_pour_update(
            demande_id
        )
        ControleAccesRepasService.exiger(
            acteur,
            "soumettre_demande_ravitaillement",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if demande.statut != demande.Statut.BROUILLON:
            raise ValidationRepasErreur("La demande n'est pas en brouillon.")
        if not LigneBesoinDenreeRepository.non_supprimees().filter(
            demande_ravitaillement_id=demande.id
        ).exists():
            raise ValidationRepasErreur(
                "Ajoutez au moins une denrée avant la soumission."
            )
        demande.effectif_reference = CandidatRepasRepository.effectif_actif(
            session_id=demande.session_id, centre_id=demande.centre_id
        )
        demande.statut = demande.Statut.SOUMISE
        demande.soumis_par = acteur
        demande.date_soumission = timezone.now()
        demande.save()
        return demande

    @classmethod
    @transaction.atomic
    def valider(cls, demande_id, *, acteur, quantites=None):
        demande = DemandeRavitaillementRepository.get_by_id_pour_update(
            demande_id
        )
        ControleAccesRepasService.exiger(
            acteur,
            "valider_demande_ravitaillement",
            session_id=demande.session_id,
        )
        if demande.statut != demande.Statut.SOUMISE:
            raise ValidationRepasErreur("Seule une demande soumise est validable.")
        quantites = quantites or {}
        lignes = LigneBesoinDenreeRepository.non_supprimees().filter(
            demande_ravitaillement_id=demande.id
        )
        for ligne in lignes:
            valeur = quantites.get(str(ligne.id), quantites.get(ligne.id))
            ligne.quantite_validee = (
                Decimal(str(valeur))
                if valeur is not None
                else ligne.quantite_demandee
            )
            ligne.statut = ligne.Statut.VALIDEE
            ligne.save()
        demande.statut = demande.Statut.VALIDEE
        demande.valide_par = acteur
        demande.date_validation = timezone.now()
        demande.save()
        return demande

    @classmethod
    @transaction.atomic
    def enregistrer_reception(cls, ligne_id, *, acteur, quantite_recue):
        ligne = LigneBesoinDenreeRepository.get_by_id_pour_update(ligne_id)
        demande = ligne.demande_ravitaillement
        ControleAccesRepasService.exiger(
            acteur,
            "enregistrer_reception_denrees",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        if demande.statut not in {
            demande.Statut.VALIDEE,
            demande.Statut.PARTIELLEMENT_RECUE,
            demande.Statut.RECUE,
        }:
            raise ValidationRepasErreur("La demande doit d'abord être validée.")
        ligne.quantite_recue = Decimal(str(quantite_recue))
        ligne.statut = (
            ligne.Statut.RECUE
            if ligne.quantite_recue >= ligne.quantite_validee
            else ligne.Statut.PARTIELLEMENT_RECUE
        )
        ligne.save()
        statuts = set(
            LigneBesoinDenreeRepository.non_supprimees()
            .filter(demande_ravitaillement_id=demande.id)
            .values_list("statut", flat=True)
        )
        demande.statut = (
            demande.Statut.RECUE
            if statuts == {LigneBesoinDenree.Statut.RECUE}
            else demande.Statut.PARTIELLEMENT_RECUE
        )
        demande.save(update_fields=["statut", "updated_at"])
        return ligne

    @staticmethod
    def consolider(*, acteur, session_id, region_id=None):
        ControleAccesRepasService.exiger(
            acteur,
            "consolider_besoins_denrees",
            session_id=session_id,
        )
        lignes = LigneBesoinDenreeRepository.consolider(
            session_id=session_id,
            region_id=region_id,
            statut_demande=[
                DemandeRavitaillementCentre.Statut.VALIDEE,
                DemandeRavitaillementCentre.Statut.PARTIELLEMENT_RECUE,
                DemandeRavitaillementCentre.Statut.RECUE,
            ],
        )
        for ligne in lignes:
            for champ in ("total_demande", "total_valide", "total_recu"):
                ligne[champ] = str(ligne[champ] or Decimal("0"))
        return lignes


class RepasService(SocleRepasService):
    CHAMPS_PLANIFICATION = {
        "date_repas",
        "type_repas",
        "heure_prevue",
        "menu_prevu",
        "description_prevue",
        "denrees_prevues",
        "preparations_speciales_prevues",
    }

    @staticmethod
    def _empreinte_besoins(besoins):
        utile = {
            "synthese": besoins.get("synthese", {}),
            "personnes": [
                {
                    "affectation_centre_id": p["affectation_centre_id"],
                    "categories": sorted(p.get("categories", [])),
                    "consignes": sorted(p.get("consignes", [])),
                    "date_debut": p.get("date_debut"),
                    "date_fin": p.get("date_fin"),
                }
                for p in besoins.get("personnes", [])
            ],
        }
        brut = json.dumps(utile, sort_keys=True, ensure_ascii=False)
        return sha256(brut.encode("utf-8")).hexdigest()

    @classmethod
    def analyser_besoins_sante(cls, repas):
        besoins = ImpactMedicalService.besoins_repas_pour_date(
            session_id=repas.session_id,
            centre_id=repas.centre_id,
            date_reference=repas.date_repas,
        )
        besoins["empreinte"] = cls._empreinte_besoins(besoins)
        effectif = CandidatRepasRepository.effectif_actif(
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        besoins["effectif_total"] = effectif
        besoins["nombre_standard_prevu"] = max(
            0, effectif - besoins["total_concernes"]
        )
        return besoins

    @staticmethod
    def _extraire_quantite_preparation(preparation):
        if isinstance(preparation, dict):
            preparation = preparation.get("quantite", 0)
        try:
            return max(0, int(preparation or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def verifier_couverture_speciale(cls, repas, besoins=None, *, reelle=False):
        besoins = besoins or cls.analyser_besoins_sante(repas)
        preparations = (
            repas.preparations_speciales_reelles
            if reelle
            else repas.preparations_speciales_prevues
        ) or {}
        manquants = {}
        for categorie, quantite in besoins["synthese"].items():
            preparee = cls._extraire_quantite_preparation(
                preparations.get(categorie)
            )
            if preparee < int(quantite):
                manquants[categorie] = {
                    "necessaire": int(quantite),
                    "preparee": preparee,
                    "manquante": int(quantite) - preparee,
                }
        if manquants:
            nature = "réelles" if reelle else "prévues"
            raise ValidationRepasErreur(
                {"preparations_speciales": (
                    f"Les préparations {nature} sont insuffisantes.", manquants
                )}
            )
        return True

    @classmethod
    @transaction.atomic
    def creer(
        cls,
        *,
        acteur,
        demande_ravitaillement_id,
        date_repas,
        type_repas,
        menu_prevu,
        heure_prevue=None,
        description_prevue="",
        denrees_prevues=None,
        preparations_speciales_prevues=None,
    ):
        demande = DemandeRavitaillementRepository.get_by_id(
            demande_ravitaillement_id
        )
        cls.exiger_module_actif(demande.session)
        cls.exiger_session_modifiable(demande.session)
        ControleAccesRepasService.exiger(
            acteur,
            "planifier_repas",
            session_id=demande.session_id,
            centre_id=demande.centre_id,
        )
        repas = RepasJournalier(
            demande_ravitaillement=demande,
            date_repas=date_repas,
            type_repas=type_repas,
            heure_prevue=heure_prevue,
            menu_prevu=menu_prevu,
            description_prevue=description_prevue,
            denrees_prevues=denrees_prevues or [],
            preparations_speciales_prevues=(
                preparations_speciales_prevues or {}
            ),
            cree_par=acteur,
        )
        repas.save()
        return cls.actualiser_besoins_sante(
            repas.id, acteur=acteur, exiger_permission=False
        )

    @classmethod
    @transaction.atomic
    def modifier(cls, repas_id, *, acteur, **donnees):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if not repas.est_modifiable:
            raise ValidationRepasErreur("Ce repas n'est plus modifiable.")
        for champ, valeur in donnees.items():
            if champ in cls.CHAMPS_PLANIFICATION:
                setattr(repas, champ, valeur)
        repas.save()
        if {"date_repas", "type_repas"} & set(donnees):
            return cls.actualiser_besoins_sante(
                repas.id, acteur=acteur, exiger_permission=False
            )
        return repas

    @classmethod
    @transaction.atomic
    def actualiser_besoins_sante(
        cls, repas_id, *, acteur, exiger_permission=True
    ):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        if repas.statut not in {
            repas.Statut.BROUILLON,
            repas.Statut.PLANIFIE,
            repas.Statut.VALIDE,
        }:
            raise ValidationRepasErreur(
                "Les besoins santé ne peuvent plus être actualisés après "
                "le démarrage de la préparation."
            )
        if exiger_permission:
            ControleAccesRepasService.exiger(
                acteur,
                "calculer_portions_repas",
                session_id=repas.session_id,
                centre_id=repas.centre_id,
            )
        besoins = cls.analyser_besoins_sante(repas)
        repas.nombre_standard_prevu = besoins["nombre_standard_prevu"]
        repas.synthese_restrictions_alimentaires = besoins["synthese"]
        repas.empreinte_besoins_sante = besoins["empreinte"]
        repas.statut_controle_sante = repas.StatutControleSante.A_JOUR
        repas.date_verification_sante = timezone.now()
        if repas.statut == repas.Statut.VALIDE:
            repas.statut = repas.Statut.PLANIFIE
            repas.valide_par = None
            repas.date_validation = None
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def planifier(cls, repas_id, *, acteur):
        repas = cls.actualiser_besoins_sante(repas_id, acteur=acteur)
        if repas.statut not in {repas.Statut.BROUILLON, repas.Statut.PLANIFIE}:
            raise ValidationRepasErreur("Le repas ne peut plus être planifié.")
        repas.statut = repas.Statut.PLANIFIE
        repas.save(update_fields=["statut", "updated_at"])
        return repas

    @classmethod
    def _preparation_personne(cls, personne, preparations):
        morceaux = []
        for categorie in personne.get("categories", []):
            preparation = preparations.get(categorie)
            if isinstance(preparation, dict):
                menu = str(preparation.get("menu") or "").strip()
            else:
                menu = ""
            if menu:
                morceaux.append(f"{categorie}: {menu}")
        return " ; ".join(morceaux)

    @classmethod
    def _synchroniser_suivis_medicaux(cls, repas, besoins, acteur):
        resultat = ResultatPreparationSuivis()
        existants = {
            suivi.affectation_centre_id: suivi
            for suivi in SuiviRepasRepository.suivis_medicaux(repas.id)
        }
        attendus = set()
        for personne in besoins["personnes"]:
            affectation_id = personne["affectation_centre_id"]
            attendus.add(affectation_id)
            preparation = cls._preparation_personne(
                personne, repas.preparations_speciales_prevues
            )
            if not preparation:
                raise ValidationRepasErreur(
                    "Chaque personne concernée doit avoir une préparation "
                    f"spéciale prévue : {personne['code_fasoim']}."
                )
            suivi = existants.get(affectation_id)
            if suivi is None:
                SuiviRepas.objects.create(
                    repas_journalier=repas,
                    type_suivi=SuiviRepas.TypeSuivi.MEDICAL,
                    affectation_centre_id=affectation_id,
                    categorie_alimentaire=personne["categorie"],
                    consigne_alimentaire=personne["consigne"],
                    preparation_speciale_prevue=preparation,
                    statut_service=SuiviRepas.StatutService.A_SERVIR,
                    saisi_par=acteur,
                )
                resultat.suivis_medicaux_crees += 1
            else:
                suivi.categorie_alimentaire = personne["categorie"]
                suivi.consigne_alimentaire = personne["consigne"]
                suivi.preparation_speciale_prevue = preparation
                if suivi.statut_service == SuiviRepas.StatutService.A_SERVIR:
                    suivi.saisi_par = acteur
                suivi.save()
                resultat.suivis_medicaux_mis_a_jour += 1
        for affectation_id, suivi in existants.items():
            if affectation_id not in attendus:
                suivi.supprimer_logiquement()
                resultat.suivis_medicaux_retires += 1
        return resultat

    @classmethod
    @transaction.atomic
    def valider_planification(cls, repas_id, *, acteur):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut not in {repas.Statut.BROUILLON, repas.Statut.PLANIFIE}:
            raise ValidationRepasErreur("Cette planification n'est pas validable.")
        besoins = cls.analyser_besoins_sante(repas)
        cls.verifier_couverture_speciale(repas, besoins)
        cls._synchroniser_suivis_medicaux(repas, besoins, acteur)
        repas.nombre_standard_prevu = besoins["nombre_standard_prevu"]
        repas.synthese_restrictions_alimentaires = besoins["synthese"]
        repas.empreinte_besoins_sante = besoins["empreinte"]
        repas.statut_controle_sante = repas.StatutControleSante.A_JOUR
        repas.date_verification_sante = timezone.now()
        repas.statut = repas.Statut.VALIDE
        repas.valide_par = acteur
        repas.date_validation = timezone.now()
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def demarrer_preparation(cls, repas_id, *, acteur):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.VALIDE:
            raise ValidationRepasErreur("Le repas doit être validé.")
        besoins = cls.analyser_besoins_sante(repas)
        if besoins["empreinte"] != repas.empreinte_besoins_sante:
            repas.statut_controle_sante = repas.StatutControleSante.A_REVOIR
            repas.save(update_fields=["statut_controle_sante", "updated_at"])
            raise ValidationRepasErreur(
                "Les restrictions alimentaires ont changé. Actualisez puis "
                "validez de nouveau la planification."
            )
        repas.statut = repas.Statut.EN_PREPARATION
        repas.heure_debut_preparation = timezone.now()
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def terminer_preparation(
        cls,
        repas_id,
        *,
        acteur,
        menu_prepare,
        nombre_standard_prepare,
        preparations_speciales_reelles,
        description_preparation_reelle="",
        denrees_reellement_utilisees=None,
        observations_preparation="",
    ):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "modifier_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.EN_PREPARATION:
            raise ValidationRepasErreur("La préparation n'est pas ouverte.")
        repas.menu_prepare = menu_prepare
        repas.nombre_standard_prepare = nombre_standard_prepare
        repas.preparations_speciales_reelles = preparations_speciales_reelles
        repas.description_preparation_reelle = description_preparation_reelle
        repas.denrees_reellement_utilisees = denrees_reellement_utilisees or []
        repas.observations_preparation = observations_preparation
        cls.verifier_couverture_speciale(repas, reelle=True)
        repas.heure_fin_preparation = timezone.now()
        repas.statut = repas.Statut.PREPARE
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def preparer_comptages(cls, repas_id, *, acteur):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "ouvrir_distribution_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut not in {
            repas.Statut.VALIDE,
            repas.Statut.EN_PREPARATION,
            repas.Statut.PREPARE,
        }:
            raise ValidationRepasErreur(
                "Les comptages exigent une planification validée."
            )
        groupes = CandidatRepasRepository.groupes_et_effectifs(
            session_id=repas.session_id, centre_id=repas.centre_id
        )
        resultat = ResultatPreparationSuivis()
        if groupes:
            SuiviRepasRepository.comptages(repas.id).filter(
                groupe__isnull=True
            ).update(deleted_at=timezone.now())
            for ligne in groupes:
                _, cree = SuiviRepas.objects.update_or_create(
                    repas_journalier=repas,
                    type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
                    groupe=ligne["groupe"],
                    defaults={
                        "effectif_attendu": ligne["effectif"],
                        "nombre_ayant_mange": 0,
                        "saisi_par": acteur,
                        "deleted_at": None,
                    },
                )
                resultat.groupes_crees += int(cree)
        else:
            SuiviRepasRepository.comptages(repas.id).filter(
                groupe__isnull=False
            ).update(deleted_at=timezone.now())
            effectif = CandidatRepasRepository.effectif_actif(
                session_id=repas.session_id, centre_id=repas.centre_id
            )
            _, cree = SuiviRepas.objects.update_or_create(
                repas_journalier=repas,
                type_suivi=SuiviRepas.TypeSuivi.COMPTAGE,
                groupe=None,
                defaults={
                    "effectif_attendu": effectif,
                    "nombre_ayant_mange": 0,
                    "saisi_par": acteur,
                    "deleted_at": None,
                },
            )
            resultat.groupes_crees += int(cree)
        return resultat

    @classmethod
    @transaction.atomic
    def ouvrir_distribution(cls, repas_id, *, acteur):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "ouvrir_distribution_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.PREPARE:
            raise ValidationRepasErreur("Le repas doit être préparé.")
        if repas.statut_controle_sante != repas.StatutControleSante.A_JOUR:
            raise ValidationRepasErreur("Le contrôle santé doit être à jour.")
        if not SuiviRepasRepository.comptages(repas.id).exists():
            cls.preparer_comptages(repas.id, acteur=acteur)
        repas.statut = repas.Statut.DISTRIBUTION_OUVERTE
        repas.date_ouverture_distribution = timezone.now()
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def saisir_comptage(
        cls, suivi_id, *, acteur, nombre_ayant_mange, observations=""
    ):
        suivi = SuiviRepasRepository.get_by_id_pour_update(suivi_id)
        repas = suivi.repas_journalier
        ControleAccesRepasService.exiger(
            acteur,
            "pointer_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.DISTRIBUTION_OUVERTE:
            raise ValidationRepasErreur("La distribution n'est pas ouverte.")
        if suivi.type_suivi != suivi.TypeSuivi.COMPTAGE:
            raise ValidationRepasErreur("Ce suivi n'est pas un comptage.")
        suivi.nombre_ayant_mange = nombre_ayant_mange
        suivi.observations = observations
        suivi.saisi_par = acteur
        suivi.date_saisie = timezone.now()
        suivi.save()
        return suivi

    @classmethod
    @transaction.atomic
    def marquer_service_medical(
        cls, suivi_id, *, acteur, statut_service, observation_service=""
    ):
        suivi = SuiviRepasRepository.get_by_id_pour_update(suivi_id)
        repas = suivi.repas_journalier
        code = {
            SuiviRepas.StatutService.SERVI_CONFORME: "marquer_regime_special",
            SuiviRepas.StatutService.SERVI_NON_CONFORME: "marquer_regime_special",
            SuiviRepas.StatutService.NON_SERVI: "pointer_repas",
            SuiviRepas.StatutService.ABSENT: "marquer_repas_absent",
            SuiviRepas.StatutService.REFUSE: "marquer_repas_refuse",
        }.get(statut_service, "modifier_pointage_repas")
        ControleAccesRepasService.exiger(
            acteur,
            code,
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.DISTRIBUTION_OUVERTE:
            raise ValidationRepasErreur("La distribution n'est pas ouverte.")
        if suivi.type_suivi != suivi.TypeSuivi.MEDICAL:
            raise ValidationRepasErreur("Ce suivi n'est pas alimentaire.")
        if statut_service == SuiviRepas.StatutService.A_SERVIR:
            raise ValidationRepasErreur("Choisissez un statut final.")
        suivi.statut_service = statut_service
        suivi.observation_service = observation_service
        suivi.saisi_par = acteur
        suivi.date_saisie = timezone.now()
        suivi.save()
        return suivi

    @classmethod
    @transaction.atomic
    def cloturer(cls, repas_id, *, acteur):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "cloturer_distribution_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut != repas.Statut.DISTRIBUTION_OUVERTE:
            raise ValidationRepasErreur("La distribution n'est pas ouverte.")
        comptages = list(SuiviRepasRepository.comptages(repas.id))
        if not comptages:
            raise ValidationRepasErreur("Aucun comptage n'est disponible.")
        non_saisis = sum(1 for ligne in comptages if ligne.date_saisie is None)
        if non_saisis:
            raise ValidationRepasErreur(
                f"{non_saisis} comptage(s) n'ont pas encore été saisis."
            )
        en_attente = SuiviRepasRepository.suivis_medicaux(repas.id).filter(
            statut_service=SuiviRepas.StatutService.A_SERVIR
        ).count()
        if en_attente:
            raise ValidationRepasErreur(
                f"{en_attente} repas adapté(s) sont encore à servir."
            )
        total_servi = sum(ligne.nombre_ayant_mange for ligne in comptages)
        if total_servi > repas.total_prepare:
            raise ValidationRepasErreur(
                "Le nombre ayant mangé dépasse le nombre de repas préparés."
            )
        repas.statut = repas.Statut.CLOTURE
        repas.date_cloture = timezone.now()
        repas.save()
        return repas

    @classmethod
    @transaction.atomic
    def annuler(cls, repas_id, *, acteur, motif):
        repas = RepasJournalierRepository.get_by_id_pour_update(repas_id)
        ControleAccesRepasService.exiger(
            acteur,
            "annuler_repas",
            session_id=repas.session_id,
            centre_id=repas.centre_id,
        )
        if repas.statut == repas.Statut.CLOTURE:
            raise ValidationRepasErreur("Un repas clôturé ne peut pas être annulé.")
        repas.statut = repas.Statut.ANNULE
        repas.motif_annulation = motif
        repas.save()
        return repas

    @staticmethod
    def statistiques(*, acteur, **filtres):
        ControleAccesRepasService.exiger(
            acteur,
            "generer_rapport_repas",
            session_id=filtres.get("session_id"),
            centre_id=filtres.get("centre_id"),
        )
        return RepasJournalierRepository.statistiques(**filtres)
