from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.service import ControleAccesService
from affectations.models import AffectationCentre, CentreImmersion
from sessions_app.models import SessionImmersion
from sante.service import ImpactMedicalService

from .models import ArticleKit, RemiseKit
from .repository import (
    ArticleKitRepository,
    CandidatRemiseKitRepository,
    RemiseKitRepository,
)


class ValidationKitErreur(ValidationError):
    """Erreur métier lisible par l'API et les tâches Celery."""


@dataclass
class ResultatLotKits:
    demandes: int = 0
    traites: int = 0
    eligibles: int = 0
    remises_creees: int = 0
    remises_validees: int = 0
    remises_annulees: int = 0
    bloques_medicaux: int = 0
    sans_article: int = 0
    erreurs: int = 0
    affectations_ignorees: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def en_dict(self):
        return asdict(self)


class ControleAccesKitsService:
    """Contrôles d'accès métier propres aux kits."""

    CREER_A_REMETTRE = "creer_article_kit_a_remettre"
    CREER_A_APPORTER = "creer_article_kit_a_apporter"
    MODIFIER_ARTICLE = "modifier_article_kit"
    DESACTIVER_ARTICLE = "desactiver_article_kit"
    REACTIVER_ARTICLE = "reactiver_article_kit"
    SUPPRIMER_ARTICLE = "supprimer_article_kit"
    ENREGISTRER_REMISE = "enregistrer_remise_kit"
    PREPARER_REMISES_MASSE = "preparer_remises_kit_masse"
    VALIDER_REMISES_MASSE = "valider_remises_kit_masse"
    ANNULER_REMISES_MASSE = "annuler_remises_kit_masse"

    @staticmethod
    def exiger(
        acteur,
        code_permission,
        *,
        session_id,
        centre_id=None,
    ):
        if acteur is None:
            raise ValidationKitErreur(
                "Un acteur authentifié est obligatoire."
            )

        if getattr(acteur, "is_superuser", False):
            return None

        resultat = ControleAccesService.acteur_peut(
            acteur,
            code_permission,
            session_id=session_id,
            centre_id=centre_id,
        )
        if not resultat.autorise:
            raise ValidationKitErreur(
                resultat.motif
                or "Permission absente ou hors périmètre."
            )
        return resultat.affectation


class EligibiliteRemiseKitService:
    """Décide si une affectation peut recevoir les kits."""

    @staticmethod
    def decision(affectation_centre_id: int):
        decision = ImpactMedicalService.decision_pour_module(
            affectation_centre_id=affectation_centre_id,
            module="ORGANISATION",
        )

        etat = decision.get("etat")
        autorise = etat not in {
            "EN_ATTENTE_VISITE",
            "INAPTE",
        }
        return {
            **decision,
            "autorise_remise_kit": autorise,
        }

    @classmethod
    def exiger(cls, affectation_centre_id: int):
        decision = cls.decision(affectation_centre_id)

        if not decision["autorise_remise_kit"]:
            if decision["etat"] == "EN_ATTENTE_VISITE":
                motif = (
                    "La remise est bloquée jusqu'à la validation "
                    "de la visite médicale."
                )
            else:
                motif = (
                    "La remise est interdite pour un immergé "
                    "déclaré inapte."
                )
            raise ValidationKitErreur(motif)

        return decision


class ArticleKitService:
    """CRUD métier des articles à apporter et à remettre."""

    CHAMPS_MODIFIABLES = {
        "designation",
        "description",
        "type_kit",
        "quantite",
        "unite",
        "obligatoire",
        "ordre",
        "statut",
        "centre_id",
    }

    @staticmethod
    def _session(session_id):
        try:
            return SessionImmersion.objects.get(
                id=session_id,
                deleted_at__isnull=True,
            )
        except SessionImmersion.DoesNotExist as exc:
            raise ValidationKitErreur(
                "La session est introuvable."
            ) from exc

    @staticmethod
    def _centre(centre_id):
        if not centre_id:
            return None

        try:
            return CentreImmersion.objects.get(
                id=centre_id,
                deleted_at__isnull=True,
            )
        except CentreImmersion.DoesNotExist as exc:
            raise ValidationKitErreur(
                "Le centre est introuvable."
            ) from exc

    @staticmethod
    def _verifier_session_modifiable(session):
        if not session.est_modifiable:
            raise ValidationKitErreur(
                "Les kits d'une session terminée, archivée "
                "ou annulée ne sont plus modifiables."
            )

    @staticmethod
    def _verifier_type_et_portee(
        *,
        type_kit,
        centre,
    ):
        if type_kit not in {
            ArticleKit.TypeKit.A_APPORTER,
            ArticleKit.TypeKit.A_REMETTRE,
        }:
            raise ValidationKitErreur(
                {"type_kit": "Type de kit inconnu."}
            )

        if (
            type_kit == ArticleKit.TypeKit.A_APPORTER
            and centre is None
        ):
            raise ValidationKitErreur(
                {
                    "centre_id": (
                        "Un article à apporter doit appartenir "
                        "à un centre précis."
                    )
                }
            )

    @staticmethod
    def _exiger_permission_creation(
        *,
        acteur,
        session_id,
        centre_id,
        type_kit,
    ):
        if type_kit == ArticleKit.TypeKit.A_REMETTRE:
            return ControleAccesKitsService.exiger(
                acteur,
                ControleAccesKitsService.CREER_A_REMETTRE,
                session_id=session_id,
            )

        return ControleAccesKitsService.exiger(
            acteur,
            ControleAccesKitsService.CREER_A_APPORTER,
            session_id=session_id,
            centre_id=centre_id,
        )

    @staticmethod
    def _exiger_permission_article(
        *,
        acteur,
        article,
        code_permission,
    ):
        centre_id = (
            article.centre_id
            if article.type_kit
            == ArticleKit.TypeKit.A_APPORTER
            else None
        )
        return ControleAccesKitsService.exiger(
            acteur,
            code_permission,
            session_id=article.session_id,
            centre_id=centre_id,
        )

    @classmethod
    @transaction.atomic
    def creer(
        cls,
        *,
        acteur,
        session_id,
        designation,
        type_kit,
        centre_id=None,
        description="",
        quantite=1,
        unite="unité",
        obligatoire=True,
        ordre=0,
        statut=ArticleKit.Statut.ACTIF,
    ):
        session = cls._session(session_id)
        centre = cls._centre(centre_id)
        cls._verifier_session_modifiable(session)
        cls._verifier_type_et_portee(
            type_kit=type_kit,
            centre=centre,
        )
        cls._exiger_permission_creation(
            acteur=acteur,
            session_id=session.id,
            centre_id=centre.id if centre else None,
            type_kit=type_kit,
        )

        if ArticleKitRepository.existe_doublon(
            session_id=session.id,
            centre_id=centre.id if centre else None,
            designation=designation,
            type_kit=type_kit,
        ):
            raise ValidationKitErreur(
                {
                    "designation": (
                        "Un article actif identique existe déjà "
                        "dans ce périmètre."
                    )
                }
            )

        return ArticleKitRepository.creer(
            session=session,
            centre=centre,
            designation=designation,
            description=description,
            type_kit=type_kit,
            quantite=quantite,
            unite=unite,
            obligatoire=obligatoire,
            ordre=ordre,
            statut=statut,
        )

    @classmethod
    @transaction.atomic
    def modifier(cls, article_id: int, *, acteur, **donnees):
        article = ArticleKitRepository.get_by_id_pour_update(
            article_id
        )
        cls._verifier_session_modifiable(article.session)
        cls._exiger_permission_article(
            acteur=acteur,
            article=article,
            code_permission=(
                ControleAccesKitsService.MODIFIER_ARTICLE
            ),
        )

        donnees = {
            champ: valeur
            for champ, valeur in donnees.items()
            if champ in cls.CHAMPS_MODIFIABLES
        }
        if not donnees:
            return article

        nouveau_type = donnees.get(
            "type_kit",
            article.type_kit,
        )
        nouveau_centre_id = donnees.get(
            "centre_id",
            article.centre_id,
        )
        nouveau_centre = cls._centre(nouveau_centre_id)

        if (
            nouveau_type != article.type_kit
            and ArticleKitRepository.possede_remises(article.id)
        ):
            raise ValidationKitErreur(
                "Le type d'un article déjà remis ne peut plus changer."
            )

        cls._verifier_type_et_portee(
            type_kit=nouveau_type,
            centre=nouveau_centre,
        )
        cls._exiger_permission_creation(
            acteur=acteur,
            session_id=article.session_id,
            centre_id=(
                nouveau_centre.id
                if nouveau_centre
                else None
            ),
            type_kit=nouveau_type,
        )

        designation = donnees.get(
            "designation",
            article.designation,
        )
        if ArticleKitRepository.existe_doublon(
            session_id=article.session_id,
            centre_id=(
                nouveau_centre.id
                if nouveau_centre
                else None
            ),
            designation=designation,
            type_kit=nouveau_type,
            exclure_id=article.id,
        ):
            raise ValidationKitErreur(
                {
                    "designation": (
                        "Un article actif identique existe déjà "
                        "dans ce périmètre."
                    )
                }
            )

        for champ, valeur in donnees.items():
            if champ == "centre_id":
                article.centre = nouveau_centre
            else:
                setattr(article, champ, valeur)

        champs = [
            "centre" if champ == "centre_id" else champ
            for champ in donnees
        ]
        champs.append("updated_at")

        return ArticleKitRepository.sauvegarder(
            article,
            update_fields=list(dict.fromkeys(champs)),
        )

    @classmethod
    @transaction.atomic
    def desactiver(cls, article_id: int, *, acteur):
        article = ArticleKitRepository.get_by_id_pour_update(
            article_id
        )
        cls._verifier_session_modifiable(article.session)
        cls._exiger_permission_article(
            acteur=acteur,
            article=article,
            code_permission=(
                ControleAccesKitsService.DESACTIVER_ARTICLE
            ),
        )
        return article.desactiver()

    @classmethod
    @transaction.atomic
    def reactiver(cls, article_id: int, *, acteur):
        article = ArticleKitRepository.get_by_id_pour_update(
            article_id
        )
        cls._verifier_session_modifiable(article.session)
        cls._exiger_permission_article(
            acteur=acteur,
            article=article,
            code_permission=(
                ControleAccesKitsService.REACTIVER_ARTICLE
            ),
        )
        return article.reactiver()

    @classmethod
    @transaction.atomic
    def supprimer_logiquement(cls, article_id: int, *, acteur):
        article = ArticleKitRepository.get_by_id_pour_update(
            article_id
        )
        cls._verifier_session_modifiable(article.session)
        cls._exiger_permission_article(
            acteur=acteur,
            article=article,
            code_permission=(
                ControleAccesKitsService.SUPPRIMER_ARTICLE
            ),
        )
        return article.supprimer_logiquement()

    @staticmethod
    def articles_pour_immerge(
        *,
        session_id,
        centre_id,
    ):
        return {
            "a_apporter": list(
                ArticleKitRepository.a_apporter(
                    session_id=session_id,
                    centre_id=centre_id,
                )
            ),
            "a_remettre": list(
                ArticleKitRepository.a_remettre(
                    session_id=session_id,
                    centre_id=centre_id,
                )
            ),
        }


class RemiseKitService:
    """Remise individuelle et opérations massives de distribution."""

    STATUT_NON_COMMENCEE = "NON_COMMENCEE"
    STATUT_PARTIELLE = "PARTIELLE"
    STATUT_COMPLETE = "COMPLETE"
    STATUT_AUCUN_ARTICLE = "AUCUN_ARTICLE"

    @staticmethod
    def _affectation(affectation_centre_id: int):
        try:
            return CandidatRemiseKitRepository.get_active(
                affectation_centre_id
            )
        except AffectationCentre.DoesNotExist as exc:
            raise ValidationKitErreur(
                "L'affectation centre active est introuvable."
            ) from exc

    @staticmethod
    def _exiger_permission_individuelle(*, acteur, affectation):
        return ControleAccesKitsService.exiger(
            acteur,
            ControleAccesKitsService.ENREGISTRER_REMISE,
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
        )

    @staticmethod
    def _verifier_article_applicable(article, affectation):
        if not article.est_actif:
            raise ValidationKitErreur(
                "L'article de kit n'est pas actif."
            )

        if not article.est_a_remettre:
            raise ValidationKitErreur(
                "Un article à apporter ne peut pas être distribué."
            )

        if article.session_id != affectation.session_id:
            raise ValidationKitErreur(
                "L'article et l'affectation ne concernent "
                "pas la même session."
            )

        if not article.applicable_au_centre(
            affectation.centre_id
        ):
            raise ValidationKitErreur(
                "L'article n'est pas applicable à ce centre."
            )

    @classmethod
    @transaction.atomic
    def preparer_remise_immerge(
        cls,
        *,
        affectation_centre_id,
        acteur,
        article_kit_ids=None,
        verifier_acces=True,
    ):
        affectation = cls._affectation(affectation_centre_id)

        if verifier_acces:
            cls._exiger_permission_individuelle(
                acteur=acteur,
                affectation=affectation,
            )

        EligibiliteRemiseKitService.exiger(affectation.id)

        articles = list(
            ArticleKitRepository.a_remettre(
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                article_ids=article_kit_ids,
            )
        )
        if not articles:
            return {
                "affectation_centre_id": affectation.id,
                "articles_attendus": 0,
                "remises_creees": 0,
                "remises_existantes": 0,
            }

        existantes = RemiseKitRepository.paires_existantes(
            affectation_centre_ids=[affectation.id],
            article_kit_ids=[article.id for article in articles],
        )
        nouvelles = [
            RemiseKit(
                affectation_centre=affectation,
                article_kit=article,
                quantite_prevue=article.quantite,
                quantite_remise=0,
                statut_remise=(
                    RemiseKit.StatutRemise.NON_REMIS
                ),
                remis_par=None,
            )
            for article in articles
            if (affectation.id, article.id) not in existantes
        ]
        RemiseKitRepository.creer_en_masse(nouvelles)

        return {
            "affectation_centre_id": affectation.id,
            "articles_attendus": len(articles),
            "remises_creees": len(nouvelles),
            "remises_existantes": (
                len(articles) - len(nouvelles)
            ),
        }

    @classmethod
    @transaction.atomic
    def enregistrer_remise_article(
        cls,
        *,
        affectation_centre_id,
        article_kit_id,
        quantite_remise,
        acteur,
        observations="",
    ):
        affectation = cls._affectation(affectation_centre_id)
        cls._exiger_permission_individuelle(
            acteur=acteur,
            affectation=affectation,
        )
        EligibiliteRemiseKitService.exiger(affectation.id)

        article = ArticleKitRepository.get_by_id(
            article_kit_id
        )
        cls._verifier_article_applicable(
            article,
            affectation,
        )

        remise = (
            RemiseKitRepository
            .get_active_par_affectation_article(
                affectation_centre_id=affectation.id,
                article_kit_id=article.id,
            )
        )
        if remise is None:
            remise = RemiseKitRepository.creer(
                affectation_centre=affectation,
                article_kit=article,
                quantite_prevue=article.quantite,
                quantite_remise=0,
                statut_remise=(
                    RemiseKit.StatutRemise.NON_REMIS
                ),
            )

        return remise.enregistrer_quantite(
            quantite_remise,
            acteur=acteur,
            observations=observations,
        )

    @classmethod
    @transaction.atomic
    def marquer_remplace(
        cls,
        *,
        remise_id,
        quantite_remise,
        acteur,
        observations="",
    ):
        remise = RemiseKitRepository.get_by_id_pour_update(
            remise_id
        )
        cls._exiger_permission_individuelle(
            acteur=acteur,
            affectation=remise.affectation_centre,
        )
        EligibiliteRemiseKitService.exiger(
            remise.affectation_centre_id
        )
        return remise.marquer_remplace(
            quantite_remise,
            acteur=acteur,
            observations=observations,
        )

    @classmethod
    @transaction.atomic
    def marquer_dispense(
        cls,
        *,
        remise_id,
        acteur,
        observations="",
    ):
        remise = RemiseKitRepository.get_by_id_pour_update(
            remise_id
        )
        cls._exiger_permission_individuelle(
            acteur=acteur,
            affectation=remise.affectation_centre,
        )
        return remise.marquer_dispense(
            acteur=acteur,
            observations=observations,
        )

    @classmethod
    @transaction.atomic
    def valider_remise_complete_immerge(
        cls,
        *,
        affectation_centre_id,
        acteur,
        article_kit_ids=None,
        verifier_acces=True,
    ):
        affectation = cls._affectation(affectation_centre_id)

        if verifier_acces:
            cls._exiger_permission_individuelle(
                acteur=acteur,
                affectation=affectation,
            )

        EligibiliteRemiseKitService.exiger(affectation.id)
        cls.preparer_remise_immerge(
            affectation_centre_id=affectation.id,
            acteur=acteur,
            article_kit_ids=article_kit_ids,
            verifier_acces=False,
        )

        articles = list(
            ArticleKitRepository.a_remettre(
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                article_ids=article_kit_ids,
            )
        )
        remises = list(
            RemiseKitRepository.lister_par_affectations(
                [affectation.id],
                article_kit_ids=[
                    article.id for article in articles
                ],
            )
        )

        maintenant = timezone.now()
        a_mettre_a_jour = []

        for remise in remises:
            if remise.statut_remise in {
                RemiseKit.StatutRemise.REMPLACE,
                RemiseKit.StatutRemise.DISPENSE,
            }:
                continue

            remise.quantite_remise = remise.quantite_prevue
            remise.statut_remise = (
                RemiseKit.StatutRemise.REMIS
            )
            remise.remis_par = acteur
            remise.date_remise = maintenant
            remise.updated_at = maintenant
            remise.observations = (
                remise.observations or ""
            ).strip()
            a_mettre_a_jour.append(remise)

        RemiseKitRepository.mettre_a_jour_en_masse(
            a_mettre_a_jour,
            [
                "quantite_remise",
                "statut_remise",
                "remis_par",
                "date_remise",
                "observations",
                "updated_at",
            ],
        )

        return {
            "affectation_centre_id": affectation.id,
            "articles_attendus": len(articles),
            "remises_validees": len(a_mettre_a_jour),
            "statut_global": cls.calculer_statut_global(
                affectation.id
            ),
        }

    @classmethod
    @transaction.atomic
    def annuler_remise_logiquement(
        cls,
        *,
        remise_id,
        acteur,
    ):
        remise = RemiseKitRepository.get_by_id_pour_update(
            remise_id
        )
        cls._exiger_permission_individuelle(
            acteur=acteur,
            affectation=remise.affectation_centre,
        )
        return remise.supprimer_logiquement()

    @classmethod
    def calculer_statut_global(
        cls,
        affectation_centre_id: int,
    ):
        affectation = cls._affectation(affectation_centre_id)
        articles = list(
            ArticleKitRepository.a_remettre(
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
            )
        )
        articles_ids = {article.id for article in articles}

        if not articles_ids:
            return {
                "statut": cls.STATUT_AUCUN_ARTICLE,
                "articles_attendus": 0,
                "articles_completes": 0,
                "articles_non_commences": 0,
            }

        remises = list(
            RemiseKitRepository.lister_par_affectation(
                affectation.id
            ).filter(article_kit_id__in=articles_ids)
        )
        par_article = {
            remise.article_kit_id: remise
            for remise in remises
        }

        complets = 0
        commences = 0
        for article_id in articles_ids:
            remise = par_article.get(article_id)
            if remise is None:
                continue

            if remise.est_complete:
                complets += 1

            if (
                remise.quantite_remise > 0
                or remise.statut_remise
                in {
                    RemiseKit.StatutRemise.REMIS,
                    RemiseKit.StatutRemise.REMPLACE,
                    RemiseKit.StatutRemise.DISPENSE,
                    RemiseKit.StatutRemise.PARTIEL,
                }
            ):
                commences += 1

        if complets == len(articles_ids):
            statut = cls.STATUT_COMPLETE
        elif commences == 0:
            statut = cls.STATUT_NON_COMMENCEE
        else:
            statut = cls.STATUT_PARTIELLE

        return {
            "statut": statut,
            "articles_attendus": len(articles_ids),
            "articles_completes": complets,
            "articles_non_commences": (
                len(articles_ids) - commences
            ),
        }

    @classmethod
    def preparer_pour_affectations(
        cls,
        *,
        session_id,
        centre_id,
        affectation_centre_ids,
        acteur,
        article_kit_ids=None,
        verifier_acces=True,
    ):
        if verifier_acces:
            ControleAccesKitsService.exiger(
                acteur,
                (
                    ControleAccesKitsService
                    .PREPARER_REMISES_MASSE
                ),
                session_id=session_id,
                centre_id=centre_id,
            )

        resultat = ResultatLotKits(
            demandes=len(affectation_centre_ids),
        )

        for affectation_id in affectation_centre_ids:
            try:
                donnees = cls.preparer_remise_immerge(
                    affectation_centre_id=affectation_id,
                    acteur=acteur,
                    article_kit_ids=article_kit_ids,
                    verifier_acces=False,
                )
                resultat.traites += 1
                resultat.eligibles += 1
                resultat.remises_creees += (
                    donnees["remises_creees"]
                )
                if donnees["articles_attendus"] == 0:
                    resultat.sans_article += 1

            except ValidationKitErreur as exc:
                resultat.traites += 1
                message = str(exc)
                if (
                    "visite médicale" in message
                    or "inapte" in message
                ):
                    resultat.bloques_medicaux += 1
                else:
                    resultat.erreurs += 1
                resultat.affectations_ignorees.append(
                    affectation_id
                )

        return resultat

    @classmethod
    def valider_pour_affectations(
        cls,
        *,
        session_id,
        centre_id,
        affectation_centre_ids,
        acteur,
        article_kit_ids=None,
        verifier_acces=True,
    ):
        if verifier_acces:
            ControleAccesKitsService.exiger(
                acteur,
                (
                    ControleAccesKitsService
                    .VALIDER_REMISES_MASSE
                ),
                session_id=session_id,
                centre_id=centre_id,
            )

        resultat = ResultatLotKits(
            demandes=len(affectation_centre_ids),
        )

        for affectation_id in affectation_centre_ids:
            try:
                donnees = (
                    cls.valider_remise_complete_immerge(
                        affectation_centre_id=affectation_id,
                        acteur=acteur,
                        article_kit_ids=article_kit_ids,
                        verifier_acces=False,
                    )
                )
                resultat.traites += 1
                resultat.eligibles += 1
                resultat.remises_validees += (
                    donnees["remises_validees"]
                )
                if donnees["articles_attendus"] == 0:
                    resultat.sans_article += 1

            except ValidationKitErreur as exc:
                resultat.traites += 1
                message = str(exc)
                if (
                    "visite médicale" in message
                    or "inapte" in message
                ):
                    resultat.bloques_medicaux += 1
                else:
                    resultat.erreurs += 1
                resultat.affectations_ignorees.append(
                    affectation_id
                )

        return resultat

    @classmethod
    def annuler_pour_affectations(
        cls,
        *,
        session_id,
        centre_id,
        affectation_centre_ids,
        acteur,
        article_kit_ids=None,
        verifier_acces=True,
    ):
        if verifier_acces:
            ControleAccesKitsService.exiger(
                acteur,
                (
                    ControleAccesKitsService
                    .ANNULER_REMISES_MASSE
                ),
                session_id=session_id,
                centre_id=centre_id,
            )

        total = RemiseKitRepository.supprimer_logiquement_en_masse(
            affectation_centre_ids=affectation_centre_ids,
            article_kit_ids=article_kit_ids,
        )
        return ResultatLotKits(
            demandes=len(affectation_centre_ids),
            traites=len(affectation_centre_ids),
            remises_annulees=total,
        )
