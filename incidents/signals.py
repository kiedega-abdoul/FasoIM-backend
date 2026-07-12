"""Déclenchement léger de contrôles ciblés après les écritures critiques.

Les signaux ne valident aucune règle métier et ne bloquent aucune opération. Les
services des applications restent seuls responsables des autorisations et des
validations. Ici, on programme seulement une lecture d'intégrité après commit.
"""

from django.db.models.signals import post_delete, post_save

from accounts.models import (
    Acteur,
    AffectationActeur,
    AffectationPermission,
    AffectationRole,
    DelegationActeur,
    DemandePermission,
    Permission,
    Role,
    RolePermission,
)
from affectations.models import AffectationCentre, AffectationRegionale, CentreImmersion, RegionImmersion
from organisation.models import AffectationGroupe, AttributionLit, Dortoir, Groupe, Lit, RegleOrganisationCentre, Section
from sessions_app.models import ParametreSession, SessionImmersion

from .tasks import programmer_scan_module_apres_commit


MODELES_PAR_MODULE = {
    "accounts": (
        Acteur,
        Role,
        Permission,
        RolePermission,
        AffectationActeur,
        AffectationRole,
        AffectationPermission,
        DemandePermission,
        DelegationActeur,
    ),
    "sessions_app": (SessionImmersion, ParametreSession),
    "affectations": (
        RegionImmersion,
        CentreImmersion,
        AffectationRegionale,
        AffectationCentre,
    ),
    "organisation": (
        RegleOrganisationCentre,
        Section,
        Groupe,
        AffectationGroupe,
        Dortoir,
        Lit,
        AttributionLit,
    ),
}


def _planifier(module):
    def receveur(sender, instance, **kwargs):
        programmer_scan_module_apres_commit(module)

    return receveur


for _module, _modeles in MODELES_PAR_MODULE.items():
    for _modele in _modeles:
        post_save.connect(
            _planifier(_module),
            sender=_modele,
            weak=False,
            dispatch_uid=f"incidents:post_save:{_module}:{_modele._meta.label_lower}",
        )
        post_delete.connect(
            _planifier(_module),
            sender=_modele,
            weak=False,
            dispatch_uid=f"incidents:post_delete:{_module}:{_modele._meta.label_lower}",
        )
