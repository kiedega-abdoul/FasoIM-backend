"""Commande d'initialisation des rôles et permissions système FasoIM.

Cette commande insère seulement :
- les permissions système déjà codées dans le backend ;
- les rôles système de base.

Elle n'associe pas automatiquement les permissions aux rôles. Ces associations
seront faites plus tard par l'administrateur ou par une commande dédiée lorsque
le catalogue final sera validé.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Permission, Role


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    libelle: str
    module: str
    description: str = ""


@dataclass(frozen=True)
class RoleDefinition:
    code: str
    libelle: str
    niveau: int
    perimetre_autorise: str
    description: str = ""


PERMISSIONS_SYSTEME = [
    # Accounts - actions communes
    PermissionDefinition("se_connecter", "Se connecter", "accounts", "Connexion d'un acteur interne."),
    PermissionDefinition("se_deconnecter", "Se déconnecter", "accounts", "Déconnexion d'un acteur interne."),
    PermissionDefinition("choisir_contexte", "Choisir un contexte", "accounts", "Choisir une affectation active."),
    PermissionDefinition("changer_mot_de_passe", "Changer son mot de passe", "accounts", "Modifier son mot de passe."),
    PermissionDefinition("consulter_profil", "Consulter son profil", "accounts", "Consulter son propre profil."),
    PermissionDefinition("modifier_profil", "Modifier son profil", "accounts", "Modifier les champs autorisés de son profil."),

    # Accounts - acteurs
    PermissionDefinition("creer_acteur", "Créer un acteur", "accounts", "Créer un compte acteur interne."),
    PermissionDefinition("modifier_acteur", "Modifier un acteur", "accounts", "Modifier les informations d'un acteur."),
    PermissionDefinition("desactiver_acteur", "Désactiver un acteur", "accounts", "Désactiver logiquement un acteur."),
    PermissionDefinition("reactiver_acteur", "Réactiver un acteur", "accounts", "Réactiver un acteur désactivé."),
    PermissionDefinition("consulter_acteur", "Consulter un acteur", "accounts", "Consulter la fiche d'un acteur."),
    PermissionDefinition("lister_acteurs", "Lister les acteurs", "accounts", "Lister les acteurs selon le périmètre."),

    # Accounts - affectations d'acteurs
    PermissionDefinition("affecter_acteur_session", "Affecter un acteur", "accounts", "Affecter un acteur à un périmètre."),
    PermissionDefinition("retirer_affectation_acteur", "Retirer une affectation", "accounts", "Retirer une affectation d'acteur."),
    PermissionDefinition("suspendre_affectation_acteur", "Suspendre une affectation", "accounts", "Suspendre une affectation d'acteur."),
    PermissionDefinition("reactiver_affectation_acteur", "Réactiver une affectation", "accounts", "Réactiver une affectation d'acteur."),

    # Accounts - rôles et permissions
    PermissionDefinition("creer_role", "Créer un rôle", "accounts", "Créer un rôle personnalisé ou système."),
    PermissionDefinition("modifier_role", "Modifier un rôle", "accounts", "Modifier un rôle autorisé."),
    PermissionDefinition("desactiver_role", "Désactiver un rôle", "accounts", "Désactiver un rôle modifiable."),
    PermissionDefinition("consulter_role", "Consulter un rôle", "accounts", "Consulter un rôle."),
    PermissionDefinition("lister_roles", "Lister les rôles", "accounts", "Lister les rôles disponibles."),
    PermissionDefinition("attribuer_role", "Attribuer un rôle", "accounts", "Attribuer un rôle à une affectation."),
    PermissionDefinition("retirer_role", "Retirer un rôle", "accounts", "Retirer un rôle d'une affectation."),
    PermissionDefinition("consulter_permission", "Consulter une permission", "accounts", "Consulter une permission système."),
    PermissionDefinition("lister_permissions", "Lister les permissions", "accounts", "Lister le catalogue des permissions."),
    PermissionDefinition("ajouter_permission_role", "Ajouter une permission à un rôle", "accounts", "Ajouter une permission existante à un rôle."),
    PermissionDefinition("retirer_permission_role", "Retirer une permission d'un rôle", "accounts", "Retirer une permission d'un rôle."),
    PermissionDefinition("attribuer_permission_directe", "Attribuer une permission directe", "accounts", "Attribuer une permission exceptionnelle."),
    PermissionDefinition("retirer_permission_directe", "Retirer une permission directe", "accounts", "Retirer une permission exceptionnelle."),
    PermissionDefinition("deleguer_permission", "Déléguer une permission", "accounts", "Déléguer une permission marquée déléguable."),

    # Accounts - demandes et délégations
    PermissionDefinition("demander_permission", "Demander une permission", "accounts", "Soumettre une demande de permission."),
    PermissionDefinition("lister_demandes_permissions", "Lister les demandes de permissions", "accounts", "Lister les demandes de permissions."),
    PermissionDefinition("consulter_demande_permission", "Consulter une demande de permission", "accounts", "Consulter une demande de permission."),
    PermissionDefinition("approuver_demande_permission", "Approuver une demande de permission", "accounts", "Approuver une demande de permission."),
    PermissionDefinition("refuser_demande_permission", "Refuser une demande de permission", "accounts", "Refuser une demande de permission."),
    PermissionDefinition("annuler_demande_permission", "Annuler une demande de permission", "accounts", "Annuler une demande de permission."),
    PermissionDefinition("creer_delegation", "Créer une délégation", "accounts", "Créer une délégation d'acteur."),
    PermissionDefinition("modifier_delegation", "Modifier une délégation", "accounts", "Modifier une délégation d'acteur."),
    PermissionDefinition("terminer_delegation", "Terminer une délégation", "accounts", "Terminer une délégation d'acteur."),
    PermissionDefinition("annuler_delegation", "Annuler une délégation", "accounts", "Annuler une délégation d'acteur."),
    PermissionDefinition("lister_delegations", "Lister les délégations", "accounts", "Lister les délégations selon le périmètre."),
    PermissionDefinition("consulter_delegation", "Consulter une délégation", "accounts", "Consulter une délégation."),

    # Sessions
    PermissionDefinition("creer_session", "Créer une session", "sessions_app", "Créer une session d'immersion."),
    PermissionDefinition("modifier_session", "Modifier une session", "sessions_app", "Modifier une session d'immersion."),
    PermissionDefinition("cloturer_session", "Clôturer une session", "sessions_app", "Clôturer une session d'immersion."),
    PermissionDefinition("archiver_session", "Archiver une session", "sessions_app", "Archiver une session d'immersion."),
    PermissionDefinition("consulter_session", "Consulter une session", "sessions_app", "Consulter une session selon le périmètre."),
    PermissionDefinition("lister_sessions", "Lister les sessions", "sessions_app", "Lister les sessions selon les droits."),
    PermissionDefinition("activer_module_session", "Activer un module de session", "sessions_app", "Activer un module dans les paramètres de session."),
    PermissionDefinition("desactiver_module_session", "Désactiver un module de session", "sessions_app", "Désactiver un module dans les paramètres de session."),
    PermissionDefinition("configurer_parametres_session", "Configurer les paramètres d'une session", "sessions_app", "Configurer les paramètres initiaux d'une session."),
    PermissionDefinition("modifier_parametres_session", "Modifier les paramètres d'une session", "sessions_app", "Modifier les paramètres d'une session."),
    PermissionDefinition("consulter_historique_sessions", "Consulter l'historique des sessions", "sessions_app", "Consulter les sessions supprimées ou archivées."),
    PermissionDefinition("consulter_historique_parametres_session", "Consulter l'historique des paramètres", "sessions_app", "Consulter l'historique des paramètres de session."),

    # Imports
    PermissionDefinition("creer_import_officiel", "Créer un import officiel", "imports_app", "Créer un import officiel pour une session."),
    PermissionDefinition("lister_imports_officiels", "Lister les imports officiels", "imports_app", "Lister les imports officiels selon les droits."),
    PermissionDefinition("consulter_import_officiel", "Consulter un import officiel", "imports_app", "Consulter le détail d'un import officiel."),
    PermissionDefinition("modifier_import_officiel", "Modifier un import officiel", "imports_app", "Modifier les informations autorisées d'un import officiel."),
    PermissionDefinition("supprimer_import_officiel", "Supprimer un import officiel", "imports_app", "Supprimer logiquement un import officiel."),

    PermissionDefinition("consulter_champs_attendus_import", "Consulter les champs attendus", "imports_app", "Consulter les champs attendus selon le type d'import."),
    PermissionDefinition("relancer_lecture_import", "Relancer la lecture d'un import", "imports_app", "Relancer la lecture des colonnes d'un fichier importé."),
    PermissionDefinition("valider_correspondance_import", "Valider la correspondance d'un import", "imports_app", "Valider la correspondance entre colonnes source et champs FasoIM."),
    PermissionDefinition("valider_lignes_import", "Valider les lignes d'un import", "imports_app", "Lancer ou relancer la validation des lignes d'un import."),
    PermissionDefinition("confirmer_import_officiel", "Confirmer un import officiel", "imports_app", "Confirmer l'import final après validation."),
    PermissionDefinition("annuler_import_officiel", "Annuler un import officiel", "imports_app", "Annuler un import officiel."),
    PermissionDefinition("consulter_progression_import", "Consulter la progression d'un import", "imports_app", "Consulter la progression du traitement d'un import."),

    PermissionDefinition("consulter_correspondances_import", "Consulter les correspondances d'import", "imports_app", "Consulter les correspondances de colonnes d'un import."),
    PermissionDefinition("consulter_lignes_import", "Consulter les lignes d'import", "imports_app", "Consulter les lignes lues dans un import."),
    PermissionDefinition("corriger_ligne_import", "Corriger une ligne d'import", "imports_app", "Corriger ou revalider une ligne d'import."),
    PermissionDefinition("ignorer_ligne_import", "Ignorer une ligne d'import", "imports_app", "Ignorer une ligne d'import."),
    PermissionDefinition("consulter_erreurs_import", "Consulter les erreurs d'import", "imports_app", "Consulter les erreurs détectées dans un import."),

    # Immerges - sources
    PermissionDefinition("lister_sources_immerges", "Lister les sources d'immergés", "immerges", "Lister les sources examens, concours et sélectionnés."),
    PermissionDefinition("consulter_source_immerge", "Consulter une source d'immergé", "immerges", "Consulter une source importée."),
    PermissionDefinition("creer_source_immerge", "Créer une source d'immergé", "immerges", "Créer manuellement une source d'immergé."),
    PermissionDefinition("modifier_source_immerge", "Modifier une source d'immergé", "immerges", "Modifier une source d'immergé."),
    PermissionDefinition("supprimer_source_immerge", "Supprimer une source d'immergé", "immerges", "Supprimer logiquement une source d'immergé."),
    PermissionDefinition("centraliser_source_immerge", "Centraliser une source d'immergé", "immerges", "Créer l'immergé central depuis une source."),
    PermissionDefinition("centraliser_sources_importees", "Centraliser des sources importées", "immerges", "Centraliser en lot des sources importées validées."),

    # Immerges - volontaires
    PermissionDefinition("creer_inscription_volontaire", "Créer une inscription volontaire", "immerges", "Créer une demande volontaire."),
    PermissionDefinition("lister_inscriptions_volontaires", "Lister les inscriptions volontaires", "immerges", "Lister les demandes volontaires."),
    PermissionDefinition("consulter_inscription_volontaire", "Consulter une inscription volontaire", "immerges", "Consulter une demande volontaire."),
    PermissionDefinition("modifier_inscription_volontaire", "Modifier une inscription volontaire", "immerges", "Modifier une demande volontaire."),
    PermissionDefinition("accepter_inscription_volontaire", "Accepter une inscription volontaire", "immerges", "Accepter une demande volontaire."),
    PermissionDefinition("refuser_inscription_volontaire", "Refuser une inscription volontaire", "immerges", "Refuser une demande volontaire."),
    PermissionDefinition("annuler_inscription_volontaire", "Annuler une inscription volontaire", "immerges", "Annuler une demande volontaire."),
    PermissionDefinition("supprimer_inscription_volontaire", "Supprimer une inscription volontaire", "immerges", "Supprimer logiquement une demande volontaire."),
    PermissionDefinition("accepter_inscriptions_volontaires_lot", "Accepter des volontaires en lot", "immerges", "Accepter plusieurs inscriptions volontaires."),
    PermissionDefinition("centraliser_volontaires_acceptes", "Centraliser les volontaires acceptés", "immerges", "Créer les immergés centraux des volontaires acceptés."),

    # Immerges - table centrale
    PermissionDefinition("lister_immerges", "Lister les immergés", "immerges", "Lister les immergés centraux."),
    PermissionDefinition("consulter_immerge", "Consulter un immergé", "immerges", "Consulter un immergé central."),
    PermissionDefinition("centraliser_immerge", "Centraliser un immergé", "immerges", "Créer une ligne centrale Immerge."),
    PermissionDefinition("modifier_immerge", "Modifier un immergé", "immerges", "Modifier les champs autorisés d'un immergé central."),
    PermissionDefinition("changer_statut_immerge", "Changer le statut d'un immergé", "immerges", "Changer le statut d'un immergé."),
    PermissionDefinition("changer_statut_immerges_lot", "Changer le statut en lot", "immerges", "Changer le statut de plusieurs immergés."),
    PermissionDefinition("generer_code_immerge", "Générer le code d'un immergé", "immerges", "Générer le code FasoIM d'un immergé."),
    PermissionDefinition("generer_codes_immerges", "Générer les codes des immergés", "immerges", "Générer les codes FasoIM manquants."),
    PermissionDefinition("regenerer_qr_immerges", "Régénérer les QR des immergés", "immerges", "Régénérer les contenus QR des immergés."),
    PermissionDefinition("supprimer_immerge", "Supprimer un immergé", "immerges", "Supprimer logiquement un immergé."),
    PermissionDefinition("supprimer_immerges_session", "Supprimer les immergés d'une session", "immerges", "Supprimer logiquement les immergés d'une session."),
    PermissionDefinition("consulter_progression_immerges", "Consulter la progression immerges", "immerges", "Consulter la progression des tâches immergés."),
    PermissionDefinition("consulter_statistiques_immerges", "Consulter les statistiques immergés", "immerges", "Consulter les statistiques des immergés."),
    PermissionDefinition("confirmer_import_vers_immerges", "Confirmer un import vers immergés", "immerges", "Confirmer un import officiel vers le module immergés."),
]


ROLES_SYSTEME = [
    RoleDefinition(
        "ADMINISTRATEUR",
        "Administrateur",
        0,
        Role.Perimetre.PLATEFORME,
        "Gère la plateforme, les comptes, les rôles, les permissions et les paramètres techniques.",
    ),
    RoleDefinition(
        "DGAS",
        "DGAS / Coordination nationale",
        10,
        Role.Perimetre.NATIONAL,
        "Pilote les sessions et les opérations au niveau national.",
    ),
    RoleDefinition(
        "DIRECTEUR_REGIONAL",
        "Directeur Régional",
        20,
        Role.Perimetre.REGION,
        "Gère les opérations d'immersion au niveau de sa région.",
    ),
    RoleDefinition(
        "RESPONSABLE_CENTRE",
        "Responsable de centre",
        30,
        Role.Perimetre.CENTRE,
        "Organise l'accueil et le suivi quotidien dans un centre.",
    ),
    RoleDefinition(
        "FORMATEUR",
        "Formateur / Intervenant",
        40,
        Role.Perimetre.CENTRE,
        "Encadre les activités de formation, d'orientation ou de sensibilisation.",
    ),
    RoleDefinition(
        "AGENT_SANTE",
        "Agent santé",
        40,
        Role.Perimetre.CENTRE,
        "Gère les visites médicales lorsque le module santé est activé.",
    ),
]


class Command(BaseCommand):
    help = "Initialise les permissions système et les rôles de base FasoIM, sans associations rôle-permission."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait initialisé sans modifier la base.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode dry-run : aucune donnée ne sera modifiée."))
            self.stdout.write(f"Permissions prévues : {len(PERMISSIONS_SYSTEME)}")
            self.stdout.write(f"Rôles prévus : {len(ROLES_SYSTEME)}")
            return

        permissions_creees = 0
        permissions_mises_a_jour = 0
        roles_crees = 0
        roles_mis_a_jour = 0

        for definition in PERMISSIONS_SYSTEME:
            _, created = Permission.objects.update_or_create(
                code=definition.code,
                defaults={
                    "libelle": definition.libelle,
                    "module": definition.module,
                    "description": definition.description,
                    "est_systeme": True,
                    "statut": Permission.Statut.ACTIVE,
                    "deleted_at": None,
                },
            )
            if created:
                permissions_creees += 1
            else:
                permissions_mises_a_jour += 1

        for definition in ROLES_SYSTEME:
            _, created = Role.objects.update_or_create(
                code=definition.code,
                defaults={
                    "libelle": definition.libelle,
                    "description": definition.description,
                    "niveau": definition.niveau,
                    "perimetre_autorise": definition.perimetre_autorise,
                    "est_systeme": True,
                    "est_modifiable": False,
                    "statut": Role.Statut.ACTIF,
                    "deleted_at": None,
                },
            )
            if created:
                roles_crees += 1
            else:
                roles_mis_a_jour += 1

        self.stdout.write(self.style.SUCCESS("Initialisation accounts terminée."))
        self.stdout.write(f"Permissions créées : {permissions_creees}")
        self.stdout.write(f"Permissions mises à jour : {permissions_mises_a_jour}")
        self.stdout.write(f"Rôles créés : {roles_crees}")
        self.stdout.write(f"Rôles mis à jour : {roles_mis_a_jour}")
        self.stdout.write(self.style.WARNING("Aucune association rôle-permission n'a été créée."))
