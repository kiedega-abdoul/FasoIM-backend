from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Q
from django.utils import timezone

from affectations.models import AffectationCentre
from organisation.models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "ORG_REGLES_CENTRE_ABSENTES",
    "ORG_REGLES_NON_PRETES",
    "ORG_IMMERGE_SANS_GROUPE",
    "ORG_AFFECTATION_GROUPE_A_REORGANISER",
    "ORG_GROUPE_SURCAPACITE",
    "ORG_SECTION_SURCAPACITE",
    "ORG_IMMERGE_SANS_LIT",
    "ORG_ATTRIBUTION_LIT_A_REORGANISER",
    "ORG_LIT_HORS_SERVICE_OCCUPE",
    "ORG_DORTOIR_HORS_SERVICE_OCCUPE",
    "ORG_ATTRIBUTION_HORS_CENTRE",
)


def _limite():
    return int(getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500))


def detecter():
    aujourd_hui = timezone.localdate()
    limite = _limite()
    affectations = AffectationCentre.objects.filter(
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
        session__statut__in=[
            SessionImmersion.Statut.EN_PREPARATION,
            SessionImmersion.Statut.EN_COURS,
        ],
        session__deleted_at__isnull=True,
    ).select_related("session__parametres", "centre")[:limite]

    couples = {(a.session_id, a.centre_id): a for a in affectations}
    for (session_id, centre_id), exemple in couples.items():
        regle = RegleOrganisationCentre.objects.filter(
            session_id=session_id,
            centre_id=centre_id,
            deleted_at__isnull=True,
        ).first()
        if not regle:
            yield Anomalie(
                code="ORG_REGLES_CENTRE_ABSENTES",
                cle=f"ORG_REGLES_CENTRE_ABSENTES:{session_id}:{centre_id}",
                titre="Centre sans règles d'organisation",
                description="Un centre recevant des immergés ne possède aucun paramétrage d'organisation actif.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=session_id,
                centre_id=centre_id,
                module_source="organisation",
                modele_source="RegleOrganisationCentre",
                est_bloquante=True,
            )
        elif (
            exemple.session.date_debut <= aujourd_hui + timedelta(days=2)
            and regle.statut not in {
                RegleOrganisationCentre.Statut.VALIDEE,
                RegleOrganisationCentre.Statut.PRETE_PUBLICATION,
            }
        ):
            yield Anomalie(
                code="ORG_REGLES_NON_PRETES",
                cle=f"ORG_REGLES_NON_PRETES:{session_id}:{centre_id}",
                titre="Organisation du centre non prête",
                description="La session débute bientôt mais les règles du centre ne sont pas validées ou prêtes à publier.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                session_id=session_id,
                centre_id=centre_id,
                module_source="organisation",
                modele_source="RegleOrganisationCentre",
                objet_source_id=regle.id,
                est_bloquante=exemple.session.statut == SessionImmersion.Statut.EN_COURS,
            )

    for affectation in affectations:
        groupe_ouvert = AffectationGroupe.objects.filter(
            affectation_centre_id=affectation.id,
            statut__in=[
                AffectationGroupe.Statut.PROPOSEE,
                AffectationGroupe.Statut.ACTIVE,
                AffectationGroupe.Statut.A_REORGANISER,
            ],
            deleted_at__isnull=True,
        ).exists()
        groupe_exige = affectation.session.statut == SessionImmersion.Statut.EN_COURS or (
            affectation.session.date_debut <= aujourd_hui + timedelta(days=1)
        )
        if groupe_exige and not groupe_ouvert:
            yield Anomalie(
                code="ORG_IMMERGE_SANS_GROUPE",
                cle=f"ORG_IMMERGE_SANS_GROUPE:{affectation.id}",
                titre="Immergé sans groupe",
                description="L'affectation centre ne possède aucune affectation de groupe ouverte.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                affectation_centre_id=affectation.id,
                module_source="organisation",
                modele_source="AffectationGroupe",
                est_bloquante=affectation.session.statut == SessionImmersion.Statut.EN_COURS,
            )

        parametres = getattr(affectation.session, "parametres", None)
        if parametres and parametres.hebergement_active:
            lit_ouvert = AttributionLit.objects.filter(
                affectation_centre_id=affectation.id,
                statut__in=[
                    AttributionLit.Statut.PROPOSEE,
                    AttributionLit.Statut.ACTIVE,
                    AttributionLit.Statut.A_REORGANISER,
                ],
                deleted_at__isnull=True,
            ).exists()
            lit_exige = affectation.session.statut == SessionImmersion.Statut.EN_COURS or (
                affectation.session.date_debut <= aujourd_hui + timedelta(days=1)
            )
            if lit_exige and not lit_ouvert:
                yield Anomalie(
                    code="ORG_IMMERGE_SANS_LIT",
                    cle=f"ORG_IMMERGE_SANS_LIT:{affectation.id}",
                    titre="Immergé sans lit",
                    description="L'hébergement est actif mais aucune attribution de lit ouverte n'existe.",
                    categorie=AlerteIncident.Categorie.ORGANISATION,
                    gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                    type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                    session_id=affectation.session_id,
                    centre_id=affectation.centre_id,
                    affectation_centre_id=affectation.id,
                    module_source="organisation",
                    modele_source="AttributionLit",
                    est_bloquante=affectation.session.statut == SessionImmersion.Statut.EN_COURS,
                )

    for affectation in AffectationGroupe.objects.filter(
        statut=AffectationGroupe.Statut.A_REORGANISER,
        deleted_at__isnull=True,
    ).select_related("affectation_centre")[:limite]:
        ac = affectation.affectation_centre
        yield Anomalie(
            code="ORG_AFFECTATION_GROUPE_A_REORGANISER",
            cle=f"ORG_AFFECTATION_GROUPE_A_REORGANISER:{affectation.id}",
            titre="Affectation de groupe à réorganiser",
            description="Une décision médicale ou opérationnelle exige une nouvelle affectation de groupe.",
            categorie=AlerteIncident.Categorie.ORGANISATION,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id,
            centre_id=ac.centre_id,
            affectation_centre_id=ac.id,
            module_source="organisation",
            modele_source="AffectationGroupe",
            objet_source_id=affectation.id,
            est_bloquante=True,
        )

    groupes = Groupe.objects.filter(
        statut=Groupe.Statut.ACTIF,
        deleted_at__isnull=True,
    ).annotate(
        effectif=Count(
            "affectations",
            filter=Q(
                affectations__statut__in=[
                    AffectationGroupe.Statut.PROPOSEE,
                    AffectationGroupe.Statut.ACTIVE,
                    AffectationGroupe.Statut.A_REORGANISER,
                ],
                affectations__deleted_at__isnull=True,
            ),
        )
    ).filter(effectif__gt=F("capacite_max")).select_related("section")[:limite]
    for groupe in groupes:
        yield Anomalie(
            code="ORG_GROUPE_SURCAPACITE",
            cle=f"ORG_GROUPE_SURCAPACITE:{groupe.id}",
            titre=f"Groupe en surcapacité : {groupe.code}",
            description=f"Le groupe compte {groupe.effectif} affectations ouvertes pour {groupe.capacite_max} places.",
            categorie=AlerteIncident.Categorie.ORGANISATION,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            session_id=groupe.section.session_id,
            centre_id=groupe.section.centre_id,
            module_source="organisation",
            modele_source="Groupe",
            objet_source_id=groupe.id,
            est_bloquante=True,
            contexte={"effectif": groupe.effectif, "capacite": groupe.capacite_max},
        )

    sections = Section.objects.filter(
        statut=Section.Statut.ACTIVE,
        deleted_at__isnull=True,
    ).annotate(
        effectif=Count(
            "groupes__affectations",
            filter=Q(
                groupes__affectations__statut__in=[
                    AffectationGroupe.Statut.PROPOSEE,
                    AffectationGroupe.Statut.ACTIVE,
                    AffectationGroupe.Statut.A_REORGANISER,
                ],
                groupes__affectations__deleted_at__isnull=True,
            ),
        )
    ).filter(effectif__gt=F("capacite_max"))[:limite]
    for section in sections:
        yield Anomalie(
            code="ORG_SECTION_SURCAPACITE",
            cle=f"ORG_SECTION_SURCAPACITE:{section.id}",
            titre=f"Section en surcapacité : {section.code}",
            description=f"La section compte {section.effectif} affectations ouvertes pour {section.capacite_max} places.",
            categorie=AlerteIncident.Categorie.ORGANISATION,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.CENTRE,
            session_id=section.session_id,
            centre_id=section.centre_id,
            module_source="organisation",
            modele_source="Section",
            objet_source_id=section.id,
            est_bloquante=True,
        )

    for attribution in AttributionLit.objects.filter(
        statut=AttributionLit.Statut.A_REORGANISER,
        deleted_at__isnull=True,
    ).select_related("affectation_centre")[:limite]:
        ac = attribution.affectation_centre
        yield Anomalie(
            code="ORG_ATTRIBUTION_LIT_A_REORGANISER",
            cle=f"ORG_ATTRIBUTION_LIT_A_REORGANISER:{attribution.id}",
            titre="Attribution de lit à réorganiser",
            description="Une décision médicale ou opérationnelle exige une nouvelle attribution de lit.",
            categorie=AlerteIncident.Categorie.ORGANISATION,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id,
            centre_id=ac.centre_id,
            affectation_centre_id=ac.id,
            module_source="organisation",
            modele_source="AttributionLit",
            objet_source_id=attribution.id,
            est_bloquante=True,
        )

    attributions = AttributionLit.objects.filter(
        statut__in=[AttributionLit.Statut.PROPOSEE, AttributionLit.Statut.ACTIVE],
        deleted_at__isnull=True,
    ).select_related("lit__dortoir", "affectation_centre")[:limite]
    for attribution in attributions:
        ac = attribution.affectation_centre
        lit = attribution.lit
        dortoir = lit.dortoir
        if lit.statut != Lit.Statut.DISPONIBLE or lit.deleted_at:
            yield Anomalie(
                code="ORG_LIT_HORS_SERVICE_OCCUPE",
                cle=f"ORG_LIT_HORS_SERVICE_OCCUPE:{attribution.id}",
                titre="Lit hors service encore attribué",
                description="Une attribution ouverte utilise un lit hors service, archivé ou supprimé.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=ac.session_id,
                centre_id=ac.centre_id,
                affectation_centre_id=ac.id,
                module_source="organisation",
                modele_source="AttributionLit",
                objet_source_id=attribution.id,
                est_bloquante=True,
            )
        if dortoir.statut != Dortoir.Statut.ACTIF or dortoir.deleted_at:
            yield Anomalie(
                code="ORG_DORTOIR_HORS_SERVICE_OCCUPE",
                cle=f"ORG_DORTOIR_HORS_SERVICE_OCCUPE:{attribution.id}",
                titre="Dortoir hors service encore occupé",
                description="Une attribution ouverte utilise un dortoir hors service, archivé ou supprimé.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=ac.session_id,
                centre_id=ac.centre_id,
                affectation_centre_id=ac.id,
                module_source="organisation",
                modele_source="AttributionLit",
                objet_source_id=attribution.id,
                est_bloquante=True,
            )
        if dortoir.centre_id != ac.centre_id:
            yield Anomalie(
                code="ORG_ATTRIBUTION_HORS_CENTRE",
                cle=f"ORG_ATTRIBUTION_HORS_CENTRE:{attribution.id}",
                titre="Lit attribué hors du centre de l'immergé",
                description="Le dortoir du lit n'appartient pas au centre de l'affectation.",
                categorie=AlerteIncident.Categorie.ORGANISATION,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=ac.session_id,
                centre_id=ac.centre_id,
                affectation_centre_id=ac.id,
                module_source="organisation",
                modele_source="AttributionLit",
                objet_source_id=attribution.id,
                est_bloquante=True,
            )
