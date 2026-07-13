from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import (
    Acteur,
    AffectationActeur,
    AffectationRole,
)
from audit.models import JournalAction
from audit.repository import JournalActionRepository
from immerges.models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)


@dataclass(frozen=True)
class ContactEmail:
    email: str
    nom: str = ""
    acteur_id: int | None = None
    immerge_id: int | None = None
    etablissement: str = ""


class NotificationRepository:
    """Résout les destinataires sans stocker de notification."""

    @staticmethod
    def email_valide(email) -> str:
        valeur = str(email or "").strip().lower()
        if not valeur:
            return ""
        try:
            validate_email(valeur)
        except ValidationError:
            return ""
        return valeur

    @staticmethod
    def acteur(acteur_id) -> Acteur | None:
        return (
            Acteur.objects.filter(
                id=acteur_id,
                deleted_at__isnull=True,
            )
            .first()
        )

    @classmethod
    def contact_acteur(cls, acteur_ou_id) -> ContactEmail | None:
        acteur = acteur_ou_id if isinstance(acteur_ou_id, Acteur) else cls.acteur(acteur_ou_id)
        if not acteur:
            return None
        email = cls.email_valide(acteur.email)
        if not email:
            return None
        return ContactEmail(
            email=email,
            nom=acteur.nom_complet or acteur.username,
            acteur_id=acteur.id,
        )

    @staticmethod
    def source_immerge(immerge: Immerge):
        filtres = {"id": immerge.origine_id, "deleted_at__isnull": True}
        if immerge.type_immerge in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            return ImmergeExamen.objects.filter(**filtres).first()
        if immerge.type_immerge == Immerge.TypeImmerge.CONCOURS:
            return ImmergeConcours.objects.filter(**filtres).first()
        if immerge.type_immerge == Immerge.TypeImmerge.SELECTIONNE:
            return ImmergeSelectionne.objects.filter(**filtres).first()
        if immerge.type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
            return InscriptionVolontaire.objects.filter(**filtres).first()
        return None

    @classmethod
    def contact_immerge(cls, immerge_ou_id) -> ContactEmail | None:
        immerge = (
            immerge_ou_id
            if isinstance(immerge_ou_id, Immerge)
            else Immerge.objects.filter(id=immerge_ou_id, deleted_at__isnull=True)
            .select_related("session")
            .first()
        )
        if not immerge:
            return None
        source = cls.source_immerge(immerge)
        if not source:
            return None
        email = cls.email_valide(getattr(source, "email", ""))
        if not email:
            return None
        nom = getattr(source, "identite_affichable", "") or getattr(source, "nom_et_prenoms", "")
        return ContactEmail(
            email=email,
            nom=nom,
            immerge_id=immerge.id,
            etablissement=str(getattr(source, "etablissement_origine", "") or "").strip(),
        )

    @classmethod
    def contexte_examen(cls, immerge: Immerge):
        if immerge.type_immerge not in {Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC}:
            return None
        source = cls.source_immerge(immerge)
        if not source:
            return None
        etablissement = str(source.etablissement_origine or "").strip()
        if not etablissement:
            return None
        return {
            "session_id": immerge.session_id,
            "type_examen": source.type_examen,
            "etablissement": etablissement,
        }

    @classmethod
    def relais_etablissement(cls, *, session_id, type_examen, etablissement, exclure_immerge_ids=None, limite=3):
        """Retourne quelques élèves joignables du même établissement.

        Aucun détail concernant leurs camarades n'est renvoyé au relais. Le service
        construit uniquement un message collectif indiquant qu'une information est
        disponible sur le portail officiel.
        """
        etablissement = str(etablissement or "").strip()
        if not etablissement:
            return []
        sources = (
            ImmergeExamen.objects.filter(
                deleted_at__isnull=True,
                type_examen=type_examen,
                etablissement_origine__iexact=etablissement,
                import_officiel__session_id=session_id,
            )
            .exclude(email="")
            .order_by("id")
        )
        emails_vus = set()
        contacts = []
        exclusions = set(exclure_immerge_ids or [])
        for source in sources.iterator(chunk_size=200):
            email = cls.email_valide(source.email)
            if not email or email in emails_vus:
                continue
            immerge = Immerge.objects.filter(
                session_id=session_id,
                type_immerge__in=[Immerge.TypeImmerge.BEPC, Immerge.TypeImmerge.BAC],
                origine_id=source.id,
                deleted_at__isnull=True,
            ).only("id").first()
            if immerge and immerge.id in exclusions:
                continue
            emails_vus.add(email)
            contacts.append(
                ContactEmail(
                    email=email,
                    nom=source.identite_affichable,
                    immerge_id=immerge.id if immerge else None,
                    etablissement=etablissement,
                )
            )
            if len(contacts) >= max(1, int(limite or 3)):
                break
        return contacts

    @classmethod
    def acteurs_par_role(
        cls,
        code_role,
        *,
        session_id=None,
        region_code=None,
        centre_id=None,
    ) -> list[ContactEmail]:
        aujourd_hui = timezone.localdate()
        queryset = AffectationRole.objects.filter(
            role__code=code_role,
            role__deleted_at__isnull=True,
            statut=AffectationRole.Statut.ACTIF,
            deleted_at__isnull=True,
            date_attribution__lte=aujourd_hui,
            affectation_acteur__statut=AffectationActeur.Statut.ACTIVE,
            affectation_acteur__deleted_at__isnull=True,
            affectation_acteur__date_debut__lte=aujourd_hui,
            affectation_acteur__acteur__deleted_at__isnull=True,
            affectation_acteur__acteur__statut=Acteur.Statut.ACTIF,
            affectation_acteur__acteur__is_active=True,
        ).filter(Q(date_expiration__isnull=True) | Q(date_expiration__gte=aujourd_hui)).filter(
            Q(affectation_acteur__date_fin__isnull=True)
            | Q(affectation_acteur__date_fin__gte=aujourd_hui)
        ).select_related("affectation_acteur__acteur")

        if session_id is not None:
            queryset = queryset.filter(
                Q(affectation_acteur__session_id=session_id)
                | Q(affectation_acteur__session_id__isnull=True)
            )
        if region_code:
            queryset = queryset.filter(
                Q(affectation_acteur__niveau_affectation__in=[
                    AffectationActeur.NiveauAffectation.PLATEFORME,
                    AffectationActeur.NiveauAffectation.NATIONAL,
                ])
                | Q(affectation_acteur__region_code__iexact=region_code)
            )
        if centre_id is not None:
            queryset = queryset.filter(
                Q(affectation_acteur__niveau_affectation__in=[
                    AffectationActeur.NiveauAffectation.PLATEFORME,
                    AffectationActeur.NiveauAffectation.NATIONAL,
                ])
                | Q(affectation_acteur__centre_id=centre_id)
            )

        contacts = []
        vus = set()
        for affectation_role in queryset.order_by("affectation_acteur__acteur_id").iterator(chunk_size=200):
            acteur = affectation_role.affectation_acteur.acteur
            email = cls.email_valide(acteur.email)
            if not email or email in vus:
                continue
            vus.add(email)
            contacts.append(
                ContactEmail(
                    email=email,
                    nom=acteur.nom_complet or acteur.username,
                    acteur_id=acteur.id,
                )
            )
        return contacts

    @staticmethod
    def journal_succes(cle_deduplication):
        return JournalAction.objects.filter(
            module_source="notifications",
            resultat=JournalAction.Resultat.SUCCES,
            contexte__cle_deduplication=cle_deduplication,
        ).order_by("-created_at").first()

    @staticmethod
    def tentative_recente(cle_deduplication, depuis):
        return JournalAction.objects.filter(
            module_source="notifications",
            resultat=JournalAction.Resultat.TENTATIVE,
            contexte__cle_deduplication=cle_deduplication,
            created_at__gte=depuis,
        ).order_by("-created_at").first()

    @staticmethod
    def dernier_echec(cle_deduplication):
        return JournalAction.objects.filter(
            module_source="notifications",
            resultat__in=[JournalAction.Resultat.ECHEC, JournalAction.Resultat.REFUS],
            contexte__cle_deduplication=cle_deduplication,
        ).order_by("-created_at").first()

    @staticmethod
    def statistiques_visibles(acteur, params=None):
        queryset = JournalActionRepository.visibles_par_acteur(
            acteur,
            code_permission="consulter_statistiques_notifications",
        ).filter(module_source="notifications")
        queryset = JournalActionRepository.filtrer(queryset, params or {})
        synthese = queryset.aggregate(
            total=Count("id"),
            tentatives=Count("id", filter=Q(resultat=JournalAction.Resultat.TENTATIVE)),
            succes=Count("id", filter=Q(resultat=JournalAction.Resultat.SUCCES)),
            refus=Count("id", filter=Q(resultat=JournalAction.Resultat.REFUS)),
            echecs=Count("id", filter=Q(resultat=JournalAction.Resultat.ECHEC)),
            acteurs_informes=Count(
                "acteur_id",
                filter=Q(resultat=JournalAction.Resultat.SUCCES),
                distinct=True,
            ),
            immerges_informes=Count(
                "immerge_id",
                filter=Q(resultat=JournalAction.Resultat.SUCCES),
                distinct=True,
            ),
            succes_directs=Count(
                "id",
                filter=Q(
                    resultat=JournalAction.Resultat.SUCCES,
                    contexte__mode_contact="DIRECT",
                ),
            ),
            succes_relais=Count(
                "id",
                filter=Q(
                    resultat=JournalAction.Resultat.SUCCES,
                    contexte__mode_contact="RELAIS_ETABLISSEMENT",
                ),
            ),
        )
        par_type = list(
            queryset.values("contexte__type_message", "resultat")
            .annotate(total=Count("id"))
            .order_by("contexte__type_message", "resultat")
        )
        par_periode = JournalActionRepository.statistiques_generales(queryset).get("evolution_30_jours", [])
        return {
            **synthese,
            "par_type_message": par_type,
            "evolution_30_jours": par_periode,
        }

    @staticmethod
    def emails_uniques(contacts: Iterable[ContactEmail]):
        resultat = []
        vus = set()
        for contact in contacts:
            if not contact or not contact.email or contact.email in vus:
                continue
            vus.add(contact.email)
            resultat.append(contact)
        return resultat
