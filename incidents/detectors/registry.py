from __future__ import annotations

from . import accounts, activites, affectations, imports, immerges, kits, organisation, repas, sante, sessions
from .base import Detecteur


_DETECTEURS = (
    Detecteur("accounts", accounts.CODES, accounts.detecter),
    Detecteur("sessions_app", sessions.CODES, sessions.detecter),
    Detecteur("imports_app", imports.CODES, imports.detecter),
    Detecteur("immerges", immerges.CODES, immerges.detecter),
    Detecteur("affectations", affectations.CODES, affectations.detecter),
    Detecteur("organisation", organisation.CODES, organisation.detecter),
    Detecteur("sante", sante.CODES, sante.detecter),
    Detecteur("kits", kits.CODES, kits.detecter),
    Detecteur("activites", activites.CODES, activites.detecter),
    Detecteur("repas", repas.CODES, repas.detecter),
)


def detecteurs():
    return _DETECTEURS


def get_detecteur(module):
    for detecteur in _DETECTEURS:
        if detecteur.module == module:
            return detecteur
    return None
