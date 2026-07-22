from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from immerges.models import Immerge
from immerges.repository import ImmergeRepository
from sessions_app.models import SessionImmersion
from sessions_app.service import ParametreSessionService

from .models import (
    AffectationCentre,
    AffectationRegionale,
    CentreImmersion,
    RegionImmersion,
)
from .repository import (
    STATUTS_CENTRES_OUVERTS,
    STATUTS_REGIONAUX_OUVERTS,
    AffectationCentreRepository,
    AffectationRegionaleRepository,
    CentreImmersionRepository,
    CriteresImmergeAffectationRepository,
    RegionImmersionRepository,
)


class ValidationAffectationErreur(ValidationError):
    """Erreur métier lisible par l'API sans exposer les détails internes."""


@dataclass(frozen=True)
class ProfilAffectation:
    """Profil uniforme construit depuis une table source d'immergé."""

    immerge_id: int
    origine_id: int
    type_immerge: str
    identite_affichable: str = ""
    sexe: str = ""
    date_naissance: object | None = None
    region_reference: str = ""
    province_reference: str = ""
    niveau_examen: str = ""
    serie_filiere: str = ""
    specialite: str = ""
    structure_origine: str = ""
    niveau_etude: str = ""
    profession: str = ""
    identifiant_source: str = ""
    source_valide: bool = True


@dataclass
class ResultatPropositionLot:
    """Résultat sérialisable d'une proposition automatique par lot."""

    demandes: int
    candidats_pris: int
    propositions_creees: int
    candidats_restants: int
    sans_source: list[int] = field(default_factory=list)
    sans_destination: list[int] = field(default_factory=list)
    affectation_ids: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def en_dict(self) -> dict:
        return asdict(self)


class NormalisationGeographiqueService:
    """Normalise les libellés avant comparaison région/province."""

    PREFIXES_REGION = (
        "region administrative de ",
        "region administrative du ",
        "region administrative des ",
        "region de ",
        "region du ",
        "region des ",
        "region ",
    )

    @staticmethod
    def normaliser(valeur: object) -> str:
        texte = str(valeur or "").strip().lower()
        texte = unicodedata.normalize("NFKD", texte)
        texte = "".join(caractere for caractere in texte if not unicodedata.combining(caractere))
        texte = re.sub(r"[^a-z0-9]+", " ", texte)
        texte = " ".join(texte.split())

        for prefixe in NormalisationGeographiqueService.PREFIXES_REGION:
            if texte.startswith(prefixe):
                texte = texte[len(prefixe):].strip()
                break

        # Les fichiers administratifs oscillent souvent entre singulier et
        # pluriel : "Haut Bassin" et "Hauts-Bassins", par exemple.
        morceaux = []
        for morceau in texte.split():
            if len(morceau) > 4 and morceau.endswith("s"):
                morceau = morceau[:-1]
            morceaux.append(morceau)
        return " ".join(morceaux)

    @classmethod
    def score(cls, gauche: object, droite: object) -> float:
        gauche_normalisee = cls.normaliser(gauche)
        droite_normalisee = cls.normaliser(droite)

        if not gauche_normalisee or not droite_normalisee:
            return 0.0
        if gauche_normalisee == droite_normalisee:
            return 1.0

        score_sequence = SequenceMatcher(
            None,
            gauche_normalisee,
            droite_normalisee,
        ).ratio()

        tokens_gauche = set(gauche_normalisee.split())
        tokens_droite = set(droite_normalisee.split())
        union = tokens_gauche | tokens_droite
        score_tokens = (
            len(tokens_gauche & tokens_droite) / len(union)
            if union
            else 0.0
        )
        return max(score_sequence, score_tokens)


class ProfilAffectationService:
    """Résout en quelques requêtes les sources d'un lot d'immergés."""

    @staticmethod
    def _grouper_origines(immerges) -> dict[str, list[int]]:
        groupes: dict[str, list[int]] = {}
        for immerge in immerges:
            groupes.setdefault(immerge.type_immerge, []).append(immerge.origine_id)
        return groupes

    @staticmethod
    def _indexer(lignes) -> dict[int, dict]:
        return {int(ligne["id"]): dict(ligne) for ligne in lignes}

    @classmethod
    def construire_profils(cls, immerges) -> tuple[dict[int, ProfilAffectation], list[int]]:
        immerges = list(immerges)
        groupes = cls._grouper_origines(immerges)

        examens_ids = [
            *groupes.get(Immerge.TypeImmerge.BEPC, []),
            *groupes.get(Immerge.TypeImmerge.BAC, []),
        ]
        examens = cls._indexer(
            CriteresImmergeAffectationRepository.sources_examens(examens_ids)
        )
        concours = cls._indexer(
            CriteresImmergeAffectationRepository.sources_concours(
                groupes.get(Immerge.TypeImmerge.CONCOURS, [])
            )
        )
        selectionnes = cls._indexer(
            CriteresImmergeAffectationRepository.sources_selectionnes(
                groupes.get(Immerge.TypeImmerge.SELECTIONNE, [])
            )
        )
        volontaires = cls._indexer(
            CriteresImmergeAffectationRepository.sources_volontaires(
                groupes.get(Immerge.TypeImmerge.VOLONTAIRE, [])
            )
        )

        profils: dict[int, ProfilAffectation] = {}
        sans_source: list[int] = []

        for immerge in immerges:
            source = None
            profil = None

            if immerge.type_immerge in {
                Immerge.TypeImmerge.BEPC,
                Immerge.TypeImmerge.BAC,
            }:
                source = examens.get(immerge.origine_id)
                if source:
                    profil = ProfilAffectation(
                        immerge_id=immerge.id,
                        origine_id=immerge.origine_id,
                        type_immerge=immerge.type_immerge,
                        identite_affichable=(source.get("nom_et_prenoms") or f"{source.get('nom') or ''} {source.get('prenoms') or ''}").strip(),
                        sexe=source.get("sexe") or "",
                        date_naissance=source.get("date_naissance"),
                        region_reference=source.get("region_examen") or "",
                        province_reference=source.get("province_examen") or "",
                        niveau_examen=source.get("type_examen") or immerge.type_immerge,
                        serie_filiere=source.get("serie") or "",
                        structure_origine=source.get("etablissement_origine") or "",
                        identifiant_source=source.get("numero_pv") or "",
                    )

            elif immerge.type_immerge == Immerge.TypeImmerge.CONCOURS:
                source = concours.get(immerge.origine_id)
                if source:
                    profil = ProfilAffectation(
                        immerge_id=immerge.id,
                        origine_id=immerge.origine_id,
                        type_immerge=immerge.type_immerge,
                        identite_affichable=(source.get("nom_et_prenoms") or f"{source.get('nom') or ''} {source.get('prenoms') or ''}").strip(),
                        sexe=source.get("sexe") or "",
                        date_naissance=source.get("date_naissance"),
                        region_reference=source.get("region_composition") or "",
                        province_reference=source.get("province_composition") or "",
                        specialite=source.get("specialite") or "",
                        identifiant_source=source.get("numero_recepisse") or "",
                    )

            elif immerge.type_immerge == Immerge.TypeImmerge.SELECTIONNE:
                source = selectionnes.get(immerge.origine_id)
                if source:
                    profil = ProfilAffectation(
                        immerge_id=immerge.id,
                        origine_id=immerge.origine_id,
                        type_immerge=immerge.type_immerge,
                        identite_affichable=(source.get("nom_et_prenoms") or f"{source.get('nom') or ''} {source.get('prenoms') or ''}").strip(),
                        sexe=source.get("sexe") or "",
                        date_naissance=source.get("date_naissance"),
                        region_reference=source.get("region_structure") or "",
                        province_reference=source.get("province_structure") or "",
                        structure_origine=source.get("structure_origine") or "",
                        identifiant_source=(
                            source.get("matricule")
                            or source.get("reference_selection")
                            or ""
                        ),
                    )

            elif immerge.type_immerge == Immerge.TypeImmerge.VOLONTAIRE:
                source = volontaires.get(immerge.origine_id)
                if source:
                    profil = ProfilAffectation(
                        immerge_id=immerge.id,
                        origine_id=immerge.origine_id,
                        type_immerge=immerge.type_immerge,
                        identite_affichable=(source.get("nom_et_prenoms") or f"{source.get('nom') or ''} {source.get('prenoms') or ''}").strip(),
                        sexe=source.get("sexe") or "",
                        date_naissance=source.get("date_naissance"),
                        region_reference=source.get("region_residence") or "",
                        province_reference=source.get("province_residence") or "",
                        niveau_etude=source.get("niveau_etude") or "",
                        profession=source.get("profession") or "",
                        identifiant_source=source.get("code_suivi") or "",
                    )

            if profil is None:
                sans_source.append(immerge.id)
            else:
                profils[immerge.id] = profil

        return profils, sans_source


class PerimetreCentresSessionService:
    """Expose les centres et régions explicitement retenus pour une session."""

    @staticmethod
    def session(session_id):
        try:
            return SessionImmersion.objects.select_related("parametres").get(
                id=session_id, deleted_at__isnull=True
            )
        except SessionImmersion.DoesNotExist as exc:
            raise ValidationAffectationErreur({
                "session": "La session demandée est introuvable."
            }) from exc

    @classmethod
    def centre_ids(cls, session_id):
        session = cls.session(session_id)
        ids = ParametreSessionService.ids_centres_accueil(session)
        if not ids:
            raise ValidationAffectationErreur({
                "centres_accueil": (
                    "Aucun centre d'accueil n'est configuré dans les paramètres "
                    "de cette session."
                )
            })
        return ids

    @classmethod
    def region_ids(cls, session_id):
        centre_ids = cls.centre_ids(session_id)
        regions = list(
            CentreImmersionRepository.lister_donnees_algorithme()
            .filter(id__in=centre_ids)
            .order_by()
            .values_list("region_id", flat=True)
            .distinct()
        )
        if not regions:
            raise ValidationAffectationErreur({
                "regions": (
                    "Les centres retenus pour la session ne fournissent aucune "
                    "région active admissible."
                )
            })
        return centre_ids, sorted({int(region_id) for region_id in regions})

    @classmethod
    def verifier_region(cls, *, session_id, region_id):
        _, region_ids = cls.region_ids(session_id)
        if int(region_id) not in region_ids:
            raise ValidationAffectationErreur({
                "region": (
                    "Cette région ne fait pas partie des régions déduites des "
                    "centres retenus pour la session."
                )
            })

    @classmethod
    def verifier_centre(cls, *, session_id, centre_id):
        if int(centre_id) not in cls.centre_ids(session_id):
            raise ValidationAffectationErreur({
                "centre": "Ce centre n'est pas retenu dans les paramètres de la session."
            })


class CapaciteAffectationService:
    """Interprète les agrégats bruts fournis par le repository."""

    @staticmethod
    def capacites_regions(session_id: int, region_ids: list[int]) -> dict[int, dict]:
        region_ids = sorted({int(region_id) for region_id in region_ids})
        region_ids_set = set(region_ids)
        centre_ids = PerimetreCentresSessionService.centre_ids(session_id)
        capacites = {
            int(ligne["region_id"]): {
                "capacite_totale": int(ligne["capacite_ouverte_centres"] or 0),
                "capacite_ouverte": int(ligne["capacite_ouverte_centres"] or 0),
                "nombre_centres": int(ligne["nombre_centres"] or 0),
                "propositions_en_attente": 0,
                "affectations_validees": 0,
                "places_reservees": 0,
                "occupation_ouverte": 0,
                "disponible": int(ligne["capacite_ouverte_centres"] or 0),
            }
            for ligne in CentreImmersionRepository.capacites_ouvertes_par_region(
                session_id=session_id,
                region_ids=region_ids,
                centre_ids=centre_ids,
            )
        }

        for region_id in region_ids:
            capacites.setdefault(
                int(region_id),
                {
                    "capacite_totale": 0,
                    "capacite_ouverte": 0,
                    "nombre_centres": 0,
                    "propositions_en_attente": 0,
                    "affectations_validees": 0,
                    "places_reservees": 0,
                    "occupation_ouverte": 0,
                    "disponible": 0,
                },
            )

        for ligne in AffectationRegionaleRepository.compter_par_region_et_statuts(
            session_id=session_id,
            statuts=(AffectationRegionale.Statut.PROPOSEE,),
        ):
            region_id = int(ligne["region_id"])
            if region_id not in region_ids_set:
                continue
            capacites.setdefault(
                region_id,
                {
                    "capacite_totale": 0,
                    "capacite_ouverte": 0,
                    "nombre_centres": 0,
                    "propositions_en_attente": 0,
                    "affectations_validees": 0,
                    "places_reservees": 0,
                    "occupation_ouverte": 0,
                    "disponible": 0,
                },
            )
            capacites[region_id]["propositions_en_attente"] = int(ligne["total"] or 0)

        for ligne in AffectationRegionaleRepository.compter_par_region_et_statuts(
            session_id=session_id,
            statuts=(AffectationRegionale.Statut.ACTIVE,),
        ):
            region_id = int(ligne["region_id"])
            if region_id not in region_ids_set:
                continue
            capacites.setdefault(
                region_id,
                {
                    "capacite_totale": 0,
                    "capacite_ouverte": 0,
                    "nombre_centres": 0,
                    "propositions_en_attente": 0,
                    "affectations_validees": 0,
                    "places_reservees": 0,
                    "occupation_ouverte": 0,
                    "disponible": 0,
                },
            )
            capacites[region_id]["affectations_validees"] = int(ligne["total"] or 0)

        for donnees in capacites.values():
            donnees["places_reservees"] = (
                donnees["propositions_en_attente"]
                + donnees["affectations_validees"]
            )
            # Compatibilité interne : l'occupation ouverte représente toutes les
            # places déjà réservées, qu'elles soient proposées ou validées.
            donnees["occupation_ouverte"] = donnees["places_reservees"]
            donnees["disponible"] = max(
                0,
                donnees["capacite_totale"] - donnees["places_reservees"],
            )

        return capacites


    @classmethod
    def rapport_regions(cls, session_id: int) -> dict:
        session = PerimetreCentresSessionService.session(session_id)
        centre_ids, region_ids = PerimetreCentresSessionService.region_ids(session_id)
        capacites = cls.capacites_regions(session_id, region_ids)

        centres = list(
            CentreImmersionRepository.lister_donnees_algorithme(region_ids=region_ids)
            .filter(id__in=centre_ids)
            .order_by("region_id", "nom", "id")
        )
        capacites_centres = CentreImmersionRepository.capacites_ouvertes_par_centres(
            session_id=session_id,
            centre_ids=centre_ids,
        )
        regions = {
            int(ligne["id"]): ligne
            for ligne in RegionImmersionRepository.lister_donnees_algorithme()
            if int(ligne["id"]) in set(region_ids)
        }

        centres_par_region: dict[int, list[dict]] = {int(region_id): [] for region_id in region_ids}
        for centre in centres:
            region_id = int(centre["region_id"])
            centres_par_region.setdefault(region_id, []).append({
                "centre_id": int(centre["id"]),
                "centre_code": centre["code"],
                "centre_nom": centre["nom"],
                "province": centre.get("province") or "",
                "ville": centre.get("ville") or "",
                "capacite_ouverte": int(capacites_centres.get(int(centre["id"]), 0)),
            })

        lignes_regions = []
        for region_id in region_ids:
            region_id = int(region_id)
            region = regions.get(region_id, {})
            donnees = capacites.get(region_id, {})
            lignes_regions.append({
                "region_id": region_id,
                "region_code": region.get("code", ""),
                "region_nom": region.get("nom", ""),
                "nombre_centres": int(donnees.get("nombre_centres", 0)),
                "capacite_ouverte": int(donnees.get("capacite_ouverte", 0)),
                "propositions_en_attente": int(donnees.get("propositions_en_attente", 0)),
                "affectations_validees": int(donnees.get("affectations_validees", 0)),
                "places_reservees": int(donnees.get("places_reservees", 0)),
                "occupation": int(donnees.get("affectations_validees", 0)),
                "disponible": int(donnees.get("disponible", 0)),
                "centres": centres_par_region.get(region_id, []),
            })

        lignes_regions.sort(key=lambda ligne: (ligne["region_nom"], ligne["region_id"]))
        candidats_disponibles = (
            CriteresImmergeAffectationRepository.compter_candidats_regionaux(
                session_id=session_id,
            )
        )
        disponible_total = sum(ligne["disponible"] for ligne in lignes_regions)
        return {
            "session": {
                "id": session.id,
                "code": session.code,
                "nom": session.nom,
                "statut": session.statut,
                "type_session": session.type_session,
                "public_cible": session.public_cible,
            },
            "capacite_totale": sum(ligne["capacite_ouverte"] for ligne in lignes_regions),
            "propositions_en_attente_total": sum(
                ligne["propositions_en_attente"] for ligne in lignes_regions
            ),
            "affectations_validees_total": sum(
                ligne["affectations_validees"] for ligne in lignes_regions
            ),
            "places_reservees_total": sum(
                ligne["places_reservees"] for ligne in lignes_regions
            ),
            # Conservé pour les anciens clients : il représente désormais
            # uniquement les affectations validées.
            "occupation_totale": sum(
                ligne["affectations_validees"] for ligne in lignes_regions
            ),
            "disponible_total": disponible_total,
            "candidats_disponibles": candidats_disponibles,
            "maximum_proposable": min(candidats_disponibles, disponible_total),
            "regions": lignes_regions,
        }

    @staticmethod
    def capacites_centres(
        *,
        session_id: int,
        centres: list[dict],
        region_id: int | None = None,
    ) -> dict[int, dict]:
        centre_ids = [int(centre["id"]) for centre in centres]
        ouvertes = CentreImmersionRepository.capacites_ouvertes_par_centres(
            session_id=session_id,
            centre_ids=centre_ids,
        )
        capacites = {
            centre_id: {
                "capacite_totale": int(ouvertes.get(centre_id, 0)),
                "capacite_ouverte": int(ouvertes.get(centre_id, 0)),
                "occupation_ouverte": 0,
                "disponible": int(ouvertes.get(centre_id, 0)),
            }
            for centre_id in centre_ids
        }

        for ligne in AffectationCentreRepository.compter_par_centre_et_statuts(
            session_id=session_id,
            region_id=region_id,
            statuts=STATUTS_CENTRES_OUVERTS,
        ):
            centre_id = int(ligne["centre_id"])
            if centre_id in capacites:
                capacites[centre_id]["occupation_ouverte"] = int(ligne["total"] or 0)

        for donnees in capacites.values():
            donnees["disponible"] = max(
                0,
                donnees["capacite_totale"] - donnees["occupation_ouverte"],
            )

        return capacites


    @classmethod
    def rapport_centres(cls, *, session_id: int, region_id: int) -> dict:
        session = PerimetreCentresSessionService.session(session_id)
        PerimetreCentresSessionService.verifier_region(
            session_id=session_id,
            region_id=region_id,
        )
        centre_ids = PerimetreCentresSessionService.centre_ids(session_id)
        centres = list(
            CentreImmersionRepository.lister_donnees_algorithme(region_id=region_id)
            .filter(id__in=centre_ids)
            .order_by("nom", "id")
        )
        capacites = cls.capacites_centres(
            session_id=session_id,
            centres=centres,
            region_id=region_id,
        )

        propositions = {
            int(ligne["centre_id"]): int(ligne["total"] or 0)
            for ligne in AffectationCentreRepository.compter_par_centre_et_statuts(
                session_id=session_id,
                region_id=region_id,
                statuts=(AffectationCentre.Statut.PROPOSEE,),
            )
        }
        validees = {
            int(ligne["centre_id"]): int(ligne["total"] or 0)
            for ligne in AffectationCentreRepository.compter_par_centre_et_statuts(
                session_id=session_id,
                region_id=region_id,
                statuts=(AffectationCentre.Statut.ACTIVE,),
            )
        }

        lignes = []
        for centre in centres:
            centre_id = int(centre["id"])
            capacite_ouverte = int(capacites.get(centre_id, {}).get("capacite_ouverte", 0))
            en_attente = int(propositions.get(centre_id, 0))
            actives = int(validees.get(centre_id, 0))
            reservees = en_attente + actives
            lignes.append({
                "centre_id": centre_id,
                "centre_code": centre.get("code", ""),
                "centre_nom": centre.get("nom", ""),
                "province": centre.get("province", ""),
                "ville": centre.get("ville", ""),
                "genre": centre.get("genre", ""),
                "publics_acceptes": centre.get("publics_acceptes") or [],
                "niveaux_acceptes": centre.get("niveaux_acceptes") or [],
                "capacite_ouverte": capacite_ouverte,
                "propositions_en_attente": en_attente,
                "affectations_validees": actives,
                "places_reservees": reservees,
                "disponible": max(0, capacite_ouverte - reservees),
            })

        candidats_disponibles = (
            CriteresImmergeAffectationRepository.compter_candidats_centre(
                session_id=session_id,
                region_id=region_id,
            )
        )
        disponible_total = sum(ligne["disponible"] for ligne in lignes)
        region = RegionImmersionRepository.get_by_id(region_id)
        return {
            "session": {
                "id": session.id,
                "code": session.code,
                "nom": session.nom,
                "statut": session.statut,
                "type_session": session.type_session,
                "public_cible": session.public_cible,
            },
            "region": {
                "id": region.id,
                "code": region.code,
                "nom": region.nom,
            },
            "nombre_centres": len(lignes),
            "capacite_totale": sum(ligne["capacite_ouverte"] for ligne in lignes),
            "propositions_en_attente_total": sum(ligne["propositions_en_attente"] for ligne in lignes),
            "affectations_validees_total": sum(ligne["affectations_validees"] for ligne in lignes),
            "places_reservees_total": sum(ligne["places_reservees"] for ligne in lignes),
            "disponible_total": disponible_total,
            "candidats_disponibles": candidats_disponibles,
            "maximum_proposable": min(candidats_disponibles, disponible_total),
            "centres": lignes,
        }


class AffectationRegionaleService:
    """Propose, valide et rejette les affectations régionales."""

    SEUIL_CORRESPONDANCE_FORTE = 0.82
    SEUIL_CORRESPONDANCE_ASSOUPLIE = 0.55

    @classmethod
    def valider_taille_lot(cls, nombre: int) -> int:
        try:
            nombre = int(nombre)
        except (TypeError, ValueError) as exc:
            raise ValidationAffectationErreur(
                {"nombre": "Le nombre demandé doit être un entier."}
            ) from exc

        if nombre <= 0:
            raise ValidationAffectationErreur(
                {"nombre": "Le nombre demandé doit être strictement positif."}
            )
        return nombre

    @classmethod
    def verifier_aucune_proposition_en_attente(cls, session_id: int) -> None:
        total = AffectationRegionaleRepository.compter_propositions_en_attente(
            session_id=session_id,
        )
        if total > 0:
            raise ValidationAffectationErreur({
                "propositions": (
                    f"{total} proposition(s) régionale(s) sont encore en attente "
                    "de validation. Validez-les ou rejetez-les avant de lancer "
                    "une nouvelle proposition."
                )
            })

    @staticmethod
    def _centres_par_region(centres: list[dict]) -> dict[int, list[dict]]:
        resultat: dict[int, list[dict]] = {}
        for centre in centres:
            resultat.setdefault(int(centre["region_id"]), []).append(centre)
        return resultat

    @staticmethod
    def _centre_compatible_disponible(
        *,
        profil: ProfilAffectation,
        centres: list[dict],
        capacites_centres: dict[int, dict],
    ) -> dict | None:
        """Choisit une place réelle compatible sans tenir compte de la série.

        Les centres dédiés au sexe du candidat sont consommés avant les centres
        mixtes afin de préserver ces derniers pour les candidats qui n'ont pas
        d'autre solution.
        """

        compatibles = []
        for centre in centres:
            centre_id = int(centre["id"])
            disponible = int(
                capacites_centres.get(centre_id, {}).get("disponible", 0)
            )
            if disponible <= 0:
                continue
            if not AffectationCentreService._genre_compatible(
                profil.sexe, centre.get("genre")
            ):
                continue
            if not AffectationCentreService._public_compatible(
                profil.type_immerge, centre.get("publics_acceptes")
            ):
                continue

            genre = str(centre.get("genre") or "").strip().upper()
            priorite_genre = (
                1 if genre != CentreImmersion.Genre.MIXTE else 0
            )
            compatibles.append(
                (priorite_genre, disponible, -centre_id, centre)
            )

        if not compatibles:
            return None
        compatibles.sort(reverse=True)
        return compatibles[0][3]

    @classmethod
    def _capacites_regionales_compatibles(
        cls,
        *,
        profil: ProfilAffectation,
        regions: list[dict],
        centres_par_region: dict[int, list[dict]],
        capacites_centres: dict[int, dict],
    ) -> dict[int, dict]:
        resultat: dict[int, dict] = {}
        for region in regions:
            region_id = int(region["id"])
            total = 0
            for centre in centres_par_region.get(region_id, []):
                centre_id = int(centre["id"])
                disponible = int(
                    capacites_centres.get(centre_id, {}).get("disponible", 0)
                )
                if disponible <= 0:
                    continue
                if not AffectationCentreService._genre_compatible(
                    profil.sexe, centre.get("genre")
                ):
                    continue
                if not AffectationCentreService._public_compatible(
                    profil.type_immerge, centre.get("publics_acceptes")
                ):
                    continue
                total += disponible
            resultat[region_id] = {"disponible": total}
        return resultat

    @staticmethod
    def _classer_regions(
        *,
        profil: ProfilAffectation,
        regions: list[dict],
        capacites: dict[int, dict],
    ) -> list[tuple[float, int, dict]]:
        classement = []
        for region in regions:
            region_id = int(region["id"])
            disponible = capacites.get(region_id, {}).get("disponible", 0)
            if disponible <= 0:
                continue

            score = NormalisationGeographiqueService.score(
                profil.region_reference,
                region.get("nom") or region.get("code"),
            )
            classement.append((score, disponible, region))

        classement.sort(
            key=lambda element: (
                element[0],
                element[1],
                -int(element[2]["id"]),
            ),
            reverse=True,
        )
        return classement

    @classmethod
    def _choisir_region(
        cls,
        *,
        profil: ProfilAffectation,
        regions: list[dict],
        capacites: dict[int, dict],
        forcer_reliquat: bool,
    ) -> tuple[dict | None, float, str]:
        classement = cls._classer_regions(
            profil=profil,
            regions=regions,
            capacites=capacites,
        )
        if not classement:
            return None, 0.0, "aucune_capacite"

        meilleur_score, _, meilleure_region = classement[0]

        if meilleur_score >= cls.SEUIL_CORRESPONDANCE_FORTE:
            return meilleure_region, meilleur_score, "correspondance_forte"

        if meilleur_score >= cls.SEUIL_CORRESPONDANCE_ASSOUPLIE:
            return meilleure_region, meilleur_score, "correspondance_assouplie"

        if forcer_reliquat:
            # Ce mode n'est utilisé que lorsque l'acteur l'a explicitement
            # demandé. Le backend ne doit jamais l'activer automatiquement.
            if meilleur_score > 0:
                return meilleure_region, meilleur_score, "correspondance_assouplie"

            region_capacitaire = max(
                classement,
                key=lambda element: (
                    element[1],
                    -int(element[2]["id"]),
                ),
            )
            return (
                region_capacitaire[2],
                region_capacitaire[0],
                "equilibrage_capacitaire",
            )

        return None, meilleur_score, "correspondance_insuffisante"

    @classmethod
    @transaction.atomic
    def proposer_lot(
        cls,
        *,
        session_id: int,
        nombre: int,
        acteur=None,
        forcer_reliquat: bool = False,
    ) -> ResultatPropositionLot:
        nombre = cls.valider_taille_lot(nombre)
        cls.verifier_aucune_proposition_en_attente(session_id)
        total_avant = (
            CriteresImmergeAffectationRepository.compter_candidats_regionaux(
                session_id=session_id,
            )
        )
        if total_avant == 0:
            return ResultatPropositionLot(
                demandes=nombre,
                candidats_pris=0,
                propositions_creees=0,
                candidats_restants=0,
            )

        candidats = list(
            CriteresImmergeAffectationRepository.verrouiller_lot_candidats_regionaux(
                session_id=session_id,
                limite=nombre,
            )
        )
        if not candidats:
            return ResultatPropositionLot(
                demandes=nombre,
                candidats_pris=0,
                propositions_creees=0,
                candidats_restants=total_avant,
            )

        centre_ids, region_ids = PerimetreCentresSessionService.region_ids(session_id)
        regions = list(
            RegionImmersionRepository.lister_donnees_algorithme().filter(
                id__in=region_ids
            )
        )
        if not regions:
            raise ValidationAffectationErreur(
                {"regions": "Aucune région admissible n'est disponible pour la session."}
            )

        # Tous les services d'affectation doivent verrouiller les mêmes lignes
        # régions avant de calculer les places disponibles.
        list(RegionImmersionRepository.verrouiller_par_ids(region_ids))

        capacites = CapaciteAffectationService.capacites_regions(
            session_id,
            region_ids,
        )
        if sum(donnees["disponible"] for donnees in capacites.values()) <= 0:
            raise ValidationAffectationErreur(
                {"capacite": "Aucune place régionale n'est disponible."}
            )

        centres = list(
            CentreImmersionRepository.lister_donnees_algorithme(
                region_ids=region_ids
            ).filter(id__in=centre_ids)
        )
        centre_ids_algorithme = [int(centre["id"]) for centre in centres]
        list(CentreImmersionRepository.verrouiller_par_ids(centre_ids_algorithme))
        capacites_centres = CapaciteAffectationService.capacites_centres(
            session_id=session_id,
            centres=centres,
        )
        centres_par_region = cls._centres_par_region(centres)

        # Les affectations régionales déjà validées, mais pas encore placées
        # dans un centre, consomment aussi une place compatible. On les réserve
        # d'abord afin qu'un nouveau lot DGAS ne puisse pas surcharger une
        # région par sexe ou par public.
        existantes = list(
            AffectationRegionaleRepository.lister_actives_sans_centre(
                session_id=session_id,
                region_ids=region_ids,
            )
        )
        profils_existants, _ = ProfilAffectationService.construire_profils(
            [affectation.immerge for affectation in existantes]
        )
        for affectation in existantes:
            profil_existant = profils_existants.get(affectation.immerge_id)
            if profil_existant is None:
                continue
            centre_reserve = cls._centre_compatible_disponible(
                profil=profil_existant,
                centres=centres_par_region.get(affectation.region_id, []),
                capacites_centres=capacites_centres,
            )
            if centre_reserve is not None:
                capacites_centres[int(centre_reserve["id"])]["disponible"] -= 1

        profils, sans_source = ProfilAffectationService.construire_profils(candidats)
        reliquat = bool(forcer_reliquat)

        propositions = []
        sans_destination = []
        repartition: dict[int, int] = {}

        for immerge in candidats:
            profil = profils.get(immerge.id)
            if profil is None:
                continue

            capacites_compatibles = cls._capacites_regionales_compatibles(
                profil=profil,
                regions=regions,
                centres_par_region=centres_par_region,
                capacites_centres=capacites_centres,
            )
            region, score, mode = cls._choisir_region(
                profil=profil,
                regions=regions,
                capacites=capacites_compatibles,
                forcer_reliquat=reliquat,
            )
            if region is None:
                sans_destination.append(immerge.id)
                continue

            region_id = int(region["id"])
            centre_reserve = cls._centre_compatible_disponible(
                profil=profil,
                centres=centres_par_region.get(region_id, []),
                capacites_centres=capacites_centres,
            )
            if centre_reserve is None:
                sans_destination.append(immerge.id)
                continue
            motif = (
                "Proposition automatique régionale"
                f" | région source={profil.region_reference or 'non renseignée'}"
                f" | correspondance={round(score * 100)}%"
                f" | mode={mode}"
            )
            propositions.append(
                AffectationRegionale(
                    immerge_id=immerge.id,
                    session_id=session_id,
                    region_id=region_id,
                    statut=AffectationRegionale.Statut.PROPOSEE,
                    affecte_par=acteur,
                    motif=motif,
                )
            )
            capacites[region_id]["disponible"] -= 1
            capacites_centres[int(centre_reserve["id"])]["disponible"] -= 1
            repartition[region_id] = repartition.get(region_id, 0) + 1

        creees = AffectationRegionaleRepository.creer_en_lot(propositions)
        total_apres = max(0, total_avant - len(creees))

        return ResultatPropositionLot(
            demandes=nombre,
            candidats_pris=len(candidats),
            propositions_creees=len(creees),
            candidats_restants=total_apres,
            sans_source=sans_source,
            sans_destination=sans_destination,
            affectation_ids=[affectation.id for affectation in creees],
            details={
                "reliquat_assoupli": reliquat,
                "repartition_par_region": repartition,
            },
        )

    @classmethod
    @transaction.atomic
    def proposer_reaffectations_sans_centre_compatible(
        cls,
        *,
        session_id: int,
        acteur=None,
        appliquer: bool = False,
    ) -> dict:
        """Prépare le rattrapage des immergés bloqués dans une région.

        Une affectation est transférable seulement si elle est active, ne
        possède aucune affectation centre ouverte et qu'aucun centre de sa
        région actuelle ne dispose encore d'une place compatible avec son sexe
        et son public. Les affectations déjà validées vers un centre ne sont
        jamais touchées.
        """

        centre_ids, region_ids = PerimetreCentresSessionService.region_ids(session_id)
        regions = list(
            RegionImmersionRepository.lister_donnees_algorithme().filter(
                id__in=region_ids
            )
        )
        centres = list(
            CentreImmersionRepository.lister_donnees_algorithme(
                region_ids=region_ids
            ).filter(id__in=centre_ids)
        )
        if not regions or not centres:
            raise ValidationAffectationErreur(
                {"perimetre": "Aucune région ou aucun centre admissible n'est disponible."}
            )

        list(RegionImmersionRepository.verrouiller_par_ids(region_ids))
        list(CentreImmersionRepository.verrouiller_par_ids(centre_ids))
        capacites_centres = CapaciteAffectationService.capacites_centres(
            session_id=session_id,
            centres=centres,
        )
        centres_par_region = cls._centres_par_region(centres)

        affectations = list(
            AffectationRegionaleRepository.lister_actives_sans_centre(
                session_id=session_id,
                region_ids=region_ids,
            ).select_for_update(of=("self",))
        )
        profils, sans_source = ProfilAffectationService.construire_profils(
            [affectation.immerge for affectation in affectations]
        )

        bloquees = []
        conservees = []
        for affectation in affectations:
            profil = profils.get(affectation.immerge_id)
            if profil is None:
                continue
            centre = cls._centre_compatible_disponible(
                profil=profil,
                centres=centres_par_region.get(affectation.region_id, []),
                capacites_centres=capacites_centres,
            )
            if centre is None:
                bloquees.append((affectation, profil))
                continue
            capacites_centres[int(centre["id"])]["disponible"] -= 1
            conservees.append(affectation.id)

        nouvelles = []
        transferees = []
        sans_destination = []
        repartition: dict[int, int] = {}
        regions_par_id = {int(region["id"]): region for region in regions}

        for affectation, profil in bloquees:
            regions_candidates = [
                region
                for region in regions
                if int(region["id"]) != int(affectation.region_id)
            ]
            capacites_compatibles = cls._capacites_regionales_compatibles(
                profil=profil,
                regions=regions_candidates,
                centres_par_region=centres_par_region,
                capacites_centres=capacites_centres,
            )
            region, score, mode = cls._choisir_region(
                profil=profil,
                regions=regions_candidates,
                capacites=capacites_compatibles,
                forcer_reliquat=True,
            )
            if region is None:
                sans_destination.append(affectation.immerge_id)
                continue

            region_id = int(region["id"])
            centre_reserve = cls._centre_compatible_disponible(
                profil=profil,
                centres=centres_par_region.get(region_id, []),
                capacites_centres=capacites_centres,
            )
            if centre_reserve is None:
                sans_destination.append(affectation.immerge_id)
                continue

            ancien_nom = regions_par_id[int(affectation.region_id)]["nom"]
            motif = (
                "Réaffectation automatique après absence de centre compatible"
                f" | ancienne région={ancien_nom}"
                f" | sexe={profil.sexe or 'non renseigné'}"
                f" | public={profil.type_immerge}"
                f" | correspondance={round(score * 100)}%"
                f" | mode={mode}"
            )
            nouvelles.append(
                AffectationRegionale(
                    immerge_id=affectation.immerge_id,
                    session_id=session_id,
                    region_id=region_id,
                    statut=AffectationRegionale.Statut.PROPOSEE,
                    affecte_par=acteur,
                    motif=motif,
                )
            )
            capacites_centres[int(centre_reserve["id"])]["disponible"] -= 1
            repartition[region_id] = repartition.get(region_id, 0) + 1
            transferees.append(affectation)

        if appliquer and nouvelles:
            maintenant = timezone.now()
            for affectation in transferees:
                affectation.statut = AffectationRegionale.Statut.TRANSFEREE
                affectation.motif = (
                    f"{affectation.motif} | Transférée automatiquement le "
                    f"{maintenant.isoformat()} faute de centre compatible."
                ).strip(" |")
                affectation.updated_at = maintenant
            AffectationRegionaleRepository.mettre_a_jour_en_lot(
                transferees,
                ["statut", "motif", "updated_at"],
            )
            creees = AffectationRegionaleRepository.creer_en_lot(nouvelles)
        else:
            creees = nouvelles
            transaction.set_rollback(True)

        return {
            "session_id": int(session_id),
            "mode": "application" if appliquer else "simulation",
            "affectations_regionales_sans_centre": len(affectations),
            "conservees_dans_region_actuelle": len(conservees),
            "bloquees": len(bloquees),
            "reaffectations_proposees": len(creees),
            "sans_source": sans_source,
            "sans_destination": sans_destination,
            "repartition_par_region": repartition,
            "nouveaux_ids": [objet.id for objet in creees if objet.id],
        }

    @staticmethod
    @transaction.atomic
    def proposer_manuellement(
        *,
        immerge_id: int | None = None,
        code_fasoim: str | None = None,
        region_id: int,
        acteur=None,
        motif: str = "",
    ):
        filtres = {}
        if immerge_id is not None:
            filtres["immerge_ids"] = [immerge_id]
        if code_fasoim:
            filtres["codes_fasoim"] = [str(code_fasoim).strip().upper()]
        immerge = (
            CriteresImmergeAffectationRepository.filtrer_immerges(**filtres)
            .select_for_update(of=("self",))
            .first()
        )
        if immerge is None:
            raise ValidationAffectationErreur(
                {"immerge": "L'immergé demandé est introuvable."}
            )
        if AffectationRegionaleRepository.get_ouverte_par_immerge_pour_update(
            immerge_id
        ):
            raise ValidationAffectationErreur(
                {"immerge": "Cet immergé possède déjà une affectation régionale ouverte."}
            )

        PerimetreCentresSessionService.verifier_region(
            session_id=immerge.session_id, region_id=region_id
        )
        region = RegionImmersionRepository.get_by_id_pour_update(region_id)
        if not region.est_active:
            raise ValidationAffectationErreur(
                {"region": "La région choisie n'est pas active."}
            )

        capacites = CapaciteAffectationService.capacites_regions(
            immerge.session_id,
            [region.id],
        )
        if capacites[region.id]["disponible"] <= 0:
            raise ValidationAffectationErreur(
                {"region": "La capacité de cette région est atteinte."}
            )

        affectation = AffectationRegionaleRepository.creer(
            immerge=immerge,
            session_id=immerge.session_id,
            region=region,
            statut=AffectationRegionale.Statut.ACTIVE,
            affecte_par=acteur,
            motif=motif or "Affectation régionale manuelle.",
        )
        statut_region = getattr(Immerge.Statut, "AFFECTE_REGION", None)
        if statut_region:
            immerge.statut = statut_region
            immerge.updated_at = timezone.now()
            ImmergeRepository.mettre_a_jour_en_masse(
                [immerge],
                ["statut", "updated_at"],
            )
        return affectation

    @staticmethod
    @transaction.atomic
    def valider_lot(affectation_ids, *, acteur=None, motif: str = "") -> list:
        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(AffectationRegionaleRepository.verrouiller_par_ids(ids))

        if len(affectations) != len(ids):
            raise ValidationAffectationErreur(
                {"affectations": "Une ou plusieurs propositions sont introuvables."}
            )

        capacites = CapaciteAffectationService.capacites_regions(
            session_id=affectations[0].session_id if affectations else 0,
            region_ids=list({affectation.region_id for affectation in affectations}),
        )
        for region_id, donnees in capacites.items():
            if int(donnees["occupation_ouverte"]) > int(donnees["capacite_ouverte"]):
                raise ValidationAffectationErreur(
                    {
                        "capacite": (
                            "La capacité de la région est dépassée. "
                            "Réduisez ou redistribuez les propositions avant validation."
                        )
                    }
                )

        maintenant = timezone.now()
        immerges = {
            immerge.id: immerge
            for immerge in CriteresImmergeAffectationRepository.filtrer_immerges(
                immerge_ids=[affectation.immerge_id for affectation in affectations]
            )
        }
        for affectation in affectations:
            if affectation.statut != AffectationRegionale.Statut.PROPOSEE:
                raise ValidationAffectationErreur(
                    {
                        "affectations": (
                            f"L'affectation {affectation.id} n'est plus une proposition."
                        )
                    }
                )
            affectation.statut = AffectationRegionale.Statut.ACTIVE
            affectation.affecte_par = acteur or affectation.affecte_par
            affectation.date_affectation = maintenant
            affectation.motif = motif or affectation.motif
            affectation.updated_at = maintenant

        AffectationRegionaleRepository.mettre_a_jour_en_lot(
            affectations,
            ["statut", "affecte_par", "date_affectation", "motif", "updated_at"],
        )

        statut_region = getattr(Immerge.Statut, "AFFECTE_REGION", None)
        if statut_region:
            for immerge in immerges.values():
                immerge.statut = statut_region
                immerge.updated_at = maintenant
            ImmergeRepository.mettre_a_jour_en_masse(
                list(immerges.values()),
                ["statut", "updated_at"],
            )

        return affectations

    @staticmethod
    @transaction.atomic
    def rejeter_lot(affectation_ids, *, motif: str) -> list:
        if not str(motif or "").strip():
            raise ValidationAffectationErreur(
                {"motif": "Le motif de rejet est obligatoire."}
            )

        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(AffectationRegionaleRepository.verrouiller_par_ids(ids))
        if len(affectations) != len(ids):
            raise ValidationAffectationErreur(
                {"affectations": "Une ou plusieurs propositions sont introuvables."}
            )

        for affectation in affectations:
            if affectation.statut != AffectationRegionale.Statut.PROPOSEE:
                raise ValidationAffectationErreur(
                    {
                        "affectations": (
                            f"L'affectation {affectation.id} n'est plus une proposition."
                        )
                    }
                )
            affectation.statut = AffectationRegionale.Statut.REJETEE
            affectation.motif = motif
            affectation.updated_at = timezone.now()

        AffectationRegionaleRepository.mettre_a_jour_en_lot(
            affectations,
            ["statut", "motif", "updated_at"],
        )
        return affectations


class AffectationCentreService:
    """Propose les centres compatibles puis gère la validation du lot."""

    LIMITE_MAX_LOT = 1000

    @classmethod
    def valider_taille_lot(cls, nombre: int) -> int:
        return AffectationRegionaleService.valider_taille_lot(nombre)

    @staticmethod
    def verifier_aucune_proposition_en_attente(*, session_id: int, region_id: int) -> None:
        total = AffectationCentreRepository.compter_propositions_en_attente(
            session_id=session_id,
            region_id=region_id,
        )
        if total > 0:
            raise ValidationAffectationErreur({
                "propositions": (
                    f"{total} proposition(s) vers les centres sont encore en attente "
                    "de validation. Validez-les ou rejetez-les avant de lancer "
                    "une nouvelle proposition."
                )
            })

    @staticmethod
    def _genre_compatible(sexe: str, genre_centre: str) -> bool:
        sexe = str(sexe or "").strip().upper()
        genre = str(genre_centre or "").strip().upper()

        if genre == CentreImmersion.Genre.MIXTE:
            return True
        if sexe == "M":
            return genre == CentreImmersion.Genre.MASCULIN
        if sexe == "F":
            return genre == CentreImmersion.Genre.FEMININ
        return False

    @staticmethod
    def _sexe_dortoir(sexe: str) -> str:
        valeur = str(sexe or "").strip().upper()
        if valeur == "M":
            return "MASCULIN"
        if valeur == "F":
            return "FEMININ"
        return ""

    @classmethod
    def _capacites_sexe_centres(
        cls,
        *,
        session_id: int,
        centres: list[dict],
    ) -> dict[int, dict[str, dict[str, int]]]:
        """Calcule les places d'hébergement réellement disponibles par sexe.

        Lorsque l'hébergement est actif, les propositions et affectations centre
        ouvertes sont déduites des lits utilisables du sexe correspondant. La
        capacité globale du centre reste contrôlée séparément.
        """
        session = SessionImmersion.objects.select_related("parametres").get(
            id=session_id, deleted_at__isnull=True
        )
        if not ParametreSessionService.hebergement_autorise(session):
            return {}

        from django.db.models import Count
        from organisation.models import Dortoir, Lit

        centre_ids = [int(centre["id"]) for centre in centres]
        resultat = {
            centre_id: {
                "M": {"capacite": 0, "occupation": 0, "disponible": 0},
                "F": {"capacite": 0, "occupation": 0, "disponible": 0},
            }
            for centre_id in centre_ids
        }

        lignes_lits = (
            Lit.objects.filter(
                dortoir__centre_id__in=centre_ids,
                deleted_at__isnull=True,
                statut=Lit.Statut.DISPONIBLE,
                dortoir__deleted_at__isnull=True,
                dortoir__statut=Dortoir.Statut.ACTIF,
            )
            .values("dortoir__centre_id", "dortoir__sexe_dortoir")
            .annotate(total=Count("id"))
        )
        for ligne in lignes_lits:
            centre_id = int(ligne["dortoir__centre_id"])
            sexe = "M" if ligne["dortoir__sexe_dortoir"] == Dortoir.SexeDortoir.MASCULIN else "F"
            resultat[centre_id][sexe]["capacite"] = int(ligne["total"])

        ouvertes = list(
            AffectationCentreRepository.lister_ouvertes().filter(
                session_id=session_id, centre_id__in=centre_ids
            ).only("id", "centre_id", "immerge_id", "immerge__origine_id", "immerge__type_immerge")
        )
        profils, _ = ProfilAffectationService.construire_profils(
            [affectation.immerge for affectation in ouvertes]
        )
        for affectation in ouvertes:
            profil = profils.get(affectation.immerge_id)
            sexe = str(getattr(profil, "sexe", "") or "").strip().upper()
            if sexe in {"M", "F"}:
                resultat[int(affectation.centre_id)][sexe]["occupation"] += 1

        for donnees_centre in resultat.values():
            for donnees_sexe in donnees_centre.values():
                donnees_sexe["disponible"] = max(
                    0,
                    int(donnees_sexe["capacite"])
                    - int(donnees_sexe["occupation"]),
                )
        return resultat

    @staticmethod
    def _public_compatible(type_immerge: str, publics_acceptes) -> bool:
        publics = {
            str(public).strip().upper()
            for public in (publics_acceptes or [])
            if str(public).strip()
        }
        if not publics:
            return True
        return str(type_immerge or "").strip().upper() in publics

    @staticmethod
    def _niveau_compatible(
        profil: ProfilAffectation,
        niveaux_acceptes,
    ) -> bool:
        # Ce filtre concerne en priorité BEPC/BAC. Les autres publics sont déjà
        # filtrés par publics_acceptes.
        if profil.type_immerge not in {
            Immerge.TypeImmerge.BEPC,
            Immerge.TypeImmerge.BAC,
        }:
            return True

        niveaux = {
            NormalisationGeographiqueService.normaliser(niveau)
            for niveau in (niveaux_acceptes or [])
            if str(niveau).strip()
        }
        if not niveaux:
            return True

        type_examen = NormalisationGeographiqueService.normaliser(
            profil.niveau_examen or profil.type_immerge
        )

        # Un libellé générique tel que « Tous type de BAC » signifie que le
        # centre accepte toutes les séries de ce niveau. Il ne doit pas être
        # comparé comme s'il s'agissait du nom exact d'une série.
        libelles_generiques = {
            NormalisationGeographiqueService.normaliser(libelle)
            for libelle in (
                type_examen,
                f"tout type de {type_examen}",
                f"tous les types de {type_examen}",
                f"toute serie de {type_examen}",
                f"toutes les series de {type_examen}",
                f"toute filiere de {type_examen}",
                f"toutes les filieres de {type_examen}",
            )
        }
        if niveaux & libelles_generiques:
            return True

        serie = NormalisationGeographiqueService.normaliser(profil.serie_filiere)
        combinaisons = {
            type_examen,
            serie,
            NormalisationGeographiqueService.normaliser(
                f"{type_examen} {serie}"
            ),
        }
        combinaisons.discard("")
        return bool(niveaux & combinaisons)

    @classmethod
    def _centres_compatibles(
        cls,
        *,
        profil: ProfilAffectation,
        centres: list[dict],
        capacites: dict[int, dict],
        capacites_sexe: dict[int, dict[str, dict[str, int]]] | None = None,
    ) -> list[tuple[float, float, int, dict]]:
        compatibles = []

        for centre in centres:
            centre_id = int(centre["id"])
            capacite = capacites.get(centre_id, {})
            disponible = int(capacite.get("disponible", 0))
            totale = int(capacite.get("capacite_totale", 0))
            if disponible <= 0:
                continue
            sexe = str(profil.sexe or "").strip().upper()
            if capacites_sexe is not None:
                disponible_sexe = int(
                    capacites_sexe.get(centre_id, {}).get(sexe, {}).get(
                        "disponible", 0
                    )
                )
                if sexe not in {"M", "F"} or disponible_sexe <= 0:
                    continue
            if not cls._genre_compatible(profil.sexe, centre.get("genre")):
                continue
            if not cls._public_compatible(
                profil.type_immerge,
                centre.get("publics_acceptes"),
            ):
                continue
            score_province = NormalisationGeographiqueService.score(
                profil.province_reference,
                centre.get("province"),
            )
            taux_libre = disponible / totale if totale > 0 else 0.0
            compatibles.append(
                (score_province, taux_libre, disponible, centre)
            )

        compatibles.sort(
            key=lambda element: (
                element[0],
                element[1],
                element[2],
                -int(element[3]["id"]),
            ),
            reverse=True,
        )
        return compatibles

    @classmethod
    @transaction.atomic
    def proposer_lot(
        cls,
        *,
        session_id: int,
        region_id: int,
        nombre: int,
        acteur=None,
    ) -> ResultatPropositionLot:
        nombre = cls.valider_taille_lot(nombre)
        cls.verifier_aucune_proposition_en_attente(
            session_id=session_id,
            region_id=region_id,
        )
        total_avant = (
            CriteresImmergeAffectationRepository.compter_candidats_centre(
                session_id=session_id,
                region_id=region_id,
            )
        )
        if total_avant == 0:
            return ResultatPropositionLot(
                demandes=nombre,
                candidats_pris=0,
                propositions_creees=0,
                candidats_restants=0,
            )

        candidats = list(
            CriteresImmergeAffectationRepository.verrouiller_lot_candidats_centre(
                session_id=session_id,
                region_id=region_id,
                limite=nombre,
            )
        )
        if not candidats:
            return ResultatPropositionLot(
                demandes=nombre,
                candidats_pris=0,
                propositions_creees=0,
                candidats_restants=total_avant,
            )

        centres_retenus = PerimetreCentresSessionService.centre_ids(session_id)
        centres = list(
            CentreImmersionRepository.lister_donnees_algorithme(
                region_id=region_id
            ).filter(id__in=centres_retenus)
        )
        if not centres:
            raise ValidationAffectationErreur(
                {"centres": "Aucun centre actif n'existe dans cette région."}
            )

        centre_ids = [int(centre["id"]) for centre in centres]
        list(CentreImmersionRepository.verrouiller_par_ids(centre_ids))

        capacites = CapaciteAffectationService.capacites_centres(
            session_id=session_id,
            centres=centres,
            region_id=region_id,
        )
        capacites_sexe = cls._capacites_sexe_centres(
            session_id=session_id,
            centres=centres,
        )
        profils, sans_source = ProfilAffectationService.construire_profils(candidats)

        mappings_regionaux = {
            int(ligne["immerge_id"]): dict(ligne)
            for ligne in AffectationRegionaleRepository.mapping_actives_par_immerges(
                [immerge.id for immerge in candidats]
            )
            if int(ligne["region_id"]) == int(region_id)
        }

        propositions = []
        sans_destination = []
        repartition: dict[int, int] = {}

        for immerge in candidats:
            profil = profils.get(immerge.id)
            affectation_regionale = mappings_regionaux.get(immerge.id)
            if profil is None or affectation_regionale is None:
                if profil is not None:
                    sans_destination.append(immerge.id)
                continue

            compatibles = cls._centres_compatibles(
                profil=profil,
                centres=centres,
                capacites=capacites,
                capacites_sexe=capacites_sexe if capacites_sexe else None,
            )
            if not compatibles:
                sans_destination.append(immerge.id)
                continue

            score_province, _, _, centre = compatibles[0]
            centre_id = int(centre["id"])
            motif = (
                "Proposition automatique centre"
                f" | sexe={profil.sexe or 'non renseigné'}"
                f" | niveau={profil.niveau_examen or 'sans objet'}"
                f" | série={profil.serie_filiere or 'sans objet'}"
                f" | province source={profil.province_reference or 'non renseignée'}"
                f" | correspondance province={round(score_province * 100)}%"
            )
            propositions.append(
                AffectationCentre(
                    immerge_id=immerge.id,
                    session_id=session_id,
                    affectation_regionale_id=affectation_regionale["id"],
                    centre_id=centre_id,
                    statut=AffectationCentre.Statut.PROPOSEE,
                    affecte_par=acteur,
                    motif=motif,
                )
            )
            capacites[centre_id]["disponible"] -= 1
            sexe = str(profil.sexe or "").strip().upper()
            if capacites_sexe and sexe in {"M", "F"}:
                capacites_sexe[centre_id][sexe]["disponible"] -= 1
                capacites_sexe[centre_id][sexe]["occupation"] += 1
            repartition[centre_id] = repartition.get(centre_id, 0) + 1

        creees = AffectationCentreRepository.creer_en_lot(propositions)
        total_apres = max(0, total_avant - len(creees))

        return ResultatPropositionLot(
            demandes=nombre,
            candidats_pris=len(candidats),
            propositions_creees=len(creees),
            candidats_restants=total_apres,
            sans_source=sans_source,
            sans_destination=sans_destination,
            affectation_ids=[affectation.id for affectation in creees],
            details={"repartition_par_centre": repartition},
        )

    @classmethod
    @transaction.atomic
    def proposer_manuellement(
        cls,
        *,
        centre_id: int,
        acteur=None,
        motif: str = "",
        immerge_id: int | None = None,
        code_fasoim: str | None = None,
    ):
        if code_fasoim:
            try:
                immerge_id = ImmergeRepository.get_par_code(
                    str(code_fasoim).strip().upper()
                ).id
            except Immerge.DoesNotExist as exc:
                raise ValidationAffectationErreur({
                    "code_fasoim": "Aucun immergé ne correspond à ce Code FasoIM."
                }) from exc
        if not immerge_id:
            raise ValidationAffectationErreur({
                "immerge": "L'immergé à affecter est obligatoire."
            })

        affectation_regionale = (
            AffectationRegionaleRepository.get_active_par_immerge_pour_update(
                immerge_id
            )
        )
        if affectation_regionale is None:
            raise ValidationAffectationErreur(
                {"immerge": "L'immergé ne possède aucune affectation régionale active."}
            )
        if AffectationCentreRepository.get_ouverte_par_immerge_pour_update(
            immerge_id
        ):
            raise ValidationAffectationErreur(
                {"immerge": "Cet immergé possède déjà une affectation centre ouverte."}
            )

        PerimetreCentresSessionService.verifier_centre(
            session_id=affectation_regionale.session_id, centre_id=centre_id
        )
        centre = CentreImmersionRepository.get_by_id_pour_update(centre_id)
        if centre.region_id != affectation_regionale.region_id:
            raise ValidationAffectationErreur(
                {"centre": "Le centre n'appartient pas à la région de l'immergé."}
            )

        immerge = affectation_regionale.immerge
        profils, sans_source = ProfilAffectationService.construire_profils([immerge])
        if sans_source:
            raise ValidationAffectationErreur(
                {"source": "La source valide de cet immergé est introuvable."}
            )
        profil = profils[immerge.id]

        centre_donnees = {
            "id": centre.id,
            "region_id": centre.region_id,
            "code": centre.code,
            "nom": centre.nom,
            "province": centre.province,
            "ville": centre.ville,
            "genre": centre.genre,
            "publics_acceptes": centre.publics_acceptes,
            "niveaux_acceptes": centre.niveaux_acceptes,
        }
        capacites = CapaciteAffectationService.capacites_centres(
            session_id=immerge.session_id,
            centres=[centre_donnees],
            region_id=centre.region_id,
        )
        capacites_sexe = cls._capacites_sexe_centres(
            session_id=immerge.session_id,
            centres=[centre_donnees],
        )
        if not cls._centres_compatibles(
            profil=profil,
            centres=[centre_donnees],
            capacites=capacites,
            capacites_sexe=capacites_sexe if capacites_sexe else None,
        ):
            raise ValidationAffectationErreur(
                {
                    "centre": (
                        "Le centre est plein ou ne dispose pas d'une place "
                        "d'hébergement compatible avec le sexe et le public de l'immergé."
                    )
                }
            )

        affectation = AffectationCentreRepository.creer(
            immerge=immerge,
            session_id=immerge.session_id,
            affectation_regionale=affectation_regionale,
            centre=centre,
            statut=AffectationCentre.Statut.ACTIVE,
            affecte_par=acteur,
            motif=motif or "Affectation centre manuelle.",
        )
        statut_centre = getattr(Immerge.Statut, "AFFECTE_CENTRE", None)
        if statut_centre:
            immerge.statut = statut_centre
            immerge.updated_at = timezone.now()
            ImmergeRepository.mettre_a_jour_en_masse(
                [immerge],
                ["statut", "updated_at"],
            )
        return affectation

    @staticmethod
    @transaction.atomic
    def valider_lot(affectation_ids, *, acteur=None, motif: str = "") -> list:
        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(AffectationCentreRepository.verrouiller_par_ids(ids))
        if len(affectations) != len(ids):
            raise ValidationAffectationErreur(
                {"affectations": "Une ou plusieurs propositions sont introuvables."}
            )

        maintenant = timezone.now()
        immerges = {
            immerge.id: immerge
            for immerge in CriteresImmergeAffectationRepository.filtrer_immerges(
                immerge_ids=[affectation.immerge_id for affectation in affectations]
            )
        }
        for affectation in affectations:
            if affectation.statut != AffectationCentre.Statut.PROPOSEE:
                raise ValidationAffectationErreur(
                    {
                        "affectations": (
                            f"L'affectation {affectation.id} n'est plus une proposition."
                        )
                    }
                )
            affectation.statut = AffectationCentre.Statut.ACTIVE
            affectation.affecte_par = acteur or affectation.affecte_par
            affectation.date_affectation = maintenant
            affectation.motif = motif or affectation.motif
            affectation.updated_at = maintenant

        AffectationCentreRepository.mettre_a_jour_en_lot(
            affectations,
            ["statut", "affecte_par", "date_affectation", "motif", "updated_at"],
        )

        statut_centre = getattr(Immerge.Statut, "AFFECTE_CENTRE", None)
        if statut_centre:
            for immerge in immerges.values():
                immerge.statut = statut_centre
                immerge.updated_at = maintenant
            ImmergeRepository.mettre_a_jour_en_masse(
                list(immerges.values()),
                ["statut", "updated_at"],
            )

        return affectations

    @staticmethod
    @transaction.atomic
    def rejeter_lot(affectation_ids, *, motif: str) -> list:
        if not str(motif or "").strip():
            raise ValidationAffectationErreur(
                {"motif": "Le motif de rejet est obligatoire."}
            )

        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(AffectationCentreRepository.verrouiller_par_ids(ids))
        if len(affectations) != len(ids):
            raise ValidationAffectationErreur(
                {"affectations": "Une ou plusieurs propositions sont introuvables."}
            )

        for affectation in affectations:
            if affectation.statut != AffectationCentre.Statut.PROPOSEE:
                raise ValidationAffectationErreur(
                    {
                        "affectations": (
                            f"L'affectation {affectation.id} n'est plus une proposition."
                        )
                    }
                )
            affectation.statut = AffectationCentre.Statut.REJETEE
            affectation.motif = motif
            affectation.updated_at = timezone.now()

        AffectationCentreRepository.mettre_a_jour_en_lot(
            affectations,
            ["statut", "motif", "updated_at"],
        )
        return affectations
