from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import AffectationActeur

from .models import AlerteIncident


class AlerteIncidentRepository:
    """Accès aux alertes et incidents sans logique métier de transition."""

    @staticmethod
    def base_queryset():
        return (
            AlerteIncident.objects.filter(deleted_at__isnull=True)
            .select_related(
                "session",
                "region",
                "centre",
                "centre__region",
                "affectation_centre",
                "affectation_centre__immerge",
                "acteur_concerne",
                "cree_par",
                "traite_par",
            )
        )

    @classmethod
    def get_by_id(cls, incident_id):
        return cls.base_queryset().filter(id=incident_id).first()

    @classmethod
    def get_by_id_pour_update(cls, incident_id):
        return (
            cls.base_queryset()
            .select_for_update(of=("self",))
            .filter(id=incident_id)
            .first()
        )

    @classmethod
    def get_ouvert_par_cle_pour_update(cls, cle):
        return (
            cls.base_queryset()
            .select_for_update(of=("self",))
            .filter(
                cle_deduplication=cle,
                statut__in=AlerteIncident.STATUTS_OUVERTS,
            )
            .first()
        )

    @classmethod
    def filtrer(
        cls,
        *,
        session_id=None,
        region_id=None,
        centre_id=None,
        categorie=None,
        niveau_gravite=None,
        statut=None,
        origine=None,
        type_incident=None,
        cree_par_id=None,
        traite_par_id=None,
        est_bloquante=None,
        code_detection=None,
        recherche=None,
    ):
        qs = cls.base_queryset()
        if session_id:
            qs = qs.filter(session_id=session_id)
        if region_id:
            qs = qs.filter(region_id=region_id)
        if centre_id:
            qs = qs.filter(centre_id=centre_id)
        if categorie:
            qs = qs.filter(categorie=categorie)
        if niveau_gravite:
            qs = qs.filter(niveau_gravite=niveau_gravite)
        if statut:
            qs = qs.filter(statut=statut)
        if origine:
            qs = qs.filter(origine=origine)
        if type_incident:
            qs = qs.filter(type=type_incident)
        if cree_par_id:
            qs = qs.filter(cree_par_id=cree_par_id)
        if traite_par_id:
            qs = qs.filter(traite_par_id=traite_par_id)
        if est_bloquante is not None:
            qs = qs.filter(est_bloquante=est_bloquante)
        if code_detection:
            qs = qs.filter(code_detection=code_detection)
        if recherche:
            qs = qs.filter(
                Q(titre__icontains=recherche)
                | Q(description__icontains=recherche)
                | Q(code_detection__icontains=recherche)
            )
        return qs

    @classmethod
    def visibles_pour(cls, acteur):
        if acteur is None or not getattr(acteur, "is_authenticated", False):
            return cls.base_queryset().none()
        if getattr(acteur, "is_superuser", False):
            return cls.base_queryset()

        aujourd_hui = timezone.localdate()
        affectations = AffectationActeur.objects.filter(
            acteur_id=acteur.id,
            statut=AffectationActeur.Statut.ACTIVE,
            deleted_at__isnull=True,
            date_debut__lte=aujourd_hui,
        ).filter(Q(date_fin__isnull=True) | Q(date_fin__gte=aujourd_hui))

        condition = Q(cree_par_id=acteur.id) | Q(traite_par_id=acteur.id)
        for affectation in affectations.only(
            "niveau_affectation",
            "session_id",
            "region_code",
            "centre_id",
        ):
            portee = Q()
            if affectation.session_id:
                portee &= Q(session_id=affectation.session_id)

            if affectation.niveau_affectation in {
                AffectationActeur.NiveauAffectation.PLATEFORME,
                AffectationActeur.NiveauAffectation.NATIONAL,
            }:
                # Une affectation plateforme/nationale sans session couvre tout.
                if not affectation.session_id:
                    return cls.base_queryset()
                condition |= portee
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
                condition |= portee & (
                    Q(region__code__iexact=affectation.region_code)
                    | Q(centre__region__code__iexact=affectation.region_code)
                )
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE:
                condition |= portee & Q(centre_id=affectation.centre_id)

        return cls.base_queryset().filter(condition).distinct()

    @classmethod
    def statistiques(cls, *, queryset=None, session_id=None, centre_id=None):
        # ``queryset`` permet à l'API de calculer uniquement dans le périmètre
        # visible de l'acteur et évite toute fuite de statistiques globales.
        qs = queryset if queryset is not None else cls.base_queryset()
        if session_id:
            qs = qs.filter(session_id=session_id)
        if centre_id:
            qs = qs.filter(centre_id=centre_id)

        par_statut = {
            ligne["statut"]: ligne["total"]
            for ligne in qs.values("statut").annotate(total=Count("id"))
        }
        par_gravite = {
            ligne["niveau_gravite"]: ligne["total"]
            for ligne in qs.values("niveau_gravite").annotate(total=Count("id"))
        }
        par_categorie = {
            ligne["categorie"]: ligne["total"]
            for ligne in qs.values("categorie").annotate(total=Count("id"))
        }
        return {
            "total": qs.count(),
            "ouverts": qs.filter(statut__in=AlerteIncident.STATUTS_OUVERTS).count(),
            "bloquants_ouverts": qs.filter(
                statut__in=AlerteIncident.STATUTS_OUVERTS,
                est_bloquante=True,
            ).count(),
            "par_statut": par_statut,
            "par_gravite": par_gravite,
            "par_categorie": par_categorie,
        }

    @classmethod
    def ouverts_a_escalader(cls):
        maintenant = timezone.now()
        return cls.base_queryset().filter(
            statut__in=AlerteIncident.STATUTS_OUVERTS,
        ).filter(
            Q(
                niveau_gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                date_signalement__lte=maintenant - timedelta(minutes=15),
            )
            | Q(
                niveau_gravite=AlerteIncident.NiveauGravite.ELEVE,
                date_signalement__lte=maintenant - timedelta(minutes=30),
            )
            | Q(
                niveau_gravite=AlerteIncident.NiveauGravite.MOYEN,
                date_signalement__lte=maintenant - timedelta(hours=2),
            )
        )
