from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import mimetypes
import os
import textwrap
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import qrcode
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string
from django.db.models import Count, Q, Sum
from django.utils import timezone
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from weasyprint import HTML
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounts.models import Acteur, AffectationActeur, AffectationRole
from accounts.service import ControleAccesService
from activites.models import Evaluation, Note, Presence, Seance
from activites.repository import (
    CandidatActiviteRepository,
    EvaluationRepository,
    PresenceRepository,
)
from activites.service import NoteService, PresenceService
from affectations.models import AffectationCentre, AffectationRegionale, CentreImmersion
from audit.models import JournalAction
from audit.service import JournalActionService
from imports_app.models import ErreurImport, ImportOfficiel, LigneImport
from immerges.models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)
from immerges.service import ImmergeSourceResolverService
from incidents.models import AlerteIncident
from incidents.repository import AlerteIncidentRepository
from kits.models import ArticleKit, RemiseKit
from kits.repository import RemiseKitRepository
from kits.service import ArticleKitService
from notifications.service import NotificationService, TypesMessage
from organisation.models import (
    AffectationGroupe,
    AttributionLit,
    RegleOrganisationCentre,
)
from organisation.service import HebergementService
from repas.models import DemandeRavitaillementCentre, RepasJournalier, SuiviRepas
from repas.repository import RepasJournalierRepository
from sante.models import VisiteMedicale
from sante.repository import VisiteMedicaleRepository
from sessions_app.models import SessionImmersion

from .models import DocumentGenere, PublicationOfficielle, ResultatFinal
from .repository import (
    DocumentGenereRepository,
    PublicationOfficielleRepository,
    ResultatFinalRepository,
)


class ValidationDocumentsErreur(ValidationError):
    """Erreur métier du module documents."""


@dataclass
class EtatCloture:
    session_id: int
    cloturable: bool = True
    blocages: list[dict] = field(default_factory=list)
    resume: dict = field(default_factory=dict)

    def ajouter(self, module: str, code: str, message: str, total: int | None = None):
        self.cloturable = False
        blocage = {"module": module, "code": code, "message": message}
        if total is not None:
            blocage["total"] = int(total)
        self.blocages.append(blocage)

    def en_dict(self):
        return asdict(self)


class ControleAccesDocumentsService:
    STATUTS_SESSION_FERMEE = {
        SessionImmersion.Statut.TERMINEE,
        SessionImmersion.Statut.ARCHIVEE,
        SessionImmersion.Statut.ANNULEE,
    }

    @classmethod
    def verifier_session_traitable(cls, session):
        if session.deleted_at is not None:
            raise ValidationDocumentsErreur("La session est supprimée.")
        if session.statut in cls.STATUTS_SESSION_FERMEE:
            raise ValidationDocumentsErreur(
                "Aucune nouvelle opération documentaire n'est autorisée sur une session terminée, archivée ou annulée."
            )
        return True

    @staticmethod
    def exiger(acteur, code_permission, *, session_id=None, region_code=None, centre_id=None):
        if acteur is None:
            raise ValidationDocumentsErreur("Un acteur authentifié est obligatoire.")
        if getattr(acteur, "is_superuser", False):
            return True
        resultat = ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=session_id,
            region_code=region_code,
            centre_id=centre_id,
        )
        if not resultat.autorise:
            raise ValidationDocumentsErreur(resultat.motif or "Permission documents absente ou hors périmètre.")
        return True


class IdentiteImmergeService:
    """Résout l'identité sans la dupliquer dans la table centrale."""

    @staticmethod
    def source(immerge):
        return ImmergeSourceResolverService.recuperer(immerge)

    @staticmethod
    def _valeur(source, *noms, defaut=""):
        for nom in noms:
            valeur = getattr(source, nom, None)
            if valeur not in (None, ""):
                return valeur
        return defaut

    @classmethod
    def donnees(cls, immerge):
        source = cls.source(immerge)
        nom = cls._valeur(source, "nom")
        prenoms = cls._valeur(source, "prenoms")
        nom_complet = cls._valeur(source, "nom_et_prenoms") or " ".join(
            str(x).strip() for x in (nom, prenoms) if str(x or "").strip()
        )
        identifiant_origine = ""
        if isinstance(source, ImmergeExamen):
            identifiant_origine = source.numero_pv
        elif isinstance(source, ImmergeConcours):
            identifiant_origine = source.numero_recepisse
        elif isinstance(source, ImmergeSelectionne):
            identifiant_origine = source.matricule or source.reference_selection
        elif isinstance(source, InscriptionVolontaire):
            identifiant_origine = source.code_suivi
        return {
            "nom": str(nom or ""),
            "prenoms": str(prenoms or ""),
            "nom_complet": str(nom_complet or "").strip(),
            "sexe": str(cls._valeur(source, "sexe")),
            "date_naissance": cls._valeur(source, "date_naissance", defaut=None),
            "lieu_naissance": str(cls._valeur(source, "lieu_naissance")),
            "email": str(cls._valeur(source, "email")),
            "telephone": str(cls._valeur(source, "telephone")),
            "identifiant_origine": str(identifiant_origine or ""),
            "type_immerge": immerge.type_immerge,
            "code_fasoim": immerge.code_fasoim,
        }

    @classmethod
    def rechercher_public(cls, *, code_fasoim="", type_immerge="", identifiant="", session_code="", date_naissance=None):
        code_fasoim = str(code_fasoim or "").strip()
        if code_fasoim:
            return Immerge.objects.filter(
                code_fasoim__iexact=code_fasoim,
                deleted_at__isnull=True,
            ).select_related("session", "session__parametres").first()

        type_immerge = str(type_immerge or "").strip().upper()
        identifiant = str(identifiant or "").strip()
        session_code = str(session_code or "").strip()
        if not type_immerge or not identifiant or not session_code or not date_naissance:
            raise ValidationDocumentsErreur(
                "Le type, l'identifiant, le code de session et la date de naissance sont obligatoires."
            )
        session = SessionImmersion.objects.filter(
            code__iexact=session_code,
            deleted_at__isnull=True,
        ).select_related("parametres").first()
        if session is None:
            return None

        source = None
        if type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            source = ImmergeExamen.objects.filter(
                import_officiel__session=session,
                type_examen=type_immerge,
                numero_pv__iexact=identifiant,
                date_naissance=date_naissance,
                deleted_at__isnull=True,
            ).first()
        elif type_immerge == Immerge.TypeImmerge.CONCOURS:
            source = ImmergeConcours.objects.filter(
                import_officiel__session=session,
                numero_recepisse__iexact=identifiant,
                date_naissance=date_naissance,
                deleted_at__isnull=True,
            ).first()
        elif type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            source = ImmergeSelectionne.objects.filter(
                import_officiel__session=session,
                date_naissance=date_naissance,
                deleted_at__isnull=True,
            ).filter(
                Q(matricule__iexact=identifiant)
                | Q(reference_selection__iexact=identifiant)
                | Q(email__iexact=identifiant)
            ).first()
        elif type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            source = InscriptionVolontaire.objects.filter(
                session=session,
                date_naissance=date_naissance,
                deleted_at__isnull=True,
            ).filter(Q(code_suivi__iexact=identifiant) | Q(email__iexact=identifiant)).first()
        if source is None:
            return None
        return Immerge.objects.filter(
            session=session,
            type_immerge=type_immerge,
            origine_id=source.id,
            deleted_at__isnull=True,
        ).select_related("session", "session__parametres").first()


class InformationsArriveeService:
    @staticmethod
    def _cle_ip(adresse_ip, usage="arrivee"):
        empreinte = hashlib.sha256(str(adresse_ip or "inconnue").encode()).hexdigest()[:24]
        usage = "".join(c for c in str(usage or "public") if c.isalnum() or c in "_-")[:40]
        return f"documents:public:{usage}:{empreinte}"

    @classmethod
    def verifier_limite(cls, adresse_ip, *, usage="arrivee"):
        limite = int(getattr(settings, "DOCUMENTS_PUBLIC_RATE_LIMIT", 20))
        fenetre = int(getattr(settings, "DOCUMENTS_PUBLIC_RATE_WINDOW_SECONDS", 900))
        cle = cls._cle_ip(adresse_ip, usage=usage)
        try:
            valeur = cache.get(cle)
            if valeur is None:
                cache.set(cle, 1, fenetre)
                return
            valeur = int(valeur)
            if valeur >= limite:
                raise ValidationDocumentsErreur("Trop de tentatives. Réessayez plus tard.")
            cache.incr(cle)
        except ValidationDocumentsErreur:
            raise
        except Exception:
            # Redis ne doit pas rendre la consultation officielle indisponible.
            return

    @staticmethod
    def _affectation_active(immerge):
        return (
            AffectationCentre.objects.select_related(
                "session",
                "session__parametres",
                "centre",
                "centre__region",
                "affectation_regionale",
            )
            .filter(
                immerge=immerge,
                session=immerge.session,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            .first()
        )

    @classmethod
    def construire(cls, immerge, *, journaliser=True, request=None):
        session = immerge.session
        parametres = getattr(session, "parametres", None)
        if not parametres or not parametres.consultation_publique_active:
            raise ValidationDocumentsErreur("La consultation publique n'est pas activée pour cette session.")
        affectation = cls._affectation_active(immerge)
        if affectation is None:
            raise ValidationDocumentsErreur("Aucune affectation centre active n'est disponible.")
        publication = PublicationOfficielleRepository.publication_active_centre(
            session_id=session.id,
            centre_id=affectation.centre_id,
            type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
        )
        if publication is None:
            raise ValidationDocumentsErreur("Les informations d'arrivée ne sont pas encore publiées.")
        regle = RegleOrganisationCentre.objects.filter(
            session=session,
            centre=affectation.centre,
            statut=RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
            deleted_at__isnull=True,
        ).first()
        if regle is None:
            raise ValidationDocumentsErreur("L'organisation du centre n'est pas prête pour consultation.")

        identite = IdentiteImmergeService.donnees(immerge)
        affectation_groupe = (
            AffectationGroupe.objects.select_related("groupe", "groupe__section")
            .filter(
                affectation_centre=affectation,
                statut=AffectationGroupe.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            .first()
        )
        attribution_lit = None
        if parametres.hebergement_active:
            attribution_lit = (
                AttributionLit.objects.select_related("lit", "lit__dortoir")
                .filter(
                    affectation_centre=affectation,
                    statut=AttributionLit.Statut.ACTIVE,
                    deleted_at__isnull=True,
                )
                .first()
            )

        kits = ArticleKitService.articles_pour_immerge(
            session_id=session.id,
            centre_id=affectation.centre_id,
        )["a_apporter"]
        articles = [
            {
                "designation": article.designation,
                "description": article.description,
                "quantite": article.quantite,
                "unite": article.unite,
                "obligatoire": article.obligatoire,
            }
            for article in kits
        ]
        donnees = {
            "publication": {
                "reference": publication.reference,
                "version": publication.version,
                "date_publication": publication.date_publication,
            },
            "immerge": {
                "nom_complet": identite["nom_complet"],
                "code_fasoim": immerge.code_fasoim,
                "type_immerge": immerge.type_immerge,
                "qr_code": immerge.qr_code,
            },
            "session": {
                "nom": session.nom,
                "code": session.code,
                "annee": session.annee,
                "date_debut": session.date_debut,
                "date_fin": session.date_fin,
                "directives_generales": parametres.directives_generales,
                "consignes_generales": parametres.consignes_generales,
                "documents_exiges": parametres.documents_exiges,
            },
            "affectation": {
                "region": affectation.centre.region.nom,
                "centre": affectation.centre.nom,
                "code_centre": affectation.centre.code,
                "province": affectation.centre.province,
                "ville": affectation.centre.ville,
                "adresse": affectation.centre.adresse,
                "lieu_accueil": regle.lieu_accueil,
                "heure_accueil": regle.heure_accueil,
                "horaires_generaux": regle.horaires_generaux,
                "section": (
                    affectation_groupe.groupe.section.nom if affectation_groupe else None
                ),
                "groupe": affectation_groupe.groupe.nom if affectation_groupe else None,
            },
            "hebergement": None,
            "consignes_centre": {
                "accueil": regle.consignes_accueil,
                "hebergement": regle.consignes_hebergement if parametres.hebergement_active else "",
                "kits_a_apporter": regle.consignes_kits_a_apporter,
                "repas": regle.consignes_repas if parametres.repas_active else "",
                "discipline": regle.regles_discipline,
                "directives_locales": regle.directives_locales,
            },
            "kits_a_apporter": articles,
        }
        if parametres.hebergement_active:
            donnees["hebergement"] = {
                "dortoir": attribution_lit.lit.dortoir.nom if attribution_lit else None,
                "lit": attribution_lit.lit.numero_lit if attribution_lit else None,
            }

        if journaliser:
            JournalActionService.journaliser_consultation_immerge(
                immerge=immerge,
                session=session,
                region=affectation.centre.region,
                centre=affectation.centre,
                code_action="consulter_affectation_publique",
                resultat=JournalAction.Resultat.SUCCES,
                motif="Informations d'arrivée consultées.",
                informations_consultees=[
                    "session", "region", "centre", "section", "groupe",
                    "hebergement", "consignes", "kits_a_apporter",
                ],
                request=request,
            )
        return donnees


class DocumentArriveeService:
    """Génère la fiche PDF d'arrivée à partir des données déjà publiées."""

    @classmethod
    @transaction.atomic
    def generer_fiche(cls, *, immerge_id, acteur):
        immerge = Immerge.objects.select_related(
            "session", "session__parametres"
        ).get(id=immerge_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(immerge.session)
        affectation = InformationsArriveeService._affectation_active(immerge)
        if affectation is None:
            raise ValidationDocumentsErreur("Aucune affectation centre active n'est disponible.")
        ControleAccesDocumentsService.exiger(
            acteur,
            "consulter_documents",
            session_id=immerge.session_id,
            region_code=affectation.centre.region.code,
            centre_id=affectation.centre_id,
        )
        donnees = InformationsArriveeService.construire(
            immerge, journaliser=False
        )
        reference = donnees["publication"]["reference"]
        cle = f"FICHE_ARRIVEE:{reference}:{immerge.id}"
        existant = DocumentGenere.objects.filter(
            cle_generation=cle,
            deleted_at__isnull=True,
        ).exclude(statut=DocumentGenere.Statut.ECHEC).first()
        if existant:
            return existant

        document = DocumentGenere(
            type_document=DocumentGenere.TypeDocument.FICHE_ARRIVEE,
            format_fichier=DocumentGenere.Format.PDF,
            titre=f"Fiche d'arrivée - {immerge.code_fasoim}",
            cle_generation=cle,
            session=immerge.session,
            region=affectation.centre.region,
            centre=affectation.centre,
            immerge=immerge,
            affectation_centre=affectation,
            statut=DocumentGenere.Statut.EN_GENERATION,
            visibilite=DocumentGenere.Visibilite.IMMERGE_CONCERNE,
            genere_par=acteur,
            parametres_generation={"publication_reference": reference},
            donnees_figees={
                "code_fasoim": immerge.code_fasoim,
                "session": donnees["session"]["nom"],
                "centre": donnees["affectation"]["centre"],
                "publication_reference": reference,
            },
        )
        document.save()
        sections = [
            ("Immergé", donnees["immerge"]),
            ("Session", donnees["session"]),
            ("Affectation et accueil", donnees["affectation"]),
            ("Hébergement", donnees["hebergement"] or {"applicable": False}),
            ("Consignes du centre", donnees["consignes_centre"]),
            ("Articles à apporter", donnees["kits_a_apporter"]),
        ]
        try:
            contenu = GenerationFichierService.pdf_rapport(
                titre=document.titre, sections=sections
            )
            document.statut = DocumentGenere.Statut.GENERE
            document.resume_generation = {
                "publication_reference": reference,
                "articles_a_apporter": len(donnees["kits_a_apporter"]),
            }
            GenerationFichierService.enregistrer(document, contenu, extension="pdf")
        except Exception as exc:
            document.statut = DocumentGenere.Statut.ECHEC
            document.message_erreur = str(exc)
            document.save(update_fields=["statut", "message_erreur", "updated_at"])
            raise
        JournalActionService.journaliser_succes(
            acteur=acteur,
            session=immerge.session,
            region=affectation.centre.region,
            centre=affectation.centre,
            immerge=immerge,
            code_action="generer_fiche_arrivee",
            module_source="documents",
            objet=document,
            motif="Fiche d'arrivée générée.",
            contexte={"publication_reference": reference},
        )
        return document


class CentreCertificationService:
    """Vérifie la fin des opérations d'un centre avant les attestations."""

    @classmethod
    def verifier(cls, *, session, centre):
        blocages = []
        affectations = AffectationCentre.objects.filter(
            session=session,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )
        total = affectations.count()
        if total == 0:
            return {"pret": True, "total_immerges": 0, "blocages": []}
        if timezone.localdate() < session.date_fin:
            blocages.append({"code": "DATE_FIN_NON_ATTEINTE", "message": "La date de fin de la session n'est pas atteinte."})

        regle = RegleOrganisationCentre.objects.filter(
            session=session,
            centre=centre,
            deleted_at__isnull=True,
        ).first()
        if regle is None or regle.statut != RegleOrganisationCentre.Statut.PRETE_PUBLICATION:
            blocages.append({
                "code": "ORGANISATION_NON_FINALISEE",
                "message": "L'organisation du centre n'est pas finalisée.",
            })

        publication_arrivee = PublicationOfficielleRepository.publication_active_centre(
            session_id=session.id,
            centre_id=centre.id,
            type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
        )
        if publication_arrivee is None:
            blocages.append({
                "code": "INFORMATIONS_ARRIVEE_NON_PUBLIEES",
                "message": "Les informations avant l'arrivée ne sont pas encore publiées pour ce centre.",
            })

        non_liberes = affectations.exclude(
            immerge__statut=Immerge.Statut.LIBERE
        ).count()
        if non_liberes:
            blocages.append({
                "code": "IMMERGES_NON_LIBERES",
                "message": "Des immergés du centre ne sont pas encore libérés.",
                "total": non_liberes,
            })

        parametres = session.parametres
        if parametres.activites_active:
            seances = Seance.objects.filter(
                session=session, centre=centre, deleted_at__isnull=True
            ).exclude(statut__in=[Seance.Statut.ANNULEE, Seance.Statut.REPORTEE])
            if not seances.exists():
                blocages.append({
                    "code": "AUCUNE_SEANCE",
                    "message": "Aucune séance exploitable n'est enregistrée pour le centre.",
                })
            seances_incompletes = seances.exclude(
                statut_feuille_presence=Seance.StatutFeuillePresence.CLOTUREE
            ).count()
            if seances_incompletes:
                blocages.append({"code": "PRESENCES_NON_CLOTUREES", "message": "Des feuilles de présence ne sont pas clôturées.", "total": seances_incompletes})

        if parametres.evaluation_active:
            evaluations = Evaluation.objects.filter(
                session=session, centre=centre, deleted_at__isnull=True
            ).exclude(statut=Evaluation.Statut.ANNULEE)
            if not evaluations.exists():
                blocages.append({
                    "code": "AUCUNE_EVALUATION",
                    "message": "Aucune évaluation exploitable n'est enregistrée pour le centre.",
                })
            evaluations_incompletes = evaluations.exclude(
                statut=Evaluation.Statut.CLOTUREE
            ).count()
            if evaluations_incompletes:
                blocages.append({"code": "EVALUATIONS_NON_CLOTUREES", "message": "Des évaluations ne sont pas clôturées.", "total": evaluations_incompletes})

        if parametres.visite_medicale_active:
            visites_valides = VisiteMedicaleRepository.validees().filter(
                session=session,
                centre=centre,
                statut_application=VisiteMedicale.StatutApplication.APPLIQUEE,
            ).values("affectation_centre_id").distinct().count()
            if visites_valides != total:
                blocages.append({"code": "VISITES_MEDICALES_INCOMPLETES", "message": "Toutes les visites médicales ne sont pas validées et appliquées.", "total": total - visites_valides})

        articles_remettre = ArticleKit.objects.filter(
            session=session,
            statut=ArticleKit.Statut.ACTIF,
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
            deleted_at__isnull=True,
        ).filter(Q(centre__isnull=True) | Q(centre=centre))
        nb_articles = articles_remettre.count()
        if nb_articles:
            remises_finales = RemiseKit.objects.filter(
                affectation_centre__in=affectations,
                article_kit__in=articles_remettre,
                deleted_at__isnull=True,
                statut_remise__in=[
                    RemiseKit.StatutRemise.REMIS,
                    RemiseKit.StatutRemise.REMPLACE,
                    RemiseKit.StatutRemise.DISPENSE,
                ],
            ).count()
            attendu = total * nb_articles
            if remises_finales < attendu:
                blocages.append({"code": "REMISES_KITS_INCOMPLETES", "message": "Les remises de kits ne sont pas terminées.", "total": attendu - remises_finales})

        if parametres.hebergement_active:
            propositions_lits = AttributionLit.objects.filter(
                affectation_centre__in=affectations,
                statut=AttributionLit.Statut.PROPOSEE,
                deleted_at__isnull=True,
            ).count()
            if propositions_lits:
                blocages.append({
                    "code": "PROPOSITIONS_LITS_EN_ATTENTE",
                    "message": "Des propositions de lit restent à traiter.",
                    "total": propositions_lits,
                })

            lits_a_reorganiser = AttributionLit.objects.filter(
                affectation_centre__in=affectations,
                statut=AttributionLit.Statut.A_REORGANISER,
                deleted_at__isnull=True,
            ).count()
            if lits_a_reorganiser:
                blocages.append({
                    "code": "LITS_A_REORGANISER",
                    "message": (
                        "Des attributions de lit doivent encore être "
                        "réorganisées."
                    ),
                    "total": lits_a_reorganiser,
                })

        # Le suivi de l'alimentation reste opérationnel et traçable,
        # mais il ne bloque jamais la finalisation du centre.

        incidents = AlerteIncident.objects.filter(
            session=session,
            deleted_at__isnull=True,
            statut__in=AlerteIncident.STATUTS_OUVERTS,
            est_bloquante=True,
        ).filter(Q(centre=centre) | Q(affectation_centre__centre=centre)).distinct().count()
        if incidents:
            blocages.append({"code": "INCIDENTS_BLOQUANTS", "message": "Des incidents bloquants restent ouverts.", "total": incidents})

        return {"pret": not blocages, "total_immerges": total, "blocages": blocages}


class EligibiliteAttestationService:
    @staticmethod
    def _groupe_actif(affectation):
        affectation_groupe = AffectationGroupe.objects.select_related(
            "groupe", "groupe__section"
        ).filter(
            affectation_centre=affectation,
            statut=AffectationGroupe.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).first()
        return affectation_groupe.groupe if affectation_groupe else None

    @staticmethod
    def _cible_applicable(*, groupe, groupe_id=None, section_id=None):
        if groupe_id:
            return bool(groupe and groupe.id == groupe_id)
        if section_id:
            return bool(groupe and groupe.section_id == section_id)
        return True

    @classmethod
    def _seances_applicables(cls, affectation):
        groupe = cls._groupe_actif(affectation)
        seances = Seance.objects.filter(
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
            deleted_at__isnull=True,
        ).exclude(
            statut__in=[Seance.Statut.ANNULEE, Seance.Statut.REPORTEE]
        ).only("id", "groupe_id", "section_id", "statut_feuille_presence")
        return [
            seance for seance in seances
            if cls._cible_applicable(
                groupe=groupe,
                groupe_id=seance.groupe_id,
                section_id=seance.section_id,
            )
        ]

    @classmethod
    def _evaluations_applicables(cls, affectation):
        groupe = cls._groupe_actif(affectation)
        evaluations = EvaluationRepository.actives().filter(
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
        ).select_related("seance").exclude(statut=Evaluation.Statut.ANNULEE)
        applicables = []
        for evaluation in evaluations:
            seance = evaluation.seance if evaluation.seance_id else None
            if seance is None or cls._cible_applicable(
                groupe=groupe,
                groupe_id=seance.groupe_id,
                section_id=seance.section_id,
            ):
                applicables.append(evaluation)
        return applicables

    @classmethod
    def calculer(cls, *, affectation, acteur=None):
        session = affectation.session
        parametres = session.parametres
        motifs_verification = []
        motifs_non_eligibilite = []

        presence = PresenceService.calculer_taux_presence(
            affectation_centre_id=affectation.id,
            session_id=session.id,
            acteur=acteur,
            verifier_acces=False,
        )
        if parametres.activites_active:
            seances_applicables = cls._seances_applicables(affectation)
            seances_cloturees = [
                seance for seance in seances_applicables
                if seance.statut_feuille_presence
                == Seance.StatutFeuillePresence.CLOTUREE
            ]
            if not seances_applicables or presence["total_eligible"] == 0:
                motifs_verification.append("AUCUNE_SEANCE_PRESENCE_EXPLOITABLE")
            if len(seances_cloturees) != len(seances_applicables):
                motifs_verification.append("FEUILLES_PRESENCE_NON_CLOTUREES")
            if presence["total_seances"] != len(seances_cloturees):
                motifs_verification.append("PRESENCES_INCOMPLETES")
            if presence["total_eligible"] > 0 and not presence["seuil_atteint"]:
                motifs_non_eligibilite.append("TAUX_PRESENCE_INSUFFISANT")

        moyenne = None
        evaluations_applicables = []
        evaluations_cloturees = 0
        notes_comptees = 0
        absences_eval = 0
        dispenses_eval = 0
        somme_coefficients = Decimal("0.00")
        if parametres.evaluation_active:
            evaluations_applicables = cls._evaluations_applicables(affectation)
            evaluations_cloturees = sum(
                1 for evaluation in evaluations_applicables
                if evaluation.statut == Evaluation.Statut.CLOTUREE
            )
            if not evaluations_applicables:
                motifs_verification.append("AUCUNE_EVALUATION_APPLICABLE")
            elif evaluations_cloturees != len(evaluations_applicables):
                motifs_verification.append("EVALUATIONS_NON_CLOTUREES")
            evaluation_ids = [e.id for e in evaluations_applicables if e.statut == Evaluation.Statut.CLOTUREE]
            notes_ids = set(
                Note.objects.filter(
                    affectation_centre=affectation,
                    evaluation_id__in=evaluation_ids,
                    deleted_at__isnull=True,
                    statut_note__in=[Note.StatutNote.NOTEE, Note.StatutNote.ABSENT, Note.StatutNote.DISPENSE],
                ).values_list("evaluation_id", flat=True)
            )
            if len(notes_ids) != len(evaluation_ids):
                motifs_verification.append("NOTES_EVALUATIONS_INCOMPLETES")
            calcul_moyenne = NoteService.calculer_moyenne(
                affectation_centre_id=affectation.id,
                session_id=session.id,
                acteur=acteur,
                verifier_acces=False,
            )
            moyenne = calcul_moyenne["moyenne_sur_20"]
            notes_comptees = calcul_moyenne["notes_comptees"]
            absences_eval = calcul_moyenne["absences"]
            dispenses_eval = calcul_moyenne["dispenses"]
            somme_coefficients = calcul_moyenne["somme_coefficients"]
            if notes_comptees == 0:
                motifs_verification.append("AUCUNE_NOTE_COMPTEE")
            elif moyenne < parametres.moyenne_minimum_attestation:
                motifs_non_eligibilite.append("MOYENNE_INSUFFISANTE")

        statut_medical = "VISITE_NON_REQUISE"
        participation_autorisee = True
        if parametres.visite_medicale_active:
            visite = VisiteMedicaleRepository.get_courante_par_affectation(affectation.id)
            if not visite or visite.statut != VisiteMedicale.Statut.VALIDEE:
                statut_medical = "EN_ATTENTE_VISITE"
                participation_autorisee = False
                motifs_verification.append("VISITE_MEDICALE_NON_VALIDEE")
            else:
                statut_medical = visite.resultat
                participation_autorisee = visite.resultat in VisiteMedicale.RESULTATS_AUTORISANT_IMMERSION
                if not participation_autorisee:
                    motifs_non_eligibilite.append("INAPTITUDE_MEDICALE")

        incident_bloquant = AlerteIncident.objects.filter(
            session=session,
            affectation_centre=affectation,
            est_bloquante=True,
            statut__in=AlerteIncident.STATUTS_OUVERTS,
            deleted_at__isnull=True,
        ).exists()
        if incident_bloquant:
            motifs_verification.append("INCIDENT_BLOQUANT_OUVERT")

        if affectation.immerge.statut == Immerge.Statut.ANNULE:
            motifs_non_eligibilite.append("IMMERGE_ANNULE")
        elif affectation.immerge.statut != Immerge.Statut.LIBERE:
            motifs_verification.append("IMMERSION_NON_LIBEREE")

        if motifs_verification:
            decision = ResultatFinal.Decision.A_VERIFIER
            motifs = list(dict.fromkeys(motifs_verification + motifs_non_eligibilite))
        elif motifs_non_eligibilite:
            decision = ResultatFinal.Decision.NON_ELIGIBLE
            motifs = list(dict.fromkeys(motifs_non_eligibilite))
        else:
            decision = ResultatFinal.Decision.ELIGIBLE
            motifs = []

        donnees = {
            "session": session,
            "region": affectation.centre.region,
            "centre": affectation.centre,
            "affectation_centre": affectation,
            "immerge": affectation.immerge,
            "total_seances": presence["total_seances"],
            "total_eligible_presence": presence["total_eligible"],
            "presences_favorables": presence["favorables"],
            "presents": presence["presents"],
            "retards": presence["retards"],
            "absences": presence["absences"],
            "excuses": presence["excuses"],
            "dispenses_presence": presence["dispenses"],
            "taux_presence": presence["taux_presence"],
            "seuil_presence": presence["seuil_attestation"],
            "evaluation_active": parametres.evaluation_active,
            "evaluations_applicables": len(evaluations_applicables),
            "evaluations_cloturees": evaluations_cloturees,
            "notes_comptees": notes_comptees,
            "absences_evaluation": absences_eval,
            "dispenses_evaluation": dispenses_eval,
            "somme_coefficients": somme_coefficients,
            "moyenne_sur_20": moyenne,
            "seuil_moyenne_sur_20": parametres.moyenne_minimum_attestation,
            "visite_medicale_active": parametres.visite_medicale_active,
            "statut_medical_administratif": statut_medical,
            "participation_medicale_autorisee": participation_autorisee,
            "incident_bloquant": incident_bloquant,
            "decision": decision,
            "motifs": motifs,
            "details_calcul": {
                "presence_complete": not any(m.startswith("AUCUNE_SEANCE") for m in motifs_verification),
                "evaluations_completes": not any(m in {"EVALUATIONS_NON_CLOTUREES", "NOTES_EVALUATIONS_INCOMPLETES", "AUCUNE_EVALUATION_APPLICABLE", "AUCUNE_NOTE_COMPTEE"} for m in motifs_verification),
            },
            "calcule_par": acteur,
            "date_calcul": timezone.now(),
            "statut": ResultatFinal.Statut.CALCULE,
        }
        return donnees

    @classmethod
    @transaction.atomic
    def calculer_centre(cls, *, session_id, centre_id, acteur=None):
        session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
        if acteur:
            ControleAccesDocumentsService.exiger(
                acteur,
                "calculer_resultats_finaux",
                session_id=session.id,
                region_code=centre.region.code,
                centre_id=centre.id,
            )
        if not session.parametres.attestation_active:
            raise ValidationDocumentsErreur("Les attestations sont désactivées pour cette session.")
        etat = CentreCertificationService.verifier(session=session, centre=centre)
        if not etat["pret"]:
            raise ValidationDocumentsErreur({"centre": etat["blocages"]})

        affectations = list(
            AffectationCentre.objects.select_related(
                "session", "session__parametres", "centre", "centre__region", "immerge"
            ).filter(
                session=session,
                centre=centre,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).order_by("id")
        )
        resultats = []
        for affectation in affectations:
            donnees = cls.calculer(affectation=affectation, acteur=acteur)
            resultat = ResultatFinalRepository.get_par_affectation(affectation.id)
            if resultat and resultat.statut in {
                ResultatFinal.Statut.SOUMIS_REGION,
                ResultatFinal.Statut.VALIDE_REGION,
                ResultatFinal.Statut.PUBLIE,
            }:
                raise ValidationDocumentsErreur(
                    f"Le résultat de {affectation.immerge.code_fasoim} est déjà engagé dans une publication."
                )
            if resultat is None:
                resultat = ResultatFinal(**donnees)
            else:
                for champ, valeur in donnees.items():
                    setattr(resultat, champ, valeur)
                resultat.version += 1
            resultat.save()
            resultats.append(resultat)

        stats = ResultatFinalRepository.statistiques(
            ResultatFinalRepository.lister_centre(session.id, centre.id)
        )
        JournalActionService.journaliser_succes(
            acteur=acteur,
            session=session,
            region=centre.region,
            centre=centre,
            code_action="calculer_resultats_finaux",
            module_source="documents",
            objet_type="CentreImmersion",
            objet_id=centre.id,
            objet_reference=centre.code,
            motif="Résultats finaux calculés pour le centre.",
            contexte=stats,
        )
        return stats

    @classmethod
    @transaction.atomic
    def valider_centre(cls, *, session_id, centre_id, acteur):
        session = SessionImmersion.objects.get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.exiger(
            acteur,
            "valider_resultats_centre",
            session_id=session.id,
            region_code=centre.region.code,
            centre_id=centre.id,
        )
        queryset = ResultatFinal.objects.select_for_update().filter(
            session=session,
            centre=centre,
            deleted_at__isnull=True,
        )
        total_affectations = AffectationCentre.objects.filter(
            session=session,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).count()
        if queryset.count() != total_affectations:
            raise ValidationDocumentsErreur("Tous les immergés du centre n'ont pas encore un résultat final.")
        a_verifier = queryset.filter(decision=ResultatFinal.Decision.A_VERIFIER).count()
        if a_verifier:
            raise ValidationDocumentsErreur(f"{a_verifier} résultat(s) restent à vérifier.")
        maintenant = timezone.now()
        queryset.update(
            statut=ResultatFinal.Statut.VALIDE_CENTRE,
            valide_centre_par=acteur,
            date_validation_centre=maintenant,
            updated_at=maintenant,
        )
        statistiques = ResultatFinalRepository.statistiques(queryset)
        JournalActionService.journaliser_succes(
            acteur=acteur, session=session, region=centre.region, centre=centre,
            code_action="valider_resultats_centre", module_source="documents",
            objet=centre, motif="Résultats finaux validés par le centre.",
            contexte=statistiques,
        )
        return statistiques


class GenerationFichierService:
    MIME = {
        DocumentGenere.Format.PDF: "application/pdf",
        DocumentGenere.Format.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        DocumentGenere.Format.CSV: "text/csv",
    }

    @staticmethod
    def _slug(texte):
        valeur = "".join(caractere if caractere.isalnum() else "_" for caractere in str(texte or ""))
        return "_".join(x for x in valeur.split("_") if x)[:120].lower() or "document"

    @staticmethod
    def qr_bytes(contenu):
        qr = qrcode.QRCode(version=None, box_size=6, border=2)
        qr.add_data(contenu)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        sortie = io.BytesIO()
        image.save(sortie, format="PNG")
        return sortie.getvalue()

    @staticmethod
    def hash_bytes(contenu):
        return hashlib.sha256(contenu).hexdigest()

    @classmethod
    def verifier_integrite(cls, document):
        if not document or not document.fichier or not document.hash_sha256:
            return False
        try:
            with document.fichier.open("rb") as fichier:
                return cls.hash_bytes(fichier.read()) == document.hash_sha256
        except (OSError, ValueError, FileNotFoundError):
            return False

    @classmethod
    def enregistrer(cls, document, contenu, *, extension):
        nom = f"{cls._slug(document.numero_document)}.{extension}"
        document.fichier.save(nom, ContentFile(contenu), save=False)
        document.nom_fichier = nom
        document.type_mime = cls.MIME.get(document.format_fichier, mimetypes.guess_type(nom)[0] or "application/octet-stream")
        document.taille_octets = len(contenu)
        document.hash_sha256 = cls.hash_bytes(contenu)
        document.date_generation = timezone.now()
        document.message_erreur = ""
        document.save()
        return document

    @staticmethod
    def _image_reader(champ):
        if not champ:
            return None
        try:
            champ.open("rb")
            contenu = champ.read()
            champ.close()
            if not contenu:
                return None
            return ImageReader(io.BytesIO(contenu))
        except (ValueError, OSError, FileNotFoundError, NotImplementedError):
            return None

    @classmethod
    def images_signataire_disponibles(cls, signataire):
        return bool(
            cls._image_reader(getattr(signataire, "signature_image", None))
            and cls._image_reader(getattr(signataire, "cachet_image", None))
        )

    @staticmethod
    def _champ_en_data_uri(champ):
        if not champ:
            return ""
        try:
            champ.open("rb")
            contenu = champ.read()
            champ.close()
            if not contenu:
                return ""
            type_mime = mimetypes.guess_type(getattr(champ, "name", ""))[0] or "image/png"
            return f"data:{type_mime};base64,{base64.b64encode(contenu).decode('ascii')}"
        except (ValueError, OSError, FileNotFoundError, NotImplementedError):
            return ""

    @staticmethod
    def _fichier_en_data_uri(chemin, *, type_mime="image/png"):
        if not chemin:
            return ""
        try:
            with open(chemin, "rb") as fichier:
                contenu = fichier.read()
            if not contenu:
                return ""
            mime = mimetypes.guess_type(str(chemin))[0] or type_mime
            return f"data:{mime};base64,{base64.b64encode(contenu).decode('ascii')}"
        except (OSError, ValueError, TypeError):
            return ""

    @staticmethod
    def _libelle_identifiant_origine(type_immerge):
        return {
            Immerge.TypeImmerge.BEPC: "Numéro PV BEPC",
            Immerge.TypeImmerge.BAC: "Numéro PV BAC",
            Immerge.TypeImmerge.CONCOURS: "Numéro de récépissé",
            Immerge.TypeImmerge.SELECTIONNE: "Matricule / référence",
            Immerge.TypeImmerge.VOLONTAIRE: "Code de suivi",
        }.get(type_immerge, "Identifiant d'origine")

    @classmethod
    def pdf_attestation(cls, *, resultat, document, signataire=None):
        """Génère une attestation institutionnelle A4 paysage depuis HTML/CSS."""
        identite = IdentiteImmergeService.donnees(resultat.immerge)
        verification_url = (
            f"{getattr(settings, 'FASOIM_PUBLIC_URL', 'http://127.0.0.1:3000').rstrip('/')}"
            f"/verifier-attestation/{document.code_verification}"
        )
        qr = cls.qr_bytes(verification_url)
        contexte = {
            "document": document,
            "resultat": resultat,
            "immerge": resultat.immerge,
            "identite": identite,
            "identifiant_origine_libelle": cls._libelle_identifiant_origine(
                resultat.immerge.type_immerge
            ),
            "qr_data_uri": f"data:image/png;base64,{base64.b64encode(qr).decode('ascii')}",
            "verification_url": verification_url,
            "signataire": signataire,
            "signature_data_uri": (
                cls._champ_en_data_uri(getattr(signataire, "signature_image", None))
                if signataire else ""
            ),
            "cachet_data_uri": (
                cls._champ_en_data_uri(getattr(signataire, "cachet_image", None))
                if signataire else ""
            ),
            "armoiries_data_uri": cls._fichier_en_data_uri(
                getattr(settings, "FASOIM_ATTESTATION_ARMOIRIES_PATH", "")
            ),
            "logo_data_uri": cls._fichier_en_data_uri(
                getattr(settings, "FASOIM_ATTESTATION_LOGO_PATH", "")
            ),
            "date_delivrance": timezone.localdate(),
        }
        html = render_to_string("documents/attestation.html", contexte)
        pdf = HTML(
            string=html,
            base_url=str(getattr(settings, "BASE_DIR", "")),
        ).write_pdf()
        return pdf, qr

    @classmethod
    def pdf_rapport(cls, *, titre, sections):
        sortie = io.BytesIO()
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="TitreFasoIM", parent=styles["Title"], alignment=TA_CENTER, fontSize=18, spaceAfter=18))
        styles.add(ParagraphStyle(name="TexteFasoIM", parent=styles["BodyText"], alignment=TA_LEFT, fontSize=9, leading=12))
        doc = SimpleDocTemplate(sortie, pagesize=A4, rightMargin=1.3 * cm, leftMargin=1.3 * cm, topMargin=1.3 * cm, bottomMargin=1.3 * cm)
        elements = [Paragraph(titre, styles["TitreFasoIM"]), Spacer(1, 0.3 * cm)]
        for section_titre, contenu in sections:
            elements.append(Paragraph(str(section_titre), styles["Heading2"]))
            if isinstance(contenu, dict):
                data = [["Indicateur", "Valeur"]] + [[str(k), str(v)] for k, v in contenu.items()]
                table = Table(data, colWidths=[9 * cm, 7 * cm], repeatRows=1)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))
                elements.append(table)
            elif isinstance(contenu, list) and contenu:
                if isinstance(contenu[0], dict):
                    colonnes = list(contenu[0].keys())
                    data = [colonnes] + [[str(ligne.get(col, "")) for col in colonnes] for ligne in contenu]
                    table = Table(data, repeatRows=1)
                    table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]))
                    elements.append(table)
                else:
                    elements.append(Paragraph("<br/>".join(str(x) for x in contenu), styles["TexteFasoIM"]))
            else:
                elements.append(Paragraph(str(contenu or "Aucune donnée."), styles["TexteFasoIM"]))
            elements.append(Spacer(1, 0.35 * cm))
        doc.build(elements)
        return sortie.getvalue()

    @staticmethod
    def xlsx(*, titre, sections):
        wb = Workbook()
        ws = wb.active
        ws.title = "Rapport"
        ws.append([titre])
        ws.append([])
        for section_titre, contenu in sections:
            ws.append([section_titre])
            if isinstance(contenu, dict):
                ws.append(["Indicateur", "Valeur"])
                for cle, valeur in contenu.items():
                    ws.append([str(cle), json.dumps(valeur, ensure_ascii=False) if isinstance(valeur, (dict, list)) else valeur])
            elif isinstance(contenu, list) and contenu:
                if isinstance(contenu[0], dict):
                    colonnes = list(contenu[0].keys())
                    ws.append(colonnes)
                    for ligne in contenu:
                        ws.append([ligne.get(cle, "") for cle in colonnes])
                else:
                    for ligne in contenu:
                        ws.append([str(ligne)])
            else:
                ws.append([str(contenu or "Aucune donnée")])
            ws.append([])
        sortie = io.BytesIO()
        wb.save(sortie)
        return sortie.getvalue()

    @staticmethod
    def csv(*, titre, sections):
        sortie = io.StringIO()
        writer = csv.writer(sortie)
        writer.writerow([titre])
        writer.writerow([])
        for section_titre, contenu in sections:
            writer.writerow([section_titre])
            if isinstance(contenu, dict):
                writer.writerow(["Indicateur", "Valeur"])
                for cle, valeur in contenu.items():
                    writer.writerow([cle, json.dumps(valeur, ensure_ascii=False) if isinstance(valeur, (dict, list)) else valeur])
            elif isinstance(contenu, list) and contenu:
                if isinstance(contenu[0], dict):
                    colonnes = list(contenu[0].keys())
                    writer.writerow(colonnes)
                    for ligne in contenu:
                        writer.writerow([ligne.get(cle, "") for cle in colonnes])
                else:
                    for ligne in contenu:
                        writer.writerow([ligne])
            writer.writerow([])
        return sortie.getvalue().encode("utf-8-sig")


class AttestationService:
    @classmethod
    @transaction.atomic
    def generer_centre(cls, *, session_id, centre_id, acteur):
        session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.exiger(
            acteur,
            "generer_attestations",
            session_id=session.id,
            region_code=centre.region.code,
            centre_id=centre.id,
        )
        resultats = list(
            ResultatFinal.objects.select_for_update().select_related(
                "session", "centre", "centre__region", "immerge", "affectation_centre"
            ).filter(
                session=session,
                centre=centre,
                decision=ResultatFinal.Decision.ELIGIBLE,
                statut=ResultatFinal.Statut.VALIDE_CENTRE,
                deleted_at__isnull=True,
            )
        )
        crees = 0
        deja = 0
        for resultat in resultats:
            existant = DocumentGenereRepository.get_attestation_resultat(resultat.id)
            if existant:
                deja += 1
                continue
            cle = f"ATTESTATION:{session.id}:{resultat.immerge_id}:V{resultat.version}"
            document = DocumentGenere(
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                format_fichier=DocumentGenere.Format.PDF,
                titre=f"Attestation FasoIM - {resultat.immerge.code_fasoim}",
                cle_generation=cle,
                session=session,
                region=centre.region,
                centre=centre,
                immerge=resultat.immerge,
                affectation_centre=resultat.affectation_centre,
                resultat_final=resultat,
                version=resultat.version,
                statut=DocumentGenere.Statut.EN_GENERATION,
                visibilite=DocumentGenere.Visibilite.IMMERGE_CONCERNE,
                genere_par=acteur,
                donnees_figees={
                    "code_fasoim": resultat.immerge.code_fasoim,
                    "taux_presence": str(resultat.taux_presence),
                    "moyenne_sur_20": str(resultat.moyenne_sur_20) if resultat.moyenne_sur_20 is not None else None,
                    "session": session.nom,
                    "centre": centre.nom,
                },
            )
            document.save()
            pdf, qr = GenerationFichierService.pdf_attestation(resultat=resultat, document=document)
            document.qr_code_image.save(
                f"qr_{document.code_verification.lower()}.png",
                ContentFile(qr),
                save=False,
            )
            document.statut = DocumentGenere.Statut.GENERE
            GenerationFichierService.enregistrer(document, pdf, extension="pdf")
            crees += 1
        resume = {"eligibles": len(resultats), "generes": crees, "deja_generes": deja}
        JournalActionService.journaliser_succes(
            acteur=acteur, session=session, region=centre.region, centre=centre,
            code_action="generer_attestations_centre", module_source="documents",
            objet=centre, motif="Attestations éligibles générées pour le centre.",
            contexte=resume,
        )
        return resume

    @classmethod
    @transaction.atomic
    def signer_region(cls, *, publication_id, acteur):
        publication = PublicationOfficielleRepository.get_by_id_pour_update(publication_id)
        ControleAccesDocumentsService.verifier_session_traitable(publication.session)
        if publication.type_publication != PublicationOfficielle.TypePublication.ATTESTATIONS:
            raise ValidationDocumentsErreur("Cette publication ne concerne pas les attestations.")
        if publication.statut != PublicationOfficielle.Statut.SOUMISE_REGION:
            raise ValidationDocumentsErreur("Le lot doit être soumis à la région avant signature.")
        ControleAccesDocumentsService.exiger(
            acteur,
            "signer_attestations_region",
            session_id=publication.session_id,
            region_code=publication.region.code,
            centre_id=publication.centre_id,
        )
        if not GenerationFichierService.images_signataire_disponibles(acteur):
            raise ValidationDocumentsErreur(
                "La signature et le cachet du signataire doivent être enregistrés et accessibles dans son compte."
            )
        resultats = list(ResultatFinal.objects.select_for_update().filter(
            session=publication.session,
            centre=publication.centre,
            deleted_at__isnull=True,
        ))
        if any(r.decision == ResultatFinal.Decision.A_VERIFIER for r in resultats):
            raise ValidationDocumentsErreur("Des résultats restent à vérifier dans ce centre.")

        documents = list(
            DocumentGenere.objects
            .select_for_update(of=("self",))
            .select_related("resultat_final", "immerge")
            .filter(
                session=publication.session,
                centre=publication.centre,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                resultat_final__decision=ResultatFinal.Decision.ELIGIBLE,
                deleted_at__isnull=True,
            )
        )

        eligibles = sum(1 for r in resultats if r.decision == ResultatFinal.Decision.ELIGIBLE)
        if len(documents) != eligibles:
            raise ValidationDocumentsErreur("Toutes les attestations éligibles ne sont pas générées.")
        for document in documents:
            pdf, qr = GenerationFichierService.pdf_attestation(
                resultat=document.resultat_final,
                document=document,
                signataire=acteur,
            )
            document.signataire = acteur
            document.nom_signataire_snapshot = acteur.nom_complet or acteur.username
            document.fonction_signataire_snapshot = acteur.titre
            document.organisation_signataire_snapshot = acteur.organisation
            document.signature_appliquee = True
            document.cachet_applique = True
            document.date_signature = timezone.now()
            document.statut = DocumentGenere.Statut.SIGNE
            GenerationFichierService.enregistrer(document, pdf, extension="pdf")
        maintenant = timezone.now()
        ResultatFinal.objects.filter(id__in=[r.id for r in resultats]).update(
            statut=ResultatFinal.Statut.VALIDE_REGION,
            valide_region_par=acteur,
            date_validation_region=maintenant,
            updated_at=maintenant,
        )
        publication.statut = PublicationOfficielle.Statut.VALIDEE_REGION
        publication.validee_region_par = acteur
        publication.date_validation_region = maintenant
        publication.save()
        resume = {"signes": len(documents), "centre": publication.centre.nom}
        JournalActionService.journaliser_succes(
            acteur=acteur, session=publication.session, region=publication.region,
            centre=publication.centre, code_action="signer_attestations_region",
            module_source="documents", objet=publication,
            motif="Attestations du centre contrôlées et signées par la région.",
            contexte=resume,
        )
        NotificationService.planifier_acteurs_role(
            code_role="RESPONSABLE_CENTRE",
            sujet="Attestations validées pour votre centre",
            message=(
                f"Les attestations du centre {publication.centre.nom} ont été "
                "contrôlées et signées par la Direction régionale."
            ),
            type_message=TypesMessage.DOCUMENT_SIGNE,
            cle_evenement=f"ATTESTATIONS_SIGNEES:{publication.reference}",
            session_id=publication.session_id,
            region_code=publication.region.code,
            centre_id=publication.centre_id,
            contexte=resume,
        )
        PublicationService._notifier_dgas_si_tous_centres_valides(
            session=publication.session,
            type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
        )
        return resume


class WorkflowAutomatiqueAttestationService:
    """Prépare automatiquement les attestations, puis attend la validation régionale."""

    @staticmethod
    def _acteur_systeme():
        acteur = Acteur.objects.filter(
            is_superuser=True,
            is_active=True,
            statut=Acteur.Statut.ACTIF,
            deleted_at__isnull=True,
        ).order_by("id").first()
        if acteur is None:
            raise ValidationDocumentsErreur(
                "Aucun compte système actif n'est disponible pour le traitement automatique."
            )
        return acteur

    @classmethod
    @transaction.atomic
    def preparer_centre(cls, *, session, centre):
        etat = CentreCertificationService.verifier(session=session, centre=centre)
        if not etat["pret"]:
            return {"prepare": False, "centre_id": centre.id, "blocages": etat["blocages"]}

        acteur_systeme = cls._acteur_systeme()

        EligibiliteAttestationService.calculer_centre(
            session_id=session.id,
            centre_id=centre.id,
            acteur=acteur_systeme,
        )
        maintenant = timezone.now()
        ResultatFinal.objects.filter(
            session=session,
            centre=centre,
            statut=ResultatFinal.Statut.CALCULE,
            deleted_at__isnull=True,
        ).update(
            statut=ResultatFinal.Statut.VALIDE_CENTRE,
            valide_centre_par=acteur_systeme,
            date_validation_centre=maintenant,
            updated_at=maintenant,
        )
        AttestationService.generer_centre(
            session_id=session.id,
            centre_id=centre.id,
            acteur=acteur_systeme,
        )
        publication = PublicationService.soumettre_attestations_centre(
            session_id=session.id,
            centre_id=centre.id,
            acteur=acteur_systeme,
        )

        documents = DocumentGenere.objects.filter(
            session=session,
            centre=centre,
            type_document=DocumentGenere.TypeDocument.ATTESTATION,
            resultat_final__decision=ResultatFinal.Decision.ELIGIBLE,
            statut=DocumentGenere.Statut.GENERE,
            deleted_at__isnull=True,
        )

        publication.statut = PublicationOfficielle.Statut.SOUMISE_REGION
        publication.resume = {
            **(publication.resume or {}),
            "attestations_generees": documents.count(),
            "attestations_signees": 0,
            "validation_regionale_requise": True,
        }
        publication.save(update_fields=["statut", "resume", "updated_at"])
        NotificationService.planifier_acteurs_role(
            code_role="DIRECTEUR_REGIONAL",
            sujet="Attestations prêtes à valider",
            message=(
                f"Les attestations du centre {centre.nom} ont été calculées et générées. "
                "Elles attendent votre vérification, votre signature et leur publication."
            ),
            type_message=getattr(TypesMessage, "ATTESTATIONS_SOUMISES_REGION", "ATTESTATIONS_SOUMISES_REGION"),
            cle_evenement=f"ATTESTATIONS_A_VALIDER:{publication.reference}",
            session_id=session.id,
            region_code=centre.region.code,
            centre_id=centre.id,
            contexte={"publication_id": publication.id, "centre_id": centre.id},
        )
        return {
            "prepare": True,
            "centre_id": centre.id,
            "publication_id": publication.id,
            "attestations_generees": documents.count(),
        }

    @classmethod
    @transaction.atomic
    def valider_et_publier(cls, *, publication_id, acteur):
        publication = PublicationOfficielleRepository.get_by_id_pour_update(publication_id)
        if publication.type_publication != PublicationOfficielle.TypePublication.ATTESTATIONS:
            raise ValidationDocumentsErreur("Cette publication ne concerne pas les attestations.")
        if publication.statut == PublicationOfficielle.Statut.PUBLIEE:
            return {"publication_id": publication.id, "deja_publiee": True}
        if publication.statut != PublicationOfficielle.Statut.SOUMISE_REGION:
            raise ValidationDocumentsErreur("Le lot d'attestations n'est pas prêt à être validé.")
        ControleAccesDocumentsService.exiger(
            acteur,
            "valider_publication_region",
            session_id=publication.session_id,
            region_code=publication.region.code,
            centre_id=publication.centre_id,
        )
        if not AffectationRole.objects.filter(
            affectation_acteur__acteur=acteur,
            affectation_acteur__session=publication.session,
            affectation_acteur__region_code=publication.region.code,
            affectation_acteur__statut=AffectationActeur.Statut.ACTIVE,
            affectation_acteur__deleted_at__isnull=True,
            role__code="DIRECTEUR_REGIONAL",
            statut=AffectationRole.Statut.ACTIF,
            deleted_at__isnull=True,
        ).exists():
            raise ValidationDocumentsErreur("Seul le Directeur régional de ce périmètre peut valider ces attestations.")

        if not GenerationFichierService.images_signataire_disponibles(acteur):
            raise ValidationDocumentsErreur(
                "La signature et le cachet du Directeur régional sont obligatoires avant publication."
            )

        documents = list(
            DocumentGenere.objects.select_for_update(of=("self",)).select_related(
                "resultat_final", "immerge"
            ).filter(
                publication__isnull=True,
                session=publication.session,
                centre=publication.centre,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                statut=DocumentGenere.Statut.GENERE,
                resultat_final__decision=ResultatFinal.Decision.ELIGIBLE,
                deleted_at__isnull=True,
            )
        )
        attendus = ResultatFinal.objects.filter(
            session=publication.session,
            centre=publication.centre,
            decision=ResultatFinal.Decision.ELIGIBLE,
            deleted_at__isnull=True,
        ).count()
        if len(documents) != attendus:
            raise ValidationDocumentsErreur(
                "Toutes les attestations éligibles doivent être générées avant validation."
            )

        maintenant = timezone.now()
        for document in documents:
            pdf, _qr = GenerationFichierService.pdf_attestation(
                resultat=document.resultat_final,
                document=document,
                signataire=acteur,
            )
            document.signataire = acteur
            document.nom_signataire_snapshot = acteur.nom_complet or acteur.username
            document.fonction_signataire_snapshot = acteur.titre
            document.organisation_signataire_snapshot = acteur.organisation
            document.signature_appliquee = True
            document.cachet_applique = True
            document.date_signature = maintenant
            document.statut = DocumentGenere.Statut.PUBLIE
            document.visibilite = DocumentGenere.Visibilite.PUBLIC_VERIFICATION
            document.publication = publication
            document.date_publication = maintenant
            GenerationFichierService.enregistrer(document, pdf, extension="pdf")
        ResultatFinal.objects.filter(
            session=publication.session,
            centre=publication.centre,
            deleted_at__isnull=True,
        ).update(
            statut=ResultatFinal.Statut.PUBLIE,
            valide_region_par=acteur,
            date_validation_region=maintenant,
            date_publication=maintenant,
            updated_at=maintenant,
        )
        publication.statut = PublicationOfficielle.Statut.PUBLIEE
        publication.validee_region_par = acteur
        publication.publiee_par = acteur
        publication.date_validation_region = maintenant
        publication.date_publication = maintenant
        publication.resume = {
            **(publication.resume or {}),
            "attestations_signees": attendus,
            "attestations_publiees": attendus,
        }
        publication.save()
        immerge_ids = list(ResultatFinal.objects.filter(
            session=publication.session,
            centre=publication.centre,
            decision=ResultatFinal.Decision.ELIGIBLE,
            deleted_at__isnull=True,
        ).values_list("immerge_id", flat=True))
        NotificationService.planifier_attestations_publiees(
            immerge_ids=immerge_ids,
            publication_reference=publication.reference,
            region_id=publication.region_id,
            centre_id=publication.centre_id,
        )
        JournalActionService.journaliser_succes(
            acteur=acteur,
            session=publication.session,
            region=publication.region,
            centre=publication.centre,
            code_action="valider_publier_attestations_region",
            module_source="documents",
            objet=publication,
            motif="Attestations validées par la région et publiées automatiquement.",
            contexte={"attestations_publiees": attendus},
        )
        return {"publication_id": publication.id, "publiees": attendus}

    @classmethod
    def valider_lot(cls, *, publication_ids, acteur):
        resultat = {"selectionnees": len(publication_ids), "validees": 0, "publiees": 0, "ignorees": 0, "echecs": []}
        for publication_id in dict.fromkeys(publication_ids):
            try:
                ligne = cls.valider_et_publier(publication_id=publication_id, acteur=acteur)
                if ligne.get("deja_publiee"):
                    resultat["ignorees"] += 1
                else:
                    resultat["validees"] += 1
                    resultat["publiees"] += ligne.get("publiees", 0)
            except Exception as exc:
                resultat["echecs"].append({"publication_id": publication_id, "motif": str(exc)})
        return resultat

    @classmethod
    def statistiques_region(cls, *, session_id, acteur, region_id=None):
        session = SessionImmersion.objects.get(id=session_id, deleted_at__isnull=True)
        publications = PublicationOfficielleRepository.visibles_par_acteur(acteur).filter(
            session=session,
            type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
            deleted_at__isnull=True,
        )
        if region_id:
            publications = publications.filter(region_id=region_id)
        regions = publications.values("region_id", "region__nom").distinct()
        sorties = []
        for region in regions:
            rid = region["region_id"]
            resultats = ResultatFinal.objects.filter(session=session, region_id=rid, deleted_at__isnull=True)
            documents = DocumentGenere.objects.filter(
                session=session,
                region_id=rid,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                deleted_at__isnull=True,
            )
            total = resultats.count()
            publiees = documents.filter(statut=DocumentGenere.Statut.PUBLIE).count()
            sorties.append({
                "region_id": rid,
                "region_nom": region["region__nom"],
                "total_immerges": total,
                "eligibles": resultats.filter(decision=ResultatFinal.Decision.ELIGIBLE).count(),
                "non_eligibles": resultats.filter(decision=ResultatFinal.Decision.NON_ELIGIBLE).count(),
                "a_verifier": resultats.filter(decision=ResultatFinal.Decision.A_VERIFIER).count(),
                "generees": documents.count(),
                "signees": documents.filter(statut=DocumentGenere.Statut.SIGNE).count(),
                "publiees": publiees,
                "bloquees": documents.filter(statut=DocumentGenere.Statut.ECHEC).count(),
                "taux_couverture": round((publiees * 100 / total), 2) if total else 100.0,
                "centres": list(publications.filter(region_id=rid).values(
                    "centre_id", "centre__nom", "statut", "resume"
                ).order_by("centre__nom")),
            })
        return {"session_id": session.id, "regions": sorties}


class PublicationService:
    @staticmethod
    def _resume_arrivee(session, centre):
        total = AffectationCentre.objects.filter(
            session=session,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).count()
        return {"immerges": total, "centre": centre.nom, "region": centre.region.nom}

    @classmethod
    @transaction.atomic
    def soumettre_arrivee_centre(cls, *, session_id, centre_id, acteur):
        session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.exiger(
            acteur,
            "soumettre_publication_centre",
            session_id=session.id,
            region_code=centre.region.code,
            centre_id=centre.id,
        )
        if not session.parametres.consultation_publique_active:
            raise ValidationDocumentsErreur("La consultation publique doit être activée avant la soumission.")
        regle = RegleOrganisationCentre.objects.filter(
            session=session,
            centre=centre,
            statut=RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
            deleted_at__isnull=True,
        ).first()
        if regle is None:
            raise ValidationDocumentsErreur("L'organisation doit être validée et marquée prête pour publication.")
        publication = PublicationOfficielleRepository.get_centre_courante(
            session_id=session.id,
            centre_id=centre.id,
            type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
        )
        if publication and publication.statut == PublicationOfficielle.Statut.PUBLIEE:
            raise ValidationDocumentsErreur("Les informations de ce centre sont déjà publiées.")
        if publication is None or publication.statut in {
            PublicationOfficielle.Statut.REMPLACEE,
            PublicationOfficielle.Statut.ANNULEE,
        }:
            version = 1
            derniere = PublicationOfficielle.objects.filter(
                session=session,
                centre=centre,
                type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
            ).order_by("-version").first()
            if derniere:
                version = derniere.version + 1
            publication = PublicationOfficielle(
                type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
                perimetre=PublicationOfficielle.Perimetre.CENTRE,
                session=session,
                region=centre.region,
                centre=centre,
                version=version,
                preparee_par=acteur,
            )
        maintenant = timezone.now()
        publication.statut = PublicationOfficielle.Statut.PUBLIEE
        publication.soumise_par = acteur
        publication.publiee_par = acteur
        publication.date_soumission = maintenant
        publication.date_publication = maintenant
        publication.motif_correction = ""
        publication.resume = cls._resume_arrivee(session, centre)
        publication.save()

        immerge_ids = list(
            AffectationCentre.objects.filter(
                session=session,
                centre=centre,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).values_list("immerge_id", flat=True)
        )
        NotificationService.planifier_affectations_publiees(
            immerge_ids=immerge_ids,
            publication_reference=publication.reference,
            region_id=centre.region_id,
            centre_id=centre.id,
        )
        JournalActionService.journaliser_succes(
            acteur=acteur, session=session, region=centre.region, centre=centre,
            code_action="publier_informations_arrivee_centre", module_source="documents",
            objet=publication,
            motif="Informations avant l'arrivée publiées directement par le Responsable de centre.",
            contexte=publication.resume,
        )
        return publication

    @classmethod
    @transaction.atomic
    def soumettre_attestations_centre(cls, *, session_id, centre_id, acteur):
        session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.exiger(
            acteur,
            "soumettre_publication_centre",
            session_id=session.id,
            region_code=centre.region.code,
            centre_id=centre.id,
        )
        resultats = ResultatFinal.objects.select_for_update().filter(
            session=session,
            centre=centre,
            deleted_at__isnull=True,
        )
        total_affectations = AffectationCentre.objects.filter(
            session=session,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).count()
        if resultats.count() != total_affectations:
            raise ValidationDocumentsErreur("Tous les immergés du centre doivent avoir un résultat final.")
        if resultats.filter(decision=ResultatFinal.Decision.A_VERIFIER).exists():
            raise ValidationDocumentsErreur("Des résultats restent à vérifier.")
        if resultats.exclude(statut=ResultatFinal.Statut.VALIDE_CENTRE).exists():
            raise ValidationDocumentsErreur("Les résultats doivent être validés par le centre.")
        eligibles = resultats.filter(decision=ResultatFinal.Decision.ELIGIBLE)
        docs = DocumentGenere.objects.filter(
            resultat_final__in=eligibles,
            type_document=DocumentGenere.TypeDocument.ATTESTATION,
            statut=DocumentGenere.Statut.GENERE,
            deleted_at__isnull=True,
        ).count()
        if docs != eligibles.count():
            raise ValidationDocumentsErreur("Toutes les attestations éligibles doivent être générées avant soumission.")

        liberation_hebergement = {"lits_liberes": 0}
        if session.parametres.hebergement_active:
            liberation_hebergement = (
                HebergementService.liberer_lits_fin_immersion(
                    session_id=session.id,
                    centre_id=centre.id,
                    observations=(
                        "Libération automatique lors de la finalisation "
                        "de l'immersion du centre."
                    ),
                )
            )

        publication = PublicationOfficielleRepository.get_centre_courante(
            session_id=session.id,
            centre_id=centre.id,
            type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
        )
        if publication is None:
            publication = PublicationOfficielle(
                type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
                perimetre=PublicationOfficielle.Perimetre.CENTRE,
                session=session,
                region=centre.region,
                centre=centre,
                version=1,
                preparee_par=acteur,
            )
        publication.statut = PublicationOfficielle.Statut.SOUMISE_REGION
        publication.soumise_par = acteur
        publication.date_soumission = timezone.now()
        publication.resume = {
            **ResultatFinalRepository.statistiques(resultats),
            "hebergement": liberation_hebergement,
        }
        publication.save()
        resultats.update(statut=ResultatFinal.Statut.SOUMIS_REGION, updated_at=timezone.now())
        JournalActionService.journaliser_succes(
            acteur=acteur, session=session, region=centre.region, centre=centre,
            code_action="soumettre_attestations_region", module_source="documents",
            objet=publication, motif="Lot d'attestations soumis à la région.",
            contexte=publication.resume,
        )
        NotificationService.planifier_acteurs_role(
            code_role="DIRECTEUR_REGIONAL",
            sujet="Attestations à contrôler et signer",
            message=(
                f"Le centre {centre.nom} a soumis ses attestations pour la "
                f"session {session.nom}."
            ),
            type_message=TypesMessage.DOCUMENT_A_SIGNER,
            cle_evenement=f"ATTESTATIONS_SOUMISES_REGION:{publication.reference}",
            session_id=session.id, region_code=centre.region.code, centre_id=centre.id,
            contexte={"publication_reference": publication.reference},
        )
        return publication

    @classmethod
    def _notifier_dgas_si_tous_centres_valides(cls, *, session, type_publication):
        centres = cls._centres_attendus(session)
        if not centres:
            return False
        valides = PublicationOfficielle.objects.filter(
            session=session,
            centre__in=centres,
            type_publication=type_publication,
            statut=PublicationOfficielle.Statut.VALIDEE_REGION,
            deleted_at__isnull=True,
        ).values("centre_id").distinct().count()
        if valides != len(centres):
            return False
        libelle = (
            "les informations avant l'arrivée"
            if type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE
            else "les attestations signées"
        )
        NotificationService.planifier_acteurs_role(
            code_role="DGAS",
            sujet=f"FasoIM : {libelle} sont prêts à publier",
            message=(
                f"Tous les centres de la session {session.nom} ont été validés. "
                f"La DGAS peut maintenant publier {libelle}."
            ),
            type_message=(
                TypesMessage.ORGANISATION_PRETE
                if type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE
                else TypesMessage.ATTESTATIONS_SOUMISES_DGAS
            ),
            cle_evenement=f"DOCUMENTS_PRETS_DGAS:{type_publication}:{session.id}",
            session_id=session.id,
            contexte={"type_publication": type_publication, "centres": len(centres)},
        )
        return True

    @classmethod
    @transaction.atomic
    def valider_region(cls, *, publication_id, acteur):
        publication = PublicationOfficielleRepository.get_by_id_pour_update(publication_id)
        ControleAccesDocumentsService.verifier_session_traitable(publication.session)
        if publication.type_publication == PublicationOfficielle.TypePublication.ATTESTATIONS:
            raise ValidationDocumentsErreur(
                "Les attestations doivent être contrôlées et signées avec l'action de signature régionale."
            )
        if publication.statut != PublicationOfficielle.Statut.SOUMISE_REGION:
            raise ValidationDocumentsErreur("La publication doit être soumise à la région.")
        ControleAccesDocumentsService.exiger(
            acteur,
            "valider_publication_region",
            session_id=publication.session_id,
            region_code=publication.region.code,
            centre_id=publication.centre_id,
        )
        publication.statut = PublicationOfficielle.Statut.VALIDEE_REGION
        publication.validee_region_par = acteur
        publication.date_validation_region = timezone.now()
        publication.save()
        JournalActionService.journaliser_succes(
            acteur=acteur, session=publication.session, region=publication.region,
            centre=publication.centre, code_action="valider_publication_region",
            module_source="documents", objet=publication,
            motif="Publication de centre validée par la région.",
            contexte={"type_publication": publication.type_publication},
        )
        NotificationService.planifier_acteurs_role(
            code_role="RESPONSABLE_CENTRE",
            sujet="Publication de votre centre validée",
            message=(
                f"La publication {publication.get_type_publication_display()} "
                f"du centre {publication.centre.nom} a été validée par la région."
            ),
            type_message=TypesMessage.PUBLICATION_VALIDEE,
            cle_evenement=f"PUBLICATION_VALIDEE_REGION:{publication.reference}",
            session_id=publication.session_id, region_code=publication.region.code,
            centre_id=publication.centre_id,
            contexte={"publication_reference": publication.reference},
        )
        cls._notifier_dgas_si_tous_centres_valides(
            session=publication.session,
            type_publication=publication.type_publication,
        )
        return publication

    @classmethod
    @transaction.atomic
    def rejeter_region(cls, *, publication_id, acteur, motif):
        publication = PublicationOfficielleRepository.get_by_id_pour_update(publication_id)
        ControleAccesDocumentsService.verifier_session_traitable(publication.session)
        if publication.statut != PublicationOfficielle.Statut.SOUMISE_REGION:
            raise ValidationDocumentsErreur("Seule une publication soumise peut être renvoyée.")
        ControleAccesDocumentsService.exiger(
            acteur,
            "rejeter_publication_region",
            session_id=publication.session_id,
            region_code=publication.region.code,
            centre_id=publication.centre_id,
        )
        publication.statut = PublicationOfficielle.Statut.A_CORRIGER
        publication.motif_correction = str(motif or "").strip()
        publication.validee_region_par = acteur
        publication.date_validation_region = timezone.now()
        publication.save()
        if publication.type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE:
            RegleOrganisationCentre.objects.filter(
                session=publication.session,
                centre=publication.centre,
                deleted_at__isnull=True,
            ).update(
                statut=RegleOrganisationCentre.Statut.EN_COURS,
                date_pret_publication=None,
                updated_at=timezone.now(),
            )
        else:
            # Un lot d'attestations rejeté doit revenir au centre. Les résultats
            # repassent à l'état calculé afin de permettre une correction, une
            # nouvelle validation et une régénération. Les anciens PDF restent
            # conservés comme preuve, mais ne sont plus considérés actifs.
            maintenant = timezone.now()
            ResultatFinal.objects.filter(
                session=publication.session,
                centre=publication.centre,
                deleted_at__isnull=True,
            ).update(
                statut=ResultatFinal.Statut.CALCULE,
                valide_region_par=None,
                date_validation_region=None,
                updated_at=maintenant,
            )
            DocumentGenere.objects.filter(
                session=publication.session,
                centre=publication.centre,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                statut=DocumentGenere.Statut.GENERE,
                deleted_at__isnull=True,
            ).update(
                statut=DocumentGenere.Statut.ANNULE,
                message_erreur=(
                    "Lot renvoyé par la région pour correction avant signature."
                ),
                updated_at=maintenant,
            )
        JournalActionService.journaliser_succes(
            acteur=acteur, session=publication.session, region=publication.region,
            centre=publication.centre, code_action="rejeter_publication_region",
            module_source="documents", objet=publication,
            motif="Publication renvoyée au centre pour correction.",
            contexte={"type_publication": publication.type_publication, "motif": publication.motif_correction},
        )
        NotificationService.planifier_acteurs_role(
            code_role="RESPONSABLE_CENTRE",
            sujet="Correction demandée pour votre publication",
            message=(
                f"La publication du centre {publication.centre.nom} doit être "
                f"corrigée. Motif : {publication.motif_correction}"
            ),
            type_message=TypesMessage.PUBLICATION_A_CORRIGER,
            cle_evenement=f"PUBLICATION_A_CORRIGER:{publication.reference}:{publication.updated_at.isoformat()}",
            session_id=publication.session_id, region_code=publication.region.code,
            centre_id=publication.centre_id,
            contexte={"publication_reference": publication.reference},
        )
        return publication

    @classmethod
    def _centres_attendus(cls, session):
        return list(
            CentreImmersion.objects.filter(
                affectations_centres__session=session,
                affectations_centres__statut=AffectationCentre.Statut.ACTIVE,
                affectations_centres__deleted_at__isnull=True,
                deleted_at__isnull=True,
            ).select_related("region").distinct().order_by("id")
        )

    @classmethod
    @transaction.atomic
    def publier_session(cls, *, session_id, type_publication, acteur):
        session = SessionImmersion.objects.select_related("parametres").get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        permission = (
            "publier_informations_arrivee"
            if type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE
            else "publier_attestations"
        )
        ControleAccesDocumentsService.exiger(acteur, permission, session_id=session.id)
        centres = cls._centres_attendus(session)
        publications = list(
            PublicationOfficielle.objects.select_for_update().filter(
                session=session,
                centre__in=centres,
                type_publication=type_publication,
                statut=PublicationOfficielle.Statut.VALIDEE_REGION,
                deleted_at__isnull=True,
            ).select_related("centre", "centre__region")
        )
        ids_centres_valides = {p.centre_id for p in publications}
        manquants = [centre.nom for centre in centres if centre.id not in ids_centres_valides]
        if manquants:
            raise ValidationDocumentsErreur({"centres_non_valides": manquants})
        maintenant = timezone.now()
        for publication in publications:
            publication.statut = PublicationOfficielle.Statut.PUBLIEE
            publication.publiee_par = acteur
            publication.date_publication = maintenant
            publication.save()
            immerge_ids = list(
                AffectationCentre.objects.filter(
                    session=session,
                    centre=publication.centre,
                    statut=AffectationCentre.Statut.ACTIVE,
                    deleted_at__isnull=True,
                ).values_list("immerge_id", flat=True)
            )
            if type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE:
                NotificationService.planifier_affectations_publiees(
                    immerge_ids=immerge_ids,
                    publication_reference=publication.reference,
                    region_id=publication.region_id,
                    centre_id=publication.centre_id,
                )
            else:
                publies_ids = list(ResultatFinal.objects.filter(
                    session=session,
                    centre=publication.centre,
                    decision=ResultatFinal.Decision.ELIGIBLE,
                    deleted_at__isnull=True,
                ).values_list("immerge_id", flat=True))
                NotificationService.planifier_attestations_publiees(
                    immerge_ids=publies_ids,
                    publication_reference=publication.reference,
                    region_id=publication.region_id,
                    centre_id=publication.centre_id,
                )
                DocumentGenere.objects.filter(
                    session=session,
                    centre=publication.centre,
                    type_document=DocumentGenere.TypeDocument.ATTESTATION,
                    statut=DocumentGenere.Statut.SIGNE,
                    deleted_at__isnull=True,
                ).update(
                    statut=DocumentGenere.Statut.PUBLIE,
                    visibilite=DocumentGenere.Visibilite.PUBLIC_VERIFICATION,
                    publication=publication,
                    date_publication=maintenant,
                    updated_at=maintenant,
                )
                ResultatFinal.objects.filter(
                    session=session,
                    centre=publication.centre,
                    deleted_at__isnull=True,
                ).update(
                    statut=ResultatFinal.Statut.PUBLIE,
                    date_publication=maintenant,
                    updated_at=maintenant,
                )
        nationale = PublicationOfficielle.objects.filter(
            session=session,
            type_publication=type_publication,
            perimetre=PublicationOfficielle.Perimetre.NATIONAL,
            deleted_at__isnull=True,
        ).order_by("-version").first()
        if nationale is None:
            nationale = PublicationOfficielle(
                type_publication=type_publication,
                perimetre=PublicationOfficielle.Perimetre.NATIONAL,
                session=session,
                version=1,
                preparee_par=acteur,
            )
        nationale.statut = PublicationOfficielle.Statut.PUBLIEE
        nationale.publiee_par = acteur
        nationale.date_publication = maintenant
        nationale.resume = {"centres": len(centres), "publications": len(publications)}
        nationale.save()
        JournalActionService.journaliser_succes(
            acteur=acteur, session=session, code_action=(
                "publier_informations_arrivee"
                if type_publication == PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE
                else "publier_attestations"
            ), module_source="documents", objet=nationale,
            motif="Publication nationale effectuée par la DGAS.",
            contexte=nationale.resume,
        )
        return nationale


class RapportService:
    """Rapports facultatifs. Leur échec ne bloque jamais la session."""

    @staticmethod
    def _scope(session, region=None, centre=None):
        filtre_aff = Q(session=session, statut=AffectationCentre.Statut.ACTIVE, deleted_at__isnull=True)
        if centre:
            filtre_aff &= Q(centre=centre)
        elif region:
            filtre_aff &= Q(centre__region=region)
        return AffectationCentre.objects.filter(filtre_aff)

    @classmethod
    def collecter(cls, *, type_document, session, region=None, centre=None, parametres=None):
        parametres = parametres or {}
        affectations = cls._scope(session, region, centre)
        scope = {
            "session": session.nom,
            "code_session": session.code,
            "region": region.nom if region else "Toutes",
            "centre": centre.nom if centre else "Tous",
        }
        sections = [("Périmètre", scope)]

        if type_document == DocumentGenere.TypeDocument.CONSIGNES_ARRIVEE:
            if centre is None:
                raise ValidationDocumentsErreur(
                    "Le centre est obligatoire pour générer les consignes d'arrivée."
                )
            regle = RegleOrganisationCentre.objects.filter(
                session=session, centre=centre, deleted_at__isnull=True
            ).exclude(statut=RegleOrganisationCentre.Statut.ARCHIVEE).first()
            if regle is None:
                raise ValidationDocumentsErreur(
                    "Les règles d'organisation du centre sont introuvables."
                )
            articles = ArticleKitService.articles_pour_immerge(
                session_id=session.id, centre_id=centre.id
            )["a_apporter"]
            sections.extend([
                ("Session", {
                    "nom": session.nom,
                    "code": session.code,
                    "date_debut": session.date_debut,
                    "date_fin": session.date_fin,
                    "directives_generales": session.parametres.directives_generales,
                    "consignes_generales": session.parametres.consignes_generales,
                    "documents_exiges": session.parametres.documents_exiges,
                }),
                ("Accueil", {
                    "centre": centre.nom,
                    "ville": centre.ville,
                    "adresse": centre.adresse,
                    "lieu_accueil": regle.lieu_accueil,
                    "heure_accueil": regle.heure_accueil,
                    "horaires_generaux": regle.horaires_generaux,
                }),
                ("Consignes du centre", {
                    "accueil": regle.consignes_accueil,
                    "hebergement": (
                        regle.consignes_hebergement
                        if session.parametres.hebergement_active else "Non applicable"
                    ),
                    "kits": regle.consignes_kits_a_apporter,
                    "repas": (
                        regle.consignes_repas
                        if session.parametres.repas_active else "Non applicable"
                    ),
                    "discipline": regle.regles_discipline,
                    "directives_locales": regle.directives_locales,
                }),
                ("Articles à apporter", [
                    {
                        "designation": article.designation,
                        "quantite": article.quantite,
                        "unite": article.unite,
                        "obligatoire": article.obligatoire,
                    }
                    for article in articles
                ]),
            ])
        elif type_document == DocumentGenere.TypeDocument.FEUILLE_PRESENCE:
            seance_id = parametres.get("seance_id")
            if not seance_id:
                raise ValidationDocumentsErreur(
                    "Le paramètre seance_id est obligatoire pour une feuille de présence."
                )
            seance = Seance.objects.select_related(
                "session", "centre", "module_activite", "section", "groupe", "formateur"
            ).get(id=seance_id, deleted_at__isnull=True)
            if seance.session_id != session.id:
                raise ValidationDocumentsErreur("La séance n'appartient pas à la session demandée.")
            if centre and seance.centre_id != centre.id:
                raise ValidationDocumentsErreur("La séance n'appartient pas au centre demandé.")
            if region and seance.centre.region_id != region.id:
                raise ValidationDocumentsErreur("La séance n'appartient pas à la région demandée.")
            presences = {
                p.affectation_centre_id: p
                for p in Presence.objects.filter(
                    seance=seance, deleted_at__isnull=True
                )
            }
            lignes = []
            for aff in CandidatActiviteRepository.pour_seance(seance):
                identite = IdentiteImmergeService.donnees(aff.immerge)
                presence = presences.get(aff.id)
                lignes.append({
                    "code_fasoim": aff.immerge.code_fasoim,
                    "nom_complet": identite["nom_complet"],
                    "statut_presence": (
                        presence.statut_presence if presence else "NON_SAISI"
                    ),
                    "heure_arrivee": (presence.heure_arrivee if presence else ""),
                    "observation": (presence.observations if presence else ""),
                })
            sections.extend([
                ("Séance", {
                    "titre": seance.titre,
                    "module": seance.module_activite.titre,
                    "centre": seance.centre.nom,
                    "date": seance.date_seance,
                    "heure_debut": seance.heure_debut,
                    "heure_fin": seance.heure_fin,
                    "lieu": seance.lieu,
                    "section": seance.section.nom if seance.section_id else "",
                    "groupe": seance.groupe.nom if seance.groupe_id else "",
                    "formateur": (
                        seance.formateur.nom_complet if seance.formateur_id else ""
                    ),
                    "statut_feuille": seance.statut_feuille_presence,
                }),
                ("Liste", lignes),
            ])
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_IMPORT:
            imports = ImportOfficiel.objects.filter(session=session, deleted_at__isnull=True)
            lignes = list(imports.values("id", "nom_fichier_original", "type_source", "statut", "total_lignes", "lignes_valides", "lignes_erreur", "lignes_importees"))
            sections.append(("Imports officiels", lignes))
        elif type_document in {
            DocumentGenere.TypeDocument.RAPPORT_CENTRE,
            DocumentGenere.TypeDocument.RAPPORT_REGIONAL,
            DocumentGenere.TypeDocument.RAPPORT_NATIONAL,
        }:
            synthese = {
                "immerges_affectes": affectations.count(),
                "centres": affectations.values("centre_id").distinct().count(),
                "regions": affectations.values("centre__region_id").distinct().count(),
                "resultats_eligibles": ResultatFinal.objects.filter(session=session, centre__in=affectations.values("centre"), decision=ResultatFinal.Decision.ELIGIBLE, deleted_at__isnull=True).count(),
                "resultats_non_eligibles": ResultatFinal.objects.filter(session=session, centre__in=affectations.values("centre"), decision=ResultatFinal.Decision.NON_ELIGIBLE, deleted_at__isnull=True).count(),
                "incidents_ouverts": AlerteIncident.objects.filter(session=session, statut__in=AlerteIncident.STATUTS_OUVERTS, deleted_at__isnull=True).filter(Q(centre__in=affectations.values("centre")) | Q(centre__isnull=True)).count(),
            }
            sections.append(("Synthèse", synthese))
            par_centre = list(affectations.values("centre__code", "centre__nom", "centre__region__nom").annotate(effectif=Count("id")).order_by("centre__nom"))
            sections.append(("Effectifs par centre", par_centre))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_PRESENCES:
            qs = Presence.objects.filter(seance__session=session, affectation_centre__in=affectations, deleted_at__isnull=True)
            sections.append(("Présences", {row["statut_presence"]: row["total"] for row in qs.values("statut_presence").annotate(total=Count("id"))}))
            sections.append(("Séances", {"total": Seance.objects.filter(session=session, centre__in=affectations.values("centre"), deleted_at__isnull=True).count(), "feuilles_cloturees": Seance.objects.filter(session=session, centre__in=affectations.values("centre"), statut_feuille_presence=Seance.StatutFeuillePresence.CLOTUREE, deleted_at__isnull=True).count()}))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_EVALUATIONS:
            evaluations = Evaluation.objects.filter(session=session, centre__in=affectations.values("centre"), deleted_at__isnull=True)
            notes = Note.objects.filter(evaluation__in=evaluations, affectation_centre__in=affectations, deleted_at__isnull=True)
            sections.append(("Évaluations", {row["statut"]: row["total"] for row in evaluations.values("statut").annotate(total=Count("id"))}))
            sections.append(("Notes", {row["statut_note"]: row["total"] for row in notes.values("statut_note").annotate(total=Count("id"))}))
            resultats = ResultatFinal.objects.filter(session=session, centre__in=affectations.values("centre"), deleted_at__isnull=True, evaluation_active=True)
            sections.append(("Moyennes finales", list(resultats.values("immerge__code_fasoim", "centre__nom", "moyenne_sur_20", "decision")[:5000])))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_KITS:
            remises = RemiseKit.objects.filter(affectation_centre__in=affectations, deleted_at__isnull=True)
            sections.append(("Remises de kits", {row["statut_remise"]: row["total"] for row in remises.values("statut_remise").annotate(total=Count("id"))}))
            sections.append(("Articles", list(ArticleKit.objects.filter(session=session, deleted_at__isnull=True).values("designation", "type_kit", "quantite", "unite", "centre__nom"))))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_REPAS:
            statistiques = RepasJournalierRepository.statistiques(
                session_id=session.id,
                region_id=region.id if region else None,
                centre_id=centre.id if centre else None,
            )
            repas = RepasJournalierRepository.filtrer(
                session_id=session.id,
                region_id=region.id if region else None,
                centre_id=centre.id if centre else None,
            )
            sections.append(("Statistiques de restauration", statistiques))
            sections.append(("Statuts", {
                row["statut"]: row["total"]
                for row in repas.values("statut").annotate(total=Count("id"))
            }))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_INCIDENTS:
            incidents = AlerteIncident.objects.filter(session=session, deleted_at__isnull=True)
            if centre:
                incidents = incidents.filter(
                    Q(centre=centre) | Q(affectation_centre__centre=centre)
                )
            elif region:
                incidents = incidents.filter(
                    Q(region=region) | Q(centre__region=region)
                )
            sections.append((
                "Synthèse des incidents",
                AlerteIncidentRepository.statistiques(queryset=incidents),
            ))
        elif type_document == DocumentGenere.TypeDocument.RAPPORT_ATTESTATIONS:
            resultats = ResultatFinal.objects.filter(session=session, deleted_at__isnull=True)
            if centre:
                resultats = resultats.filter(centre=centre)
            elif region:
                resultats = resultats.filter(region=region)
            sections.append(("Résultats finaux", ResultatFinalRepository.statistiques(resultats)))
            docs = DocumentGenere.objects.filter(session=session, type_document=DocumentGenere.TypeDocument.ATTESTATION, deleted_at__isnull=True)
            if centre:
                docs = docs.filter(centre=centre)
            elif region:
                docs = docs.filter(region=region)
            sections.append(("Documents", {row["statut"]: row["total"] for row in docs.values("statut").annotate(total=Count("id"))}))
        elif type_document == DocumentGenere.TypeDocument.SYNTHESE_MEDICALE:
            visites = VisiteMedicaleRepository.validees().filter(session=session)
            if centre:
                visites = visites.filter(centre=centre)
            elif region:
                visites = visites.filter(centre__region=region)
            sections.append(("Résultats administratifs", {row["resultat"]: row["total"] for row in visites.values("resultat").annotate(total=Count("id"))}))
        elif type_document == DocumentGenere.TypeDocument.LISTE_IMMERGES:
            lignes = []
            for aff in affectations.select_related("immerge", "centre", "centre__region")[:5000]:
                identite = IdentiteImmergeService.donnees(aff.immerge)
                lignes.append({"code_fasoim": aff.immerge.code_fasoim, "nom_complet": identite["nom_complet"], "type": aff.immerge.type_immerge, "region": aff.centre.region.nom, "centre": aff.centre.nom})
            sections.append(("Immergés", lignes))
        else:
            raise ValidationDocumentsErreur("Type de rapport non pris en charge.")
        return sections

    @classmethod
    @transaction.atomic
    def generer(cls, *, type_document, format_fichier, session_id, acteur, region_id=None, centre_id=None, parametres=None):
        session = SessionImmersion.objects.get(id=session_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.verifier_session_traitable(session)
        types_centre = {
            DocumentGenere.TypeDocument.CONSIGNES_ARRIVEE,
            DocumentGenere.TypeDocument.RAPPORT_CENTRE,
        }
        if type_document in types_centre and not centre_id:
            raise ValidationDocumentsErreur("Un centre est obligatoire pour ce type de document.")
        if type_document == DocumentGenere.TypeDocument.RAPPORT_REGIONAL and not region_id:
            raise ValidationDocumentsErreur("Une région est obligatoire pour un rapport régional.")
        if type_document == DocumentGenere.TypeDocument.RAPPORT_NATIONAL and (region_id or centre_id):
            raise ValidationDocumentsErreur("Un rapport national ne doit pas être limité à une région ou un centre.")
        region = None
        centre = None
        if centre_id:
            centre = CentreImmersion.objects.select_related("region").get(id=centre_id, deleted_at__isnull=True)
            region = centre.region
        elif region_id:
            from affectations.models import RegionImmersion
            region = RegionImmersion.objects.get(id=region_id, deleted_at__isnull=True)
        ControleAccesDocumentsService.exiger(
            acteur,
            "generer_rapports",
            session_id=session.id,
            region_code=region.code if region else None,
            centre_id=centre.id if centre else None,
        )
        cle_brute = json.dumps({"type": type_document, "format": format_fichier, "session": session.id, "region": region_id, "centre": centre_id, "parametres": parametres or {}}, sort_keys=True, default=str)
        cle = "RAPPORT:" + hashlib.sha256(cle_brute.encode()).hexdigest()
        existant = DocumentGenere.objects.filter(cle_generation=cle, deleted_at__isnull=True).exclude(statut=DocumentGenere.Statut.ECHEC).first()
        if existant:
            return existant
        document = DocumentGenere(
            type_document=type_document,
            format_fichier=format_fichier,
            titre=dict(DocumentGenere.TypeDocument.choices).get(type_document, type_document),
            cle_generation=cle,
            session=session,
            region=region,
            centre=centre,
            statut=DocumentGenere.Statut.EN_GENERATION,
            visibilite=DocumentGenere.Visibilite.PERIMETRE_INTERNE,
            parametres_generation=parametres or {},
            genere_par=acteur,
        )
        document.save()
        try:
            sections = cls.collecter(type_document=type_document, session=session, region=region, centre=centre, parametres=parametres)
            if format_fichier == DocumentGenere.Format.PDF:
                contenu = GenerationFichierService.pdf_rapport(titre=document.titre, sections=sections)
                extension = "pdf"
            elif format_fichier == DocumentGenere.Format.XLSX:
                contenu = GenerationFichierService.xlsx(titre=document.titre, sections=sections)
                extension = "xlsx"
            elif format_fichier == DocumentGenere.Format.CSV:
                contenu = GenerationFichierService.csv(titre=document.titre, sections=sections)
                extension = "csv"
            else:
                raise ValidationDocumentsErreur("Format non pris en charge.")
            document.resume_generation = {"sections": len(sections)}
            document.statut = DocumentGenere.Statut.GENERE
            GenerationFichierService.enregistrer(document, contenu, extension=extension)
            NotificationService.planifier_rapport_disponible(
                acteur=acteur,
                rapport_reference=document.numero_document,
                type_rapport=document.get_type_document_display(),
                url_telechargement=f"{getattr(settings, 'FASOIM_PUBLIC_URL', '').rstrip('/')}/documents/{document.id}",
                session=session,
                region=region,
                centre=centre,
                objet=document,
            )
            JournalActionService.journaliser_export(
                acteur=acteur, code_action="generer_rapport",
                resultat=JournalAction.Resultat.SUCCES, objet=document,
                session=session, region=region, centre=centre,
                contexte={"type_document": type_document, "format": format_fichier},
                motif="Rapport généré avec succès.",
            )
            return document
        except Exception as exc:
            document.statut = DocumentGenere.Statut.ECHEC
            document.message_erreur = str(exc)
            document.save(update_fields=["statut", "message_erreur", "updated_at"])
            JournalActionService.journaliser_export(
                acteur=acteur, code_action="generer_rapport",
                resultat=JournalAction.Resultat.ECHEC, objet=document,
                session=session, region=region, centre=centre,
                contexte={"type_document": type_document, "format": format_fichier},
                motif=str(exc),
            )
            raise


class AttestationPubliqueService:
    @classmethod
    def consulter_immerge(cls, *, immerge, request=None):
        affectation = InformationsArriveeService._affectation_active(immerge)
        if affectation is None:
            raise ValidationDocumentsErreur("Aucune affectation centre active n'est disponible.")
        publication = PublicationOfficielleRepository.publication_active_centre(
            session_id=immerge.session_id,
            centre_id=affectation.centre_id,
            type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
        )
        if publication is None:
            raise ValidationDocumentsErreur("Les attestations ne sont pas encore publiées.")
        resultat = ResultatFinal.objects.filter(
            session=immerge.session,
            immerge=immerge,
            statut=ResultatFinal.Statut.PUBLIE,
            deleted_at__isnull=True,
        ).first()
        if resultat is None:
            raise ValidationDocumentsErreur("Le résultat final n'est pas disponible.")
        reponse = {
            "publication": {
                "reference": publication.reference,
                "version": publication.version,
                "date_publication": publication.date_publication,
            },
            "code_fasoim": immerge.code_fasoim,
            "decision": resultat.decision,
            "attestation_disponible": False,
        }
        document = None
        if resultat.decision == ResultatFinal.Decision.ELIGIBLE:
            document = DocumentGenere.objects.filter(
                resultat_final=resultat,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                statut=DocumentGenere.Statut.PUBLIE,
                deleted_at__isnull=True,
            ).first()
            if document:
                reponse.update({
                    "attestation_disponible": True,
                    "numero_document": document.numero_document,
                    "code_verification": document.code_verification,
                    "date_publication": document.date_publication,
                    "url_telechargement": (
                        f"/api/documents/public/attestations/{document.code_verification}/telecharger/"
                    ),
                })
        JournalActionService.journaliser_consultation_immerge(
            immerge=immerge,
            session=immerge.session,
            region=affectation.centre.region,
            centre=affectation.centre,
            code_action="consulter_attestation_publique",
            resultat=JournalAction.Resultat.SUCCES,
            motif="Disponibilité de l'attestation consultée.",
            informations_consultees=[
                "decision", "disponibilite_attestation", "numero_document"
            ],
            request=request,
        )
        return reponse

    @staticmethod
    def verifier(*, code="", numero="", journaliser=True, request=None):
        document = None
        if code:
            document = DocumentGenereRepository.get_par_code_verification(code)
        elif numero:
            document = DocumentGenereRepository.get_par_numero(numero)
        if document is None or document.type_document != DocumentGenere.TypeDocument.ATTESTATION:
            return {"valide": False, "statut": "INTROUVABLE"}
        statut_public = document.statut in {
            DocumentGenere.Statut.PUBLIE,
            DocumentGenere.Statut.REMPLACE,
            DocumentGenere.Statut.ANNULE,
        }
        if not statut_public:
            return {"valide": False, "statut": "NON_PUBLIEE"}
        integrite = False
        if document.fichier:
            try:
                with document.fichier.open("rb") as fichier:
                    integrite = hashlib.sha256(fichier.read()).hexdigest() == document.hash_sha256
            except OSError:
                integrite = False
        identite = IdentiteImmergeService.donnees(document.immerge)
        valide = document.statut == DocumentGenere.Statut.PUBLIE and integrite
        resultat = {
            "valide": valide,
            "statut": document.statut,
            "integrite": integrite,
            "numero_document": document.numero_document,
            "nom_complet": identite["nom_complet"],
            "code_fasoim": document.immerge.code_fasoim,
            "session": document.session.nom,
            "date_delivrance": document.date_publication,
            "signataire": document.nom_signataire_snapshot,
            "fonction_signataire": document.fonction_signataire_snapshot,
        }
        if journaliser:
            JournalActionService.journaliser_consultation_immerge(
                immerge=document.immerge,
                session=document.session,
                region=document.region,
                centre=document.centre,
                code_action="verifier_attestation_qr",
                resultat=JournalAction.Resultat.SUCCES if valide else JournalAction.Resultat.REFUS,
                motif="Vérification publique d'une attestation.",
                informations_consultees=[
                    "validite", "numero_document", "identite_minimale",
                    "session", "date_delivrance", "signataire",
                ],
                request=request,
            )
        return resultat


class SessionClotureService:
    """Vérifie tous les traitements dépendant de la session avant TERMINEE."""

    @classmethod
    def verifier(cls, session):
        etat = EtatCloture(session_id=session.id)
        parametres = session.parametres

        if timezone.localdate() < session.date_fin:
            etat.ajouter(
                "sessions_app",
                "DATE_FIN_NON_ATTEINTE",
                "La date de fin de la session n'est pas atteinte.",
            )

        imports_en_cours = ImportOfficiel.objects.filter(
            session=session, deleted_at__isnull=True
        ).exclude(
            statut__in=[
                ImportOfficiel.Statut.TERMINE,
                ImportOfficiel.Statut.ANNULE,
                ImportOfficiel.Statut.ECHEC,
            ]
        ).count()
        if imports_en_cours:
            etat.ajouter(
                "imports_app",
                "IMPORTS_NON_TERMINES",
                "Des imports officiels ne sont pas terminés.",
                imports_en_cours,
            )

        immerges_actifs = Immerge.objects.filter(
            session=session, deleted_at__isnull=True
        ).exclude(statut=Immerge.Statut.ANNULE)
        total_immerges = immerges_actifs.count()

        sans_region = immerges_actifs.exclude(
            affectations_regionales__session=session,
            affectations_regionales__statut=AffectationRegionale.Statut.ACTIVE,
            affectations_regionales__deleted_at__isnull=True,
        ).distinct().count()
        if sans_region:
            etat.ajouter(
                "affectations",
                "IMMERGES_SANS_REGION_ACTIVE",
                "Des immergés n'ont pas d'affectation régionale active.",
                sans_region,
            )

        sans_centre = immerges_actifs.exclude(
            affectations_centres__session=session,
            affectations_centres__statut=AffectationCentre.Statut.ACTIVE,
            affectations_centres__deleted_at__isnull=True,
        ).distinct().count()
        if sans_centre:
            etat.ajouter(
                "affectations",
                "IMMERGES_SANS_CENTRE_ACTIF",
                "Des immergés n'ont pas d'affectation centre active.",
                sans_centre,
            )

        affectations_ouvertes = AffectationRegionale.objects.filter(
            session=session,
            statut=AffectationRegionale.Statut.PROPOSEE,
            deleted_at__isnull=True,
        ).count()
        affectations_ouvertes += AffectationCentre.objects.filter(
            session=session,
            statut=AffectationCentre.Statut.PROPOSEE,
            deleted_at__isnull=True,
        ).count()
        if affectations_ouvertes:
            etat.ajouter(
                "affectations",
                "AFFECTATIONS_NON_VALIDEES",
                "Des affectations restent proposées.",
                affectations_ouvertes,
            )

        if total_immerges and not parametres.consultation_publique_active:
            etat.ajouter(
                "sessions_app",
                "CONSULTATION_PUBLIQUE_DESACTIVEE",
                "La consultation publique des informations avant l'arrivée doit être activée.",
            )

        centres = PublicationService._centres_attendus(session)
        for centre in centres:
            regle_pret = RegleOrganisationCentre.objects.filter(
                session=session,
                centre=centre,
                statut=RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
                deleted_at__isnull=True,
            ).exists()
            if not regle_pret:
                etat.ajouter(
                    "organisation",
                    "ORGANISATION_NON_PRETE",
                    f"L'organisation du centre {centre.nom} n'est pas prête.",
                )

            pub_arrivee = PublicationOfficielleRepository.publication_active_centre(
                session_id=session.id,
                centre_id=centre.id,
                type_publication=PublicationOfficielle.TypePublication.INFORMATIONS_ARRIVEE,
            )
            if pub_arrivee is None:
                etat.ajouter(
                    "documents",
                    "INFORMATIONS_ARRIVEE_NON_PUBLIEES",
                    f"Les informations d'arrivée du centre {centre.nom} ne sont pas publiées.",
                )

            centre_etat = CentreCertificationService.verifier(
                session=session, centre=centre
            )
            for blocage in centre_etat["blocages"]:
                etat.ajouter(
                    "centre",
                    blocage["code"],
                    f"{centre.nom} : {blocage['message']}",
                    blocage.get("total"),
                )

        incidents = AlerteIncident.objects.filter(
            session=session,
            est_bloquante=True,
            statut__in=AlerteIncident.STATUTS_OUVERTS,
            deleted_at__isnull=True,
        ).count()
        if incidents:
            etat.ajouter(
                "incidents",
                "INCIDENTS_BLOQUANTS",
                "Des incidents bloquants restent ouverts.",
                incidents,
            )

        if parametres.attestation_active:
            total_affectations = AffectationCentre.objects.filter(
                session=session,
                statut=AffectationCentre.Statut.ACTIVE,
                deleted_at__isnull=True,
            ).count()
            resultats = ResultatFinal.objects.filter(
                session=session, deleted_at__isnull=True
            )
            total_resultats = resultats.count()
            if total_resultats != total_affectations:
                etat.ajouter(
                    "documents",
                    "RESULTATS_FINAUX_INCOMPLETS",
                    "Tous les immergés n'ont pas un résultat final.",
                    abs(total_affectations - total_resultats),
                )

            a_verifier = resultats.filter(
                decision=ResultatFinal.Decision.A_VERIFIER
            ).count()
            if a_verifier:
                etat.ajouter(
                    "documents",
                    "RESULTATS_A_VERIFIER",
                    "Des résultats finaux restent à vérifier.",
                    a_verifier,
                )

            eligibles = resultats.filter(
                decision=ResultatFinal.Decision.ELIGIBLE
            ).count()
            attestations_publiees = DocumentGenere.objects.filter(
                session=session,
                type_document=DocumentGenere.TypeDocument.ATTESTATION,
                statut=DocumentGenere.Statut.PUBLIE,
                resultat_final__decision=ResultatFinal.Decision.ELIGIBLE,
                deleted_at__isnull=True,
            ).count()
            if attestations_publiees != eligibles:
                etat.ajouter(
                    "documents",
                    "ATTESTATIONS_ELIGIBLES_NON_PUBLIEES",
                    "Toutes les attestations des immergés éligibles ne sont pas publiées.",
                    abs(eligibles - attestations_publiees),
                )

            publications_attestations = (
                PublicationOfficielleRepository.centres_session(
                    session_id=session.id,
                    type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
                )
                .filter(statut=PublicationOfficielle.Statut.PUBLIEE)
                .values("centre_id")
                .distinct()
                .count()
            )
            if publications_attestations != len(centres):
                etat.ajouter(
                    "documents",
                    "ATTESTATIONS_NON_PUBLIEES",
                    "Toutes les attestations ne sont pas publiées par la DGAS.",
                    abs(len(centres) - publications_attestations),
                )

            publication_nationale = PublicationOfficielle.objects.filter(
                session=session,
                type_publication=PublicationOfficielle.TypePublication.ATTESTATIONS,
                perimetre=PublicationOfficielle.Perimetre.NATIONAL,
                statut=PublicationOfficielle.Statut.PUBLIEE,
                deleted_at__isnull=True,
            ).exists()
            if not publication_nationale and centres:
                etat.ajouter(
                    "documents",
                    "PUBLICATION_NATIONALE_ATTESTATIONS_ABSENTE",
                    "La publication nationale des attestations n'est pas effectuée.",
                )

        etat.resume = {
            "immerges": total_immerges,
            "centres": len(centres),
            "blocages": len(etat.blocages),
        }
        return etat
