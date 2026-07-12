from __future__ import annotations

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery

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


def _taille_lot():
    return int(
        getattr(
            settings,
            "INCIDENTS_TAILLE_LOT_SCAN",
            getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500),
        )
    )


def detecter():
    taille_lot = _taille_lot()

    # On parcourt les articles obligatoires puis on annote les affectations
    # concernées avec leur remise. Cela évite une requête par combinaison
    # affectation/article, qui devenait prohibitive avec plusieurs milliers
    # d'immergés.
    articles = ArticleKit.objects.filter(
        type_kit=ArticleKit.TypeKit.A_REMETTRE,
        obligatoire=True,
        statut=ArticleKit.Statut.ACTIF,
        deleted_at__isnull=True,
        session__statut=SessionImmersion.Statut.EN_COURS,
        session__deleted_at__isnull=True,
    ).only("id", "session_id", "centre_id", "designation")

    for article in articles.iterator(chunk_size=taille_lot):
        remise_active = RemiseKit.objects.filter(
            affectation_centre_id=OuterRef("pk"),
            article_kit_id=article.id,
            deleted_at__isnull=True,
        ).order_by("id")

        affectations = AffectationCentre.objects.filter(
            session_id=article.session_id,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )
        if article.centre_id is not None:
            affectations = affectations.filter(centre_id=article.centre_id)

        affectations = affectations.annotate(
            remise_id=Subquery(remise_active.values("id")[:1]),
            remise_statut=Subquery(remise_active.values("statut_remise")[:1]),
            remise_quantite_prevue=Subquery(remise_active.values("quantite_prevue")[:1]),
            remise_quantite=Subquery(remise_active.values("quantite_remise")[:1]),
        ).only("id", "session_id", "centre_id")

        for affectation in affectations.iterator(chunk_size=taille_lot):
            if affectation.remise_id is None:
                yield Anomalie(
                    code="KIT_REMISE_OBLIGATOIRE_ABSENTE",
                    cle=f"KIT_REMISE_OBLIGATOIRE_ABSENTE:{affectation.id}:{article.id}",
                    titre="Article obligatoire non préparé pour remise",
                    description=(
                        f"L'article obligatoire « {article.designation} » ne possède "
                        "aucune remise active."
                    ),
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

            if (
                affectation.remise_statut
                in {
                    RemiseKit.StatutRemise.PARTIEL,
                    RemiseKit.StatutRemise.NON_REMIS,
                }
                or (affectation.remise_quantite or 0)
                < (affectation.remise_quantite_prevue or 0)
            ):
                yield Anomalie(
                    code="KIT_REMISE_INCOMPLETE",
                    cle=f"KIT_REMISE_INCOMPLETE:{affectation.remise_id}",
                    titre="Remise de kit obligatoire incomplète",
                    description=(
                        f"La remise de « {article.designation} » reste partielle ou non "
                        f"effectuée ({affectation.remise_quantite or 0}/"
                        f"{affectation.remise_quantite_prevue or 0})."
                    ),
                    categorie=AlerteIncident.Categorie.KIT,
                    gravite=AlerteIncident.NiveauGravite.ELEVE,
                    type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
                    session_id=affectation.session_id,
                    centre_id=affectation.centre_id,
                    affectation_centre_id=affectation.id,
                    module_source="kits",
                    modele_source="RemiseKit",
                    objet_source_id=affectation.remise_id,
                    est_bloquante=True,
                )

    for remise in (
        RemiseKit.objects.filter(deleted_at__isnull=True)
        .select_related("affectation_centre", "article_kit")
        .iterator(chunk_size=taille_lot)
    ):
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
                description=(
                    "La session, le centre ou le type de l'article ne correspond pas "
                    "à l'affectation centre."
                ),
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
        .values(
            "affectation_centre_id",
            "affectation_centre__session_id",
            "affectation_centre__centre_id",
            "article_kit_id",
        )
        .annotate(total=Count("id"))
        .filter(total__gt=1)
        .iterator(chunk_size=taille_lot)
    )
    for ligne in doublons:
        yield Anomalie(
            code="KIT_REMISE_DUPLIQUEE",
            cle=(
                "KIT_REMISE_DUPLIQUEE:"
                f"{ligne['affectation_centre_id']}:{ligne['article_kit_id']}"
            ),
            titre="Remise de kit dupliquée",
            description=(
                "Plusieurs remises actives existent pour le même article et le même immergé."
            ),
            categorie=AlerteIncident.Categorie.KIT,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.IMMERGE,
            session_id=ligne["affectation_centre__session_id"],
            centre_id=ligne["affectation_centre__centre_id"],
            affectation_centre_id=ligne["affectation_centre_id"],
            module_source="kits",
            modele_source="RemiseKit",
            est_bloquante=True,
            contexte={"nombre_remises": ligne["total"]},
        )
