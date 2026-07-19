# FasoIM

Backend de gestion des sessions d’immersion patriotique au Burkina Faso.

FasoIM centralise le parcours d’un immergé depuis son import ou son inscription volontaire jusqu’à son affectation, son organisation en section et groupe, puis son suivi pendant la session : santé, activités, repas, kits, incidents, notifications, audit et production de documents.

## État du projet

- Version stable actuelle : `v1.3-documents-stable`
- Commit de référence : `dab4b58`
- Dernière validation globale : **363 tests réussis sur 363**
- API REST documentée avec Swagger et ReDoc
- Authentification JWT et contrôle d’accès par rôles, permissions et périmètres
- Traitements asynchrones avec Celery et Redis

> Les résultats ci-dessus correspondent au dernier état stable validé avec PostgreSQL et Redis disponibles.

## Fonctionnalités principales

| Application | Responsabilité |
| --- | --- |
| `accounts` | Acteurs, authentification, rôles, permissions, affectations et délégations |
| `sessions_app` | Sessions d’immersion et paramètres d’activation des modules |
| `imports_app` | Import contrôlé des listes officielles, normalisation et rapports d’erreurs |
| `immerges` | Dossier central des immergés, origine, code FasoIM et QR code |
| `affectations` | Affectations régionales et affectations dans les centres |
| `organisation` | Règles locales, sections, groupes, dortoirs et lits |
| `sante` | Visites médicales, restrictions et impacts opérationnels |
| `kits` | Articles, remises, contrôles et opérations sur les kits |
| `activites` | Activités, séances, présences, évaluations et notes |
| `repas` | Planification des repas, menus, portions, distributions et pointages |
| `incidents` | Signalement, qualification, prise en charge, résolution et clôture des incidents |
| `audit` | Traçabilité des actions sensibles et des changements métier |
| `notifications` | Notifications applicatives et traitements de diffusion |
| `documents` | Génération, suivi, vérification et publication des documents |

## Parcours métier simplifié

```text
Liste officielle ou inscription volontaire
                    │
                    ▼
          Validation et normalisation
                    │
                    ▼
              Dossier Immergé
       (type d’origine + identifiant d’origine)
                    │
                    ▼
          Code FasoIM et QR code
                    │
                    ▼
       Région → Centre → Section → Groupe
                    │
                    ▼
 Santé · Kits · Activités · Repas · Incidents
                    │
                    ▼
       Audit · Notifications · Documents
```

La classe centrale `Immerge` ne duplique pas toutes les données provenant des concours, examens, sélections ou inscriptions volontaires. L’origine reste identifiable par le couple `type_immerge` et `origine_id`.

## Architecture du backend

Le projet utilise une architecture Django modulaire. Selon les besoins d’une application, on retrouve notamment :

```text
application/
├── models.py          # Entités et contraintes de persistance
├── repository.py      # Requêtes et accès aux données
├── service.py         # Règles métier et transactions
├── serializers.py     # Validation et représentation de l’API
├── views.py           # Points d’entrée HTTP
├── urls.py            # Routes de l’application
├── permissions.py     # Permissions propres au domaine
├── signals.py         # Réactions aux événements Django
├── tasks.py           # Tâches asynchrones Celery
├── admin.py           # Administration Django
├── migrations/       # Évolution du schéma de données
└── tests.py           # Tests automatisés
```

Les vues et sérialiseurs restent centrés sur l’interface HTTP. Les règles métier importantes sont placées dans les services, tandis que les accès aux données complexes sont isolés dans les repositories.

## Technologies utilisées

- Python 3.12
- Django 5.2
- Django REST Framework
- PostgreSQL
- Redis
- Celery
- JWT avec `djangorestframework-simplejwt`
- Documentation OpenAPI avec `drf-spectacular`
- `django-redis`
- `openpyxl` pour les fichiers tableurs
- Pillow pour les traitements d’images
- `python-decouple` pour la configuration

## Prérequis

Avant l’installation, vérifier la présence de :

- Python 3.12 ou une version compatible avec les dépendances du projet ;
- PostgreSQL ;
- Redis ;
- `python3-venv` et `pip` ;
- Git.

Sous Ubuntu, Python est généralement accessible par la commande `python3`. Une fois l’environnement virtuel activé, la commande à utiliser est `python`.

## Installation locale

### 1. Récupérer le projet

```bash
git clone <URL_DU_DEPOT>
cd fasoim/backend
```

Remplacer `<URL_DU_DEPOT>` par l’adresse réelle du dépôt Git.

### 2. Créer l’environnement virtuel

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Le préfixe `(venv)` doit apparaître dans le terminal après l’activation.

### 3. Préparer PostgreSQL

Exemple de création d’une base et d’un utilisateur :

```sql
CREATE DATABASE fasoim;
CREATE USER fasoim WITH PASSWORD 'mot_de_passe_a_modifier';
GRANT ALL PRIVILEGES ON DATABASE fasoim TO fasoim;
```

PostgreSQL est recommandé pour le développement et requis pour reproduire fidèlement l’exécution complète des tests, notamment les recherches spécifiques dans les champs JSON.

### 4. Configurer les variables d’environnement

Créer un fichier `.env` dans le dossier `backend` :

```dotenv
SECRET_KEY=remplacer-par-une-cle-secrete-longue
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

DB_ENGINE=postgresql
DB_NAME=fasoim
DB_USER=fasoim
DB_PASSWORD=mot_de_passe_a_modifier
DB_HOST=127.0.0.1
DB_PORT=5432

REDIS_CACHE_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

Ne jamais versionner un fichier `.env` contenant des secrets réels.

### 5. Initialiser la base de données

```bash
python manage.py migrate
python manage.py seed_accounts
python manage.py createsuperuser
```

La commande `seed_accounts` initialise notamment le catalogue des permissions et les rôles prévus par le projet. Elle peut être relancée après l’ajout d’un module ou de nouvelles permissions.

## Démarrage du projet

Les services suivants doivent être lancés dans des terminaux séparés.

### Redis

```bash
redis-server
```

### Worker Celery

```bash
cd fasoim/backend
source venv/bin/activate
celery -A config worker -l info
```

### Serveur Django

```bash
cd fasoim/backend
source venv/bin/activate
python manage.py runserver
```

Le serveur est alors disponible à l’adresse <http://127.0.0.1:8000/>.

## Accès à l’API

| Adresse | Usage |
| --- | --- |
| `/` | Vérification de l’état de l’API |
| `/admin/` | Interface d’administration Django |
| `/api/auth/token/` | Obtention d’un couple de jetons JWT |
| `/api/auth/token/refresh/` | Renouvellement du jeton d’accès |
| `/api/schema/` | Schéma OpenAPI |
| `/api/docs/` | Documentation Swagger |
| `/api/redoc/` | Documentation ReDoc |

Les principaux domaines de l’API sont exposés sous `/api/` : comptes, sessions, imports, immergés, affectations, organisation, santé, kits, activités, repas, incidents, audit, notifications et documents.

Swagger constitue la référence pour connaître les routes, paramètres, filtres et corps de requête exactement disponibles dans la version exécutée.

### Exemple d’authentification

```bash
curl -X POST http://127.0.0.1:8000/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"utilisateur@example.com","password":"mot_de_passe"}'
```

Utiliser ensuite le jeton d’accès :

```bash
curl http://127.0.0.1:8000/api/sessions/ \
  -H "Authorization: Bearer <JETON_D_ACCES>"
```

## Contrôle d’accès et sécurité

- Le modèle utilisateur du projet est `accounts.Acteur`.
- L’authentification de l’API utilise des jetons JWT.
- Les droits sont construits à partir des rôles, permissions, affectations et délégations.
- Le périmètre d’un acteur peut être national, régional, lié à un centre ou à une session.
- Chaque application déclare les permissions propres à son domaine.
- Le contrôle central reste assuré par le service d’accès du module `accounts`.
- Les vérifications de permissions sont synchrones : elles ne sont jamais différées dans une tâche Celery.
- Les actions sensibles sont destinées à être tracées dans le module `audit`.

Les règles d’accès ne doivent pas être reproduites directement dans chaque vue. Toute nouvelle opération métier doit être reliée au catalogue de permissions puis initialisée avec `seed_accounts`.

## Interaction entre santé et repas

Le module `sante` conserve les informations médicales et détermine les restrictions applicables à un immergé. Le module `repas` ne doit pas recopier un diagnostic ni exposer des données médicales confidentielles.

L’interaction se limite aux conséquences opérationnelles nécessaires, par exemple :

- repas ou aliments interdits ;
- adaptation d’une portion ou d’un menu ;
- autorisation ou dispense de distribution ;
- période de validité de la restriction.

Cette séparation permet au service de restauration d’appliquer une consigne sans accéder au dossier médical détaillé.

## Tâches asynchrones et Redis

Celery est utilisé pour les traitements qui ne doivent pas bloquer une requête HTTP, notamment certaines opérations longues, notifications ou productions de documents. Redis sert de broker Celery, de backend de résultats, de cache et, dans certains traitements, de support aux mécanismes de verrouillage.

Une panne de Redis peut donc provoquer l’échec de tâches ou de tests qui vérifient ces mécanismes. Avant de diagnostiquer une erreur Celery ou un test de concurrence, vérifier d’abord que Redis répond.

## Vérification et tests

### Vérifications de base

```bash
cd fasoim/backend
source venv/bin/activate

python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py seed_accounts
python manage.py check
```

### Exécuter toute la suite

```bash
python manage.py test
```

Dernier résultat stable connu :

```text
Ran 363 tests
OK
```

### Exécuter un module précis

```bash
python manage.py test repas
python manage.py test incidents
python manage.py test audit
python manage.py test notifications
python manage.py test documents
```

Pour obtenir un résultat comparable à la validation globale, utiliser PostgreSQL et laisser Redis actif pendant les tests.

## Workflow des patches

Les patches reçus sont conservés dans `backend/patches` avant toute vérification. Pour le moment, ils ne sont pas inclus dans les commits Git.

```bash
cd ~/Documents/fasoim/backend
source venv/bin/activate

git status --short
git apply --check patches/<nom_du_patch>.patch
git apply patches/<nom_du_patch>.patch

python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py seed_accounts
python manage.py check
python manage.py test

git status --short
```

Règles à respecter :

1. Ne jamais appliquer un patch avant la réussite de `git apply --check`.
2. Lire les chemins et les fichiers touchés par le patch avant de l’appliquer.
3. Ne pas utiliser automatiquement `-p0` ou une autre option de réécriture de chemin ; inspecter d’abord le format du patch.
4. Vérifier l’absence de dossiers dupliqués ou imbriqués par erreur.
5. Exécuter les migrations, l’initialisation des permissions et les tests après application.
6. Ne valider dans Git que les fichiers métier voulus, sans ajouter les patches tant que cette règle reste en vigueur.
7. Créer un commit et un tag stable uniquement après la validation globale.

## Workflow Git recommandé

```bash
git status --short
git diff --check
python manage.py test

git add <fichiers_valides>
git commit -m "Description du module ou de la correction"
git tag -a <version> -m "Description de la version stable"
```

Avant un nouveau module, le dépôt doit revenir à un état connu et stable. Éviter les commandes destructrices lorsque des modifications locales ne sont pas encore sauvegardées.

## Jalons stables

| Tag | Contenu principal | Référence connue |
| --- | --- | --- |
| `v0.8-activites-stable` | Module activités stabilisé | — |
| `v0.9-repas-stable` | Module repas complet | `af705ae` |
| `v1.0-incidents-stable` | Application incidents | — |
| `v1.0.1-incidents-hardening-stable` | Durcissement du module incidents | — |
| `v1.1-audit-stable` | Traçabilité et audit | — |
| `v1.2-notifications-stable` | Notifications | — |
| `v1.3-documents-stable` | Génération et gestion des documents | `dab4b58` |

## Dépannage courant

### `python` n’est pas trouvé

Créer l’environnement avec `python3`, puis l’activer :

```bash
python3 -m venv venv
source venv/bin/activate
python --version
```

### Échec de connexion PostgreSQL

- vérifier que PostgreSQL est démarré ;
- contrôler `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` et `DB_PORT` ;
- vérifier que l’utilisateur possède les droits sur la base.

### Échec Redis ou Celery

```bash
redis-cli ping
```

La réponse attendue est `PONG`. Redémarrer ensuite le worker Celery si nécessaire.

### Des migrations sont détectées pendant le contrôle

Ne pas générer automatiquement une migration sans comprendre l’écart. Vérifier d’abord les modèles modifiés et l’historique des migrations de l’application concernée.

### Les permissions d’un nouveau module sont absentes

```bash
python manage.py seed_accounts
```

Puis vérifier les associations entre rôles et permissions prévues pour ce module.

## Principes de contribution

- Respecter la séparation entre vues, services et repositories.
- Ajouter des tests pour toute nouvelle règle métier ou correction de régression.
- Protéger chaque action sensible par une permission explicite.
- Utiliser des transactions pour les opérations qui modifient plusieurs objets liés.
- Ne pas dupliquer les données confidentielles d’un autre domaine.
- Préserver la suppression logique lorsqu’elle est prévue par le modèle.
- Documenter les nouvelles routes dans le schéma OpenAPI.
- Vérifier le projet complet avant la création d’un nouveau tag stable.

---

Ce README décrit l’état stable du backend FasoIM jusqu’au module `documents`. Il doit être mis à jour après chaque nouveau jalon validé.
