from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)
from .repository import (
    ImmergeConcoursRepository,
    ImmergeExamenRepository,
    ImmergeRepository,
    ImmergeSelectionneRepository,
    InscriptionVolontaireRepository,
)


class ValidationMetierErreur(ValidationError):
    """Erreur métier volontairement simple pour éviter le théâtre inutile."""


@dataclass(frozen=True)
class SourceCentralisation:
    type_immerge: str
    origine_id: int
    session: Any


class NettoyageImmergeService:
    @staticmethod
    def texte(valeur, *, upper=False):
        valeur = " ".join(str(valeur or "").strip().split())
        return valeur.upper() if upper else valeur

    @staticmethod
    def email(valeur):
        return NettoyageImmergeService.texte(valeur).lower()

    @staticmethod
    def telephone(valeur):
        return NettoyageImmergeService.texte(valeur)

    @staticmethod
    def nettoyer_identite(donnees: dict) -> dict:
        donnees = dict(donnees)
        for champ in ["nom", "prenoms", "nom_et_prenoms", "lieu_naissance", "nationalite"]:
            if champ in donnees:
                donnees[champ] = NettoyageImmergeService.texte(donnees.get(champ))
        if "nom" in donnees:
            donnees["nom"] = NettoyageImmergeService.texte(donnees.get("nom"), upper=True)
        if "email" in donnees:
            donnees["email"] = NettoyageImmergeService.email(donnees.get("email"))
        for champ in ["telephone", "contact_urgence", "numero_cnib"]:
            if champ in donnees:
                donnees[champ] = NettoyageImmergeService.telephone(donnees.get(champ))
        return donnees


class BrouillageSuppressionService:
    @staticmethod
    def suffixe(objet):
        return f"__supprime__{objet.pk or 'x'}__{timezone.now().strftime('%Y%m%d%H%M%S')}"

    @staticmethod
    def brouiller_valeur(valeur, suffixe, longueur_max):
        valeur = str(valeur or "").strip()
        if not valeur:
            return valeur
        nouveau = f"{valeur}{suffixe}"
        return nouveau[:longueur_max]


class CodeFasoIMService:
    PREFIXES = {
        Immerge.TypeImmerge.BEPC: "BEPC",
        Immerge.TypeImmerge.BAC: "BAC",
        Immerge.TypeImmerge.CONCOURS: "CC",
        Immerge.TypeImmerge.SELECTIONNE: "INT",
        Immerge.TypeImmerge.VOLONTAIRE: "VOL",
    }

    @staticmethod
    def annee_session(session):
        return int(getattr(session, "annee", None) or timezone.now().year)

    @staticmethod
    def numero_promotion_session(session):
        numero = getattr(session, "numero_promotion", None)
        if numero is None:
            annee = CodeFasoIMService.annee_session(session)
            numero = max(1, annee - 2024)
        return int(numero)

    @classmethod
    def generer_code(cls, *, session, type_immerge):
        prefixe = cls.PREFIXES.get(type_immerge)
        if not prefixe:
            raise ValidationMetierErreur({"type_immerge": "Type d'immergé non pris en charge."})

        annee = cls.annee_session(session)
        promotion = cls.numero_promotion_session(session)
        sequence = ImmergeRepository.actifs().filter(session=session, type_immerge=type_immerge).count() + 1

        while True:
            code = f"IP{annee}{prefixe}{promotion:02d}{sequence:05d}"
            if not ImmergeRepository.code_existe(code):
                return code
            sequence += 1

    @staticmethod
    def generer_qr_code(code_fasoim):
        # Pour l'instant on stocke le contenu textuel du QR. La génération image/PDF ira dans documents.
        return f"FASOIM:{code_fasoim}"

    @classmethod
    def generer_code_et_qr(cls, *, session, type_immerge):
        code = cls.generer_code(session=session, type_immerge=type_immerge)
        return code, cls.generer_qr_code(code)


class SourceImporteeServiceMixin:
    model = None
    repository = None
    identifiant_fields: tuple[str, ...] = ()

    @classmethod
    def nettoyer(cls, donnees):
        return NettoyageImmergeService.nettoyer_identite(donnees)

    @classmethod
    def creer(cls, **donnees):
        donnees = cls.nettoyer(donnees)
        objet = cls.model(**donnees)
        objet.full_clean()
        objet.save()
        return objet

    @classmethod
    def modifier(cls, objet, **donnees):
        donnees = cls.nettoyer(donnees)
        for champ, valeur in donnees.items():
            setattr(objet, champ, valeur)
        objet.full_clean()
        objet.save()
        return objet

    @classmethod
    def supprimer_logiquement(cls, objet):
        suffixe = BrouillageSuppressionService.suffixe(objet)
        champs_update = ["deleted_at", "updated_at"]
        for champ in cls.identifiant_fields:
            valeur = getattr(objet, champ, "")
            if valeur:
                field = objet._meta.get_field(champ)
                setattr(objet, champ, BrouillageSuppressionService.brouiller_valeur(valeur, suffixe, field.max_length))
                champs_update.append(champ)
        objet.deleted_at = timezone.now()
        objet.save(update_fields=champs_update)
        return objet


class ImmergeExamenService(SourceImporteeServiceMixin):
    model = ImmergeExamen
    repository = ImmergeExamenRepository
    identifiant_fields = ("numero_pv",)


class ImmergeConcoursService(SourceImporteeServiceMixin):
    model = ImmergeConcours
    repository = ImmergeConcoursRepository
    identifiant_fields = ("numero_recepisse",)


class ImmergeSelectionneService(SourceImporteeServiceMixin):
    model = ImmergeSelectionne
    repository = ImmergeSelectionneRepository
    identifiant_fields = ("matricule", "reference_selection")


class InscriptionVolontaireService:
    @staticmethod
    def generer_code_suivi(session):
        annee = int(getattr(session, "annee", None) or timezone.now().year)
        sequence = InscriptionVolontaireRepository.actifs().filter(session=session).count() + 1
        while True:
            code = f"VOL{annee}{sequence:06d}"
            if not InscriptionVolontaireRepository.code_suivi_existe(code):
                return code
            sequence += 1

    @staticmethod
    def creer(**donnees):
        donnees = NettoyageImmergeService.nettoyer_identite(donnees)
        session = donnees.get("session")
        if not donnees.get("code_suivi"):
            donnees["code_suivi"] = InscriptionVolontaireService.generer_code_suivi(session)
        inscription = InscriptionVolontaire(**donnees)
        inscription.full_clean()
        inscription.save()
        return inscription

    @staticmethod
    def modifier(inscription, **donnees):
        donnees = NettoyageImmergeService.nettoyer_identite(donnees)
        for champ, valeur in donnees.items():
            setattr(inscription, champ, valeur)
        inscription.full_clean()
        inscription.save()
        return inscription

    @staticmethod
    @transaction.atomic
    def accepter(inscription, *, acteur=None, motif_decision="", creer_immerge=True):
        inscription.statut_demande = InscriptionVolontaire.StatutDemande.ACCEPTEE
        inscription.date_decision = timezone.now()
        inscription.motif_decision = motif_decision or inscription.motif_decision
        inscription.traite_par = acteur
        inscription.full_clean()
        inscription.save(update_fields=["statut_demande", "date_decision", "motif_decision", "traite_par", "updated_at"])
        if creer_immerge:
            ImmergeService.creer_depuis_volontaire(inscription)
        return inscription

    @staticmethod
    def rejeter(inscription, *, acteur=None, motif_decision=""):
        inscription.statut_demande = InscriptionVolontaire.StatutDemande.REJETEE
        inscription.date_decision = timezone.now()
        inscription.motif_decision = motif_decision
        inscription.traite_par = acteur
        inscription.full_clean()
        inscription.save(update_fields=["statut_demande", "date_decision", "motif_decision", "traite_par", "updated_at"])
        return inscription

    @staticmethod
    def annuler(inscription, *, motif_decision=""):
        inscription.statut_demande = InscriptionVolontaire.StatutDemande.ANNULEE
        inscription.date_decision = timezone.now()
        inscription.motif_decision = motif_decision or inscription.motif_decision
        inscription.full_clean()
        inscription.save(update_fields=["statut_demande", "date_decision", "motif_decision", "updated_at"])
        return inscription

    @staticmethod
    def supprimer_logiquement(inscription):
        suffixe = BrouillageSuppressionService.suffixe(inscription)
        champs_update = ["deleted_at", "updated_at"]
        if inscription.code_suivi:
            inscription.code_suivi = BrouillageSuppressionService.brouiller_valeur(inscription.code_suivi, suffixe, 80)
            champs_update.append("code_suivi")
        inscription.deleted_at = timezone.now()
        inscription.save(update_fields=champs_update)
        return inscription


class ImmergeSourceResolverService:
    @staticmethod
    def construire(type_immerge, source):
        if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            session = source.import_officiel.session
        elif type_immerge == Immerge.TypeImmerge.CONCOURS:
            session = source.import_officiel.session
        elif type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            session = source.import_officiel.session
        elif type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            session = source.session
        else:
            raise ValidationMetierErreur({"type_immerge": "Type d'immergé non pris en charge."})
        return SourceCentralisation(type_immerge=type_immerge, origine_id=source.id, session=session)

    @staticmethod
    def recuperer(immerge):
        if immerge.type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            return ImmergeExamenRepository.get_by_id(immerge.origine_id)
        if immerge.type_immerge == Immerge.TypeImmerge.CONCOURS:
            return ImmergeConcoursRepository.get_by_id(immerge.origine_id)
        if immerge.type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            return ImmergeSelectionneRepository.get_by_id(immerge.origine_id)
        if immerge.type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            return InscriptionVolontaireRepository.get_by_id(immerge.origine_id)
        raise ValidationMetierErreur({"type_immerge": "Type d'immergé non pris en charge."})


class ImmergeService:
    @staticmethod
    @transaction.atomic
    def creer_depuis_source(*, type_immerge, source):
        contexte = ImmergeSourceResolverService.construire(type_immerge, source)
        existant = ImmergeRepository.actifs().filter(
            session=contexte.session,
            type_immerge=contexte.type_immerge,
            origine_id=contexte.origine_id,
        ).first()
        if existant:
            return existant

        code_fasoim, qr_code = CodeFasoIMService.generer_code_et_qr(
            session=contexte.session,
            type_immerge=contexte.type_immerge,
        )
        immerge = Immerge(
            session=contexte.session,
            type_immerge=contexte.type_immerge,
            origine_id=contexte.origine_id,
            code_fasoim=code_fasoim,
            qr_code=qr_code,
            statut=Immerge.Statut.CODE_GENERE,
            date_creation_code=timezone.now(),
        )
        immerge.full_clean()
        immerge.save()
        return immerge

    @staticmethod
    def creer_depuis_examen(examen):
        type_immerge = examen.type_examen if examen.type_examen in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC} else Immerge.TypeImmerge.BEPC
        return ImmergeService.creer_depuis_source(type_immerge=type_immerge, source=examen)

    @staticmethod
    def creer_depuis_concours(concours):
        return ImmergeService.creer_depuis_source(type_immerge=Immerge.TypeImmerge.CONCOURS, source=concours)

    @staticmethod
    def creer_depuis_selectionne(selectionne):
        return ImmergeService.creer_depuis_source(type_immerge=Immerge.TypeImmerge.SELECTIONNE, source=selectionne)

    @staticmethod
    def creer_depuis_volontaire(inscription):
        if inscription.statut_demande != InscriptionVolontaire.StatutDemande.ACCEPTEE:
            raise ValidationMetierErreur({"statut_demande": "Seule une inscription volontaire acceptée peut créer un immergé."})
        return ImmergeService.creer_depuis_source(type_immerge=Immerge.TypeImmerge.VOLONTAIRE, source=inscription)

    @staticmethod
    def changer_statut(immerge, statut):
        immerge.statut = statut
        immerge.full_clean()
        immerge.save(update_fields=["statut", "updated_at"])
        return immerge

    @staticmethod
    def generer_code_si_absent(immerge):
        if immerge.code_fasoim and immerge.qr_code:
            return immerge
        code_fasoim, qr_code = CodeFasoIMService.generer_code_et_qr(
            session=immerge.session,
            type_immerge=immerge.type_immerge,
        )
        return ImmergeRepository.marquer_code_genere(immerge, code_fasoim, qr_code)

    @staticmethod
    def supprimer_logiquement(immerge):
        suffixe = BrouillageSuppressionService.suffixe(immerge)
        champs_update = ["deleted_at", "updated_at"]
        if immerge.code_fasoim:
            immerge.code_fasoim = BrouillageSuppressionService.brouiller_valeur(immerge.code_fasoim, suffixe, 80)
            champs_update.append("code_fasoim")
        if immerge.qr_code:
            immerge.qr_code = BrouillageSuppressionService.brouiller_valeur(immerge.qr_code, suffixe, 255)
            champs_update.append("qr_code")
        immerge.deleted_at = timezone.now()
        immerge.save(update_fields=champs_update)
        return immerge
