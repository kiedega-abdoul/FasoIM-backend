from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from affectations.models import AffectationCentre
from affectations.service import ProfilAffectationService

from .models import (
    AffectationGroupe,
    AttributionLit,
    Dortoir,
    Groupe,
    Lit,
    RegleOrganisationCentre,
    Section,
)
from .repository import (
    STATUTS_GROUPES_OUVERTS,
    STATUTS_LITS_OUVERTS,
    AffectationGroupeRepository,
    AttributionLitRepository,
    CandidatsOrganisationRepository,
    DortoirRepository,
    GroupeRepository,
    LitRepository,
    RegleOrganisationCentreRepository,
    SectionRepository,
)


class ValidationOrganisationErreur(ValidationError):
    """Erreur métier lisible par l'API et les tâches Celery."""


@dataclass
class ResultatOperationOrganisation:
    """Résultat sérialisable d'une opération lourde d'organisation."""

    demandes: int = 0
    traites: int = 0
    crees: int = 0
    restants: int = 0
    sans_destination: list[int] = field(default_factory=list)
    ids_crees: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def en_dict(self) -> dict:
        return asdict(self)


class RegleOrganisationCentreService:
    """Création, modification et validation des règles locales du centre."""

    @staticmethod
    def _verifier_capacite_ouverte(*, session, centre, capacite_ouverte, occupation=0):
        capacite_ouverte = int(capacite_ouverte)
        if capacite_ouverte < int(occupation):
            raise ValidationOrganisationErreur({
                "capacite_ouverte": (
                    "La capacité ouverte ne peut pas être inférieure au nombre "
                    "d'affectations centre déjà ouvertes."
                )
            })
        parametres = getattr(session, "parametres", None)
        if parametres and parametres.hebergement_active:
            capacite_physique = LitRepository.compter_exploitables_par_centre(centre.id)
            if capacite_ouverte > capacite_physique:
                raise ValidationOrganisationErreur({
                    "capacite_ouverte": (
                        f"La capacité ouverte ({capacite_ouverte}) dépasse les "
                        f"{capacite_physique} lits exploitables du centre."
                    )
                })

    @staticmethod
    @transaction.atomic
    def creer(*, session, centre, acteur=None, **donnees):
        RegleOrganisationCentreService._verifier_capacite_ouverte(
            session=session, centre=centre,
            capacite_ouverte=donnees.get("capacite_ouverte"), occupation=0,
        )
        if RegleOrganisationCentreRepository.existe_pour_session_centre(
            session.id,
            centre.id,
        ):
            raise ValidationOrganisationErreur(
                {
                    "centre": (
                        "Une règle d'organisation ouverte existe déjà pour "
                        "ce centre et cette session."
                    )
                }
            )

        regle = RegleOrganisationCentreRepository.creer(
            session=session,
            centre=centre,
            validee_par=None,
            **donnees,
        )
        return regle

    @staticmethod
    @transaction.atomic
    def modifier(regle_id: int, **donnees):
        regle = RegleOrganisationCentre.objects.select_for_update().get(
            id=regle_id,
            deleted_at__isnull=True,
        )

        if regle.statut == RegleOrganisationCentre.Statut.PRETE_PUBLICATION:
            raise ValidationOrganisationErreur(
                "Une organisation prête pour publication doit d'abord être "
                "rouverte avant modification."
            )

        nouvelle_capacite = donnees.get("capacite_ouverte", regle.capacite_ouverte)
        occupation = CandidatsOrganisationRepository.compter_affectations_centre_actives(
            session_id=regle.session_id, centre_id=regle.centre_id,
        )
        RegleOrganisationCentreService._verifier_capacite_ouverte(
            session=regle.session, centre=regle.centre,
            capacite_ouverte=nouvelle_capacite, occupation=occupation,
        )

        for champ, valeur in donnees.items():
            setattr(regle, champ, valeur)

        if regle.statut == RegleOrganisationCentre.Statut.VALIDEE:
            regle.statut = RegleOrganisationCentre.Statut.EN_COURS
            regle.date_validation = None
            regle.date_pret_publication = None

        champs = list(donnees.keys())
        for champ in ("statut", "date_validation", "date_pret_publication"):
            if champ not in champs:
                champs.append(champ)
        champs.append("updated_at")

        return RegleOrganisationCentreRepository.sauvegarder(
            regle,
            update_fields=champs,
        )

    @staticmethod
    @transaction.atomic
    def valider_organisation(
        *,
        session_id: int,
        centre_id: int,
        acteur=None,
    ):
        regle = (
            RegleOrganisationCentreRepository.get_par_session_centre_pour_update(
                session_id,
                centre_id,
            )
        )

        total_centre = (
            CandidatsOrganisationRepository.compter_affectations_centre_actives(
                session_id=session_id,
                centre_id=centre_id,
            )
        )
        total_groupes = AffectationGroupeRepository.lister_actives().filter(
            affectation_centre__session_id=session_id,
            affectation_centre__centre_id=centre_id,
        ).count()
        propositions_groupes = (
            AffectationGroupeRepository.lister_proposees().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            ).count()
        )
        a_reorganiser_groupes = (
            AffectationGroupeRepository.lister_a_reorganiser().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            ).count()
        )

        RegleOrganisationCentreService._verifier_capacite_ouverte(
            session=regle.session, centre=regle.centre,
            capacite_ouverte=regle.capacite_ouverte, occupation=total_centre,
        )

        erreurs = {}
        if total_groupes != total_centre:
            erreurs["groupes"] = (
                f"{total_groupes} immergé(s) ont un groupe actif sur "
                f"{total_centre} affectation(s) centre active(s)."
            )
        if propositions_groupes:
            erreurs["propositions_groupes"] = (
                f"{propositions_groupes} proposition(s) de groupe restent "
                "à valider."
            )
        if a_reorganiser_groupes:
            erreurs["groupes_a_reorganiser"] = (
                f"{a_reorganiser_groupes} immergé(s) doivent encore être "
                "réorganisés."
            )

        if regle.hebergement_active:
            total_lits = AttributionLitRepository.lister_actives().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            ).count()
            propositions_lits = (
                AttributionLitRepository.lister_proposees().filter(
                    affectation_centre__session_id=session_id,
                    affectation_centre__centre_id=centre_id,
                ).count()
            )
            a_reorganiser_lits = (
                AttributionLitRepository.lister_a_reorganiser().filter(
                    affectation_centre__session_id=session_id,
                    affectation_centre__centre_id=centre_id,
                ).count()
            )

            if total_lits != total_centre:
                erreurs["lits"] = (
                    f"{total_lits} immergé(s) ont un lit actif sur "
                    f"{total_centre} affectation(s) centre active(s)."
                )
            if propositions_lits:
                erreurs["propositions_lits"] = (
                    f"{propositions_lits} proposition(s) de lit restent "
                    "à valider."
                )
            if a_reorganiser_lits:
                erreurs["lits_a_reorganiser"] = (
                    f"{a_reorganiser_lits} attribution(s) doivent encore "
                    "être réorganisées."
                )

        if erreurs:
            raise ValidationOrganisationErreur(erreurs)

        return regle.valider_organisation(validee_par=acteur)

    @staticmethod
    @transaction.atomic
    def marquer_prete_publication(*, session_id: int, centre_id: int):
        regle = (
            RegleOrganisationCentreRepository.get_par_session_centre_pour_update(
                session_id,
                centre_id,
            )
        )
        return regle.marquer_prete_publication()


class OrganisationCentreService:
    """Génération des structures et affectation équilibrée aux groupes."""

    LIMITE_MAX_LOT = 5000

    @classmethod
    def valider_taille_lot(cls, nombre: int) -> int:
        try:
            nombre = int(nombre)
        except (TypeError, ValueError) as exc:
            raise ValidationOrganisationErreur(
                {"nombre": "Le nombre demandé doit être un entier."}
            ) from exc

        if nombre <= 0:
            raise ValidationOrganisationErreur(
                {"nombre": "Le nombre demandé doit être strictement positif."}
            )
        if nombre > cls.LIMITE_MAX_LOT:
            raise ValidationOrganisationErreur(
                {
                    "nombre": (
                        f"Un lot ne peut pas dépasser {cls.LIMITE_MAX_LOT} "
                        "immergés."
                    )
                }
            )
        return nombre

    @staticmethod
    def _repartir_equitablement(total: int, nombre_blocs: int) -> list[int]:
        if nombre_blocs <= 0:
            return []
        base, reste = divmod(total, nombre_blocs)
        return [
            base + (1 if index < reste else 0)
            for index in range(nombre_blocs)
        ]

    @staticmethod
    def _nombre_sections(total: int, regle: RegleOrganisationCentre) -> int:
        if total <= 0:
            return 0

        if (
            total < regle.seuil_division_sections
            and total <= regle.capacite_max_section
        ):
            return 1

        return max(1, ceil(total / regle.capacite_max_section))

    @staticmethod
    def _nombre_groupes(
        effectif_section: int,
        regle: RegleOrganisationCentre,
    ) -> int:
        if effectif_section <= 0:
            return 0

        if (
            effectif_section < regle.seuil_division_groupes
            and effectif_section <= regle.capacite_max_groupe
        ):
            return 1

        return max(1, ceil(effectif_section / regle.capacite_max_groupe))

    @classmethod
    @transaction.atomic
    def generer_sections_groupes(
        cls,
        *,
        session_id: int,
        centre_id: int,
        recreer: bool = False,
    ) -> ResultatOperationOrganisation:
        regle = (
            RegleOrganisationCentreRepository.get_par_session_centre_pour_update(
                session_id,
                centre_id,
            )
        )
        if not regle.repartition_sections_groupes_automatique:
            raise ValidationOrganisationErreur(
                "La génération automatique des sections et groupes est "
                "désactivée dans les règles du centre."
            )

        total = (
            CandidatsOrganisationRepository.compter_affectations_centre_actives(
                session_id=session_id,
                centre_id=centre_id,
            )
        )
        if total <= 0:
            raise ValidationOrganisationErreur(
                "Aucun immergé avec une affectation centre active n'est "
                "disponible pour cette organisation."
            )

        sections_existantes = list(
            SectionRepository.verrouiller_par_session_centre(
                session_id,
                centre_id,
            )
        )
        groupes_existants = list(
            GroupeRepository.verrouiller_par_session_centre(
                session_id,
                centre_id,
            )
        )

        if sections_existantes or groupes_existants:
            if not recreer:
                return ResultatOperationOrganisation(
                    demandes=total,
                    traites=total,
                    crees=0,
                    restants=0,
                    details={
                        "sections_existantes": len(sections_existantes),
                        "groupes_existants": len(groupes_existants),
                        "message": (
                            "Les structures existent déjà. Utiliser une "
                            "régénération explicite après avoir vidé "
                            "l'organisation."
                        ),
                    },
                )

            if AffectationGroupeRepository.compter_ouvertes_centre(
                session_id=session_id,
                centre_id=centre_id,
            ):
                raise ValidationOrganisationErreur(
                    "Les structures ne peuvent pas être régénérées tant que "
                    "des affectations groupe sont ouvertes."
                )

            maintenant = timezone.now()
            for groupe in groupes_existants:
                groupe.statut = Groupe.Statut.ARCHIVE
                groupe.deleted_at = maintenant
            GroupeRepository.mettre_a_jour_en_lot(
                groupes_existants,
                ["statut", "deleted_at", "updated_at"],
            )

            for section in sections_existantes:
                section.statut = Section.Statut.ARCHIVEE
                section.deleted_at = maintenant
            SectionRepository.mettre_a_jour_en_lot(
                sections_existantes,
                ["statut", "deleted_at", "updated_at"],
            )

        nombre_sections = cls._nombre_sections(total, regle)
        effectifs_sections = cls._repartir_equitablement(
            total,
            nombre_sections,
        )

        sections = [
            Section(
                session_id=session_id,
                centre_id=centre_id,
                code=f"SEC-{index:02d}",
                nom=f"Section {index}",
                capacite_max=max(
                    effectif,
                    min(regle.capacite_max_section, total),
                ),
                statut=Section.Statut.ACTIVE,
            )
            for index, effectif in enumerate(effectifs_sections, start=1)
        ]
        sections = SectionRepository.creer_en_lot(sections)

        groupes = []
        details_sections = {}
        for section, effectif_section in zip(
            sections,
            effectifs_sections,
            strict=True,
        ):
            nombre_groupes = cls._nombre_groupes(
                effectif_section,
                regle,
            )
            effectifs_groupes = cls._repartir_equitablement(
                effectif_section,
                nombre_groupes,
            )
            details_sections[section.id] = {
                "effectif_cible": effectif_section,
                "nombre_groupes": nombre_groupes,
            }

            for index, effectif_groupe in enumerate(
                effectifs_groupes,
                start=1,
            ):
                groupes.append(
                    Groupe(
                        section_id=section.id,
                        code=f"{section.code}-G{index:02d}",
                        nom=f"Groupe {index}",
                        capacite_max=max(
                            effectif_groupe,
                            min(
                                regle.capacite_max_groupe,
                                effectif_section,
                            ),
                        ),
                        statut=Groupe.Statut.ACTIF,
                    )
                )

        groupes = GroupeRepository.creer_en_lot(groupes)
        regle.demarrer_organisation()

        return ResultatOperationOrganisation(
            demandes=total,
            traites=total,
            crees=len(sections) + len(groupes),
            restants=0,
            ids_crees=[
                *[section.id for section in sections],
                *[groupe.id for groupe in groupes],
            ],
            details={
                "sections_creees": len(sections),
                "groupes_crees": len(groupes),
                "effectifs_sections": effectifs_sections,
                "sections": details_sections,
            },
        )

    @staticmethod
    def _capacites_groupes(
        *,
        session_id: int,
        centre_id: int,
        groupes: list[dict],
    ) -> dict[int, dict]:
        capacites = {
            int(groupe["id"]): {
                "capacite_max": int(groupe["capacite_max"]),
                "occupation_ouverte": 0,
                "disponible": int(groupe["capacite_max"]),
                "section_id": int(groupe["section_id"]),
            }
            for groupe in groupes
        }

        for ligne in AffectationGroupeRepository.compter_par_groupe_et_statuts(
            session_id=session_id,
            centre_id=centre_id,
            statuts=STATUTS_GROUPES_OUVERTS,
        ):
            groupe_id = int(ligne["groupe_id"])
            if groupe_id in capacites:
                capacites[groupe_id]["occupation_ouverte"] = int(
                    ligne["total"] or 0
                )

        for donnees in capacites.values():
            donnees["disponible"] = max(
                0,
                donnees["capacite_max"]
                - donnees["occupation_ouverte"],
            )

        return capacites

    @staticmethod
    def _choisir_groupe(
        groupes: list[dict],
        capacites: dict[int, dict],
        *,
        exclure_groupe_id: int | None = None,
    ) -> dict | None:
        disponibles = []
        for groupe in groupes:
            groupe_id = int(groupe["id"])
            if exclure_groupe_id and groupe_id == exclure_groupe_id:
                continue

            donnees = capacites.get(groupe_id, {})
            disponible = int(donnees.get("disponible", 0))
            capacite_max = int(donnees.get("capacite_max", 0))
            if disponible <= 0 or capacite_max <= 0:
                continue

            occupation = capacite_max - disponible
            taux_occupation = occupation / capacite_max
            disponibles.append(
                (
                    taux_occupation,
                    occupation,
                    groupe_id,
                    groupe,
                )
            )

        if not disponibles:
            return None

        disponibles.sort(
            key=lambda element: (
                element[0],
                element[1],
                element[2],
            )
        )
        return disponibles[0][3]

    @classmethod
    @transaction.atomic
    def proposer_affectations_groupes(
        cls,
        *,
        session_id: int,
        centre_id: int,
        nombre: int,
        acteur=None,
    ) -> ResultatOperationOrganisation:
        nombre = cls.valider_taille_lot(nombre)
        RegleOrganisationCentreRepository.get_par_session_centre_pour_update(
            session_id,
            centre_id,
        )

        groupes = list(
            GroupeRepository.lister_donnees_algorithme(
                session_id,
                centre_id,
            )
        )
        if not groupes:
            raise ValidationOrganisationErreur(
                "Aucun groupe actif n'est disponible pour ce centre."
            )

        list(
            GroupeRepository.verrouiller_par_ids(
                [groupe["id"] for groupe in groupes]
            )
        )

        total_avant = (
            CandidatsOrganisationRepository.compter_candidats_groupes(
                session_id=session_id,
                centre_id=centre_id,
            )
        )
        candidats = list(
            CandidatsOrganisationRepository.verrouiller_lot_candidats_groupes(
                session_id=session_id,
                centre_id=centre_id,
                limite=nombre,
            )
        )
        capacites = cls._capacites_groupes(
            session_id=session_id,
            centre_id=centre_id,
            groupes=groupes,
        )

        propositions = []
        sans_destination = []

        for affectation_centre in candidats:
            groupe = cls._choisir_groupe(groupes, capacites)
            if groupe is None:
                sans_destination.append(affectation_centre.id)
                continue

            groupe_id = int(groupe["id"])
            propositions.append(
                AffectationGroupe(
                    affectation_centre_id=affectation_centre.id,
                    groupe_id=groupe_id,
                    statut=AffectationGroupe.Statut.PROPOSEE,
                    affecte_par=acteur,
                    observations=(
                        "Proposition automatique équilibrée selon les "
                        "capacités du centre."
                    ),
                )
            )
            capacites[groupe_id]["disponible"] -= 1

        creees = AffectationGroupeRepository.creer_en_lot(propositions)

        return ResultatOperationOrganisation(
            demandes=nombre,
            traites=len(candidats),
            crees=len(creees),
            restants=max(0, total_avant - len(creees)),
            sans_destination=sans_destination,
            ids_crees=[objet.id for objet in creees],
            details={
                "occupation_groupes": capacites,
            },
        )

    @staticmethod
    @transaction.atomic
    def affecter_manuellement(
        *,
        affectation_centre_id: int,
        groupe_id: int,
        acteur=None,
        observations: str = "",
    ):
        affectations_centres = list(
            CandidatsOrganisationRepository.verrouiller_affectations_centres_par_ids(
                [affectation_centre_id]
            )
        )
        if not affectations_centres:
            raise ValidationOrganisationErreur(
                "L'affectation centre active est introuvable."
            )
        affectation_centre = affectations_centres[0]

        if AffectationGroupeRepository.get_ouverte_par_affectation_centre_pour_update(
            affectation_centre_id
        ):
            raise ValidationOrganisationErreur(
                "Cet immergé possède déjà une affectation groupe ouverte."
            )

        groupe = GroupeRepository.get_by_id_pour_update(groupe_id)
        if (
            groupe.section.session_id != affectation_centre.session_id
            or groupe.section.centre_id != affectation_centre.centre_id
        ):
            raise ValidationOrganisationErreur(
                "Le groupe n'appartient pas à la session et au centre de "
                "l'immergé."
            )

        occupation = AffectationGroupeRepository.filtrer(
            groupe_id=groupe.id,
        ).filter(
            statut__in=STATUTS_GROUPES_OUVERTS,
        ).count()
        if occupation >= groupe.capacite_max:
            raise ValidationOrganisationErreur(
                "La capacité du groupe est atteinte."
            )

        return AffectationGroupeRepository.creer(
            affectation_centre=affectation_centre,
            groupe=groupe,
            statut=AffectationGroupe.Statut.ACTIVE,
            affecte_par=acteur,
            observations=(
                observations or "Affectation manuelle au groupe."
            ),
        )

    @staticmethod
    @transaction.atomic
    def valider_affectations_groupes(
        affectation_ids,
        *,
        acteur=None,
        observations: str = "",
    ) -> list[AffectationGroupe]:
        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(
            AffectationGroupeRepository.verrouiller_par_ids(ids)
        )
        if len(affectations) != len(ids):
            raise ValidationOrganisationErreur(
                "Une ou plusieurs propositions de groupe sont introuvables."
            )

        maintenant = timezone.now()
        for affectation in affectations:
            if affectation.statut not in {
                AffectationGroupe.Statut.PROPOSEE,
                AffectationGroupe.Statut.A_REORGANISER,
            }:
                raise ValidationOrganisationErreur(
                    f"L'affectation {affectation.id} n'est pas validable."
                )
            affectation.statut = AffectationGroupe.Statut.ACTIVE
            affectation.affecte_par = acteur or affectation.affecte_par
            affectation.date_affectation = maintenant
            affectation.observations = (
                observations or affectation.observations
            )
            affectation.updated_at = maintenant

        AffectationGroupeRepository.mettre_a_jour_en_lot(
            affectations,
            [
                "statut",
                "affecte_par",
                "date_affectation",
                "observations",
                "updated_at",
            ],
        )
        return affectations

    @staticmethod
    @transaction.atomic
    def rejeter_affectations_groupes(
        affectation_ids,
        *,
        observations: str,
    ) -> list[AffectationGroupe]:
        if not str(observations or "").strip():
            raise ValidationOrganisationErreur(
                "Le motif du rejet est obligatoire."
            )

        ids = list(dict.fromkeys(int(valeur) for valeur in affectation_ids))
        affectations = list(
            AffectationGroupeRepository.verrouiller_par_ids(ids)
        )
        if len(affectations) != len(ids):
            raise ValidationOrganisationErreur(
                "Une ou plusieurs propositions de groupe sont introuvables."
            )

        maintenant = timezone.now()
        for affectation in affectations:
            if affectation.statut != AffectationGroupe.Statut.PROPOSEE:
                raise ValidationOrganisationErreur(
                    f"L'affectation {affectation.id} n'est pas une proposition."
                )
            affectation.statut = AffectationGroupe.Statut.REJETEE
            affectation.observations = observations
            affectation.updated_at = maintenant

        AffectationGroupeRepository.mettre_a_jour_en_lot(
            affectations,
            ["statut", "observations", "updated_at"],
        )
        return affectations


class HebergementService:
    """Attribution équilibrée des lits, avec le sexe comme seule contrainte."""

    LIMITE_MAX_LOT = 5000

    @classmethod
    def valider_taille_lot(cls, nombre: int) -> int:
        return OrganisationCentreService.valider_taille_lot(nombre)

    @staticmethod
    def _sexe_dortoir(sexe: str) -> str | None:
        valeur = str(sexe or "").strip().upper()
        if valeur in {"M", "MASCULIN", "HOMME"}:
            return Dortoir.SexeDortoir.MASCULIN
        if valeur in {"F", "FEMININ", "FEMME"}:
            return Dortoir.SexeDortoir.FEMININ
        return None

    @staticmethod
    @transaction.atomic
    def generer_lits_dortoir(*, dortoir_id: int) -> ResultatOperationOrganisation:
        dortoir = DortoirRepository.get_by_id_pour_update(dortoir_id)
        if not dortoir.est_actif:
            raise ValidationOrganisationErreur(
                "Le dortoir doit être actif pour créer ses lits."
            )

        lits_existants = list(
            Lit.objects.select_for_update(of=("self",)).filter(
                dortoir_id=dortoir.id,
                deleted_at__isnull=True,
            ).order_by("id")
        )
        total_existants = len(lits_existants)
        manquants = max(0, int(dortoir.capacite) - total_existants)
        if manquants == 0:
            return ResultatOperationOrganisation(
                demandes=int(dortoir.capacite),
                traites=total_existants,
                crees=0,
                restants=0,
                details={"message": "Tous les lits du dortoir existent déjà."},
            )

        numeros_existants = {str(lit.numero_lit) for lit in lits_existants}
        lits = []
        numero = 1
        while len(lits) < manquants:
            numero_lit = str(numero).zfill(2)
            numero += 1
            if numero_lit in numeros_existants:
                continue
            lit = Lit(
                dortoir=dortoir,
                numero_lit=numero_lit,
                statut=Lit.Statut.DISPONIBLE,
            )
            lit.full_clean()
            lits.append(lit)
            numeros_existants.add(numero_lit)

        lits_crees = LitRepository.creer_en_lot(lits)
        return ResultatOperationOrganisation(
            demandes=int(dortoir.capacite),
            traites=total_existants + len(lits_crees),
            crees=len(lits_crees),
            restants=max(0, int(dortoir.capacite) - total_existants - len(lits_crees)),
            ids_crees=[lit.id for lit in lits_crees],
            details={"dortoir_id": dortoir.id},
        )

    @staticmethod
    def _choisir_lit(
        lits: list[dict],
        *,
        sexe_dortoir: str,
        occupations_dortoirs: dict[int, int],
    ) -> dict | None:
        compatibles = []
        for lit in lits:
            if lit["dortoir__sexe_dortoir"] != sexe_dortoir:
                continue

            dortoir_id = int(lit["dortoir_id"])
            occupation = int(occupations_dortoirs.get(dortoir_id, 0))
            capacite = int(lit["dortoir__capacite"] or 0)
            taux = occupation / capacite if capacite > 0 else 1
            compatibles.append(
                (taux, occupation, dortoir_id, int(lit["id"]), lit)
            )

        if not compatibles:
            return None

        compatibles.sort(
            key=lambda element: (
                element[0],
                element[1],
                element[2],
                element[3],
            )
        )
        return compatibles[0][4]

    @classmethod
    @transaction.atomic
    def proposer_attributions_lits(
        cls,
        *,
        session_id: int,
        centre_id: int,
        nombre: int,
        acteur=None,
    ) -> ResultatOperationOrganisation:
        nombre = cls.valider_taille_lot(nombre)
        regle = (
            RegleOrganisationCentreRepository.get_par_session_centre_pour_update(
                session_id,
                centre_id,
            )
        )
        if not regle.hebergement_active:
            raise ValidationOrganisationErreur(
                "L'hébergement n'est pas activé pour cette session."
            )
        if not regle.attribution_lits_automatique:
            raise ValidationOrganisationErreur(
                "L'attribution automatique des lits est désactivée dans "
                "les règles du centre."
            )

        total_avant = (
            CandidatsOrganisationRepository.compter_candidats_lits(
                session_id=session_id,
                centre_id=centre_id,
            )
        )
        candidats = list(
            CandidatsOrganisationRepository.verrouiller_lot_candidats_lits(
                session_id=session_id,
                centre_id=centre_id,
                limite=nombre,
            )
        )
        if not candidats:
            return ResultatOperationOrganisation(
                demandes=nombre,
                traites=0,
                crees=0,
                restants=total_avant,
            )

        lits = list(LitRepository.lister_donnees_algorithme(centre_id))
        if not lits:
            raise ValidationOrganisationErreur(
                "Aucun lit disponible n'existe dans ce centre."
            )
        list(
            LitRepository.verrouiller_par_ids(
                [lit["id"] for lit in lits]
            )
        )

        profils, sans_source_immerges = (
            ProfilAffectationService.construire_profils(
                [candidat.immerge for candidat in candidats]
            )
        )
        sans_source = {
            candidat.id
            for candidat in candidats
            if candidat.immerge_id in set(sans_source_immerges)
        }
        occupations_dortoirs = {
            int(ligne["lit__dortoir_id"]): int(ligne["total"] or 0)
            for ligne in AttributionLitRepository.compter_par_dortoir_et_statuts(
                session_id=session_id,
                centre_id=centre_id,
                statuts=STATUTS_LITS_OUVERTS,
            )
        }

        propositions = []
        sans_destination = list(sans_source)
        lits_disponibles = list(lits)

        for affectation_centre in candidats:
            profil = profils.get(affectation_centre.immerge_id)
            if profil is None:
                continue

            sexe_dortoir = cls._sexe_dortoir(profil.sexe)
            if sexe_dortoir is None:
                sans_destination.append(affectation_centre.id)
                continue

            lit = cls._choisir_lit(
                lits_disponibles,
                sexe_dortoir=sexe_dortoir,
                occupations_dortoirs=occupations_dortoirs,
            )
            if lit is None:
                sans_destination.append(affectation_centre.id)
                continue

            lit_id = int(lit["id"])
            dortoir_id = int(lit["dortoir_id"])
            propositions.append(
                AttributionLit(
                    affectation_centre_id=affectation_centre.id,
                    lit_id=lit_id,
                    statut=AttributionLit.Statut.PROPOSEE,
                    attribue_par=acteur,
                    observations=(
                        "Proposition automatique respectant le sexe du "
                        "dortoir et l'équilibre des occupations."
                    ),
                )
            )
            occupations_dortoirs[dortoir_id] = (
                occupations_dortoirs.get(dortoir_id, 0) + 1
            )
            lits_disponibles = [
                element
                for element in lits_disponibles
                if int(element["id"]) != lit_id
            ]

        creees = AttributionLitRepository.creer_en_lot(propositions)

        return ResultatOperationOrganisation(
            demandes=nombre,
            traites=len(candidats),
            crees=len(creees),
            restants=max(0, total_avant - len(creees)),
            sans_destination=sans_destination,
            ids_crees=[objet.id for objet in creees],
            details={
                "occupation_dortoirs": occupations_dortoirs,
            },
        )

    @staticmethod
    @transaction.atomic
    def attribuer_manuellement(
        *,
        affectation_centre_id: int,
        lit_id: int,
        acteur=None,
        observations: str = "",
    ):
        affectations_centres = list(
            CandidatsOrganisationRepository.verrouiller_affectations_centres_par_ids(
                [affectation_centre_id]
            )
        )
        if not affectations_centres:
            raise ValidationOrganisationErreur(
                "L'affectation centre active est introuvable."
            )
        affectation_centre = affectations_centres[0]

        if AttributionLitRepository.get_ouverte_par_affectation_centre_pour_update(
            affectation_centre_id
        ):
            raise ValidationOrganisationErreur(
                "Cet immergé possède déjà une attribution de lit ouverte."
            )

        lit = LitRepository.get_by_id_pour_update(lit_id)
        if not lit.est_utilisable:
            raise ValidationOrganisationErreur(
                "Le lit sélectionné n'est pas utilisable."
            )
        if lit.dortoir.centre_id != affectation_centre.centre_id:
            raise ValidationOrganisationErreur(
                "Le lit n'appartient pas au centre de l'immergé."
            )
        if AttributionLitRepository.get_ouverte_par_lit_pour_update(lit_id):
            raise ValidationOrganisationErreur(
                "Ce lit possède déjà une attribution ouverte."
            )

        profils, sans_source = ProfilAffectationService.construire_profils(
            [affectation_centre.immerge]
        )
        if sans_source:
            raise ValidationOrganisationErreur(
                "La source de l'immergé est introuvable."
            )
        sexe_dortoir = HebergementService._sexe_dortoir(
            profils[affectation_centre.immerge_id].sexe
        )
        if sexe_dortoir != lit.dortoir.sexe_dortoir:
            raise ValidationOrganisationErreur(
                "Le sexe de l'immergé ne correspond pas au dortoir."
            )

        return AttributionLitRepository.creer(
            affectation_centre=affectation_centre,
            lit=lit,
            statut=AttributionLit.Statut.ACTIVE,
            attribue_par=acteur,
            observations=(
                observations or "Attribution manuelle du lit."
            ),
        )

    @staticmethod
    @transaction.atomic
    def valider_attributions_lits(
        attribution_ids,
        *,
        acteur=None,
        observations: str = "",
    ) -> list[AttributionLit]:
        ids = list(dict.fromkeys(int(valeur) for valeur in attribution_ids))
        attributions = list(
            AttributionLitRepository.verrouiller_par_ids(ids)
        )
        if len(attributions) != len(ids):
            raise ValidationOrganisationErreur(
                "Une ou plusieurs propositions de lit sont introuvables."
            )

        maintenant = timezone.now()
        for attribution in attributions:
            if attribution.statut not in {
                AttributionLit.Statut.PROPOSEE,
                AttributionLit.Statut.A_REORGANISER,
            }:
                raise ValidationOrganisationErreur(
                    f"L'attribution {attribution.id} n'est pas validable."
                )
            attribution.statut = AttributionLit.Statut.ACTIVE
            attribution.attribue_par = acteur or attribution.attribue_par
            attribution.date_attribution = maintenant
            attribution.date_liberation = None
            attribution.observations = (
                observations or attribution.observations
            )
            attribution.updated_at = maintenant

        AttributionLitRepository.mettre_a_jour_en_lot(
            attributions,
            [
                "statut",
                "attribue_par",
                "date_attribution",
                "date_liberation",
                "observations",
                "updated_at",
            ],
        )
        return attributions

    @staticmethod
    @transaction.atomic
    def rejeter_attributions_lits(
        attribution_ids,
        *,
        observations: str,
    ) -> list[AttributionLit]:
        if not str(observations or "").strip():
            raise ValidationOrganisationErreur(
                "Le motif du rejet est obligatoire."
            )

        ids = list(dict.fromkeys(int(valeur) for valeur in attribution_ids))
        attributions = list(
            AttributionLitRepository.verrouiller_par_ids(ids)
        )
        if len(attributions) != len(ids):
            raise ValidationOrganisationErreur(
                "Une ou plusieurs propositions de lit sont introuvables."
            )

        maintenant = timezone.now()
        for attribution in attributions:
            if attribution.statut != AttributionLit.Statut.PROPOSEE:
                raise ValidationOrganisationErreur(
                    f"L'attribution {attribution.id} n'est pas une proposition."
                )
            attribution.statut = AttributionLit.Statut.REJETEE
            attribution.observations = observations
            attribution.updated_at = maintenant

        AttributionLitRepository.mettre_a_jour_en_lot(
            attributions,
            ["statut", "observations", "updated_at"],
        )
        return attributions

    @staticmethod
    @transaction.atomic
    def liberer_lits_fin_immersion(
        *,
        session_id: int,
        centre_id: int,
        observations: str = "",
    ) -> dict:
        """Libère les lits du centre à la fin de l'immersion.

        Les dortoirs et les lits restent permanents. Seules les attributions
        ouvertes de la session et du centre concernés sont traitées.
        """
        attributions_ouvertes = list(
            AttributionLit.objects.select_for_update().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
                affectation_centre__statut=AffectationCentre.Statut.ACTIVE,
                affectation_centre__deleted_at__isnull=True,
                statut__in=[
                    AttributionLit.Statut.PROPOSEE,
                    AttributionLit.Statut.ACTIVE,
                    AttributionLit.Statut.A_REORGANISER,
                ],
                deleted_at__isnull=True,
            ).order_by("id")
        )

        propositions = sum(
            1
            for attribution in attributions_ouvertes
            if attribution.statut == AttributionLit.Statut.PROPOSEE
        )
        a_reorganiser = sum(
            1
            for attribution in attributions_ouvertes
            if attribution.statut == AttributionLit.Statut.A_REORGANISER
        )
        if propositions or a_reorganiser:
            raise ValidationOrganisationErreur({
                "hebergement": (
                    "La fin de l'immersion ne peut pas être confirmée tant que "
                    "des propositions de lit ou des attributions à réorganiser "
                    "restent ouvertes."
                ),
                "propositions_lits": propositions,
                "lits_a_reorganiser": a_reorganiser,
            })

        motif = (
            observations
            or "Libération automatique à la fin de l'immersion du centre."
        )
        actives = [
            attribution
            for attribution in attributions_ouvertes
            if attribution.statut == AttributionLit.Statut.ACTIVE
        ]
        for attribution in actives:
            attribution.liberer(motif)

        return {"lits_liberes": len(actives)}


class VisiteMedicaleOrganisationService:
    """Applique les résultats médicaux à l'organisation déjà préparée."""

    RESULTAT_APTE = "APTE"
    RESULTAT_APTE_SOUS_RESERVE = "APTE_SOUS_RESERVE"

    @staticmethod
    @transaction.atomic
    def appliquer_resultat(
        *,
        affectation_centre_id: int,
        resultat: str,
        observations: str = "",
        reorganiser_groupe: bool = True,
        reorganiser_lit: bool = True,
    ) -> dict:
        affectations_centres = list(
            CandidatsOrganisationRepository.verrouiller_affectations_centres_par_ids(
                [affectation_centre_id]
            )
        )
        if not affectations_centres:
            raise ValidationOrganisationErreur(
                "L'affectation centre active est introuvable."
            )

        resultat = str(resultat or "").strip().upper()
        affectation_groupe = (
            AffectationGroupeRepository.get_ouverte_par_affectation_centre_pour_update(
                affectation_centre_id
            )
        )
        attribution_lit = (
            AttributionLitRepository.get_ouverte_par_affectation_centre_pour_update(
                affectation_centre_id
            )
        )

        if resultat == VisiteMedicaleOrganisationService.RESULTAT_APTE:
            return {
                "affectation_centre_id": affectation_centre_id,
                "resultat": resultat,
                "action": "ORGANISATION_CONSERVEE",
                "affectation_groupe_id": (
                    affectation_groupe.id if affectation_groupe else None
                ),
                "attribution_lit_id": (
                    attribution_lit.id if attribution_lit else None
                ),
            }

        if (
            resultat
            == VisiteMedicaleOrganisationService.RESULTAT_APTE_SOUS_RESERVE
        ):
            if (
                reorganiser_groupe
                and affectation_groupe
                and affectation_groupe.est_active
            ):
                affectation_groupe.marquer_a_reorganiser(observations)

            if (
                reorganiser_lit
                and attribution_lit
                and attribution_lit.est_active
            ):
                attribution_lit.marquer_a_reorganiser(observations)

            return {
                "affectation_centre_id": affectation_centre_id,
                "resultat": resultat,
                "action": "A_REORGANISER",
                "affectation_groupe_id": (
                    affectation_groupe.id if affectation_groupe else None
                ),
                "attribution_lit_id": (
                    attribution_lit.id if attribution_lit else None
                ),
            }

        if affectation_groupe and affectation_groupe.est_ouverte:
            affectation_groupe.annuler(
                observations
                or f"Retrait après résultat médical {resultat}."
            )

        if attribution_lit and attribution_lit.est_ouverte:
            attribution_lit.liberer(
                observations
                or f"Libération après résultat médical {resultat}."
            )

        return {
            "affectation_centre_id": affectation_centre_id,
            "resultat": resultat,
            "action": "RETIRE_DE_L_ORGANISATION",
            "affectation_groupe_id": (
                affectation_groupe.id if affectation_groupe else None
            ),
            "attribution_lit_id": (
                attribution_lit.id if attribution_lit else None
            ),
        }

    @staticmethod
    @transaction.atomic
    def reorganiser_aptitudes_sous_reserve(
        *,
        session_id: int,
        centre_id: int,
        affectation_centre_ids=None,
        acteur=None,
    ) -> ResultatOperationOrganisation:
        groupes_a_reorganiser = list(
            AffectationGroupeRepository.lister_a_reorganiser().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
        )
        lits_a_reorganiser = list(
            AttributionLitRepository.lister_a_reorganiser().filter(
                affectation_centre__session_id=session_id,
                affectation_centre__centre_id=centre_id,
            )
        )

        filtre_ids = (
            set(int(valeur) for valeur in affectation_centre_ids)
            if affectation_centre_ids
            else None
        )
        if filtre_ids is not None:
            groupes_a_reorganiser = [
                objet
                for objet in groupes_a_reorganiser
                if objet.affectation_centre_id in filtre_ids
            ]
            lits_a_reorganiser = [
                objet
                for objet in lits_a_reorganiser
                if objet.affectation_centre_id in filtre_ids
            ]

        groupes = list(
            GroupeRepository.lister_donnees_algorithme(
                session_id,
                centre_id,
            )
        )
        capacites_groupes = OrganisationCentreService._capacites_groupes(
            session_id=session_id,
            centre_id=centre_id,
            groupes=groupes,
        )

        propositions_groupes = []
        sans_destination = []
        maintenant = timezone.now()

        for ancienne in groupes_a_reorganiser:
            nouveau_groupe = OrganisationCentreService._choisir_groupe(
                groupes,
                capacites_groupes,
                exclure_groupe_id=ancienne.groupe_id,
            )
            if nouveau_groupe is None:
                sans_destination.append(ancienne.affectation_centre_id)
                continue

            ancienne.statut = AffectationGroupe.Statut.TRANSFEREE
            ancienne.deleted_at = maintenant
            ancienne.updated_at = maintenant

            nouveau_groupe_id = int(nouveau_groupe["id"])
            propositions_groupes.append(
                AffectationGroupe(
                    affectation_centre_id=ancienne.affectation_centre_id,
                    groupe_id=nouveau_groupe_id,
                    statut=AffectationGroupe.Statut.PROPOSEE,
                    affecte_par=acteur,
                    observations=(
                        "Nouvelle proposition après aptitude sous réserve."
                    ),
                )
            )
            capacites_groupes[nouveau_groupe_id]["disponible"] -= 1

        AffectationGroupeRepository.mettre_a_jour_en_lot(
            [
                objet
                for objet in groupes_a_reorganiser
                if objet.statut == AffectationGroupe.Statut.TRANSFEREE
            ],
            ["statut", "deleted_at", "updated_at"],
        )
        nouvelles_affectations = (
            AffectationGroupeRepository.creer_en_lot(
                propositions_groupes
            )
        )

        lits_disponibles = list(
            LitRepository.lister_donnees_algorithme(centre_id)
        )
        occupations_dortoirs = {
            int(ligne["lit__dortoir_id"]): int(ligne["total"] or 0)
            for ligne in AttributionLitRepository.compter_par_dortoir_et_statuts(
                session_id=session_id,
                centre_id=centre_id,
                statuts=STATUTS_LITS_OUVERTS,
            )
        }

        profils, _ = ProfilAffectationService.construire_profils(
            [objet.affectation_centre.immerge for objet in lits_a_reorganiser]
        )
        propositions_lits = []

        for ancienne in lits_a_reorganiser:
            profil = profils.get(ancienne.affectation_centre.immerge_id)
            if profil is None:
                sans_destination.append(ancienne.affectation_centre_id)
                continue

            sexe_dortoir = HebergementService._sexe_dortoir(profil.sexe)
            candidats_lits = [
                lit
                for lit in lits_disponibles
                if int(lit["id"]) != ancienne.lit_id
            ]
            nouveau_lit = HebergementService._choisir_lit(
                candidats_lits,
                sexe_dortoir=sexe_dortoir,
                occupations_dortoirs=occupations_dortoirs,
            )
            if nouveau_lit is None:
                sans_destination.append(ancienne.affectation_centre_id)
                continue

            ancienne.statut = AttributionLit.Statut.TRANSFEREE
            ancienne.date_liberation = maintenant
            ancienne.deleted_at = maintenant
            ancienne.updated_at = maintenant

            nouveau_lit_id = int(nouveau_lit["id"])
            dortoir_id = int(nouveau_lit["dortoir_id"])
            propositions_lits.append(
                AttributionLit(
                    affectation_centre_id=ancienne.affectation_centre_id,
                    lit_id=nouveau_lit_id,
                    statut=AttributionLit.Statut.PROPOSEE,
                    attribue_par=acteur,
                    observations=(
                        "Nouvelle proposition de lit après aptitude "
                        "sous réserve."
                    ),
                )
            )
            occupations_dortoirs[dortoir_id] = (
                occupations_dortoirs.get(dortoir_id, 0) + 1
            )
            lits_disponibles = [
                lit
                for lit in lits_disponibles
                if int(lit["id"]) != nouveau_lit_id
            ]

        AttributionLitRepository.mettre_a_jour_en_lot(
            [
                objet
                for objet in lits_a_reorganiser
                if objet.statut == AttributionLit.Statut.TRANSFEREE
            ],
            [
                "statut",
                "date_liberation",
                "deleted_at",
                "updated_at",
            ],
        )
        nouvelles_attributions = AttributionLitRepository.creer_en_lot(
            propositions_lits
        )

        total = len(groupes_a_reorganiser) + len(lits_a_reorganiser)
        crees = len(nouvelles_affectations) + len(nouvelles_attributions)
        return ResultatOperationOrganisation(
            demandes=total,
            traites=total,
            crees=crees,
            restants=max(0, total - crees),
            sans_destination=list(dict.fromkeys(sans_destination)),
            ids_crees=[
                *[objet.id for objet in nouvelles_affectations],
                *[objet.id for objet in nouvelles_attributions],
            ],
            details={
                "propositions_groupes": len(nouvelles_affectations),
                "propositions_lits": len(nouvelles_attributions),
            },
        )


__all__ = [
    "ValidationOrganisationErreur",
    "ResultatOperationOrganisation",
    "RegleOrganisationCentreService",
    "OrganisationCentreService",
    "HebergementService",
    "VisiteMedicaleOrganisationService",
]
