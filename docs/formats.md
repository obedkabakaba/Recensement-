# Formats d'entrée et API

## Enregistrements en CSV (une ligne par personne)

Le séparateur (`,` ou `;`) est détecté tout seul, tout comme les décimales à virgule. Les colonnes du ménage sont répétées sur chaque ligne.

| Champ | Noms de colonne reconnus | Exemple |
|---|---|---|
| Identifiant du ménage (**obligatoire**) | `menage_id`, `id_menage`, `household_id`, `hh_id` | `TAB07-000123` |
| Agent | `agent_id`, `enqueteur`, `interviewer_id` | `AG012` |
| Appareil | `appareil_id`, `tablette`, `device_id` | `TAB07` |
| Date et heure | `date_collecte`, `date_heure`, `timestamp`, `start` | `2026-12-15 10:42` ou `15/12/2026 10:42` |
| Latitude / longitude | `latitude`, `lat`, `gps_latitude` / `longitude`, `lon`, `gps_longitude` | `-4.4012` |
| Précision GPS (m) | `precision_gps`, `accuracy` | `6` |
| Zone assignée | `zone_assignee`, `code_zone`, `zd`, `aire_denombrement` | `NDJ-Q07` |
| Taille déclarée | `taille_menage`, `nb_membres`, `household_size` | `5` |
| Rang dans le ménage | `rang`, `ligne`, `line_number` | `1` |
| Nom, postnom, prénom | `nom`, `postnom`, `prenom` (ou `last_name`, `middle_name`, `first_name`) | `Tshibangu` |
| Sexe | `sexe`, `sex` : `M`/`F`, `H`/`F`, `1`/`2` | `M` |
| Date de naissance | `date_naissance`, `dob` | `1985-03-12` ou `12/03/1985` |
| Âge | `age` | `41` |
| Lien avec le chef | `lien`, `lien_parente`, `relationship` : `1`=chef, `2`=conjoint, `3`=enfant… | `chef` |
| NIN | `nin`, `numero_identification` | (jamais stocké en clair) |

Une heure sans fuseau est lue comme une **heure locale** : UTC+1 à Kinshasa, ou ce que fixe `DECENSIO_DECALAGE_HORAIRE`. Par exemple UTC+2 pour Lubumbashi ou Goma.

Si les colonnes portent d'autres noms (dictionnaire CSPro particulier, par exemple), fournissez une correspondance :

```bash
decensio importer export.csv --colonnes exemples/colonnes-cspro.json
```

Un ménage déjà connu (même identifiant) est **mis à jour**, pas dupliqué. On peut donc réimporter un export complet sans risque.

## Synchronisation (JSON)

`POST /api/sync` avec l'en-tête `X-Cle-API`. Voir [exemples/sync.json](../exemples/sync.json).

La réponse contient `alertes_doublons`. Pour chaque personne du lot qui ressemble à une personne déjà enregistrée, on y trouve le ménage concerné, le score et le détail des critères. L'application de l'agent peut alors afficher : « Cette personne semble déjà recensée dans le ménage TAB03-000045. Vérifiez avant de continuer. »

## Zones

GeoJSON (`FeatureCollection`) en WGS 84. Propriétés lues automatiquement :

- code : `code`, `pcode`, `id`, `adm3_pcode`… ;
- nom : `nom`, `name`, `adm3_fr`… ;
- parent : `code_parent`, `parent` ;
- `niveau` (facultatif).

Sinon, précisez `--champ-code`, `--champ-nom`, `--champ-parent`.

## API (extrait)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/resume` | indicateurs clés |
| GET | `/api/couverture?niveau=quartier` | couverture par zone |
| GET | `/api/zones.geojson?niveau=quartier` | carte (GeoJSON avec la couverture) |
| GET | `/api/doublons?statut=en_attente&niveau=probable` | paires à trancher |
| GET | `/api/doublons/menages` | ménages visités deux fois |
| POST | `/api/doublons/{id}/decision` | `{"decision": "confirme" \| "rejete"}` |
| GET | `/api/anomalies?gravite=haute` | saisies suspectes |
| POST | `/api/anomalies/{id}/statut` | `{"statut": "justifiee" \| "corrigee"}` |
| GET | `/api/agents` | suivi des agents |
| POST | `/api/sync` | synchronisation d'une tablette |
| POST | `/api/import/enregistrements`, `/api/import/zones`, `/api/import/estimations` | imports (formulaire) |
| POST | `/api/recalcul` | recalcul complet |
| GET | `/api/journal` | journal d'audit |

Documentation interactive : `/docs`.
