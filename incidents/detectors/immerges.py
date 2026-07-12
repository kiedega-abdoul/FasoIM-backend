from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Exists, OuterRef
from django.utils import timezone

from affectations.models import AffectationCentre, AffectationRegionale
from immerges.models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
    SourceImporteeBase,
)
from imports_app.models import ImportOfficiel
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "IMM_SOURCE_VALIDEE_NON_CENTRALISEE",
    "IMM_VOLONTAIRE_ACCEPTE_NON_CENTRALISE",
    "IMM_ORIGINE_INTROUVABLE",
    "IMM_CODE_OU_QR_ABSENT",
    "IMM_SANS_AFFECTATION_REGIONALE",
    "IMM_SANS_AFFECTATION_CENTRE",
    "IMM_STATUT_AFFECTATION_INCOHERENT",
)


def _limite():
    return int(getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500))


def _anomalie_source(source, type_immerge):
    return Anomalie(
        code="IMM_SOURCE_VALIDEE_NON_CENTRALISEE",
        cle=f"IMM_SOURCE_VALIDEE_NON_CENTRALISEE:{type_immerge}:{source.id}",
        titre="Source validée non centralisée",
        description="Une ligne source validée n'a pas produit la ligne centrale immergée attendue.",
        categorie=AlerteIncident.Categorie.IMPORT,
        gravite=AlerteIncident.NiveauGravite.ELEVE,
        type_concerne=AlerteIncident.TypeConcerne.DONNEE,
        session_id=source.import_officiel.session_id,
        module_source="immerges",
        modele_source=source.__class__.__name__,
        objet_source_id=source.id,
        est_bloquante=True,
        contexte={"type_immerge": type_immerge},
    )


def detecter():
    aujourd_hui = timezone.localdate()
    limite = _limite()

    sources = (
        (
            ImmergeExamen,
            [ImportOfficiel.TypeSource.BEPC, ImportOfficiel.TypeSource.BAC],
            [Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC],
        ),
        (
            ImmergeConcours,
            [ImportOfficiel.TypeSource.CONCOURS],
            [Immerge.TypeImmerge.CONCOURS],
        ),
        (
            ImmergeSelectionne,
            [ImportOfficiel.TypeSource.SELECTIONNES],
            [Immerge.TypeImmerge.SELECTIONNE],
        ),
    )
    for modele, types_source, types_immerge in sources:
        qs = modele.objects.filter(
            statut_validation=SourceImporteeBase.StatutValidation.VALIDE,
            import_officiel__type_source__in=types_source,
            import_officiel__statut=ImportOfficiel.Statut.TERMINE,
            import_officiel__deleted_at__isnull=True,
            deleted_at__isnull=True,
        )
        for source in qs.select_related("import_officiel")[:limite]:
            type_immerge = types_immerge[0]
            if isinstance(source, ImmergeExamen):
                type_immerge = (
                    Immerge.TypeImmerge.BEPC
                    if source.type_examen == ImmergeExamen.TypeExamen.BEPC
                    else Immerge.TypeImmerge.BAC
                )
            existe = Immerge.objects.filter(
                session_id=source.import_officiel.session_id,
                type_immerge=type_immerge,
                origine_id=source.id,
                deleted_at__isnull=True,
            ).exists()
            if not existe:
                yield _anomalie_source(source, type_immerge)

    volontaires = InscriptionVolontaire.objects.filter(
        statut_demande=InscriptionVolontaire.StatutDemande.ACCEPTEE,
        deleted_at__isnull=True,
    ).select_related("session")[:limite]
    for source in volontaires:
        if not Immerge.objects.filter(
            session_id=source.session_id,
            type_immerge=Immerge.TypeImmerge.VOLONTAIRE,
            origine_id=source.id,
            deleted_at__isnull=True,
        ).exists():
            yield Anomalie(
                code="IMM_VOLONTAIRE_ACCEPTE_NON_CENTRALISE",
                cle=f"IMM_VOLONTAIRE_ACCEPTE_NON_CENTRALISE:{source.id}",
                titre="Volontaire accepté non centralisé",
                description="Une inscription volontaire acceptée n'a pas produit la ligne centrale immergée.",
                categorie=AlerteIncident.Categorie.IMPORT,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                session_id=source.session_id,
                module_source="immerges",
                modele_source="InscriptionVolontaire",
                objet_source_id=source.id,
                est_bloquante=True,
            )

    mapping = {
        Immerge.TypeImmerge.BEPC: ImmergeExamen,
        Immerge.TypeImmerge.BAC: ImmergeExamen,
        Immerge.TypeImmerge.CONCOURS: ImmergeConcours,
        Immerge.TypeImmerge.SELECTIONNE: ImmergeSelectionne,
        Immerge.TypeImmerge.VOLONTAIRE: InscriptionVolontaire,
    }
    for immerge in Immerge.objects.filter(deleted_at__isnull=True).select_related("session")[:limite]:
        modele_source = mapping.get(immerge.type_immerge)
        source_existe = bool(modele_source and modele_source.objects.filter(
            id=immerge.origine_id,
            deleted_at__isnull=True,
        ).exists())
        if not source_existe:
            yield Anomalie(
                code="IMM_ORIGINE_INTROUVABLE",
                cle=f"IMM_ORIGINE_INTROUVABLE:{immerge.id}",
                titre="Origine d'un immergé introuvable",
                description="La ligne centrale immergée ne retrouve plus sa donnée source active.",
                categorie=AlerteIncident.Categorie.IMPORT,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=immerge.session_id,
                module_source="immerges",
                modele_source="Immerge",
                objet_source_id=immerge.id,
                est_bloquante=True,
            )

        if immerge.statut != Immerge.Statut.CREE and (not immerge.code_fasoim or not immerge.qr_code):
            yield Anomalie(
                code="IMM_CODE_OU_QR_ABSENT",
                cle=f"IMM_CODE_OU_QR_ABSENT:{immerge.id}",
                titre="Code FasoIM ou QR code absent",
                description="Un immergé ayant avancé dans le workflow ne possède pas son code et son QR code complets.",
                categorie=AlerteIncident.Categorie.SYSTEME,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=immerge.session_id,
                module_source="immerges",
                modele_source="Immerge",
                objet_source_id=immerge.id,
                est_bloquante=True,
            )

        session = immerge.session
        if session.statut not in {
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        }:
            continue

        region_active = AffectationRegionale.objects.filter(
            immerge_id=immerge.id,
            statut=AffectationRegionale.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).first()
        centre_actif = AffectationCentre.objects.filter(
            immerge_id=immerge.id,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).select_related("centre").first()

        region_exigee = session.statut == SessionImmersion.Statut.EN_COURS or (
            session.date_debut <= aujourd_hui + timedelta(days=7)
        )
        centre_exige = session.statut == SessionImmersion.Statut.EN_COURS or (
            session.date_debut <= aujourd_hui + timedelta(days=3)
        )
        if region_exigee and not region_active:
            yield Anomalie(
                code="IMM_SANS_AFFECTATION_REGIONALE",
                cle=f"IMM_SANS_AFFECTATION_REGIONALE:{immerge.id}",
                titre="Immergé sans affectation régionale",
                description="La session approche ou a commencé mais l'immergé ne possède aucune affectation régionale active.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=(
                    AlerteIncident.NiveauGravite.CRITIQUE
                    if session.statut == SessionImmersion.Statut.EN_COURS
                    else AlerteIncident.NiveauGravite.ELEVE
                ),
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=session.id,
                module_source="immerges",
                modele_source="Immerge",
                objet_source_id=immerge.id,
                est_bloquante=session.statut == SessionImmersion.Statut.EN_COURS,
            )
        elif centre_exige and region_active and not centre_actif:
            yield Anomalie(
                code="IMM_SANS_AFFECTATION_CENTRE",
                cle=f"IMM_SANS_AFFECTATION_CENTRE:{immerge.id}",
                titre="Immergé sans affectation centre",
                description="La session approche ou a commencé mais l'immergé n'a aucun centre actif.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=(
                    AlerteIncident.NiveauGravite.CRITIQUE
                    if session.statut == SessionImmersion.Statut.EN_COURS
                    else AlerteIncident.NiveauGravite.ELEVE
                ),
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=session.id,
                module_source="immerges",
                modele_source="Immerge",
                objet_source_id=immerge.id,
                est_bloquante=session.statut == SessionImmersion.Statut.EN_COURS,
            )

        incoherent = (
            immerge.statut == Immerge.Statut.AFFECTE_REGION and not region_active
            or immerge.statut in {Immerge.Statut.AFFECTE_CENTRE, Immerge.Statut.EN_IMMERSION} and not centre_actif
            or centre_actif and not region_active
        )
        if incoherent:
            yield Anomalie(
                code="IMM_STATUT_AFFECTATION_INCOHERENT",
                cle=f"IMM_STATUT_AFFECTATION_INCOHERENT:{immerge.id}",
                titre="Statut de l'immergé incohérent avec ses affectations",
                description="Le statut central ne correspond pas aux affectations régionales ou centre actives.",
                categorie=AlerteIncident.Categorie.AFFECTATION,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=session.id,
                centre_id=centre_actif.centre_id if centre_actif else None,
                affectation_centre_id=centre_actif.id if centre_actif else None,
                module_source="immerges",
                modele_source="Immerge",
                objet_source_id=immerge.id,
            )
