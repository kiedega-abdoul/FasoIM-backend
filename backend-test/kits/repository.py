from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from affectations.models import AffectationCentre

from .models import ArticleKit, RemiseKit


class ArticleKitRepository:
    """Requêtes et persistance des articles de kits."""

    @staticmethod
    def base_queryset():
        return ArticleKit.objects.select_related(
            "session",
            "centre",
        )

    @classmethod
    def non_supprimes(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def actifs(cls):
        return cls.non_supprimes().filter(
            statut=ArticleKit.Statut.ACTIF,
        )

    @classmethod
    def get_by_id(cls, article_id: int):
        return cls.non_supprimes().get(id=article_id)

    @classmethod
    def get_by_id_pour_update(cls, article_id: int):
        return (
            ArticleKit.objects.select_for_update()
            .select_related("session", "centre")
            .get(
                id=article_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        type_kit=None,
        statut=None,
        obligatoire=None,
        recherche=None,
        inclure_globaux=True,
    ):
        queryset = cls.non_supprimes()

        if session_id:
            queryset = queryset.filter(session_id=session_id)

        if centre_id:
            if inclure_globaux:
                queryset = queryset.filter(
                    Q(centre_id=centre_id)
                    | Q(centre__isnull=True)
                )
            else:
                queryset = queryset.filter(centre_id=centre_id)

        if type_kit:
            queryset = queryset.filter(type_kit=type_kit)

        if statut:
            queryset = queryset.filter(statut=statut)

        if obligatoire is not None:
            queryset = queryset.filter(obligatoire=obligatoire)

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(designation__icontains=recherche)
                | Q(description__icontains=recherche)
                | Q(unite__icontains=recherche)
                | Q(session__code__icontains=recherche)
                | Q(session__nom__icontains=recherche)
                | Q(centre__code__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "ordre",
            "designation",
            "id",
        )

    @classmethod
    def applicables(
        cls,
        *,
        session_id: int,
        centre_id: int,
        type_kit=None,
        article_ids=None,
    ):
        queryset = cls.actifs().filter(
            session_id=session_id,
        ).filter(
            Q(centre__isnull=True)
            | Q(centre_id=centre_id)
        )

        if type_kit:
            queryset = queryset.filter(type_kit=type_kit)

        if article_ids is not None:
            queryset = queryset.filter(id__in=article_ids)

        return queryset.order_by(
            "ordre",
            "designation",
            "id",
        )

    @classmethod
    def a_apporter(cls, *, session_id: int, centre_id: int):
        return cls.applicables(
            session_id=session_id,
            centre_id=centre_id,
            type_kit=ArticleKit.TypeKit.A_APPORTER,
        )

    @classmethod
    def a_remettre(
        cls,
        *,
        session_id: int,
        centre_id: int,
        article_ids=None,
    ):
        return cls.applicables(
            session_id=session_id,
            centre_id=centre_id,
            type_kit=ArticleKit.TypeKit.A_REMETTRE,
            article_ids=article_ids,
        )

    @classmethod
    def existe_doublon(
        cls,
        *,
        session_id: int,
        centre_id,
        designation: str,
        type_kit: str,
        exclure_id=None,
    ):
        queryset = cls.non_supprimes().filter(
            session_id=session_id,
            centre_id=centre_id,
            designation__iexact=str(designation).strip(),
            type_kit=type_kit,
        )

        if exclure_id:
            queryset = queryset.exclude(id=exclure_id)

        return queryset.exists()

    @staticmethod
    def creer(**donnees):
        article = ArticleKit(**donnees)
        article.save()
        return article

    @staticmethod
    def sauvegarder(article, *, update_fields=None):
        article.save(update_fields=update_fields)
        return article

    @staticmethod
    def possede_remises(article_id: int):
        return RemiseKit.objects.filter(
            article_kit_id=article_id,
            deleted_at__isnull=True,
        ).exists()


class RemiseKitRepository:
    """Requêtes et persistance des remises de kits."""

    @staticmethod
    def base_queryset():
        return RemiseKit.objects.select_related(
            "affectation_centre",
            "affectation_centre__immerge",
            "affectation_centre__session",
            "affectation_centre__centre",
            "article_kit",
            "article_kit__session",
            "article_kit__centre",
            "remis_par",
        )

    @classmethod
    def actives(cls):
        return cls.base_queryset().filter(
            deleted_at__isnull=True,
        )

    @classmethod
    def get_by_id(cls, remise_id: int):
        return cls.actives().get(id=remise_id)

    @classmethod
    def get_by_id_pour_update(cls, remise_id: int):
        return (
            RemiseKit.objects.select_for_update()
            .select_related(
                "affectation_centre",
                "affectation_centre__immerge",
                "affectation_centre__session",
                "affectation_centre__centre",
                "article_kit",
                "article_kit__session",
                "article_kit__centre",
                "remis_par",
            )
            .get(
                id=remise_id,
                deleted_at__isnull=True,
            )
        )

    @classmethod
    def get_active_par_affectation_article(
        cls,
        *,
        affectation_centre_id: int,
        article_kit_id: int,
    ):
        return cls.actives().filter(
            affectation_centre_id=affectation_centre_id,
            article_kit_id=article_kit_id,
        ).first()

    @classmethod
    def lister_par_affectation(
        cls,
        affectation_centre_id: int,
    ):
        return cls.actives().filter(
            affectation_centre_id=affectation_centre_id,
        ).order_by(
            "article_kit__ordre",
            "article_kit__designation",
            "id",
        )

    @classmethod
    def lister_par_affectations(
        cls,
        affectation_centre_ids,
        *,
        article_kit_ids=None,
    ):
        queryset = cls.actives().filter(
            affectation_centre_id__in=affectation_centre_ids,
        )

        if article_kit_ids is not None:
            queryset = queryset.filter(
                article_kit_id__in=article_kit_ids,
            )

        return queryset.order_by(
            "affectation_centre_id",
            "article_kit__ordre",
            "article_kit__designation",
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        centre_id=None,
        affectation_centre_id=None,
        article_kit_id=None,
        statut_remise=None,
        remis_par_id=None,
        date_debut=None,
        date_fin=None,
        recherche=None,
    ):
        queryset = cls.actives()

        if session_id:
            queryset = queryset.filter(
                affectation_centre__session_id=session_id,
            )

        if centre_id:
            queryset = queryset.filter(
                affectation_centre__centre_id=centre_id,
            )

        if affectation_centre_id:
            queryset = queryset.filter(
                affectation_centre_id=affectation_centre_id,
            )

        if article_kit_id:
            queryset = queryset.filter(
                article_kit_id=article_kit_id,
            )

        if statut_remise:
            queryset = queryset.filter(
                statut_remise=statut_remise,
            )

        if remis_par_id:
            queryset = queryset.filter(
                remis_par_id=remis_par_id,
            )

        if date_debut:
            queryset = queryset.filter(
                date_remise__date__gte=date_debut,
            )

        if date_fin:
            queryset = queryset.filter(
                date_remise__date__lte=date_fin,
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(
                    affectation_centre__immerge__code_fasoim__icontains=(
                        recherche
                    )
                )
                | Q(article_kit__designation__icontains=recherche)
                | Q(
                    affectation_centre__centre__nom__icontains=(
                        recherche
                    )
                )
                | Q(observations__icontains=recherche)
            )

        return queryset.order_by("-date_remise", "-id")

    @classmethod
    def paires_existantes(
        cls,
        *,
        affectation_centre_ids,
        article_kit_ids,
    ):
        return set(
            cls.actives()
            .filter(
                affectation_centre_id__in=affectation_centre_ids,
                article_kit_id__in=article_kit_ids,
            )
            .values_list(
                "affectation_centre_id",
                "article_kit_id",
            )
        )

    @staticmethod
    def creer(**donnees):
        remise = RemiseKit(**donnees)
        remise.save()
        return remise

    @staticmethod
    def sauvegarder(remise, *, update_fields=None):
        remise.save(update_fields=update_fields)
        return remise

    @staticmethod
    def creer_en_masse(remises, *, batch_size=500):
        if not remises:
            return []

        return RemiseKit.objects.bulk_create(
            remises,
            batch_size=batch_size,
            ignore_conflicts=True,
        )

    @staticmethod
    def mettre_a_jour_en_masse(
        remises,
        champs,
        *,
        batch_size=500,
    ):
        if not remises:
            return 0

        RemiseKit.objects.bulk_update(
            remises,
            champs,
            batch_size=batch_size,
        )
        return len(remises)

    @classmethod
    def statistiques(
        cls,
        *,
        session_id=None,
        centre_id=None,
    ):
        queryset = cls.actives()

        if session_id:
            queryset = queryset.filter(
                affectation_centre__session_id=session_id,
            )

        if centre_id:
            queryset = queryset.filter(
                affectation_centre__centre_id=centre_id,
            )

        return queryset.values("statut_remise").annotate(
            total=Count("id"),
        ).order_by("statut_remise")

    @classmethod
    def supprimer_logiquement_en_masse(
        cls,
        *,
        affectation_centre_ids,
        article_kit_ids=None,
    ):
        queryset = RemiseKit.objects.filter(
            affectation_centre_id__in=affectation_centre_ids,
            deleted_at__isnull=True,
        )

        if article_kit_ids is not None:
            queryset = queryset.filter(
                article_kit_id__in=article_kit_ids,
            )

        maintenant = timezone.now()
        return queryset.update(
            deleted_at=maintenant,
            updated_at=maintenant,
        )


class CandidatRemiseKitRepository:
    """Affectations centre pouvant recevoir des kits."""

    @staticmethod
    def base_queryset():
        return AffectationCentre.objects.select_related(
            "immerge",
            "session",
            "session__parametres",
            "centre",
            "affectation_regionale",
        ).filter(
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id: int,
        centre_id: int,
        affectation_centre_ids=None,
        recherche=None,
    ):
        queryset = cls.base_queryset().filter(
            session_id=session_id,
            centre_id=centre_id,
        )

        if affectation_centre_ids is not None:
            queryset = queryset.filter(
                id__in=affectation_centre_ids,
            )

        if recherche:
            recherche = str(recherche).strip()
            queryset = queryset.filter(
                Q(immerge__code_fasoim__icontains=recherche)
                | Q(centre__nom__icontains=recherche)
            )

        return queryset.order_by(
            "immerge__code_fasoim",
            "id",
        )

    @classmethod
    def get_active(cls, affectation_centre_id: int):
        return cls.base_queryset().get(
            id=affectation_centre_id,
        )

    @classmethod
    def ids(
        cls,
        *,
        session_id: int,
        centre_id: int,
        affectation_centre_ids=None,
    ):
        return list(
            cls.filtrer(
                session_id=session_id,
                centre_id=centre_id,
                affectation_centre_ids=affectation_centre_ids,
            ).values_list("id", flat=True)
        )
