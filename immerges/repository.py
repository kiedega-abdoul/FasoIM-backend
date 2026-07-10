from __future__ import annotations

from typing import Iterable

from django.db import transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from .models import (
    Immerge,
    ImmergeConcours,
    ImmergeExamen,
    ImmergeSelectionne,
    InscriptionVolontaire,
)


class SourceImporteeRepositoryMixin:
    """Requêtes communes aux sources importées.

    Les sources importées n'ont pas directement session_id. Elles passent par
    import_officiel -> session. On évite donc de dupliquer la session dans les
    tables sources, toujours cette étrange ambition de ne pas salir la base.
    """

    model = None
    identifiant_field = ""

    @classmethod
    def actifs(cls) -> QuerySet:
        return cls.model.objects.filter(deleted_at__isnull=True).select_related(
            "import_officiel",
            "import_officiel__session",
        )

    @classmethod
    def tous(cls) -> QuerySet:
        return cls.model.objects.all().select_related(
            "import_officiel",
            "import_officiel__session",
        )

    @classmethod
    def get_by_id(cls, source_id):
        return cls.actifs().get(id=source_id)

    @classmethod
    def get_by_id_pour_update(cls, source_id):
        return cls.actifs().select_for_update(of=("self",)).get(id=source_id)

    @classmethod
    def lister(cls, *, import_officiel_id=None, session_id=None, statut_validation=None, recherche=None):
        queryset = cls.actifs()
        if import_officiel_id is not None:
            queryset = queryset.filter(import_officiel_id=import_officiel_id)
        if session_id is not None:
            queryset = queryset.filter(import_officiel__session_id=session_id)
        if statut_validation:
            queryset = queryset.filter(statut_validation=statut_validation)
        if recherche:
            queryset = cls.appliquer_recherche(queryset, recherche)
        return queryset

    @classmethod
    def appliquer_recherche(cls, queryset: QuerySet, recherche: str) -> QuerySet:
        recherche = (recherche or "").strip()
        if not recherche:
            return queryset
        # On évite une dépendance inutile à Q dans chaque méthode concrète.
        from django.db.models import Q

        condition = (
            Q(nom__icontains=recherche)
            | Q(prenoms__icontains=recherche)
            | Q(nom_et_prenoms__icontains=recherche)
            | Q(numero_cnib__icontains=recherche)
            | Q(telephone__icontains=recherche)
            | Q(email__icontains=recherche)
        )
        if cls.identifiant_field:
            condition |= Q(**{f"{cls.identifiant_field}__icontains": recherche})
        return queryset.filter(condition)

    @classmethod
    def lister_par_import(cls, import_officiel_id):
        return cls.actifs().filter(import_officiel_id=import_officiel_id)

    @classmethod
    def lister_par_session(cls, session_id):
        return cls.actifs().filter(import_officiel__session_id=session_id)

    @classmethod
    def lister_valides(cls, *, import_officiel_id=None, session_id=None):
        queryset = cls.actifs().filter(statut_validation=cls.model.StatutValidation.VALIDE)
        if import_officiel_id is not None:
            queryset = queryset.filter(import_officiel_id=import_officiel_id)
        if session_id is not None:
            queryset = queryset.filter(import_officiel__session_id=session_id)
        return queryset

    @classmethod
    def compter_par_statut_validation(cls, *, import_officiel_id=None, session_id=None):
        queryset = cls.actifs()
        if import_officiel_id is not None:
            queryset = queryset.filter(import_officiel_id=import_officiel_id)
        if session_id is not None:
            queryset = queryset.filter(import_officiel__session_id=session_id)
        return queryset.values("statut_validation").annotate(total=Count("id")).order_by("statut_validation")

    @classmethod
    def existe_identifiant(cls, *, import_officiel_id, valeur, exclure_id=None):
        if not cls.identifiant_field:
            return False
        valeur = (valeur or "").strip()
        if not valeur:
            return False
        queryset = cls.actifs().filter(import_officiel_id=import_officiel_id, **{cls.identifiant_field: valeur})
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @classmethod
    def creer_en_masse(cls, objets: Iterable, batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return cls.model.objects.bulk_create(objets, batch_size=batch_size)

    @classmethod
    def mettre_a_jour_en_masse(cls, objets: Iterable, champs: list[str], batch_size=1000):
        objets = list(objets)
        if not objets:
            return 0
        cls.model.objects.bulk_update(objets, champs, batch_size=batch_size)
        return len(objets)

    @classmethod
    def soft_delete(cls, objet, date_suppression=None):
        objet.deleted_at = date_suppression or timezone.now()
        objet.save(update_fields=["deleted_at", "updated_at"])
        return objet

    @classmethod
    def soft_delete_par_import(cls, import_officiel_id, date_suppression=None):
        date_suppression = date_suppression or timezone.now()
        return cls.actifs().filter(import_officiel_id=import_officiel_id).update(deleted_at=date_suppression)


class ImmergeExamenRepository(SourceImporteeRepositoryMixin):
    model = ImmergeExamen
    identifiant_field = "numero_pv"

    @staticmethod
    def lister_par_type_examen(type_examen, *, session_id=None):
        queryset = ImmergeExamenRepository.actifs().filter(type_examen=type_examen)
        if session_id is not None:
            queryset = queryset.filter(import_officiel__session_id=session_id)
        return queryset

    @staticmethod
    def get_par_numero_pv(import_officiel_id, numero_pv):
        return ImmergeExamenRepository.actifs().get(
            import_officiel_id=import_officiel_id,
            numero_pv=numero_pv,
        )


class ImmergeConcoursRepository(SourceImporteeRepositoryMixin):
    model = ImmergeConcours
    identifiant_field = "numero_recepisse"

    @staticmethod
    def get_par_numero_recepisse(import_officiel_id, numero_recepisse):
        return ImmergeConcoursRepository.actifs().get(
            import_officiel_id=import_officiel_id,
            numero_recepisse=numero_recepisse,
        )


class ImmergeSelectionneRepository(SourceImporteeRepositoryMixin):
    model = ImmergeSelectionne
    identifiant_field = "matricule"

    @staticmethod
    def get_par_matricule(import_officiel_id, matricule):
        return ImmergeSelectionneRepository.actifs().get(
            import_officiel_id=import_officiel_id,
            matricule=matricule,
        )

    @staticmethod
    def get_par_reference_selection(import_officiel_id, reference_selection):
        return ImmergeSelectionneRepository.actifs().get(
            import_officiel_id=import_officiel_id,
            reference_selection=reference_selection,
        )

    @staticmethod
    def existe_matricule_ou_reference(*, import_officiel_id, matricule="", reference_selection="", exclure_id=None):
        queryset = ImmergeSelectionneRepository.actifs().filter(import_officiel_id=import_officiel_id)
        from django.db.models import Q

        condition = Q()
        if matricule:
            condition |= Q(matricule=matricule)
        if reference_selection:
            condition |= Q(reference_selection=reference_selection)
        if not condition:
            return False
        queryset = queryset.filter(condition)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()


class InscriptionVolontaireRepository:
    @staticmethod
    def actifs() -> QuerySet:
        return InscriptionVolontaire.objects.filter(deleted_at__isnull=True).select_related("session")

    @staticmethod
    def tous() -> QuerySet:
        return InscriptionVolontaire.objects.all().select_related("session")

    @staticmethod
    def get_by_id(inscription_id):
        return InscriptionVolontaireRepository.actifs().get(id=inscription_id)

    @staticmethod
    def get_by_id_pour_update(inscription_id):
        return InscriptionVolontaireRepository.actifs().select_for_update(of=("self",)).get(id=inscription_id)

    @staticmethod
    def get_par_code_suivi(code_suivi):
        return InscriptionVolontaireRepository.actifs().get(code_suivi=code_suivi)

    @staticmethod
    def code_suivi_existe(code_suivi, exclure_id=None):
        queryset = InscriptionVolontaireRepository.actifs().filter(code_suivi=code_suivi)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def lister(*, session_id=None, statut_demande=None, region_residence=None, recherche=None):
        queryset = InscriptionVolontaireRepository.actifs()
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if statut_demande:
            queryset = queryset.filter(statut_demande=statut_demande)
        if region_residence:
            queryset = queryset.filter(region_residence=region_residence)
        if recherche:
            from django.db.models import Q

            recherche = recherche.strip()
            queryset = queryset.filter(
                Q(code_suivi__icontains=recherche)
                | Q(nom__icontains=recherche)
                | Q(prenoms__icontains=recherche)
                | Q(nom_et_prenoms__icontains=recherche)
                | Q(numero_cnib__icontains=recherche)
                | Q(telephone__icontains=recherche)
                | Q(email__icontains=recherche)
            )
        return queryset

    @staticmethod
    def lister_par_session(session_id):
        return InscriptionVolontaireRepository.actifs().filter(session_id=session_id)

    @staticmethod
    def lister_acceptees(session_id=None):
        queryset = InscriptionVolontaireRepository.actifs().filter(
            statut_demande=InscriptionVolontaire.StatutDemande.ACCEPTEE
        )
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        return queryset

    @staticmethod
    def compter_par_statut(session_id=None):
        queryset = InscriptionVolontaireRepository.actifs()
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        return queryset.values("statut_demande").annotate(total=Count("id")).order_by("statut_demande")

    @staticmethod
    def creer(**donnees):
        return InscriptionVolontaire.objects.create(**donnees)

    @staticmethod
    def soft_delete(inscription, date_suppression=None):
        inscription.deleted_at = date_suppression or timezone.now()
        inscription.save(update_fields=["deleted_at", "updated_at"])
        return inscription


class ImmergeRepository:
    @staticmethod
    def actifs() -> QuerySet:
        return Immerge.objects.filter(deleted_at__isnull=True).select_related("session")

    @staticmethod
    def tous() -> QuerySet:
        return Immerge.objects.all().select_related("session")

    @staticmethod
    def get_by_id(immerge_id):
        return ImmergeRepository.actifs().get(id=immerge_id)

    @staticmethod
    def get_by_id_pour_update(immerge_id):
        return ImmergeRepository.actifs().select_for_update(of=("self",)).get(id=immerge_id)

    @staticmethod
    def get_par_code(code_fasoim):
        return ImmergeRepository.actifs().get(code_fasoim=code_fasoim)

    @staticmethod
    def get_par_qr_code(qr_code):
        return ImmergeRepository.actifs().get(qr_code=qr_code)

    @staticmethod
    def lister(*, session_id=None, type_immerge=None, statut=None, recherche=None):
        queryset = ImmergeRepository.actifs()
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        if type_immerge:
            queryset = queryset.filter(type_immerge=type_immerge)
        if statut:
            queryset = queryset.filter(statut=statut)
        if recherche:
            from django.db.models import Q

            recherche = recherche.strip()
            condition = Q(code_fasoim__icontains=recherche) | Q(qr_code__icontains=recherche)
            if recherche.isdigit():
                condition |= Q(origine_id=int(recherche))
            queryset = queryset.filter(condition)
        return queryset

    @staticmethod
    def lister_par_session(session_id):
        return ImmergeRepository.actifs().filter(session_id=session_id)

    @staticmethod
    def lister_par_source(session_id, type_immerge, origine_ids=None):
        queryset = ImmergeRepository.actifs().filter(session_id=session_id, type_immerge=type_immerge)
        if origine_ids is not None:
            queryset = queryset.filter(origine_id__in=list(origine_ids))
        return queryset

    @staticmethod
    def source_deja_centralisee(*, session_id, type_immerge, origine_id):
        return ImmergeRepository.actifs().filter(
            session_id=session_id,
            type_immerge=type_immerge,
            origine_id=origine_id,
        ).exists()

    @staticmethod
    def code_existe(code_fasoim, exclure_id=None):
        queryset = ImmergeRepository.actifs().filter(code_fasoim=code_fasoim)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def qr_code_existe(qr_code, exclure_id=None):
        queryset = ImmergeRepository.actifs().filter(qr_code=qr_code)
        if exclure_id is not None:
            queryset = queryset.exclude(id=exclure_id)
        return queryset.exists()

    @staticmethod
    def compter_par_statut(session_id=None):
        queryset = ImmergeRepository.actifs()
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        return queryset.values("statut").annotate(total=Count("id")).order_by("statut")

    @staticmethod
    def compter_par_type(session_id=None):
        queryset = ImmergeRepository.actifs()
        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)
        return queryset.values("type_immerge").annotate(total=Count("id")).order_by("type_immerge")

    @staticmethod
    def creer(**donnees):
        return Immerge.objects.create(**donnees)

    @staticmethod
    def creer_en_masse(objets: Iterable[Immerge], batch_size=1000):
        objets = list(objets)
        if not objets:
            return []
        return Immerge.objects.bulk_create(objets, batch_size=batch_size)

    @staticmethod
    def mettre_a_jour_en_masse(objets: Iterable[Immerge], champs: list[str], batch_size=1000):
        objets = list(objets)
        if not objets:
            return 0
        Immerge.objects.bulk_update(objets, champs, batch_size=batch_size)
        return len(objets)

    @staticmethod
    def changer_statut(immerge, statut):
        immerge.statut = statut
        immerge.save(update_fields=["statut", "updated_at"])
        return immerge

    @staticmethod
    def marquer_code_genere(immerge, code_fasoim, qr_code):
        immerge.code_fasoim = code_fasoim
        immerge.qr_code = qr_code
        immerge.statut = Immerge.Statut.CODE_GENERE
        immerge.date_creation_code = timezone.now()
        immerge.save(update_fields=["code_fasoim", "qr_code", "statut", "date_creation_code", "updated_at"])
        return immerge

    @staticmethod
    def soft_delete(immerge, date_suppression=None):
        immerge.deleted_at = date_suppression or timezone.now()
        immerge.save(update_fields=["deleted_at", "updated_at"])
        return immerge

    @staticmethod
    @transaction.atomic
    def soft_delete_par_session(session_id, date_suppression=None):
        date_suppression = date_suppression or timezone.now()
        return ImmergeRepository.actifs().filter(session_id=session_id).update(deleted_at=date_suppression)
