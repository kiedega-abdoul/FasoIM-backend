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

class ImportVersImmergeService:
    """Pont métier entre imports_app et immerges.

    imports_app lit et valide les fichiers. Cette classe transforme ensuite les
    lignes valides en sources métier, puis crée la ligne centrale Immerge avec
    code FasoIM et contenu QR.
    """

    CHAMPS_COMMUNS_SOURCE = (
        "nom",
        "prenoms",
        "nom_et_prenoms",
        "sexe",
        "date_naissance",
        "lieu_naissance",
        "nationalite",
        "numero_cnib",
        "telephone",
        "email",
        "contact_urgence",
        "nom_contact_urgence",
    )
    CHAMPS_EXAMEN = CHAMPS_COMMUNS_SOURCE + (
        "numero_pv",
        "type_examen",
        "serie",
        "annee_obtention",
        "statut",
        "centre_examen",
        "etablissement_origine",
        "region_examen",
        "province_examen",
    )
    CHAMPS_CONCOURS = CHAMPS_COMMUNS_SOURCE + (
        "numero_recepisse",
        "specialite",
        "centre_composition",
        "region_composition",
        "province_composition",
    )
    CHAMPS_SELECTIONNE = CHAMPS_COMMUNS_SOURCE + (
        "matricule",
        "reference_selection",
        "structure_origine",
        "motif_selection",
        "region_structure",
        "province_structure",
    )
    CHAMPS_VOLONTAIRE = CHAMPS_COMMUNS_SOURCE + (
        "code_suivi",
        "region_residence",
        "province_residence",
        "commune_residence",
        "adresse_residence",
        "niveau_etude",
        "profession",
        "motivation",
    )

    @staticmethod
    def _donnees_ligne(ligne):
        donnees = dict(ligne.donnees_normalisees or {})
        if not donnees:
            donnees = dict(ligne.donnees_brutes or {})
        return donnees

    @staticmethod
    def _extraire(donnees, champs):
        return {champ: donnees.get(champ) for champ in champs if champ in donnees}

    @staticmethod
    def _base_source(import_officiel, ligne, donnees):
        return {
            "import_officiel": import_officiel,
            "numero_ligne_import": ligne.numero_ligne,
            "donnees_brutes": ligne.donnees_brutes or {},
            "donnees_normalisees": donnees,
        }

    @staticmethod
    def _creer_depuis_examen(import_officiel, ligne):
        donnees = ImportVersImmergeService._donnees_ligne(ligne)
        payload = ImportVersImmergeService._base_source(import_officiel, ligne, donnees)
        payload.update(ImportVersImmergeService._extraire(donnees, ImportVersImmergeService.CHAMPS_EXAMEN))

        type_source = str(import_officiel.type_source or "").upper()
        type_examen = str(payload.get("type_examen") or type_source or ImmergeExamen.TypeExamen.AUTRE).upper()
        if type_examen not in {ImmergeExamen.TypeExamen.BEPC, ImmergeExamen.TypeExamen.BAC, ImmergeExamen.TypeExamen.AUTRE}:
            type_examen = ImmergeExamen.TypeExamen.AUTRE
        payload["type_examen"] = type_examen
        payload["statut_validation"] = ImmergeExamen.StatutValidation.VALIDE

        source = ImmergeExamenService.creer(**payload)
        return source, ImmergeService.creer_depuis_examen(source)

    @staticmethod
    def _creer_depuis_concours(import_officiel, ligne):
        donnees = ImportVersImmergeService._donnees_ligne(ligne)
        payload = ImportVersImmergeService._base_source(import_officiel, ligne, donnees)
        payload.update(ImportVersImmergeService._extraire(donnees, ImportVersImmergeService.CHAMPS_CONCOURS))
        payload["statut_validation"] = ImmergeConcours.StatutValidation.VALIDE

        source = ImmergeConcoursService.creer(**payload)
        return source, ImmergeService.creer_depuis_concours(source)

    @staticmethod
    def _creer_depuis_selectionne(import_officiel, ligne):
        donnees = ImportVersImmergeService._donnees_ligne(ligne)
        payload = ImportVersImmergeService._base_source(import_officiel, ligne, donnees)
        payload.update(ImportVersImmergeService._extraire(donnees, ImportVersImmergeService.CHAMPS_SELECTIONNE))
        payload["statut_validation"] = ImmergeSelectionne.StatutValidation.VALIDE

        source = ImmergeSelectionneService.creer(**payload)
        return source, ImmergeService.creer_depuis_selectionne(source)

    @staticmethod
    def _creer_depuis_volontaire(import_officiel, ligne, *, confirme_par=None):
        donnees = ImportVersImmergeService._donnees_ligne(ligne)
        payload = ImportVersImmergeService._extraire(donnees, ImportVersImmergeService.CHAMPS_VOLONTAIRE)
        payload.update(
            {
                "session": import_officiel.session,
                "statut_demande": InscriptionVolontaire.StatutDemande.ACCEPTEE,
                "date_decision": timezone.now(),
                "motif_decision": "Volontaire accepté par import officiel confirmé.",
                "donnees_brutes": ligne.donnees_brutes or {},
            }
        )

        source = InscriptionVolontaireService.creer(**payload)
        return source, ImmergeService.creer_depuis_volontaire(source)

    @staticmethod
    def _creer_source_et_immerge(import_officiel, ligne, *, confirme_par=None):
        from imports_app.models import ImportOfficiel

        type_source = import_officiel.type_source
        if type_source in {ImportOfficiel.TypeSource.BEPC, ImportOfficiel.TypeSource.BAC}:
            return ImportVersImmergeService._creer_depuis_examen(import_officiel, ligne)
        if type_source == ImportOfficiel.TypeSource.CONCOURS:
            return ImportVersImmergeService._creer_depuis_concours(import_officiel, ligne)
        if type_source == ImportOfficiel.TypeSource.SELECTIONNES:
            return ImportVersImmergeService._creer_depuis_selectionne(import_officiel, ligne)
        if type_source == ImportOfficiel.TypeSource.VOLONTAIRES_ACCEPTES:
            return ImportVersImmergeService._creer_depuis_volontaire(import_officiel, ligne, confirme_par=confirme_par)
        raise ValidationMetierErreur({"type_source": "Type de source non pris en charge pour la confirmation."})

    @staticmethod
    @transaction.atomic
    def confirmer_import(import_id, *, confirme_par=None):
        from imports_app.models import ImportOfficiel, LigneImport
        from imports_app.repository import ImportOfficielRepository, LigneImportRepository

        import_officiel = ImportOfficielRepository.get_by_id_pour_update(import_id)
        if not import_officiel:
            raise ValidationMetierErreur({"import": "Import officiel introuvable."})
        if not import_officiel.peut_etre_confirme:
            raise ValidationMetierErreur({"statut": "Cet import n'est pas prêt pour la confirmation."})

        lignes_valides = list(
            LigneImportRepository.lister_valides(import_officiel)
            .select_for_update()
            .order_by("numero_ligne")
        )
        if not lignes_valides:
            raise ValidationMetierErreur({"lignes": "Aucune ligne valide à confirmer."})

        import_officiel.statut = ImportOfficiel.Statut.CONFIRMATION_EN_COURS
        import_officiel.date_confirmation = timezone.now()
        import_officiel.confirme_par = confirme_par
        import_officiel.message_erreur = ""
        import_officiel.save(update_fields=["statut", "date_confirmation", "confirme_par", "message_erreur", "updated_at"])

        total_importees = 0
        total_erreurs = 0
        lignes_a_mettre_a_jour = []

        for ligne in lignes_valides:
            try:
                _, immerge = ImportVersImmergeService._creer_source_et_immerge(
                    import_officiel,
                    ligne,
                    confirme_par=confirme_par,
                )
                ligne.statut = LigneImport.Statut.IMPORTEE
                ligne.message_statut = f"Importée dans FasoIM avec le code {immerge.code_fasoim}."
                total_importees += 1
            except ValidationError as erreur:
                ligne.statut = LigneImport.Statut.ERREUR
                ligne.message_statut = str(erreur.message_dict if hasattr(erreur, "message_dict") else erreur.messages)
                total_erreurs += 1
            ligne.updated_at = timezone.now()
            lignes_a_mettre_a_jour.append(ligne)

        LigneImportRepository.mettre_a_jour_en_masse(
            lignes_a_mettre_a_jour,
            ["statut", "message_statut", "updated_at"],
        )
        ImportOfficielRepository.mettre_a_jour_statistiques(import_officiel)
        import_officiel = ImportOfficielRepository.get_by_id_pour_update(import_id)

        if total_erreurs:
            import_officiel.statut = ImportOfficiel.Statut.VALIDE_AVEC_ERREURS
            import_officiel.message_erreur = f"Confirmation partielle : {total_importees} ligne(s) importée(s), {total_erreurs} ligne(s) en erreur."
            champs = ["statut", "message_erreur", "updated_at"]
        else:
            import_officiel.statut = ImportOfficiel.Statut.TERMINE
            import_officiel.message_erreur = ""
            import_officiel.date_fin_traitement = timezone.now()
            champs = ["statut", "message_erreur", "date_fin_traitement", "updated_at"]

        import_officiel.confirme_par = confirme_par
        if not import_officiel.date_confirmation:
            import_officiel.date_confirmation = timezone.now()
        import_officiel.save(update_fields=[*champs, "confirme_par", "date_confirmation"])

        return {
            "import_officiel": import_officiel,
            "lignes_traitees": len(lignes_valides),
            "lignes_importees": total_importees,
            "lignes_erreur": total_erreurs,
        }

