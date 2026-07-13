"""Commande d'initialisation des rôles et permissions système FasoIM.

Cette commande insère :
- les permissions système déjà codées dans le backend ;
- les rôles système de base ;
- les associations minimales des modules incidents et audit aux rôles système.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Permission, Role, RolePermission


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

    # Affectations - régions
    PermissionDefinition("creer_region", "Créer une région", "affectations", "Créer une région d'immersion."),
    PermissionDefinition("modifier_region", "Modifier une région", "affectations", "Modifier une région d'immersion."),
    PermissionDefinition("desactiver_region", "Désactiver une région", "affectations", "Désactiver logiquement une région d'immersion."),
    PermissionDefinition("consulter_region", "Consulter une région", "affectations", "Consulter une région selon le périmètre autorisé."),
    PermissionDefinition("lister_regions", "Lister les régions", "affectations", "Lister les régions selon le périmètre autorisé."),

    # Affectations - centres
    PermissionDefinition("creer_centre", "Créer un centre", "affectations", "Créer un centre d'immersion dans une région."),
    PermissionDefinition("modifier_centre", "Modifier un centre", "affectations", "Modifier un centre selon le périmètre autorisé."),
    PermissionDefinition("desactiver_centre", "Désactiver un centre", "affectations", "Désactiver logiquement un centre d'immersion."),
    PermissionDefinition("mettre_centre_maintenance", "Mettre un centre en maintenance", "affectations", "Suspendre temporairement l'utilisation d'un centre."),
    PermissionDefinition("reactiver_centre", "Réactiver un centre", "affectations", "Réactiver un centre désactivé ou en maintenance."),
    PermissionDefinition("consulter_centre", "Consulter un centre", "affectations", "Consulter un centre selon le périmètre autorisé."),
    PermissionDefinition("lister_centres", "Lister les centres", "affectations", "Lister les centres selon le périmètre autorisé."),
    PermissionDefinition("verifier_capacite_centre", "Vérifier la capacité d'un centre", "affectations", "Consulter la capacité et l'occupation d'un centre."),

    # Affectations - affectations régionales
    PermissionDefinition("proposer_affectation_regionale", "Proposer une affectation régionale", "affectations", "Lancer la proposition automatique d'un lot d'affectations régionales."),
    PermissionDefinition("affecter_region", "Affecter un immergé à une région", "affectations", "Effectuer une affectation régionale manuelle."),
    PermissionDefinition("modifier_affectation_regionale", "Modifier une affectation régionale", "affectations", "Modifier, rejeter ou transférer une affectation régionale."),
    PermissionDefinition("annuler_affectation_regionale", "Annuler une affectation régionale", "affectations", "Annuler logiquement une affectation régionale."),
    PermissionDefinition("valider_affectation_regionale", "Valider une affectation régionale", "affectations", "Valider une ou plusieurs propositions régionales."),
    PermissionDefinition("consulter_affectations_regionales", "Consulter les affectations régionales", "affectations", "Consulter les propositions et affectations régionales selon le périmètre."),

    # Affectations - affectations centres
    PermissionDefinition("proposer_affectation_centre", "Proposer une affectation centre", "affectations", "Lancer la proposition automatique d'un lot d'affectations aux centres."),
    PermissionDefinition("affecter_centre", "Affecter un immergé à un centre", "affectations", "Effectuer une affectation centre manuelle."),
    PermissionDefinition("modifier_affectation_centre", "Modifier une affectation centre", "affectations", "Modifier, rejeter ou transférer une affectation centre."),
    PermissionDefinition("annuler_affectation_centre", "Annuler une affectation centre", "affectations", "Annuler logiquement une affectation centre."),
    PermissionDefinition("valider_affectation_centre", "Valider une affectation centre", "affectations", "Valider une ou plusieurs propositions de centres."),
    PermissionDefinition("verifier_compatibilite_centre", "Vérifier la compatibilité centre", "affectations", "Vérifier la compatibilité d'un immergé avec un centre."),
    PermissionDefinition("consulter_affectations_centres", "Consulter les affectations centres", "affectations", "Consulter les propositions et affectations centres selon le périmètre."),

    # Organisation - règles du centre
    PermissionDefinition("configurer_regles_centre", "Configurer les règles du centre", "organisation", "Définir les règles locales d'organisation d'un centre pour une session."),
    PermissionDefinition("modifier_regles_centre", "Modifier les règles du centre", "organisation", "Modifier les règles locales d'organisation d'un centre."),
    PermissionDefinition("consulter_regles_centre", "Consulter les règles du centre", "organisation", "Consulter les règles et l'état d'organisation d'un centre."),
    PermissionDefinition("generer_sections_groupes", "Générer les sections et groupes", "organisation", "Lancer la génération automatique des sections et groupes selon les règles du centre."),
    PermissionDefinition("valider_organisation_interne", "Valider l'organisation interne", "organisation", "Valider l'organisation interne complète d'un centre."),
    PermissionDefinition("marquer_centre_pret_publication", "Marquer le centre prêt pour publication", "organisation", "Déclarer l'organisation du centre prête à être publiée."),

    # Organisation - sections
    PermissionDefinition("creer_section", "Créer une section", "organisation", "Créer manuellement une section dans un centre."),
    PermissionDefinition("modifier_section", "Modifier une section", "organisation", "Modifier une section existante."),
    PermissionDefinition("supprimer_section", "Supprimer une section", "organisation", "Archiver logiquement une section vide."),

    # Organisation - groupes
    PermissionDefinition("creer_groupe", "Créer un groupe", "organisation", "Créer manuellement un groupe dans une section."),
    PermissionDefinition("modifier_groupe", "Modifier un groupe", "organisation", "Modifier un groupe existant."),
    PermissionDefinition("supprimer_groupe", "Supprimer un groupe", "organisation", "Archiver logiquement un groupe vide."),
    PermissionDefinition("affecter_immerge_groupe", "Affecter un immergé à un groupe", "organisation", "Affecter manuellement ou en lot un immergé à un groupe."),
    PermissionDefinition("retirer_immerge_groupe", "Retirer un immergé d'un groupe", "organisation", "Retirer un immergé de son groupe en conservant l'historique."),

    # Organisation - dortoirs
    PermissionDefinition("creer_dortoir", "Créer un dortoir", "organisation", "Créer un dortoir dans un centre."),
    PermissionDefinition("modifier_dortoir", "Modifier un dortoir", "organisation", "Modifier les informations d'un dortoir."),
    PermissionDefinition("desactiver_dortoir", "Désactiver un dortoir", "organisation", "Archiver logiquement un dortoir vide."),
    PermissionDefinition("mettre_dortoir_hors_service", "Mettre un dortoir hors service", "organisation", "Suspendre l'utilisation d'un dortoir."),

    # Organisation - lits
    PermissionDefinition("creer_lit", "Créer un lit", "organisation", "Créer un lit dans un dortoir."),
    PermissionDefinition("modifier_lit", "Modifier un lit", "organisation", "Modifier les informations d'un lit."),
    PermissionDefinition("mettre_lit_hors_service", "Mettre un lit hors service", "organisation", "Suspendre l'utilisation d'un lit."),
    PermissionDefinition("reactiver_lit", "Réactiver un lit", "organisation", "Réactiver un lit hors service."),

    # Organisation - hébergement
    PermissionDefinition("proposer_attribution_lit", "Proposer une attribution de lit", "organisation", "Lancer la proposition automatique des attributions de lits."),
    PermissionDefinition("attribuer_lit", "Attribuer un lit", "organisation", "Attribuer manuellement ou valider une proposition de lit."),
    PermissionDefinition("modifier_attribution_lit", "Modifier une attribution de lit", "organisation", "Modifier ou rejeter une attribution de lit."),
    PermissionDefinition("liberer_lit", "Libérer un lit", "organisation", "Libérer un lit en conservant l'historique de son attribution."),
    PermissionDefinition("consulter_hebergement", "Consulter l'hébergement", "organisation", "Consulter les dortoirs, lits et attributions selon le périmètre autorisé."),

    # Santé - visites médicales
    PermissionDefinition("consulter_visites_medicales", "Consulter les visites médicales", "sante", "Consulter les résultats et informations médicales selon le périmètre autorisé."),
    PermissionDefinition("saisir_resultat_visite_medicale", "Saisir un résultat médical", "sante", "Créer un brouillon ou enregistrer et valider une visite médicale."),
    PermissionDefinition("corriger_resultat_visite_medicale", "Corriger un résultat médical", "sante", "Créer une contre-visite en conservant l'historique médical."),
    PermissionDefinition("appliquer_resultat_visite_medicale", "Appliquer un résultat médical", "sante", "Appliquer ou réappliquer les conséquences d'une visite validée."),
    PermissionDefinition("annuler_visite_medicale", "Annuler une visite médicale", "sante", "Annuler logiquement une visite médicale en conservant l'historique."),
    PermissionDefinition("consulter_candidats_visite_medicale", "Consulter les candidats à la visite", "sante", "Consulter les immergés du centre restant à examiner."),
    PermissionDefinition("consulter_statistiques_sante", "Consulter les statistiques de santé", "sante", "Consulter les synthèses de visites médicales selon le périmètre."),

    # Santé - restrictions médicales
    PermissionDefinition("consulter_restrictions_medicales", "Consulter les restrictions médicales", "sante", "Consulter les restrictions médicales selon le périmètre autorisé."),
    PermissionDefinition("enregistrer_restriction_medicale", "Enregistrer une restriction médicale", "sante", "Ajouter une restriction et ses consignes opérationnelles à une visite."),
    PermissionDefinition("modifier_restriction_medicale", "Modifier une restriction médicale", "sante", "Modifier une restriction appartenant à une visite non validée."),
    PermissionDefinition("annuler_restriction_medicale", "Annuler une restriction médicale", "sante", "Annuler logiquement une restriction médicale."),
    PermissionDefinition("lever_restriction_medicale", "Lever une restriction médicale", "sante", "Clôturer une restriction médicale devenue sans objet."),

    # Santé - impacts opérationnels
    PermissionDefinition("consulter_impacts_medicaux", "Consulter les impacts médicaux", "sante", "Consulter uniquement les décisions et consignes opérationnelles utiles aux autres modules."),


    # Kits - articles
    PermissionDefinition("consulter_articles_kit", "Consulter les articles de kit", "kits", "Consulter les articles à apporter et à remettre selon le périmètre."),
    PermissionDefinition("creer_article_kit_a_remettre", "Créer un article à remettre", "kits", "Créer au niveau DGAS un article que le centre doit remettre aux immergés."),
    PermissionDefinition("creer_article_kit_a_apporter", "Créer un article à apporter", "kits", "Créer au niveau du centre un article que les immergés doivent apporter."),
    PermissionDefinition("modifier_article_kit", "Modifier un article de kit", "kits", "Modifier un article de kit dans le périmètre autorisé."),
    PermissionDefinition("desactiver_article_kit", "Désactiver un article de kit", "kits", "Désactiver un article sans supprimer son historique."),
    PermissionDefinition("reactiver_article_kit", "Réactiver un article de kit", "kits", "Réactiver un article de kit précédemment désactivé."),
    PermissionDefinition("supprimer_article_kit", "Supprimer un article de kit", "kits", "Supprimer logiquement un article de kit."),

    # Kits - remises
    PermissionDefinition("consulter_remises_kit", "Consulter les remises de kits", "kits", "Consulter les remises individuelles selon le périmètre."),
    PermissionDefinition("enregistrer_remise_kit", "Enregistrer une remise de kit", "kits", "Préparer, enregistrer ou valider la remise individuelle d'un kit."),
    PermissionDefinition("annuler_remise_kit", "Annuler une remise de kit", "kits", "Annuler logiquement une remise individuelle."),
    PermissionDefinition("consulter_statistiques_kits", "Consulter les statistiques de kits", "kits", "Consulter les statistiques de distribution des kits."),

    # Kits - opérations massives
    PermissionDefinition("preparer_remises_kit_masse", "Préparer les remises en masse", "kits", "Préparer avec Celery les lignes de remise pour plusieurs immergés."),
    PermissionDefinition("valider_remises_kit_masse", "Valider les remises en masse", "kits", "Valider avec Celery les remises de plusieurs immergés."),
    PermissionDefinition("annuler_remises_kit_masse", "Annuler les remises en masse", "kits", "Annuler logiquement un lot de remises avec Celery."),
    PermissionDefinition("consulter_progression_kits", "Consulter la progression des kits", "kits", "Consulter dans Redis la progression d'une opération massive de kits."),

    # Activités - catalogue
    PermissionDefinition("consulter_activites", "Consulter les activités", "activites", "Consulter le catalogue permanent des activités."),
    PermissionDefinition("creer_activite", "Créer une activité", "activites", "Créer une activité réutilisable dans le catalogue."),
    PermissionDefinition("modifier_activite", "Modifier une activité", "activites", "Modifier une activité du catalogue."),
    PermissionDefinition("desactiver_activite", "Désactiver une activité", "activites", "Désactiver, réactiver ou supprimer logiquement une activité."),

    # Activités - séances
    PermissionDefinition("consulter_seances", "Consulter les séances", "activites", "Consulter le planning des séances selon le périmètre autorisé."),
    PermissionDefinition("planifier_seance", "Planifier une séance", "activites", "Programmer une activité dans une session et un centre."),
    PermissionDefinition("modifier_seance", "Modifier une séance", "activites", "Modifier une séance encore modifiable."),
    PermissionDefinition("annuler_seance", "Annuler une séance", "activites", "Annuler une séance en conservant son historique."),
    PermissionDefinition("reporter_seance", "Reporter une séance", "activites", "Reporter une séance et créer sa nouvelle planification."),
    PermissionDefinition("affecter_formateur_seance", "Affecter un formateur", "activites", "Affecter ou remplacer le formateur d'une séance."),

    # Activités - présences
    PermissionDefinition("consulter_presences", "Consulter les présences", "activites", "Consulter les feuilles et les présences selon le périmètre."),
    PermissionDefinition("ouvrir_feuille_presence", "Ouvrir une feuille de présence", "activites", "Ouvrir et préparer une feuille de présence."),
    PermissionDefinition("saisir_presence", "Saisir une présence", "activites", "Saisir une présence individuelle ou en masse."),
    PermissionDefinition("modifier_presence", "Modifier une présence", "activites", "Corriger une présence sur une feuille ouverte."),
    PermissionDefinition("valider_presence", "Valider une feuille de présence", "activites", "Valider une feuille de présence complète."),
    PermissionDefinition("cloturer_feuille_presence", "Clôturer une feuille de présence", "activites", "Clôturer définitivement une feuille déjà validée."),
    PermissionDefinition("calculer_taux_presence", "Calculer le taux de présence", "activites", "Calculer le taux de présence utilisé pour l'attestation."),

    # Activités - évaluations
    PermissionDefinition("consulter_evaluations", "Consulter les évaluations", "activites", "Consulter les évaluations selon le périmètre autorisé."),
    PermissionDefinition("creer_evaluation", "Créer une évaluation", "activites", "Créer une évaluation en brouillon."),
    PermissionDefinition("modifier_evaluation", "Modifier une évaluation", "activites", "Modifier une évaluation encore en brouillon."),
    PermissionDefinition("ouvrir_saisie_notes", "Ouvrir la saisie des notes", "activites", "Ouvrir une évaluation pour la saisie des notes."),
    PermissionDefinition("cloturer_evaluation", "Clôturer une évaluation", "activites", "Clôturer une évaluation ouverte."),
    PermissionDefinition("annuler_evaluation", "Annuler une évaluation", "activites", "Annuler une évaluation non clôturée."),
    PermissionDefinition("consulter_resultats", "Consulter les résultats", "activites", "Consulter les notes et statistiques d'une évaluation."),
    PermissionDefinition("valider_resultats", "Valider les résultats", "activites", "Vérifier la complétude puis clôturer les résultats."),

    # Activités - notes
    PermissionDefinition("consulter_notes", "Consulter les notes", "activites", "Consulter les notes selon le périmètre autorisé."),
    PermissionDefinition("saisir_note", "Saisir une note", "activites", "Saisir une note individuelle ou en masse."),
    PermissionDefinition("modifier_note", "Modifier une note", "activites", "Corriger une note lorsque l'évaluation est ouverte."),
    PermissionDefinition("marquer_absence_note", "Marquer une absence à une évaluation", "activites", "Enregistrer l'absence d'un immergé à une évaluation."),
    PermissionDefinition("marquer_dispense_note", "Marquer une dispense d'évaluation", "activites", "Enregistrer une dispense médicale ou autorisée."),
    PermissionDefinition("annuler_note", "Annuler une note", "activites", "Annuler une note en conservant son historique."),
    PermissionDefinition("calculer_moyenne", "Calculer une moyenne", "activites", "Calculer la moyenne pondérée d'un immergé."),

    # Activités - opérations massives
    PermissionDefinition("consulter_progression_activites", "Consulter la progression des activités", "activites", "Consulter dans Redis la progression d'une opération massive."),

    # Repas - ravitaillement des centres
    PermissionDefinition("consulter_demandes_ravitaillement", "Consulter les demandes de ravitaillement", "repas", "Consulter les demandes et les denrées selon le périmètre autorisé."),
    PermissionDefinition("creer_demande_ravitaillement", "Créer une demande de ravitaillement", "repas", "Créer le dossier de besoins en denrées d'un centre."),
    PermissionDefinition("modifier_demande_ravitaillement", "Modifier une demande de ravitaillement", "repas", "Modifier le brouillon et ses lignes de denrées."),
    PermissionDefinition("soumettre_demande_ravitaillement", "Soumettre une demande de ravitaillement", "repas", "Soumettre les besoins du centre à la validation."),
    PermissionDefinition("valider_demande_ravitaillement", "Valider une demande de ravitaillement", "repas", "Valider les quantités demandées par un centre."),
    PermissionDefinition("enregistrer_reception_denrees", "Enregistrer la réception des denrées", "repas", "Saisir les quantités réellement reçues au centre."),
    PermissionDefinition("consolider_besoins_denrees", "Consolider les besoins en denrées", "repas", "Consolider par session ou région les demandes des centres."),

    # Repas - planification et préparation
    PermissionDefinition("consulter_repas", "Consulter les repas", "repas", "Consulter les repas journaliers selon le périmètre."),
    PermissionDefinition("planifier_repas", "Planifier un repas", "repas", "Créer et planifier un repas journalier du centre."),
    PermissionDefinition("modifier_repas", "Modifier un repas", "repas", "Modifier la planification ou renseigner la préparation réelle."),
    PermissionDefinition("annuler_repas", "Annuler un repas", "repas", "Annuler un repas non clôturé avec un motif."),
    PermissionDefinition("calculer_portions_repas", "Calculer les portions d'un repas", "repas", "Calculer l'effectif standard et les besoins alimentaires spéciaux."),
    PermissionDefinition("ouvrir_distribution_repas", "Ouvrir une distribution de repas", "repas", "Préparer les comptages puis ouvrir la distribution."),
    PermissionDefinition("cloturer_distribution_repas", "Clôturer une distribution de repas", "repas", "Contrôler la complétude et clôturer la distribution."),

    # Repas - comptage et suivi alimentaire
    PermissionDefinition("pointer_repas", "Pointer un repas", "repas", "Saisir le comptage ou le service d'un repas adapté."),
    PermissionDefinition("modifier_pointage_repas", "Modifier un pointage de repas", "repas", "Corriger un suivi tant que la distribution reste ouverte."),
    PermissionDefinition("marquer_repas_servi", "Marquer un repas servi", "repas", "Marquer le service d'un repas standard."),
    PermissionDefinition("marquer_repas_absent", "Marquer une absence au repas", "repas", "Marquer absent un immergé suivi pour un repas adapté."),
    PermissionDefinition("marquer_repas_refuse", "Marquer un repas refusé", "repas", "Enregistrer le refus d'un repas adapté."),
    PermissionDefinition("marquer_repas_dispense", "Marquer une dispense de repas", "repas", "Enregistrer une dispense opérationnelle lorsqu'elle est applicable."),
    PermissionDefinition("marquer_regime_special", "Marquer un régime spécial", "repas", "Confirmer la conformité ou la non-conformité du repas adapté."),
    PermissionDefinition("consulter_pointages_repas", "Consulter les suivis de repas", "repas", "Consulter les comptages et consignes alimentaires non confidentielles."),

    # Repas - rapports et opérations massives
    PermissionDefinition("generer_rapport_repas", "Générer un rapport de repas", "repas", "Préparer les indicateurs d'un rapport repas par périmètre et période."),
    PermissionDefinition("consulter_progression_repas", "Consulter la progression des repas", "repas", "Consulter dans Redis la progression d'une opération massive."),

    # Alertes et incidents
    PermissionDefinition("signaler_incident", "Signaler un incident", "incidents", "Signaler rapidement un incident dans son périmètre."),
    PermissionDefinition("modifier_incident", "Modifier un incident", "incidents", "Corriger un signalement manuel encore nouveau."),
    PermissionDefinition("prendre_en_charge_incident", "Prendre en charge un incident", "incidents", "Prendre en charge une alerte ou un incident ouvert."),
    PermissionDefinition("mettre_incident_en_attente", "Mettre un incident en attente", "incidents", "Mettre en attente un incident en cours avec un motif."),
    PermissionDefinition("resoudre_incident", "Résoudre un incident", "incidents", "Enregistrer la résolution d'un incident ouvert."),
    PermissionDefinition("cloturer_incident", "Clôturer un incident", "incidents", "Clôturer un incident déjà résolu."),
    PermissionDefinition("annuler_incident", "Annuler un incident", "incidents", "Annuler un signalement avec un motif."),
    PermissionDefinition("escalader_incident", "Escalader un incident", "incidents", "Augmenter le niveau d'urgence et le périmètre de traitement."),
    PermissionDefinition("consulter_incidents", "Consulter les incidents", "incidents", "Consulter les alertes et incidents selon le périmètre autorisé."),
    PermissionDefinition("generer_alerte_automatique", "Générer les alertes automatiques", "incidents", "Lancer ou superviser les scans automatiques d'intégrité."),

    # Notifications et e-mails (aucune table métier)
    PermissionDefinition("envoyer_email_test", "Envoyer un e-mail de test", "notifications", "Tester la configuration e-mail sur sa propre adresse."),
    PermissionDefinition("relancer_email_echoue", "Relancer un e-mail échoué", "notifications", "Relancer uniquement un envoi dont l'échec est tracé dans l'audit."),
    PermissionDefinition("consulter_statistiques_notifications", "Consulter les statistiques des e-mails", "notifications", "Consulter les succès et échecs d'envoi selon le périmètre autorisé."),

    # Audit et traçabilité
    PermissionDefinition("consulter_journaux_audit", "Consulter les journaux d'audit", "audit", "Consulter les actions selon le périmètre autorisé."),
    PermissionDefinition("consulter_statistiques_audit", "Consulter les statistiques d'audit", "audit", "Consulter les statistiques des acteurs, immergés, documents et du système."),
    PermissionDefinition("consulter_audit_securite", "Consulter les détails de sécurité de l'audit", "audit", "Consulter IP, user-agent, chemins techniques et identifiants de tâches."),
    PermissionDefinition("consulter_audit_acces_publics", "Consulter les accès publics audités", "audit", "Consulter les recherches, consultations et téléchargements des immergés."),
    PermissionDefinition("exporter_journaux_audit", "Exporter les journaux d'audit", "audit", "Générer et télécharger un export filtré des journaux autorisés."),
    PermissionDefinition("consulter_activite_acteur", "Consulter l'activité d'un acteur", "audit", "Consulter les actions d'un acteur selon le périmètre autorisé."),
    PermissionDefinition("consulter_activite_immerge", "Consulter l'activité d'un immergé", "audit", "Consulter les informations reçues et les consultations d'un immergé."),
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


PERMISSIONS_INCIDENTS_PAR_ROLE = {
    "ADMINISTRATEUR": {
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "cloturer_incident",
        "annuler_incident",
        "escalader_incident",
        "consulter_incidents",
        "generer_alerte_automatique",
    },
    "DGAS": {
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "cloturer_incident",
        "annuler_incident",
        "escalader_incident",
        "consulter_incidents",
        "generer_alerte_automatique",
    },
    "DIRECTEUR_REGIONAL": {
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "cloturer_incident",
        "annuler_incident",
        "escalader_incident",
        "consulter_incidents",
    },
    "RESPONSABLE_CENTRE": {
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "cloturer_incident",
        "annuler_incident",
        "escalader_incident",
        "consulter_incidents",
    },
    "FORMATEUR": {
        "signaler_incident",
        "modifier_incident",
        "consulter_incidents",
    },
    "AGENT_SANTE": {
        "signaler_incident",
        "modifier_incident",
        "prendre_en_charge_incident",
        "mettre_incident_en_attente",
        "resoudre_incident",
        "consulter_incidents",
    },
}


PERMISSIONS_NOTIFICATIONS_PAR_ROLE = {
    "ADMINISTRATEUR": {
        "envoyer_email_test",
        "relancer_email_echoue",
        "consulter_statistiques_notifications",
    },
    "DGAS": {
        "relancer_email_echoue",
        "consulter_statistiques_notifications",
    },
    "DIRECTEUR_REGIONAL": {
        "relancer_email_echoue",
        "consulter_statistiques_notifications",
    },
    "RESPONSABLE_CENTRE": {
        "consulter_statistiques_notifications",
    },
}


PERMISSIONS_AUDIT_PAR_ROLE = {
    "ADMINISTRATEUR": {
        "consulter_journaux_audit",
        "consulter_statistiques_audit",
        "consulter_audit_securite",
        "consulter_audit_acces_publics",
        "exporter_journaux_audit",
        "consulter_activite_acteur",
        "consulter_activite_immerge",
    },
    "DGAS": {
        "consulter_journaux_audit",
        "consulter_statistiques_audit",
        "consulter_audit_securite",
        "consulter_audit_acces_publics",
        "exporter_journaux_audit",
        "consulter_activite_acteur",
        "consulter_activite_immerge",
    },
    "DIRECTEUR_REGIONAL": {
        "consulter_journaux_audit",
        "consulter_statistiques_audit",
        "consulter_audit_acces_publics",
        "exporter_journaux_audit",
        "consulter_activite_acteur",
        "consulter_activite_immerge",
    },
    "RESPONSABLE_CENTRE": {
        "consulter_journaux_audit",
        "consulter_statistiques_audit",
        "consulter_audit_acces_publics",
        "exporter_journaux_audit",
        "consulter_activite_immerge",
    },
}


class Command(BaseCommand):
    help = "Initialise les permissions, les rôles de base et les droits incidents/audit/notifications FasoIM."

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
        associations_incidents_creees = 0
        associations_incidents_mises_a_jour = 0
        associations_audit_creees = 0
        associations_audit_mises_a_jour = 0
        associations_notifications_creees = 0
        associations_notifications_mises_a_jour = 0

        permission_obsolete = Permission.objects.filter(
            code="creer_alerte",
            deleted_at__isnull=True,
        ).first()
        if permission_obsolete:
            permission_obsolete.code = (
                f"creer_alerte__obsolete__{permission_obsolete.id}"
            )[:120]
            permission_obsolete.statut = Permission.Statut.INACTIVE
            permission_obsolete.deleted_at = timezone.now()
            permission_obsolete.save(
                update_fields=["code", "statut", "deleted_at", "updated_at"]
            )

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

        for code_role, codes_permissions in PERMISSIONS_INCIDENTS_PAR_ROLE.items():
            role = Role.objects.get(code=code_role, deleted_at__isnull=True)
            permissions = Permission.objects.filter(
                code__in=codes_permissions,
                module="incidents",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            for permission in permissions:
                _, created = RolePermission.objects.update_or_create(
                    role=role,
                    permission=permission,
                    deleted_at__isnull=True,
                    defaults={
                        "est_delegable": False,
                        "perimetre_delegation_max": role.perimetre_autorise,
                        "statut": RolePermission.Statut.ACTIVE,
                        "deleted_at": None,
                    },
                )
                if created:
                    associations_incidents_creees += 1
                else:
                    associations_incidents_mises_a_jour += 1

        for code_role, codes_permissions in PERMISSIONS_NOTIFICATIONS_PAR_ROLE.items():
            role = Role.objects.get(code=code_role, deleted_at__isnull=True)
            permissions = Permission.objects.filter(
                code__in=codes_permissions,
                module="notifications",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            for permission in permissions:
                _, created = RolePermission.objects.update_or_create(
                    role=role,
                    permission=permission,
                    deleted_at__isnull=True,
                    defaults={
                        "est_delegable": False,
                        "perimetre_delegation_max": role.perimetre_autorise,
                        "statut": RolePermission.Statut.ACTIVE,
                        "deleted_at": None,
                    },
                )
                if created:
                    associations_notifications_creees += 1
                else:
                    associations_notifications_mises_a_jour += 1

        for code_role, codes_permissions in PERMISSIONS_AUDIT_PAR_ROLE.items():
            role = Role.objects.get(code=code_role, deleted_at__isnull=True)
            permissions = Permission.objects.filter(
                code__in=codes_permissions,
                module="audit",
                statut=Permission.Statut.ACTIVE,
                deleted_at__isnull=True,
            )
            for permission in permissions:
                _, created = RolePermission.objects.update_or_create(
                    role=role,
                    permission=permission,
                    deleted_at__isnull=True,
                    defaults={
                        "est_delegable": False,
                        "perimetre_delegation_max": role.perimetre_autorise,
                        "statut": RolePermission.Statut.ACTIVE,
                        "deleted_at": None,
                    },
                )
                if created:
                    associations_audit_creees += 1
                else:
                    associations_audit_mises_a_jour += 1

        self.stdout.write(self.style.SUCCESS("Initialisation accounts terminée."))
        self.stdout.write(f"Permissions créées : {permissions_creees}")
        self.stdout.write(f"Permissions mises à jour : {permissions_mises_a_jour}")
        self.stdout.write(f"Rôles créés : {roles_crees}")
        self.stdout.write(f"Rôles mis à jour : {roles_mis_a_jour}")
        self.stdout.write(
            f"Associations incidents créées : {associations_incidents_creees}"
        )
        self.stdout.write(
            "Associations incidents mises à jour : "
            f"{associations_incidents_mises_a_jour}"
        )
        self.stdout.write(
            f"Associations audit créées : {associations_audit_creees}"
        )
        self.stdout.write(
            "Associations audit mises à jour : "
            f"{associations_audit_mises_a_jour}"
        )
        self.stdout.write(
            f"Associations notifications créées : {associations_notifications_creees}"
        )
        self.stdout.write(
            "Associations notifications mises à jour : "
            f"{associations_notifications_mises_a_jour}"
        )
