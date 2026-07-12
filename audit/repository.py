from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.models import AffectationActeur
from accounts.repository import ControleAccesRepository

from .models import JournalAction


class JournalActionRepository:
    """Lecture, filtrage, périmètres et statistiques du journal central."""

    ACTIONS_CONSULTATION_IMMERGE = {
        "rechercher_affectation_publique",
        "consulter_affectation_publique",
        "telecharger_fiche_affectation",
        "consulter_attestation",
        "telecharger_attestation",
        "verifier_attestation_qr",
    }
    ACTIONS_INFORMATION_IMMERGE = {
        "envoyer_information_immerge",
        "informer_relais_etablissement",
        "information_immerge_delivree",
    }
    ACTIONS_ATTESTATION = {
        "consulter_attestation",
        "telecharger_attestation",
        "verifier_attestation_qr",
        "publier_attestations",
        "generer_attestations",
        "soumettre_attestations_dgas",
    }
    ACTIONS_RAPPORT = {
        "demander_export_rapport",
        "generer_export_rapport",
        "telecharger_export_rapport",
        "echec_export_rapport",
        "exporter_journaux_audit",
    }

    @staticmethod
    def base_queryset():
        return JournalAction.objects.select_related(
            "acteur",
            "immerge",
            "session",
            "region",
            "centre",
        ).all()

    @staticmethod
    def visibles_par_acteur(acteur, code_permission="consulter_journaux_audit"):
        queryset = JournalActionRepository.base_queryset()
        if not acteur or not getattr(acteur, "is_authenticated", False):
            return queryset.none()
        if getattr(acteur, "is_superuser", False):
            return queryset

        affectations = AffectationActeur.objects.filter(
            acteur_id=acteur.id,
            statut=AffectationActeur.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).select_related("session")

        filtre_total = Q()
        autorisation_trouvee = False
        for affectation in affectations:
            if not affectation.est_active:
                continue
            if not ControleAccesRepository.acteur_a_permission(
                acteur,
                affectation,
                code_permission,
            ):
                continue

            autorisation_trouvee = True
            filtre = Q()
            if affectation.session_id:
                filtre &= Q(session_id=affectation.session_id)

            if affectation.niveau_affectation in {
                AffectationActeur.NiveauAffectation.PLATEFORME,
                AffectationActeur.NiveauAffectation.NATIONAL,
            }:
                filtre_total |= filtre
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.REGION:
                filtre_total |= filtre & (
                    Q(region__code__iexact=affectation.region_code)
                    | Q(centre__region__code__iexact=affectation.region_code)
                )
            elif affectation.niveau_affectation == AffectationActeur.NiveauAffectation.CENTRE:
                filtre_total |= filtre & Q(centre_id=affectation.centre_id)

        if not autorisation_trouvee:
            return queryset.none()
        return queryset.filter(filtre_total).distinct()

    @staticmethod
    def filtrer(queryset, params):
        valeurs = params or {}
        champs_entiers = {
            "acteur": "acteur_id",
            "immerge": "immerge_id",
            "session": "session_id",
            "region": "region_id",
            "centre": "centre_id",
            "objet_id": "objet_id",
        }
        for parametre, champ in champs_entiers.items():
            valeur = valeurs.get(parametre)
            if valeur not in (None, ""):
                try:
                    queryset = queryset.filter(**{champ: int(valeur)})
                except (TypeError, ValueError):
                    return queryset.none()

        champs_textes = {
            "origine": "origine",
            "resultat": "resultat",
            "canal": "canal",
            "module": "module_source",
            "code_action": "code_action",
            "objet_type": "objet_type",
            "task_id": "task_id",
        }
        for parametre, champ in champs_textes.items():
            valeur = str(valeurs.get(parametre) or "").strip()
            if valeur:
                queryset = queryset.filter(**{f"{champ}__iexact": valeur})

        recherche = str(valeurs.get("recherche") or "").strip()
        if recherche:
            queryset = queryset.filter(
                Q(code_action__icontains=recherche)
                | Q(module_source__icontains=recherche)
                | Q(motif__icontains=recherche)
                | Q(objet_type__icontains=recherche)
                | Q(objet_reference__icontains=recherche)
                | Q(acteur__username__icontains=recherche)
                | Q(acteur__first_name__icontains=recherche)
                | Q(acteur__last_name__icontains=recherche)
            )

        date_debut = JournalActionRepository._date(valeurs.get("date_debut"), fin=False)
        date_fin = JournalActionRepository._date(valeurs.get("date_fin"), fin=True)
        if date_debut:
            queryset = queryset.filter(created_at__gte=date_debut)
        if date_fin:
            queryset = queryset.filter(created_at__lte=date_fin)

        ordre = str(valeurs.get("ordering") or "-created_at").strip()
        ordres_autorises = {
            "created_at",
            "-created_at",
            "code_action",
            "-code_action",
            "resultat",
            "-resultat",
            "module_source",
            "-module_source",
        }
        return queryset.order_by(ordre if ordre in ordres_autorises else "-created_at")

    @staticmethod
    def _date(valeur, *, fin):
        if not valeur:
            return None
        texte = str(valeur)
        instant = parse_datetime(texte)
        if instant:
            if timezone.is_naive(instant):
                instant = timezone.make_aware(instant)
            return instant
        jour = parse_date(texte)
        if not jour:
            return None
        instant = timezone.make_aware(
            timezone.datetime.combine(
                jour,
                timezone.datetime.max.time() if fin else timezone.datetime.min.time(),
            )
        )
        return instant

    @staticmethod
    def statistiques_generales(queryset):
        synthese = queryset.aggregate(
            total=Count("id"),
            succes=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
            refus=Count("id", filter=Q(resultat=JournalAction.Resultat.REFUS)),
            echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
            partiels=Count("id", filter=Q(resultat=JournalAction.Resultat.PARTIEL)),
            acteurs_distincts=Count("acteur_id", distinct=True),
            immerges_distincts=Count("immerge_id", distinct=True),
        )
        par_origine = list(
            queryset.values("origine").annotate(total=Count("id")).order_by("origine")
        )
        par_module = list(
            queryset.values("module_source")
            .annotate(total=Count("id"))
            .order_by("-total", "module_source")[:20]
        )
        actions_frequentes = list(
            queryset.values("code_action")
            .annotate(total=Count("id"))
            .order_by("-total", "code_action")[:20]
        )
        depuis = timezone.now() - timedelta(days=30)
        evolution = list(
            queryset.filter(created_at__gte=depuis)
            .annotate(jour=TruncDate("created_at"))
            .values("jour")
            .annotate(total=Count("id"))
            .order_by("jour")
        )
        return {
            "synthese": synthese,
            "par_origine": par_origine,
            "par_module": par_module,
            "actions_frequentes": actions_frequentes,
            "evolution_30_jours": evolution,
        }

    @staticmethod
    def statistiques_immerges(queryset):
        consultations = queryset.filter(
            code_action__in=JournalActionRepository.ACTIONS_CONSULTATION_IMMERGE
        )
        informations = queryset.filter(
            code_action__in=JournalActionRepository.ACTIONS_INFORMATION_IMMERGE
        )
        return {
            "informations": informations.aggregate(
                total=Count("id"),
                envoyees=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
                echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
                immerges_distincts=Count("immerge_id", distinct=True),
            ),
            "consultations": consultations.aggregate(
                total=Count("id"),
                reussies=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
                refusees=Count("id", filter=Q(resultat=JournalAction.Resultat.REFUS)),
                echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
                immerges_distincts=Count("immerge_id", distinct=True),
            ),
            "par_action": list(
                consultations.values("code_action", "resultat")
                .annotate(total=Count("id"))
                .order_by("code_action", "resultat")
            ),
        }

    @staticmethod
    def statistiques_documents(queryset):
        attestations = queryset.filter(
            code_action__in=JournalActionRepository.ACTIONS_ATTESTATION
        )
        rapports = queryset.filter(code_action__in=JournalActionRepository.ACTIONS_RAPPORT)
        return {
            "attestations": attestations.aggregate(
                total=Count("id"),
                succes=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
                echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
                immerges_ayant_consulte=Count(
                    "immerge_id",
                    filter=Q(code_action="consulter_attestation", resultat=JournalAction.Resultat.SUCCES),
                    distinct=True,
                ),
                immerges_ayant_telecharge=Count(
                    "immerge_id",
                    filter=Q(code_action="telecharger_attestation", resultat=JournalAction.Resultat.SUCCES),
                    distinct=True,
                ),
                verifications_qr_reussies=Count(
                    "id",
                    filter=Q(code_action="verifier_attestation_qr", resultat=JournalAction.Resultat.SUCCES),
                ),
            ),
            "rapports_exports": rapports.aggregate(
                total=Count("id"),
                succes=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
                echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
                acteurs_distincts=Count("acteur_id", distinct=True),
            ),
            "par_action": list(
                queryset.filter(
                    Q(code_action__in=JournalActionRepository.ACTIONS_ATTESTATION)
                    | Q(code_action__in=JournalActionRepository.ACTIONS_RAPPORT)
                )
                .values("code_action", "resultat")
                .annotate(total=Count("id"))
                .order_by("code_action", "resultat")
            ),
        }

    @staticmethod
    def statistiques_systeme(queryset):
        systeme = queryset.filter(
            origine__in=[
                JournalAction.Origine.SYSTEME,
                JournalAction.Origine.CELERY,
                JournalAction.Origine.ADMIN,
            ]
        )
        return {
            "synthese": systeme.aggregate(
                total=Count("id"),
                succes=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
                echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
                partiels=Count("id", filter=Q(resultat=JournalAction.Resultat.PARTIEL)),
                duree_moyenne_ms=Avg("duree_ms"),
            ),
            "par_module": list(
                systeme.values("module_source", "resultat")
                .annotate(total=Count("id"))
                .order_by("module_source", "resultat")
            ),
            "taches_celery": list(
                systeme.filter(origine=JournalAction.Origine.CELERY)
                .values("code_action", "resultat")
                .annotate(total=Count("id"), duree_moyenne_ms=Avg("duree_ms"))
                .order_by("code_action", "resultat")
            ),
        }
