# Backend — API FastAPI

API du centre de langues La Digithèque. Le MVP implémente **tout le contrat attendu par le frontend**
([`docs/api/contrat-frontend.md`](../docs/api/contrat-frontend.md)) : le frontend fonctionne sur ce backend avec
`NEXT_PUBLIC_API_MOCK=false`, sans données simulées.

| Pile       | Choix                                                       |
| ---------- | ----------------------------------------------------------- |
| Framework  | FastAPI, Python 3.11                                        |
| Base       | PostgreSQL 16, SQLAlchemy 2, migrations Alembic             |
| Validation | Pydantic 2 (mêmes règles de saisie que le frontend)         |
| Sécurité   | JWT HS256 (`python-jose`), mots de passe hachés avec bcrypt |
| Tests      | pytest + httpx, sur une vraie base PostgreSQL de test       |

## Démarrer

Depuis la racine du dépôt (voir le [README principal](../README.md#étapes-docker)) :

```bash
make dev        # stack de développement, rechargement à chaud
make test       # tests du backend
```

Au démarrage, le conteneur applique les migrations (`alembic upgrade head`) puis charge les données de départ
(`python -m app.seed`). Swagger : <http://localhost:8000/docs>.

### Comptes de démonstration

Créés si `SEED_DEMO=true` (valeur par défaut en local, **à mettre à `false` en production**) :

| Rôle           | E-mail                    | Mot de passe |
| -------------- | ------------------------- | ------------ |
| Apprenant      | `apprenant@digitheque.mg` | `Demo2026`   |
| Formateur      | `formateur@digitheque.mg` | `Demo2026`   |
| Administrateur | `admin@digitheque.mg`     | `Demo2026`   |

Le référentiel est toujours chargé, sans doublon : 5 langues, niveaux CECRL (A1–C2) et HSK (HSK 1–6) ouverts par
langue, formules Simple, Luxe et Premium (mêmes valeurs que les données simulées du frontend).

## Routes

Toutes sous `/api/v1`. Le détail des requêtes, réponses et erreurs est dans le contrat.

| Domaine            | Routes                                                                                | Accès          |
| ------------------ | ------------------------------------------------------------------------------------- | -------------- |
| Authentification   | `POST /auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password` | public         |
| Formules           | `GET /formules`                                                                       | public         |
| Profil             | `GET` / `PATCH /users/me`, `POST` / `DELETE /users/me/photo`                          | connecté       |
| Utilisateurs       | `GET /users`, `PATCH /users/{id_user}`                                                | administrateur |
| Tableau de bord    | `GET /admin/statistiques`, `GET /admin/statistiques/inscriptions`                     | administrateur |
| Langues et niveaux | `GET` / `POST /langues`, `PATCH` / `DELETE /langues/{id}`, idem `/niveaux`            | administrateur |

Hors préfixe : `GET /health` (supervision) et `GET /media/photos/…` (photos de profil, lecture publique).

## Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── deps.py          # session, utilisateur connecté (JWT), accès administrateur, pagination
│   │   ├── router.py        # préfixe /api/v1
│   │   └── routes/          # une route par domaine du contrat
│   ├── core/                # configuration (.env), base de données, sécurité (bcrypt, JWT)
│   ├── models/              # tables, d'après le diagramme de classes
│   ├── schemas/             # entrées / sorties de l'API ; regles.py = règles de saisie du frontend
│   ├── services/            # e-mail, photos, recherche sans accents
│   ├── seed.py              # données de départ
│   └── main.py
├── alembic/versions/        # migrations
├── tests/
├── docker-entrypoint.sh     # migrations + données de départ, puis uvicorn
├── requirements.txt         # exécution
└── requirements-dev.txt     # tests
```

## Choix à connaître

- **Rôles et statuts en entiers** (SMALLINT), exposés en texte par l'API. Les codes sont dans
  `app/models/enums.py` : ne jamais en changer un, seulement en ajouter.
- **Spécialisations** : `apprenant`, `formateur` et `administrateur` ont chacune leur table, liée à `utilisateur`
  par `id_user`. Un changement de rôle crée la ligne du nouveau rôle et conserve les anciennes.
- **Suppression d'une langue ou d'un niveau** : refusée (409) dès qu'un objet l'utilise, grâce aux clés étrangères
  `ON DELETE RESTRICT` ; les lignes `LangueNiveau` partent en cascade.
- **Mot de passe oublié** : le lien contient un JWT signé, valable 60 minutes et utilisable une seule fois (il dépend
  du mot de passe actuel). Sans SMTP configuré, l'e-mail est écrit dans les journaux du conteneur
  (`docker compose logs backend`).
- **Session révoquée** : un compte désactivé reçoit 401 sur les routes protégées, même avec un JWT encore valide.
- **Statistiques par jour** calculées dans le fuseau `TIMEZONE` (Madagascar par défaut).

## Ajouter une table

1. Créer ou modifier le modèle dans `app/models/` (et l'importer dans `app/models/__init__.py`).
2. `make migration m="description"`, relire le fichier créé dans `alembic/versions/`.
3. Au prochain démarrage, la migration est appliquée automatiquement.

## Pas encore dans le MVP

Ateliers et réservations (seule la table `atelier` existe, pour le tableau de bord), parcours, tests diagnostiques,
facturation et paiements, gestion des formateurs, cache Redis, révocation des jetons à la déconnexion.
