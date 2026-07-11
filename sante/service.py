from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from organisation.service import (
    ValidationOrganisationErreur,
    VisiteMedicaleOrganisationService,
)

from .models import RestrictionMedicale, VisiteMedicale
from .repository import (
    CandidatVisiteMedicaleRepository,
    RestrictionMedicaleRepository,
    VisiteMedicaleRepository,
)


class ValidationSanteErreur(ValidationError):
    """Erreur métier du module santé directement exploitable par l'API."""


@dataclass
class ResultatApplicationMedicale:
    visite_medicale_id: int
    affectation_centre_id: int
    resultat: str
    statut_application: str
    organisation: dict = field(default_factory=dict)
    modules_concernes: list[str] = field(default_factory=list)
    decisions_modules: dict = field(default_factory=dict)

    def en_dict(self):
        return asdict(self)


@dataclass
class ResultatEnregistrementVisite:
    visite_medicale_id: int
    affectation_centre_id: int
    numero_visite: int
    resultat: str
    statut: str
    application: dict
    prochaine_affectation_centre_id: int | None = None

    def en_dict(self):
        return asdict(self)


class RestrictionMedicaleService:
    """Création et gestion des restrictions d'une visite."""

    MODULES_VALIDES = {
        valeur
        for valeur, _ in RestrictionMedicale.ModuleConcerne.choices
    }

    @classmethod
    def normaliser_modules(cls, modules):
        if not isinstance(modules, (list, tuple, set)):
            raise ValidationSanteErreur(
                {
                    "modules_concernes": (
                        "Les modules concernés doivent être une liste."
                    )
                }
            )

        modules_normalises = list(
            dict.fromkeys(
                str(module).strip().upper()
                for module in modules
                if str(module).strip()
            )
        )

        if not modules_normalises:
            raise ValidationSanteErreur(
                {
                    "modules_concernes": (
                        "Au moins un module concerné est obligatoire."
                    )
                }
            )

        inconnus = sorted(
            set(modules_normalises) - cls.MODULES_VALIDES
        )
        if inconnus:
            raise ValidationSanteErreur(
                {
                    "modules_concernes": (
                        "Modules inconnus : "
                        + ", ".join(inconnus)
                    )
                }
            )

        return modules_normalises

    @classmethod
    def preparer_donnees(cls, donnees, *, acteur=None):
        donnees = dict(donnees)
        donnees["modules_concernes"] = cls.normaliser_modules(
            donnees.get("modules_concernes", [])
        )
        consigne = str(
            donnees.get("consigne_operationnelle") or ""
        ).strip()
        if not consigne:
            raise ValidationSanteErreur(
                {
                    "consigne_operationnelle": (
                        "Une consigne opérationnelle non médicale "
                        "est obligatoire."
                    )
                }
            )
        donnees["consigne_operationnelle"] = consigne
        donnees["saisie_par"] = acteur or donnees.get("saisie_par")
        return donnees

    @classmethod
    @transaction.atomic
    def creer(cls, *, visite_medicale, acteur=None, **donnees):
        if visite_medicale.deleted_at is not None:
            raise ValidationSanteErreur(
                "Une restriction ne peut pas être créée sur une visite supprimée."
            )

        donnees = cls.preparer_donnees(
            donnees,
            acteur=acteur,
        )

        try:
            return RestrictionMedicaleRepository.creer(
                visite_medicale=visite_medicale,
                **donnees,
            )
        except (ValidationError, IntegrityError) as exc:
            raise ValidationSanteErreur(
                getattr(exc, "message_dict", str(exc))
            ) from exc

    @classmethod
    @transaction.atomic
    def modifier(cls, restriction_id, *, acteur=None, **donnees):
        restriction = (
            RestrictionMedicaleRepository.get_by_id_pour_update(
                restriction_id
            )
        )

        if restriction.visite_medicale.statut == (
            VisiteMedicale.Statut.VALIDEE
        ):
            raise ValidationSanteErreur(
                "Une restriction d'une visite validée ne peut pas être "
                "modifiée directement. Une contre-visite est nécessaire."
            )

        donnees = cls.preparer_donnees(
            {
                **{
                    "modules_concernes": (
                        restriction.modules_concernes
                    )
                },
                **donnees,
            },
            acteur=acteur or restriction.saisie_par,
        )

        for champ, valeur in donnees.items():
            setattr(restriction, champ, valeur)

        champs = list(donnees.keys())
        champs.append("updated_at")

        try:
            return RestrictionMedicaleRepository.sauvegarder(
                restriction,
                update_fields=champs,
            )
        except (ValidationError, IntegrityError) as exc:
            raise ValidationSanteErreur(
                getattr(exc, "message_dict", str(exc))
            ) from exc

    @staticmethod
    @transaction.atomic
    def lever(restriction_id, *, motif="", acteur=None):
        restriction = (
            RestrictionMedicaleRepository.get_by_id_pour_update(
                restriction_id
            )
        )
        return restriction.lever(
            motif=motif,
            levee_par=acteur,
        )

    @staticmethod
    @transaction.atomic
    def expirer_restrictions():
        aujourd_hui = timezone.localdate()
        restrictions = list(
            RestrictionMedicaleRepository.actives()
            .filter(date_fin__lt=aujourd_hui)
            .select_for_update(of=("self",))
        )

        for restriction in restrictions:
            restriction.expirer_si_necessaire()

        return len(restrictions)

    @staticmethod
    def consignes_pour_module(
        *,
        affectation_centre_id,
        module,
        date_reference=None,
    ):
        restrictions = (
            RestrictionMedicaleRepository
            .applicables_pour_affectation_module(
                affectation_centre_id=affectation_centre_id,
                module=module,
                date_reference=date_reference,
            )
        )

        return [
            {
                "restriction_id": restriction.id,
                "libelle": restriction.libelle,
                "type_restriction": restriction.type_restriction,
                "consigne_operationnelle": (
                    restriction.consigne_operationnelle
                ),
                "date_debut": restriction.date_debut.isoformat(),
                "date_fin": (
                    restriction.date_fin.isoformat()
                    if restriction.date_fin
                    else None
                ),
            }
            for restriction in restrictions
        ]

    @staticmethod
    @transaction.atomic
    def remplacer_restrictions(
        *,
        visite_medicale,
        restrictions,
        acteur=None,
    ):
        if visite_medicale.statut == VisiteMedicale.Statut.VALIDEE:
            raise ValidationSanteErreur(
                "Les restrictions d'une visite validée ne peuvent pas être "
                "remplacées."
            )

        anciennes = list(
            RestrictionMedicaleRepository.lister_par_visite(
                visite_medicale.id
            ).select_for_update(of=("self",))
        )

        for restriction in anciennes:
            restriction.supprimer_logiquement()

        nouvelles = []
        for donnees in restrictions or []:
            nouvelles.append(
                RestrictionMedicaleService.creer(
                    visite_medicale=visite_medicale,
                    acteur=acteur,
                    **dict(donnees),
                )
            )

        return nouvelles


class ImpactMedicalService:
    """Point d'entrée utilisé par hébergement, activités, évaluations, etc.

    Les autres modules ne lisent jamais les observations médicales. Ils
    reçoivent uniquement une décision et des consignes opérationnelles.
    """

    MODULES_OPERATIONNELS = [
        valeur
        for valeur, _ in RestrictionMedicale.ModuleConcerne.choices
    ]

    @staticmethod
    def decision_pour_module(
        *,
        affectation_centre_id,
        module,
        date_reference: date | None = None,
    ):
        module = str(module or "").strip().upper()
        if module not in ImpactMedicalService.MODULES_OPERATIONNELS:
            raise ValidationSanteErreur(
                {"module": f"Module médical inconnu : {module}."}
            )

        try:
            affectation = (
                CandidatVisiteMedicaleRepository.get_affectation_active(
                    affectation_centre_id
                )
            )
        except Exception as exc:
            raise ValidationSanteErreur(
                "L'affectation centre active est introuvable."
            ) from exc

        parametres = getattr(affectation.session, "parametres", None)
        if not parametres or not parametres.visite_medicale_active:
            return {
                "affectation_centre_id": affectation_centre_id,
                "module": module,
                "etat": "VISITE_NON_REQUISE",
                "resultat": None,
                "autorise": True,
                "dispense": False,
                "necessite_adaptation": False,
                "consignes": [],
            }

        visite = (
            VisiteMedicaleRepository.get_courante_par_affectation(
                affectation_centre_id
            )
        )

        if not visite or not visite.est_validee:
            return {
                "affectation_centre_id": affectation_centre_id,
                "module": module,
                "etat": "EN_ATTENTE_VISITE",
                "resultat": None,
                "autorise": False,
                "dispense": False,
                "necessite_adaptation": False,
                "consignes": [],
            }

        consignes = RestrictionMedicaleService.consignes_pour_module(
            affectation_centre_id=affectation_centre_id,
            module=module,
            date_reference=date_reference,
        )

        if visite.resultat in (
            VisiteMedicale.Resultat.INAPTE_TEMPORAIRE,
            VisiteMedicale.Resultat.INAPTE_DEFINITIF,
        ):
            return {
                "affectation_centre_id": affectation_centre_id,
                "module": module,
                "etat": "INAPTE",
                "resultat": visite.resultat,
                "autorise": False,
                "dispense": False,
                "necessite_adaptation": False,
                "consignes": consignes,
            }

        types = {
            consigne["type_restriction"]
            for consigne in consignes
        }
        dispense = (
            RestrictionMedicale.TypeRestriction.DISPENSE in types
        )
        interdit = (
            RestrictionMedicale.TypeRestriction.INTERDICTION in types
        )
        necessite_adaptation = bool(
            types
            & {
                RestrictionMedicale.TypeRestriction.ADAPTATION,
                RestrictionMedicale.TypeRestriction.SURVEILLANCE,
                RestrictionMedicale.TypeRestriction.PRIORITE,
            }
        )

        return {
            "affectation_centre_id": affectation_centre_id,
            "module": module,
            "etat": "AUTORISE_AVEC_CONSIGNES" if consignes else "AUTORISE",
            "resultat": visite.resultat,
            "autorise": not interdit and not dispense,
            "dispense": dispense,
            "necessite_adaptation": necessite_adaptation,
            "consignes": consignes,
        }

    @staticmethod
    def verifier_action_autorisee(
        *,
        affectation_centre_id,
        module,
        date_reference=None,
    ):
        decision = ImpactMedicalService.decision_pour_module(
            affectation_centre_id=affectation_centre_id,
            module=module,
            date_reference=date_reference,
        )

        if not decision["autorise"]:
            if decision["dispense"]:
                motif = (
                    f"L'immergé est dispensé pour le module {module}."
                )
            else:
                motif = (
                    f"L'action est interdite par la décision médicale "
                    f"pour le module {module}."
                )
            raise ValidationSanteErreur(motif)

        return decision

    @staticmethod
    def toutes_les_decisions(
        *,
        affectation_centre_id,
        date_reference=None,
    ):
        return {
            module: ImpactMedicalService.decision_pour_module(
                affectation_centre_id=affectation_centre_id,
                module=module,
                date_reference=date_reference,
            )
            for module in ImpactMedicalService.MODULES_OPERATIONNELS
        }


class ApplicationResultatMedicalService:
    """Applique un résultat validé à l'organisation et expose les impacts."""

    @staticmethod
    def _modules_restrictions(visite_id):
        modules = []
        restrictions = (
            RestrictionMedicaleRepository
            .lister_actives_par_visite(visite_id)
        )

        for restriction in restrictions:
            modules.extend(restriction.modules_concernes or [])

        return list(dict.fromkeys(modules))

    @staticmethod
    def appliquer(visite_medicale_id):
        try:
            with transaction.atomic():
                return (
                    ApplicationResultatMedicalService
                    ._appliquer_dans_transaction(
                        visite_medicale_id
                    )
                )
        except Exception as exc:
            with transaction.atomic():
                visite = (
                    VisiteMedicaleRepository.get_by_id_pour_update(
                        visite_medicale_id
                    )
                )
                visite.marquer_echec_application(exc)
            raise

    @staticmethod
    def _appliquer_dans_transaction(visite_medicale_id):
        visite = VisiteMedicaleRepository.get_by_id_pour_update(
            visite_medicale_id
        )

        if not visite.est_validee:
            raise ValidationSanteErreur(
                "Le résultat doit être validé avant son application."
            )

        visite.marquer_application_en_cours()
        modules = (
            ApplicationResultatMedicalService
            ._modules_restrictions(visite.id)
        )

        reorganiser_groupe = (
            RestrictionMedicale.ModuleConcerne.ORGANISATION
            in modules
        )
        reorganiser_lit = (
            RestrictionMedicale.ModuleConcerne.HEBERGEMENT
            in modules
        )

        organisation = {
            "affectation_centre_id": (
                visite.affectation_centre_id
            ),
            "resultat": visite.resultat,
            "action": "ORGANISATION_CONSERVEE",
        }

        if visite.resultat in {
            VisiteMedicale.Resultat.INAPTE_TEMPORAIRE,
            VisiteMedicale.Resultat.INAPTE_DEFINITIF,
        }:
            organisation = (
                VisiteMedicaleOrganisationService.appliquer_resultat(
                    affectation_centre_id=(
                        visite.affectation_centre_id
                    ),
                    resultat=visite.resultat,
                    observations=visite.consignes_operationnelles,
                )
            )

        elif visite.resultat == (
            VisiteMedicale.Resultat.APTE_SOUS_RESERVE
        ):
            if reorganiser_groupe or reorganiser_lit:
                organisation = (
                    VisiteMedicaleOrganisationService
                    .appliquer_resultat(
                        affectation_centre_id=(
                            visite.affectation_centre_id
                        ),
                        resultat="APTE_SOUS_RESERVE",
                        observations=(
                            visite.consignes_operationnelles
                        ),
                        reorganiser_groupe=reorganiser_groupe,
                        reorganiser_lit=reorganiser_lit,
                    )
                )
            else:
                organisation["action"] = (
                    "RESTRICTIONS_SANS_REORGANISATION"
                )

        elif visite.resultat == VisiteMedicale.Resultat.DISPENSE:
            if reorganiser_groupe or reorganiser_lit:
                organisation = (
                    VisiteMedicaleOrganisationService
                    .appliquer_resultat(
                        affectation_centre_id=(
                            visite.affectation_centre_id
                        ),
                        resultat="APTE_SOUS_RESERVE",
                        observations=(
                            visite.consignes_operationnelles
                        ),
                        reorganiser_groupe=reorganiser_groupe,
                        reorganiser_lit=reorganiser_lit,
                    )
                )
                organisation["resultat"] = (
                    VisiteMedicale.Resultat.DISPENSE
                )
            else:
                organisation["action"] = (
                    "DISPENSE_ORGANISATION_CONSERVEE"
                )

        visite.marquer_appliquee()

        decisions = ImpactMedicalService.toutes_les_decisions(
            affectation_centre_id=visite.affectation_centre_id,
        )

        return ResultatApplicationMedicale(
            visite_medicale_id=visite.id,
            affectation_centre_id=visite.affectation_centre_id,
            resultat=visite.resultat,
            statut_application=visite.statut_application,
            organisation=organisation,
            modules_concernes=modules,
            decisions_modules=decisions,
        )


class VisiteMedicaleService:
    """Saisie individuelle et continue des résultats médicaux."""

    CHAMPS_VISITE_MODIFIABLES = {
        "date_visite",
        "resultat",
        "observations_medicales",
        "consignes_operationnelles",
        "document_medical",
        "date_prochaine_visite",
    }

    RESULTATS_AVEC_RESTRICTION_OBLIGATOIRE = {
        VisiteMedicale.Resultat.APTE_SOUS_RESERVE,
        VisiteMedicale.Resultat.DISPENSE,
    }

    @staticmethod
    def _normaliser_resultat(resultat):
        resultat = str(resultat or "").strip().upper()
        valeurs = {
            valeur
            for valeur, _ in VisiteMedicale.Resultat.choices
        }
        if resultat not in valeurs:
            raise ValidationSanteErreur(
                {"resultat": "Le résultat médical est invalide."}
            )
        return resultat

    @staticmethod
    def _donnees_visite(donnees):
        return {
            champ: valeur
            for champ, valeur in dict(donnees).items()
            if champ in VisiteMedicaleService.CHAMPS_VISITE_MODIFIABLES
        }

    @staticmethod
    def _verifier_restrictions(resultat, restrictions):
        if (
            resultat
            in VisiteMedicaleService
            .RESULTATS_AVEC_RESTRICTION_OBLIGATOIRE
            and not restrictions
        ):
            raise ValidationSanteErreur(
                {
                    "restrictions": (
                        "Ce résultat exige au moins une restriction "
                        "opérationnelle."
                    )
                }
            )

    @staticmethod
    @transaction.atomic
    def creer_ou_modifier_brouillon(
        *,
        affectation_centre_id,
        acteur,
        restrictions=None,
        **donnees,
    ):
        affectation = (
            CandidatVisiteMedicaleRepository
            .get_affectation_active_pour_update(
                affectation_centre_id
            )
        )

        visite = (
            VisiteMedicaleRepository
            .get_courante_par_affectation_pour_update(
                affectation_centre_id
            )
        )

        donnees_visite = VisiteMedicaleService._donnees_visite(
            donnees
        )
        if "resultat" in donnees_visite:
            donnees_visite["resultat"] = (
                VisiteMedicaleService._normaliser_resultat(
                    donnees_visite["resultat"]
                )
            )

        if visite:
            if visite.statut == VisiteMedicale.Statut.VALIDEE:
                raise ValidationSanteErreur(
                    "La visite courante est déjà validée. Utilisez une "
                    "contre-visite pour la corriger."
                )

            for champ, valeur in donnees_visite.items():
                setattr(visite, champ, valeur)
            visite.agent_sante = acteur or visite.agent_sante

            champs = list(donnees_visite.keys())
            if "agent_sante" not in champs:
                champs.append("agent_sante")
            champs.extend(["session", "centre", "updated_at"])

            VisiteMedicaleRepository.sauvegarder(
                visite,
                update_fields=list(dict.fromkeys(champs)),
            )
        else:
            numero = (
                VisiteMedicaleRepository.dernier_numero_visite(
                    affectation_centre_id
                )
                + 1
            )
            visite = VisiteMedicaleRepository.creer(
                affectation_centre=affectation,
                numero_visite=numero,
                est_courante=True,
                statut=VisiteMedicale.Statut.BROUILLON,
                agent_sante=acteur,
                **donnees_visite,
            )

        if restrictions is not None:
            RestrictionMedicaleService.remplacer_restrictions(
                visite_medicale=visite,
                restrictions=restrictions,
                acteur=acteur,
            )

        return visite

    @staticmethod
    def enregistrer_et_appliquer(
        *,
        affectation_centre_id,
        acteur,
        restrictions=None,
        **donnees,
    ):
        resultat = VisiteMedicaleService._normaliser_resultat(
            donnees.get("resultat")
        )
        restrictions = list(restrictions or [])
        VisiteMedicaleService._verifier_restrictions(
            resultat,
            restrictions,
        )

        with transaction.atomic():
            visite = (
                VisiteMedicaleService.creer_ou_modifier_brouillon(
                    affectation_centre_id=affectation_centre_id,
                    acteur=acteur,
                    restrictions=restrictions,
                    **{
                        **donnees,
                        "resultat": resultat,
                    },
                )
            )
            visite.valider(agent_sante=acteur)

        application = (
            ApplicationResultatMedicalService.appliquer(
                visite.id
            )
        )
        suivante = (
            CandidatVisiteMedicaleRepository.prochaine_affectation(
                session_id=visite.session_id,
                centre_id=visite.centre_id,
                apres_affectation_id=affectation_centre_id,
            )
        )

        return ResultatEnregistrementVisite(
            visite_medicale_id=visite.id,
            affectation_centre_id=visite.affectation_centre_id,
            numero_visite=visite.numero_visite,
            resultat=visite.resultat,
            statut=visite.statut,
            application=application.en_dict(),
            prochaine_affectation_centre_id=(
                suivante.id if suivante else None
            ),
        )

    @staticmethod
    def corriger_par_contre_visite(
        *,
        affectation_centre_id,
        acteur,
        restrictions=None,
        **donnees,
    ):
        resultat = VisiteMedicaleService._normaliser_resultat(
            donnees.get("resultat")
        )
        restrictions = list(restrictions or [])
        VisiteMedicaleService._verifier_restrictions(
            resultat,
            restrictions,
        )

        with transaction.atomic():
            affectation = (
                CandidatVisiteMedicaleRepository
                .get_affectation_active_pour_update(
                    affectation_centre_id
                )
            )
            ancienne = (
                VisiteMedicaleRepository
                .get_courante_par_affectation_pour_update(
                    affectation_centre_id
                )
            )

            if ancienne:
                ancienne.est_courante = False
                VisiteMedicaleRepository.sauvegarder(
                    ancienne,
                    update_fields=[
                        "est_courante",
                        "session",
                        "centre",
                        "updated_at",
                    ],
                )

            numero = (
                VisiteMedicaleRepository.dernier_numero_visite(
                    affectation_centre_id
                )
                + 1
            )
            visite = VisiteMedicaleRepository.creer(
                affectation_centre=affectation,
                numero_visite=numero,
                est_courante=True,
                statut=VisiteMedicale.Statut.BROUILLON,
                agent_sante=acteur,
                **VisiteMedicaleService._donnees_visite(
                    {
                        **donnees,
                        "resultat": resultat,
                    }
                ),
            )

            RestrictionMedicaleService.remplacer_restrictions(
                visite_medicale=visite,
                restrictions=restrictions,
                acteur=acteur,
            )
            visite.valider(agent_sante=acteur)

        application = (
            ApplicationResultatMedicalService.appliquer(
                visite.id
            )
        )
        suivante = (
            CandidatVisiteMedicaleRepository.prochaine_affectation(
                session_id=visite.session_id,
                centre_id=visite.centre_id,
                apres_affectation_id=affectation_centre_id,
            )
        )

        return ResultatEnregistrementVisite(
            visite_medicale_id=visite.id,
            affectation_centre_id=visite.affectation_centre_id,
            numero_visite=visite.numero_visite,
            resultat=visite.resultat,
            statut=visite.statut,
            application=application.en_dict(),
            prochaine_affectation_centre_id=(
                suivante.id if suivante else None
            ),
        )

    @staticmethod
    def reappliquer_resultat(visite_medicale_id):
        visite = VisiteMedicaleRepository.get_by_id(
            visite_medicale_id
        )
        if not visite.est_validee:
            raise ValidationSanteErreur(
                "Seule une visite validée peut être réappliquée."
            )
        return ApplicationResultatMedicalService.appliquer(
            visite_medicale_id
        )

    @staticmethod
    @transaction.atomic
    def annuler_visite(visite_medicale_id):
        visite = VisiteMedicaleRepository.get_by_id_pour_update(
            visite_medicale_id
        )
        return visite.annuler()

    @staticmethod
    def prochaine_affectation(
        *,
        session_id,
        centre_id,
        apres_affectation_id=None,
    ):
        return (
            CandidatVisiteMedicaleRepository.prochaine_affectation(
                session_id=session_id,
                centre_id=centre_id,
                apres_affectation_id=apres_affectation_id,
            )
        )
