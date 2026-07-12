from __future__ import annotations

from django.conf import settings
from django.db.models import Count, F, Q

from affectations.models import AffectationCentre
from kits.models import ArticleKit, RemiseKit
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "KIT_REMISE_OBLIGATOIRE_ABSENTE",
    "KIT_REMISE_INCOMPLETE",
    "KIT_REMISE_INCOHERENTE",
    "KIT_REMISE_DUPLIQUEE",
)


def _limite():
    return int(getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500))


def detecter():
    limite = _limite()
    affectations = AffectationCentre.objects.filter(
        statut=AffectationCentre.Statut.ACTIVE,
        deleted_at__isnull=True,
        session__statut=SessionImmersion.Statut.EN_COURS,
        session__deleted_at__isnull=True,
    ).select_related("session", "centre")[:limite]

    for affectation in affectations:
        articles = ArticleKit.objects.filter(
            session_id=affectation.session_id,
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
            obligatoire=True,
            statut=ArticleKit.Statut.ACTIF,
            deleted_at__isnull=True,
        ).filter(Q(centre_id=affectation.centre_id) | Q(centre__isnull=True))
        for article in articles[:limite]:
            remise = RemiseKit.objects.filter(
                affectation_centre_id=affectation.id,
                article_kit_id=article.id,
                deleted_at__isnull=True,
            ).first()
            if not remise:
                yield Anomalie(
                    code="KIT_REMISE_OBLIGATOIRE_ABSENTE",
                    cle=f"KIT_REMISE_OBLIGATOIRE_ABSENTE:{affectation.id}:{article.id}",
                    titre="Article obligatoire non préparé pour remise",
                    description=f"L'article obligatoire « {article.designation} » ne possède aucune remise active.",
                    categorie=AlerteIncident.Categorie.KIT,
                    gravite=AlerteIncident.NiveauGravite.ELEVE,
                    type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                    session_id=affectation.session_id,
                    centre_id=affectation.centre_id,
                    affectation_centre_id=affectation.id,
                    module_source="kits",
                    modele_source="ArticleKit",
                    objet_source_id=article.id,
                    est_bloquante=True,
                )
                continue
            if remise.statut_remise in {
                RemiseKit.StatutRemise.PARTIEL,
                RemiseKit.StatutRemise.NON_REMIS,
            } or remise.quantite_remise < remise.quantite_prevue:
                yield Anomalie(
                    code="KIT_REMISE_INCOMPLETE",
                    cle=f"KIT_REMISE_INCOMPLETE:{remise.id}",
                    titre="Remise de kit obligatoire incomplète",
                    description=(
                        f"La remise de « {article.designation} » reste partielle ou non effectuée "
                        f"({remise.quantite_remise}/{remise.quantite_prevue})."
                    ),
                    categorie=AlerteIncident.Categorie.KIT,
                    gravite=AlerteIncident.NiveauGravite.ELEVE,
                    type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                    session_id=affectation.session_id,
                    centre_id=affectation.centre_id,
                    affectation_centre_id=affectation.id,
                    module_source="kits",
                    modele_source="RemiseKit",
                    objet_source_id=remise.id,
                    est_bloquante=True,
                )

    for remise in RemiseKit.objects.filter(deleted_at__isnull=True).select_related(
        "affectation_centre", "article_kit"
    )[:limite]:
        ac = remise.affectation_centre
        article = remise.article_kit
        incoherent = (
            article.session_id != ac.session_id
            or (article.centre_id is not None and article.centre_id != ac.centre_id)
            or article.type_kit != ArticleKit.TypeKit.A_REMETTRE
        )
        if incoherent:
            yield Anomalie(
                code="KIT_REMISE_INCOHERENTE",
                cle=f"KIT_REMISE_INCOHERENTE:{remise.id}",
                titre="Remise de kit hors périmètre",
                description="La session, le centre ou le type de l'article ne correspond pas à l'affectation centre.",
                categorie=AlerteIncident.Categorie.KIT,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                session_id=ac.session_id,
                centre_id=ac.centre_id,
                affectation_centre_id=ac.id,
                module_source="kits",
                modele_source="RemiseKit",
                objet_source_id=remise.id,
                est_bloquante=True,
            )

    doublons = (
        RemiseKit.objects.filter(deleted_at__isnull=True)
        .values("affectation_centre_id", "article_kit_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)[:limite]
    )
    for ligne in doublons:
        ac = AffectationCentre.objects.filter(id=ligne["affectation_centre_id"]).first()
        yield Anomalie(
            code="KIT_REMISE_DUPLIQUEE",
            cle=f"KIT_REMISE_DUPLIQUEE:{ligne['affectation_centre_id']}:{ligne['article_kit_id']}",
            titre="Remise de kit dupliquée",
            description="Plusieurs remises actives existent pour le même article et le même immergé.",
            categorie=AlerteIncident.Categorie.KIT,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ac.session_id if ac else None,
            centre_id=ac.centre_id if ac else None,
            affectation_centre_id=ac.id if ac else None,
            module_source="kits",
            modele_source="RemiseKit",
            est_bloquante=True,
            contexte={"nombre_remises": ligne["total"]},
        )
