from django.utils import timezone

from .models import ParametreSession, SessionImmersion


class SessionImmersionRepository:
    @staticmethod
    def base_queryset():
        return SessionImmersion.objects.filter(deleted_at__isnull=True)

    @staticmethod
    def all_active():
        return SessionImmersionRepository.base_queryset().select_related("parametres")

    @staticmethod
    def get_by_id(session_id):
        return SessionImmersionRepository.all_active().get(id=session_id)

    @staticmethod
    def get_by_code(code):
        return SessionImmersionRepository.all_active().get(code=code)

    @staticmethod
    def filter_by_annee(annee):
        return SessionImmersionRepository.all_active().filter(annee=annee)

    @staticmethod
    def filter_by_statut(statut):
        return SessionImmersionRepository.all_active().filter(statut=statut)

    @staticmethod
    def filter_by_type_session(type_session):
        return SessionImmersionRepository.all_active().filter(type_session=type_session)

    @staticmethod
    def filter_by_public_cible(public_cible):
        return SessionImmersionRepository.all_active().filter(public_cible=public_cible)

    @staticmethod
    def sessions_modifiables():
        return SessionImmersionRepository.all_active().exclude(
            statut__in=[
                SessionImmersion.Statut.TERMINEE,
                SessionImmersion.Statut.ARCHIVEE,
                SessionImmersion.Statut.ANNULEE,
            ]
        )

    @staticmethod
    def sessions_ouvertes_aux_inscriptions(date_reference=None):
        date_reference = date_reference or timezone.localdate()

        return SessionImmersionRepository.all_active().filter(
            statut=SessionImmersion.Statut.OUVERTE,
            date_ouverture_inscription__lte=date_reference,
            date_fermeture_inscription__gte=date_reference,
            parametres__mode_entree__in=[
                ParametreSession.ModeEntree.INSCRIPTION,
                ParametreSession.ModeEntree.MIXTE,
            ],
            parametres__consultation_publique_active=True,
            parametres__deleted_at__isnull=True,
            type_session__in=[
                SessionImmersion.TypeSession.VOLONTAIRE,
                SessionImmersion.TypeSession.MIXTE,
            ],
        )


class ParametreSessionRepository:
    @staticmethod
    def base_queryset():
        return ParametreSession.objects.filter(deleted_at__isnull=True)

    @staticmethod
    def all_active():
        return ParametreSessionRepository.base_queryset().select_related("session")

    @staticmethod
    def get_by_id(parametre_id):
        return ParametreSessionRepository.all_active().get(id=parametre_id)

    @staticmethod
    def get_by_session(session):
        return ParametreSessionRepository.all_active().get(session=session)

    @staticmethod
    def get_by_session_id(session_id):
        return ParametreSessionRepository.all_active().get(session_id=session_id)

    @staticmethod
    def get_or_create_for_session(session):
        return ParametreSession.objects.get_or_create(session=session)
