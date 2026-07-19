from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from accounts.management.commands.seed_accounts import PERMISSIONS_SYSTEME, ROLES_SYSTEME
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
from activites.models import Seance
from affectations.models import AffectationCentre
from sessions_app.models import SessionImmersion

from incidents.models import AlerteIncident

from .base import Anomalie


CODES = (
    "ACC_PERMISSION_SYSTEME_ABSENTE",
    "ACC_PERMISSION_SYSTEME_ALTEREE",
    "ACC_ROLE_SYSTEME_ABSENT",
    "ACC_ROLE_SYSTEME_ALTERE",
    "ACC_ACTEUR_SANS_AFFECTATION",
    "ACC_ACTEUR_INACTIF_AVEC_DROITS",
    "ACC_ROLE_ATTRIBUE_SANS_PERMISSION",
    "ACC_AFFECTATION_EXPIREE_ACTIVE",
    "ACC_ROLE_EXPIRE_ACTIF",
    "ACC_PERMISSION_EXPIREE_ACTIVE",
    "ACC_DELEGATION_EXPIREE_ACTIVE",
    "ACC_DEMANDE_APPROUVEE_NON_APPLIQUEE",
    "ACC_DELEGATION_INCOHERENTE",
    "ACC_POSTE_ADMIN_VACANT",
    "ACC_POSTE_DGAS_VACANT",
    "ACC_POSTE_DR_VACANT",
    "ACC_POSTE_RESPONSABLE_CENTRE_VACANT",
    "ACC_POSTE_AGENT_SANTE_VACANT",
    "ACC_POSTE_FORMATEUR_VACANT",
    "ACC_ACTIONS_MASSIVES_SUSPECTES",
)


def _taille_lot():
    return int(getattr(settings, "INCIDENTS_TAILLE_LOT_SCAN", getattr(settings, "INCIDENTS_MAX_ANOMALIES_PAR_REGLE", 500)))


def _active_relation_filter(prefix=""):
    aujourd_hui = timezone.localdate()
    return {
        f"{prefix}deleted_at__isnull": True,
        f"{prefix}statut": AffectationActeur.Statut.ACTIVE,
        f"{prefix}date_debut__lte": aujourd_hui,
    }, Q(**{f"{prefix}date_fin__isnull": True}) | Q(
        **{f"{prefix}date_fin__gte": aujourd_hui}
    )


def _affectations_actives():
    kwargs, dates = _active_relation_filter()
    return AffectationActeur.objects.filter(**kwargs).filter(dates).filter(
        acteur__is_active=True,
        acteur__statut=Acteur.Statut.ACTIF,
        acteur__deleted_at__isnull=True,
    )


def _role_actif(code, *, session_id=None, region_code=None, centre_id=None):
    aujourd_hui = timezone.localdate()
    qs = AffectationRole.objects.filter(
        role__code=code,
        role__statut=Role.Statut.ACTIF,
        role__deleted_at__isnull=True,
        statut=AffectationRole.Statut.ACTIF,
        deleted_at__isnull=True,
        date_attribution__lte=aujourd_hui,
        affectation_acteur__in=_affectations_actives(),
    ).filter(Q(date_expiration__isnull=True) | Q(date_expiration__gte=aujourd_hui))
    if session_id is not None:
        qs = qs.filter(
            Q(affectation_acteur__session_id=session_id)
            | Q(affectation_acteur__session__isnull=True)
        )
    if centre_id is not None:
        qs = qs.filter(
            Q(
                affectation_acteur__niveau_affectation__in=[
                    AffectationActeur.NiveauAffectation.PLATEFORME,
                    AffectationActeur.NiveauAffectation.NATIONAL,
                ]
            )
            | Q(affectation_acteur__centre_id=centre_id)
            | Q(
                affectation_acteur__niveau_affectation=AffectationActeur.NiveauAffectation.REGION,
                affectation_acteur__region_code__iexact=region_code or "",
            )
        )
    elif region_code:
        qs = qs.filter(
            Q(
                affectation_acteur__niveau_affectation__in=[
                    AffectationActeur.NiveauAffectation.PLATEFORME,
                    AffectationActeur.NiveauAffectation.NATIONAL,
                ]
            )
            | Q(
                affectation_acteur__niveau_affectation=AffectationActeur.NiveauAffectation.REGION,
                affectation_acteur__region_code__iexact=region_code,
            )
        )
    return qs.exists()


def _charger_couvertures_roles(codes):
    aujourd_hui = timezone.localdate()
    return tuple(
        AffectationRole.objects.filter(
            role__code__in=codes,
            role__statut=Role.Statut.ACTIF,
            role__deleted_at__isnull=True,
            statut=AffectationRole.Statut.ACTIF,
            deleted_at__isnull=True,
            date_attribution__lte=aujourd_hui,
            affectation_acteur__in=_affectations_actives(),
        )
        .filter(Q(date_expiration__isnull=True) | Q(date_expiration__gte=aujourd_hui))
        .values(
            "role__code",
            "affectation_acteur__session_id",
            "affectation_acteur__niveau_affectation",
            "affectation_acteur__region_code",
            "affectation_acteur__centre_id",
        )
    )


def _role_couvre(couvertures, code, *, session_id=None, region_code=None, centre_id=None):
    region_normalisee = str(region_code or "").lower()
    for ligne in couvertures:
        if ligne["role__code"] != code:
            continue
        session_affectation = ligne["affectation_acteur__session_id"]
        if session_id is not None and session_affectation not in {None, session_id}:
            continue
        niveau = ligne["affectation_acteur__niveau_affectation"]
        if centre_id is not None:
            if niveau in {
                AffectationActeur.NiveauAffectation.PLATEFORME,
                AffectationActeur.NiveauAffectation.NATIONAL,
            }:
                return True
            if ligne["affectation_acteur__centre_id"] == centre_id:
                return True
            if (
                niveau == AffectationActeur.NiveauAffectation.REGION
                and str(ligne["affectation_acteur__region_code"] or "").lower()
                == region_normalisee
            ):
                return True
            continue
        if region_code:
            if niveau in {
                AffectationActeur.NiveauAffectation.PLATEFORME,
                AffectationActeur.NiveauAffectation.NATIONAL,
            }:
                return True
            if (
                niveau == AffectationActeur.NiveauAffectation.REGION
                and str(ligne["affectation_acteur__region_code"] or "").lower()
                == region_normalisee
            ):
                return True
            continue
        return True
    return False


def detecter():
    maintenant = timezone.now()
    aujourd_hui = timezone.localdate()
    taille_lot = _taille_lot()

    attendues = {definition.code: definition for definition in PERMISSIONS_SYSTEME}
    permissions = {
        permission.code: permission
        for permission in Permission.objects.filter(code__in=attendues.keys())
    }
    for code, definition in attendues.items():
        permission = permissions.get(code)
        if permission is None:
            yield Anomalie(
                code="ACC_PERMISSION_SYSTEME_ABSENTE",
                cle=f"ACC_PERMISSION_SYSTEME_ABSENTE:{code}",
                titre=f"Permission système absente : {code}",
                description=(
                    "Une permission déclarée dans le catalogue du backend est absente de la base. "
                    "Le module accounts reste la source de vérité et doit être corrigé par le seed officiel."
                ),
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SYSTEME,
                module_source="accounts",
                modele_source="Permission",
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                contexte={"permission_code": code},
            )
            continue
        alterations = []
        if permission.deleted_at is not None:
            alterations.append("supprimée logiquement")
        if permission.statut != Permission.Statut.ACTIVE:
            alterations.append("inactive")
        if not permission.est_systeme:
            alterations.append("marquée non système")
        if permission.module != definition.module:
            alterations.append("module modifié")
        if alterations:
            yield Anomalie(
                code="ACC_PERMISSION_SYSTEME_ALTEREE",
                cle=f"ACC_PERMISSION_SYSTEME_ALTEREE:{code}",
                titre=f"Permission système altérée : {code}",
                description="La permission système est " + ", ".join(alterations) + ".",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                module_source="accounts",
                modele_source="Permission",
                objet_source_id=permission.id,
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                contexte={"permission_code": code},
            )

    roles_attendus = {definition.code: definition for definition in ROLES_SYSTEME}
    roles = {role.code: role for role in Role.objects.filter(code__in=roles_attendus.keys())}
    for code, definition in roles_attendus.items():
        role = roles.get(code)
        if role is None:
            yield Anomalie(
                code="ACC_ROLE_SYSTEME_ABSENT",
                cle=f"ACC_ROLE_SYSTEME_ABSENT:{code}",
                titre=f"Rôle système absent : {code}",
                description="Un rôle système déclaré dans le backend est absent de la base.",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SYSTEME,
                module_source="accounts",
                modele_source="Role",
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                contexte={"role_code": code},
            )
            continue
        alterations = []
        if role.deleted_at is not None:
            alterations.append("supprimé logiquement")
        if role.statut != Role.Statut.ACTIF:
            alterations.append("inactif")
        if not role.est_systeme:
            alterations.append("marqué non système")
        if role.niveau != definition.niveau:
            alterations.append("niveau modifié")
        if role.perimetre_autorise != definition.perimetre_autorise:
            alterations.append("périmètre modifié")
        if alterations:
            yield Anomalie(
                code="ACC_ROLE_SYSTEME_ALTERE",
                cle=f"ACC_ROLE_SYSTEME_ALTERE:{code}",
                titre=f"Rôle système altéré : {code}",
                description="Le rôle système est " + ", ".join(alterations) + ".",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.DONNEE,
                module_source="accounts",
                modele_source="Role",
                objet_source_id=role.id,
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                contexte={"role_code": code},
            )

    seuil_nouveau = maintenant - timedelta(minutes=10)
    actifs_sans_affectation = Acteur.objects.filter(
        is_active=True,
        statut=Acteur.Statut.ACTIF,
        deleted_at__isnull=True,
        is_superuser=False,
        date_joined__lte=seuil_nouveau,
    ).exclude(id__in=_affectations_actives().values("acteur_id")).iterator(chunk_size=taille_lot)
    for acteur in actifs_sans_affectation:
        yield Anomalie(
            code="ACC_ACTEUR_SANS_AFFECTATION",
            cle=f"ACC_ACTEUR_SANS_AFFECTATION:{acteur.id}",
            titre="Acteur actif sans affectation",
            description="Un acteur actif ne possède aucun périmètre d'affectation actuellement valide.",
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            gravite=AlerteIncident.NiveauGravite.MOYEN,
            type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
            acteur_concerne_id=acteur.id,
            module_source="accounts",
            modele_source="Acteur",
            objet_source_id=acteur.id,
            origine=AlerteIncident.Origine.SYSTEME_SECURITE,
        )

    affectations_invalides = AffectationActeur.objects.filter(
        statut=AffectationActeur.Statut.ACTIVE,
        deleted_at__isnull=True,
    ).filter(
        Q(acteur__is_active=False)
        | ~Q(acteur__statut=Acteur.Statut.ACTIF)
        | Q(acteur__deleted_at__isnull=False)
    ).select_related("acteur").iterator(chunk_size=taille_lot)
    for affectation in affectations_invalides:
        yield Anomalie(
            code="ACC_ACTEUR_INACTIF_AVEC_DROITS",
            cle=f"ACC_ACTEUR_INACTIF_AVEC_DROITS:{affectation.id}",
            titre="Acteur inactif avec une affectation active",
            description="Une affectation active subsiste pour un acteur désactivé, suspendu ou supprimé.",
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
            acteur_concerne_id=affectation.acteur_id,
            module_source="accounts",
            modele_source="AffectationActeur",
            objet_source_id=affectation.id,
            est_bloquante=True,
            origine=AlerteIncident.Origine.SYSTEME_SECURITE,
        )

    roles_sans_permissions = AffectationRole.objects.filter(
        statut=AffectationRole.Statut.ACTIF,
        deleted_at__isnull=True,
        affectation_acteur__in=_affectations_actives(),
    ).exclude(
        role__permissions_role__statut=RolePermission.Statut.ACTIVE,
        role__permissions_role__deleted_at__isnull=True,
        role__permissions_role__permission__statut=Permission.Statut.ACTIVE,
        role__permissions_role__permission__deleted_at__isnull=True,
    ).select_related("role", "affectation_acteur").iterator(chunk_size=taille_lot)
    for affectation_role in roles_sans_permissions:
        affectation = affectation_role.affectation_acteur
        yield Anomalie(
            code="ACC_ROLE_ATTRIBUE_SANS_PERMISSION",
            cle=f"ACC_ROLE_ATTRIBUE_SANS_PERMISSION:{affectation_role.id}",
            titre=f"Rôle attribué sans permission active : {affectation_role.role.code}",
            description="Le rôle est attribué à un acteur mais ne fournit aucune permission active.",
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
            acteur_concerne_id=affectation.acteur_id,
            module_source="accounts",
            modele_source="AffectationRole",
            objet_source_id=affectation_role.id,
            origine=AlerteIncident.Origine.SYSTEME_SECURITE,
        )

    for affectation in AffectationActeur.objects.filter(
        statut=AffectationActeur.Statut.ACTIVE,
        deleted_at__isnull=True,
    ).filter(Q(date_fin__lt=aujourd_hui) | Q(date_debut__gt=aujourd_hui)).iterator(chunk_size=taille_lot):
        yield Anomalie(
            code="ACC_AFFECTATION_EXPIREE_ACTIVE",
            cle=f"ACC_AFFECTATION_EXPIREE_ACTIVE:{affectation.id}",
            titre="Affectation d'acteur active hors période",
            description="Le statut de l'affectation est actif alors que sa période n'est pas valide.",
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            gravite=AlerteIncident.NiveauGravite.ELEVE,
            type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
            session_id=affectation.session_id,
            centre_id=affectation.centre_id,
            acteur_concerne_id=affectation.acteur_id,
            module_source="accounts",
            modele_source="AffectationActeur",
            objet_source_id=affectation.id,
            origine=AlerteIncident.Origine.SYSTEME_SECURITE,
        )

    expirations = (
        (
            AffectationRole.objects.filter(
                statut=AffectationRole.Statut.ACTIF,
                deleted_at__isnull=True,
                date_expiration__lt=aujourd_hui,
            ),
            "ACC_ROLE_EXPIRE_ACTIF",
            "AffectationRole",
            "Rôle expiré encore actif",
        ),
        (
            AffectationPermission.objects.filter(
                statut=AffectationPermission.Statut.ACTIVE,
                deleted_at__isnull=True,
                date_expiration__lt=aujourd_hui,
            ),
            "ACC_PERMISSION_EXPIREE_ACTIVE",
            "AffectationPermission",
            "Permission directe expirée encore active",
        ),
        (
            DelegationActeur.objects.filter(
                statut=DelegationActeur.Statut.ACTIVE,
                deleted_at__isnull=True,
                date_fin__lt=aujourd_hui,
            ),
            "ACC_DELEGATION_EXPIREE_ACTIVE",
            "DelegationActeur",
            "Délégation expirée encore active",
        ),
    )
    for queryset, code, modele, titre in expirations:
        for objet in queryset.select_related("affectation_acteur").iterator(chunk_size=taille_lot):
            affectation = objet.affectation_acteur
            yield Anomalie(
                code=code,
                cle=f"{code}:{objet.id}",
                titre=titre,
                description="Un droit temporaire reste actif après sa date de fin.",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                acteur_concerne_id=affectation.acteur_id,
                module_source="accounts",
                modele_source=modele,
                objet_source_id=objet.id,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
            )

    demandes = DemandePermission.objects.filter(
        statut=DemandePermission.Statut.APPROUVEE,
        deleted_at__isnull=True,
        affectation_acteur__isnull=False,
    )
    # Une demande approuvée doit avoir produit une permission directe active.
    # La comparaison se fait explicitement pour rester lisible et portable.
    for demande in demandes.select_related("affectation_acteur", "permission").iterator(chunk_size=taille_lot):
        existe = AffectationPermission.objects.filter(
            affectation_acteur_id=demande.affectation_acteur_id,
            permission_id=demande.permission_id,
            statut=AffectationPermission.Statut.ACTIVE,
            deleted_at__isnull=True,
        ).exists()
        if not existe:
            affectation = demande.affectation_acteur
            yield Anomalie(
                code="ACC_DEMANDE_APPROUVEE_NON_APPLIQUEE",
                cle=f"ACC_DEMANDE_APPROUVEE_NON_APPLIQUEE:{demande.id}",
                titre="Demande de permission approuvée mais non appliquée",
                description="La demande est approuvée mais aucune permission directe active correspondante n'existe.",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                acteur_concerne_id=demande.acteur_id,
                module_source="accounts",
                modele_source="DemandePermission",
                objet_source_id=demande.id,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
            )

    delegations = DelegationActeur.objects.filter(
        statut=DelegationActeur.Statut.ACTIVE,
        deleted_at__isnull=True,
    ).select_related("acteur_source", "acteur_cible", "affectation_acteur").iterator(chunk_size=taille_lot)
    for delegation in delegations:
        incoherences = []
        if delegation.acteur_source_id == delegation.acteur_cible_id:
            incoherences.append("source et cible identiques")
        if not delegation.acteur_source.est_actif_metier:
            incoherences.append("source inactive")
        if not delegation.acteur_cible.est_actif_metier:
            incoherences.append("cible inactive")
        if delegation.type_delegation == DelegationActeur.TypeDelegation.ROLE and not delegation.role_id:
            incoherences.append("rôle absent")
        if delegation.type_delegation == DelegationActeur.TypeDelegation.PERMISSION and not delegation.permission_id:
            incoherences.append("permission absente")
        if incoherences:
            affectation = delegation.affectation_acteur
            yield Anomalie(
                code="ACC_DELEGATION_INCOHERENTE",
                cle=f"ACC_DELEGATION_INCOHERENTE:{delegation.id}",
                titre="Délégation active incohérente",
                description="La délégation présente les anomalies suivantes : " + ", ".join(incoherences) + ".",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
                session_id=affectation.session_id,
                centre_id=affectation.centre_id,
                acteur_concerne_id=delegation.acteur_cible_id,
                module_source="accounts",
                modele_source="DelegationActeur",
                objet_source_id=delegation.id,
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
            )

    couvertures_roles = _charger_couvertures_roles(
        {
            "ADMINISTRATEUR",
            "DGAS",
            "DIRECTEUR_REGIONAL",
            "RESPONSABLE_CENTRE",
            "AGENT_SANTE",
            "FORMATEUR",
        }
    )
    if not (
        Acteur.objects.filter(
            is_superuser=True,
            is_active=True,
            statut=Acteur.Statut.ACTIF,
            deleted_at__isnull=True,
        ).exists()
        or _role_couvre(couvertures_roles, "ADMINISTRATEUR")
    ):
        yield Anomalie(
            code="ACC_POSTE_ADMIN_VACANT",
            cle="ACC_POSTE_ADMIN_VACANT:PLATEFORME",
            titre="Aucun administrateur actif",
            description=(
                "La plateforme ne possède aucun superutilisateur ni rôle "
                "ADMINISTRATEUR actif."
            ),
            categorie=AlerteIncident.Categorie.SECURITE_ACCES,
            gravite=AlerteIncident.NiveauGravite.CRITIQUE,
            type_concerne=AlerteIncident.TypeConcerne.SYSTEME,
            module_source="accounts",
            modele_source="AffectationRole",
            est_bloquante=True,
            resolution_automatique=False,
            origine=AlerteIncident.Origine.SYSTEME_SECURITE,
        )

    sessions = list(
        SessionImmersion.objects.filter(
            statut__in=[
                SessionImmersion.Statut.OUVERTE,
                SessionImmersion.Statut.EN_PREPARATION,
                SessionImmersion.Statut.EN_COURS,
            ],
            deleted_at__isnull=True,
        ).select_related("parametres")
    )
    session_ids = [session.id for session in sessions]
    centres_par_session = {}
    for ligne in (
        AffectationCentre.objects.filter(
            session_id__in=session_ids,
            statut=AffectationCentre.Statut.ACTIVE,
            deleted_at__isnull=True,
        )
        .values(
            "session_id",
            "centre_id",
            "centre__region_id",
            "centre__region__code",
        )
        .distinct()
        .iterator(chunk_size=taille_lot)
    ):
        centres_par_session.setdefault(ligne["session_id"], []).append(ligne)

    centres_avec_seances = set(
        Seance.objects.filter(
            session_id__in=session_ids,
            statut__in=[Seance.Statut.PLANIFIEE, Seance.Statut.EN_COURS],
            deleted_at__isnull=True,
        ).values_list("session_id", "centre_id").distinct()
    )

    for session in sessions:
        if not _role_couvre(couvertures_roles, "DGAS", session_id=session.id):
            yield Anomalie(
                code="ACC_POSTE_DGAS_VACANT",
                cle=f"ACC_POSTE_DGAS_VACANT:{session.id}",
                titre="Session sans coordination nationale active",
                description="Aucun acteur DGAS actif ne couvre cette session opérationnelle.",
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                type_concerne=AlerteIncident.TypeConcerne.SESSION,
                session_id=session.id,
                module_source="accounts",
                modele_source="SessionImmersion",
                objet_source_id=session.id,
                est_bloquante=True,
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
            )

        regions_vues = set()
        for ligne in centres_par_session.get(session.id, []):
            centre_id = ligne["centre_id"]
            region_id = ligne["centre__region_id"]
            region_code = ligne["centre__region__code"]
            if region_code not in regions_vues:
                regions_vues.add(region_code)
                if not _role_couvre(
                    couvertures_roles,
                    "DIRECTEUR_REGIONAL",
                    session_id=session.id,
                    region_code=region_code,
                ):
                    yield Anomalie(
                        code="ACC_POSTE_DR_VACANT",
                        cle=f"ACC_POSTE_DR_VACANT:{session.id}:{region_code}",
                        titre=f"Région {region_code} sans Directeur régional actif",
                        description=(
                            "Une région utilisée par la session ne possède aucun "
                            "Directeur régional actif."
                        ),
                        categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                        gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                        type_concerne=AlerteIncident.TypeConcerne.SESSION,
                        session_id=session.id,
                        region_id=region_id,
                        module_source="accounts",
                        modele_source="AffectationRole",
                        est_bloquante=True,
                        origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                        contexte={"region_code": region_code},
                    )
            if not _role_couvre(
                couvertures_roles,
                "RESPONSABLE_CENTRE",
                session_id=session.id,
                region_code=region_code,
                centre_id=centre_id,
            ):
                yield Anomalie(
                    code="ACC_POSTE_RESPONSABLE_CENTRE_VACANT",
                    cle=f"ACC_POSTE_RESPONSABLE_CENTRE_VACANT:{session.id}:{centre_id}",
                    titre="Centre opérationnel sans responsable actif",
                    description=(
                        "Aucun Responsable de centre actif ne couvre ce centre pour la session."
                    ),
                    categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                    gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                    type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                    session_id=session.id,
                    region_id=region_id,
                    centre_id=centre_id,
                    module_source="accounts",
                    modele_source="AffectationRole",
                    est_bloquante=True,
                    origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                )

            parametres = getattr(session, "parametres", None)
            if (
                parametres
                and parametres.visite_medicale_active
                and not _role_couvre(
                    couvertures_roles,
                    "AGENT_SANTE",
                    session_id=session.id,
                    region_code=region_code,
                    centre_id=centre_id,
                )
            ):
                yield Anomalie(
                    code="ACC_POSTE_AGENT_SANTE_VACANT",
                    cle=f"ACC_POSTE_AGENT_SANTE_VACANT:{session.id}:{centre_id}",
                    titre="Centre sans agent santé actif",
                    description=(
                        "La visite médicale est activée mais aucun Agent santé actif "
                        "ne couvre le centre."
                    ),
                    categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                    gravite=AlerteIncident.NiveauGravite.CRITIQUE,
                    type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                    session_id=session.id,
                    region_id=region_id,
                    centre_id=centre_id,
                    module_source="accounts",
                    modele_source="AffectationRole",
                    est_bloquante=session.statut == SessionImmersion.Statut.EN_COURS,
                    origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                )

            if (
                (session.id, centre_id) in centres_avec_seances
                and not _role_couvre(
                    couvertures_roles,
                    "FORMATEUR",
                    session_id=session.id,
                    region_code=region_code,
                    centre_id=centre_id,
                )
            ):
                yield Anomalie(
                    code="ACC_POSTE_FORMATEUR_VACANT",
                    cle=f"ACC_POSTE_FORMATEUR_VACANT:{session.id}:{centre_id}",
                    titre="Centre avec séances mais sans formateur actif",
                    description=(
                        "Des séances sont programmées alors qu'aucun rôle FORMATEUR "
                        "actif ne couvre le centre."
                    ),
                    categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                    gravite=AlerteIncident.NiveauGravite.ELEVE,
                    type_concerne=AlerteIncident.TypeConcerne.CENTRE,
                    session_id=session.id,
                    region_id=region_id,
                    centre_id=centre_id,
                    module_source="accounts",
                    modele_source="AffectationRole",
                    origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                )

    fenetre = maintenant - timedelta(minutes=5)
    seuils = (
        (Acteur.objects.filter(created_by__isnull=False, date_joined__gte=fenetre), "created_by_id", 20, "créations de comptes"),
        (AffectationActeur.objects.filter(affecte_par__isnull=False, created_at__gte=fenetre), "affecte_par_id", 30, "affectations d'acteurs"),
        (AffectationRole.objects.filter(attribue_par__isnull=False, created_at__gte=fenetre), "attribue_par_id", 20, "attributions de rôles"),
        (AffectationPermission.objects.filter(attribue_par__isnull=False, created_at__gte=fenetre), "attribue_par_id", 20, "attributions de permissions directes"),
        (DemandePermission.objects.filter(created_at__gte=fenetre), "acteur_id", 10, "demandes de permissions"),
        (DelegationActeur.objects.filter(created_at__gte=fenetre), "acteur_source_id", 15, "délégations"),
    )
    for queryset, champ, seuil, libelle in seuils:
        for ligne in queryset.values(champ).annotate(total=Count("id")).filter(total__gte=seuil):
            acteur_id = ligne[champ]
            yield Anomalie(
                code="ACC_ACTIONS_MASSIVES_SUSPECTES",
                cle=f"ACC_ACTIONS_MASSIVES_SUSPECTES:{libelle}:{acteur_id}",
                titre=f"Volume inhabituel de {libelle}",
                description=(
                    f"L'acteur a réalisé {ligne['total']} {libelle} en moins de cinq minutes. "
                    "Le volume doit être vérifié, sans bloquer les traitements massifs autorisés."
                ),
                categorie=AlerteIncident.Categorie.SECURITE_ACCES,
                gravite=AlerteIncident.NiveauGravite.ELEVE,
                type_concerne=AlerteIncident.TypeConcerne.ACTEUR,
                acteur_concerne_id=acteur_id,
                module_source="accounts",
                modele_source="ActionAccounts",
                origine=AlerteIncident.Origine.SYSTEME_SECURITE,
                contexte={"volume": ligne["total"], "fenetre_minutes": 5, "action": libelle},
            )
