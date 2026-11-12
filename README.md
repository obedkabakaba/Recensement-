# Decensio : tableau de bord

**Chaque personne, une seule fois.**

Ce dépôt **public** contient le tableau de bord de Decensio, le module de couverture et de contrôle qualité pour le recensement et l'identification de la population. Le moteur et l'API sont dans le dépôt privé `Recensement-backend`.

**Démonstration en ligne** : https://obedkabakaba.github.io/Recensement-/
Les données affichées sont **entièrement fictives** (une commune inventée placée sur N'djili), et la démonstration est en consultation seule.

## Ce que montre le tableau de bord

- **Carte** : couverture par zone. ✓ vert : couverture atteinte. ◐ orange : en cours. ✕ rouge : sous-couverture. ▲ violet : surcouverture. La liste des zones prioritaires est classée selon le nombre de personnes manquantes.
- **Zones** : la même information sous forme de tableau triable.
- **Doublons** : les fiches côte à côte, avec le détail du score, et les ménages visités deux fois.
- **Saisies suspectes** : GPS, rythme de saisie, points empilés, âges arrondis…
- **Agents** : volume de travail, anomalies et doublons, agent par agent.
- **Import** : visible seulement avec un serveur. Envoi des fichiers et recalcul.

## Fonctionnement

Le site est entièrement statique : HTML, CSS, JavaScript et la carte Leaflet, intégrée au dépôt pour fonctionner avec une connexion faible. Il ne demande aucune compilation.

| Mode | Réglage dans `static/config.js` | Usage |
|---|---|---|
| Démonstration | `statique: true` | lit les fichiers JSON de `donnees/`, sans serveur (GitHub Pages) |
| Connecté | `statique: false, api: "https://…"` | appelle le serveur Decensio : imports, décisions, synchronisation |

Pour essayer en local avec un serveur Decensio, sans modifier la configuration :

```bash
python -m http.server 8080
# puis ouvrir http://localhost:8080/?api=http://127.0.0.1:8000
```

## Mettre à jour la démonstration

Depuis le dépôt du serveur, avec des **données fictives uniquement** :

```bash
decensio exporter-demo ../Recensement-/donnees
```

Il suffit ensuite d'enregistrer (commit) les fichiers et de les envoyer sur `main` : GitHub Actions republie le site (`.github/workflows/pages.yml`).

## Protection des données

Ce dépôt et son site sont **publics**. Il ne doit **jamais** contenir de données réelles. Les données des personnes ne vivent que dans la base du serveur, protégée par une clé d'accès et un journal d'audit.

© 2026 Decensio. Tous droits réservés. Leaflet © Volodymyr Agafonkin et contributeurs (licence BSD-2, `static/vendor/leaflet/LICENSE`). Fonds de carte © contributeurs OpenStreetMap.
