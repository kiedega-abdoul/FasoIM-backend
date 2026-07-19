"""Invalidation des planifications futures après changement médical."""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from sante.models import RestrictionMedicale

from .models import RepasJournalier


def _marquer_repas_a_revoir(restriction):
    visite = restriction.visite_medicale
    if RestrictionMedicale.ModuleConcerne.REPAS not in (
        restriction.modules_concernes or []
    ):
        return
    RepasJournalier.objects.filter(
        demande_ravitaillement__session_id=visite.session_id,
        demande_ravitaillement__centre_id=visite.centre_id,
        date_repas__gte=timezone.localdate(),
        statut__in=[
            RepasJournalier.Statut.PLANIFIE,
            RepasJournalier.Statut.VALIDE,
            RepasJournalier.Statut.EN_PREPARATION,
            RepasJournalier.Statut.PREPARE,
        ],
        deleted_at__isnull=True,
    ).update(
        statut_controle_sante=RepasJournalier.StatutControleSante.A_REVOIR,
        updated_at=timezone.now(),
    )


@receiver(post_save, sender=RestrictionMedicale)
def restriction_repas_modifiee(sender, instance, **kwargs):
    _marquer_repas_a_revoir(instance)


@receiver(pre_save, sender=RestrictionMedicale)
def ancienne_restriction_repas_modifiee(sender, instance, **kwargs):
    if not instance.pk:
        return
    ancienne = RestrictionMedicale.objects.filter(pk=instance.pk).first()
    if ancienne and RestrictionMedicale.ModuleConcerne.REPAS in (
        ancienne.modules_concernes or []
    ):
        _marquer_repas_a_revoir(ancienne)


@receiver(post_delete, sender=RestrictionMedicale)
def restriction_repas_supprimee(sender, instance, **kwargs):
    _marquer_repas_a_revoir(instance)
