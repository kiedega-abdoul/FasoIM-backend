from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from incidents.models import AlerteIncident


@dataclass(frozen=True)
class Anomalie:
    code: str
    cle: str
    titre: str
    description: str
    categorie: str
    gravite: str = AlerteIncident.NiveauGravite.MOYEN
    type_concerne: str = AlerteIncident.TypeConcerne.DONNEE
    session_id: int | None = None
    centre_id: int | None = None
    affectation_centre_id: int | None = None
    acteur_concerne_id: int | None = None
    module_source: str = ""
    modele_source: str = ""
    objet_source_id: int | None = None
    est_bloquante: bool = False
    resolution_automatique: bool = True
    origine: str = AlerteIncident.Origine.AUTOMATIQUE
    contexte: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Detecteur:
    module: str
    codes: tuple[str, ...]
    fonction: Callable[[], Iterable[Anomalie]]
