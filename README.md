# Decensio

**Chaque personne, une seule fois.**

Decensio est un module de **couverture et de contrôle qualité** pour le recensement et l'identification de la population. Il ne remplace pas les outils de collecte (CSPro/CSEntry, Kobo, logiciels d'enrôlement) ni les systèmes biométriques : il se branche à côté et répond à trois questions.

1. **Où n'a-t-on pas encore compté tout le monde ?** Zone par zone, il compare la population attendue (grilles GRID3/WorldPop, puis résultats du RGPH-2) aux personnes déjà enregistrées. Les zones en retard passent en **rouge**, les zones en cours en **orange**, les zones couvertes en **vert**.
2. **Qui a été compté deux fois ?** À chaque synchronisation, il repère les doublons en comparant les noms (avec les variantes d'orthographe courantes en RDC), les dates de naissance, le lieu, le lien de parenté et, s'il existe, le numéro d'identification national (NIN).
3. **Quelles saisies sont suspectes ?** Il signale par exemple un GPS absent, un ménage hors de sa zone, des ménages saisis trop vite ou depuis un seul point, ou des âges arrondis.

![Logo](decensio/web/static/logo.svg)

## Démarrage rapide

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Essai avec des données fictives (aucune donnée réelle)
decensio donnees-test donnees/essai
decensio zones donnees/essai/zones.geojson
decensio population donnees/essai/population.tif --source "GRID3 (test)"
decensio importer donnees/essai/enregistrements.csv --source test
decensio couverture
decensio serveur          # tableau de bord : http://127.0.0.1:8000
```

## Avec les vraies données

| Étape | Commande | Données |
|---|---|---|
| 1. Limites des zones | `decensio zones quartiers.geojson --niveau quartier` | GeoJSON des quartiers, aires ou zones de santé (WGS 84). Un Shapefile se convertit avec QGIS ou mapshaper.org. |
| 2. Population attendue | `decensio population grid3_kinshasa.tif --source "GRID3 v4.4" --date 2025-12` | Grille GRID3 ou WorldPop (GeoTIFF). |
| 2 bis. Autres estimations | `decensio estimations rgph2.csv --source RGPH-2` | CSV `code_zone ; population` (RGPH-2, projections INS). Si plusieurs sources existent pour une zone, l'ordre de préférence est RGPH, puis INS, puis GRID3. |
| 3. Enregistrements | `decensio importer export.csv --source cspro` | CSV à une ligne par personne, ou JSON. Voir [docs/formats.md](docs/formats.md). |
| 4. Calcul | `decensio recalculer` | Doublons, puis saisies suspectes, puis couverture. |

Les tablettes peuvent aussi envoyer leurs ménages directement à `POST /api/sync`. La réponse contient tout de suite les **alertes de doublon**, ce qui permet à l'agent de vérifier sur place.

## Tableau de bord

- **Carte** : couverture par zone (vert, orange, rouge, violet pour la surcouverture) et liste des zones prioritaires, classées selon le nombre de personnes manquantes.
- **Zones** : la même information sous forme de tableau triable.
- **Doublons** : les deux fiches côte à côte, avec le détail du score. Un vérificateur tranche : « même personne » ou « deux personnes différentes ».
- **Saisies suspectes** : chaque anomalie peut être marquée « justifiée » ou « corrigée ».
- **Agents** : volume de travail, anomalies et doublons, agent par agent.
- **Import** : envoi des fichiers et lancement du recalcul.

## Protection des données

Le cadre légal congolais est encore incomplet. Decensio applique donc par défaut des règles strictes, détaillées dans [docs/protection-des-donnees.md](docs/protection-des-donnees.md) :

- **les noms ne sont pas conservés en clair** (`DECENSIO_STOCKER_NOMS=0`) : seules des clés phonétiques et des empreintes chiffrées (HMAC) sont gardées ;
- **le NIN n'est jamais stocké** : seule son empreinte l'est ;
- toute écriture exige une **clé d'API** et laisse une trace dans un **journal d'audit** (qui, quoi, quand) ;
- la biométrie n'est **pas** traitée : elle reste chez les fournisseurs certifiés.

## Déploiement

- **Base de données** : PostgreSQL. Supabase convient : il suffit de renseigner `DECENSIO_DATABASE_URL`. Les tables se créent au premier démarrage. SQLite suffit pour les essais.
- **Serveur** : Render, avec le fichier `render.yaml` fourni (Blueprint), ou toute plateforme acceptant Docker (`Dockerfile`).
- **Paramètres** : voir `.env.example` (seuils de couverture, secret de pseudonymisation, clé d'API, fuseau horaire).

## Documentation

- [docs/fonctionnement.md](docs/fonctionnement.md) : comment sont calculés la couverture, les doublons et les anomalies.
- [docs/formats.md](docs/formats.md) : formats d'entrée et API.
- [docs/protection-des-donnees.md](docs/protection-des-donnees.md) : mesures de protection.

## Tests

```bash
pytest
```

Les tests de bout en bout génèrent une commune fictive avec des doublons et des fraudes injectés, puis vérifient que Decensio les retrouve.

## Licence

© 2026 Decensio. Tous droits réservés. Le choix d'une licence (éventuellement open source) reste à faire.
