# Comment Decensio calcule

## 1. Couverture

Pour chaque zone :

- **population attendue** : somme des cellules de la grille GRID3 (environ 100 m de côté) dont le centre tombe dans la zone, ou chiffre importé (RGPH-2, INS). Une zone sans estimation propre additionne celles de ses zones filles ;
- **personnes enregistrées** : personnes dont le ménage a un point GPS dans la zone. Chaque personne n'est comptée **qu'une fois** : quand plusieurs fiches désignent la même personne (doublon probable ou confirmé), une seule est retenue ;
- **taux de couverture** = personnes uniques ÷ population attendue.

| Statut | Règle (modifiable) | Lecture |
|---|---|---|
| ✓ Vert | taux ≥ 90 % | couverture atteinte |
| ◐ Orange | 70 % ≤ taux < 90 % | en cours |
| ✕ Rouge | taux < 70 % | sous-couverture : envoyer des équipes |
| ▲ Surcouverture | taux ≥ 115 % | doublons non repérés ou estimation trop basse |
| ? Sans estimation | — | aucune estimation pour cette zone |

Les zones parentes (commune, zone de santé) cumulent leurs zones filles.

**Limite à connaître** : les grilles GRID3 sont des *estimations*, avec une marge d'erreur qui peut être grande à l'échelle d'un quartier. Une zone rouge est un signal à vérifier sur le terrain, pas une preuve. Le RGPH-2 donnera ensuite des chiffres plus fiables.

## 2. Doublons

1. **Clés phonétiques.** Chaque élément du nom (nom, postnom, prénom) est ramené à une forme commune qui gomme les variantes d'orthographe fréquentes : Tshibangu / Tchibangu / Chibangu, Ilunga / Ilounga, Kasongo / Kassongo, Kalonji / Kalondji, Mwamba / Mouamba, etc.
2. **Blocs.** Pour éviter de comparer tout le monde avec tout le monde, deux fiches ne sont comparées que si elles ont le même sexe et au moins **deux** éléments de nom en commun (sur les 4 premières lettres de leur clé), ou le même NIN.
3. **Score** (de 0 à 1) :

| Critère | Poids | Détail |
|---|---|---|
| Nom | 50 % | ressemblance des clés (Jaro-Winkler). Un élément du nom sans correspondance fait fortement baisser le score. |
| Naissance | 30 % | date identique : 1 ; jour et mois inversés : 0,9 ; même année : 0,7 ; âge déclaré seulement : 0,8 si même année. |
| Lieu | 15 % | moins de 50 m : 1 ; moins de 250 m : 0,8 ; moins de 1 km : 0,5 ; plus loin : 0 à 0,4. |
| Lien de parenté | 5 % | identique ou non |

Plusieurs règles corrigent ensuite le score :

- même NIN : score de 1 ;
- deux NIN différents ou deux sexes différents : score fortement réduit ;
- nom porté par beaucoup de personnes, sans date complète ni domicile proche : la paire reste « à vérifier » (homonymes probables) ;
- deux fiches d'un même ménage sans date de naissance concordante : pas de conclusion, car ce sont peut-être des jumeaux ;
- deux ménages qui partagent plusieurs personnes en double : le score de chaque paire est renforcé. Le ménage a sans doute été **visité deux fois**.

4. **Niveaux.** Un score d'au moins 0,85 donne un doublon **probable**, un score entre 0,70 et 0,85 une paire **à vérifier**.
5. **Décision humaine.** Un vérificateur confirme ou rejette chaque paire, et ces décisions sont conservées d'un calcul à l'autre. Les doublons probables non rejetés et les doublons confirmés sont fusionnés en une seule personne pour le calcul de la couverture.

Sur les données de test (42 000 personnes et 25 ménages recensés deux fois avec des orthographes différentes), **toutes les fiches recopiées sont retrouvées** et **96 % des doublons « probables » sont de vrais doublons**. Ces chiffres seront à mesurer à nouveau sur des données réelles.

## 3. Saisies suspectes

| Contrôle | Niveau | Gravité |
|---|---|---|
| GPS absent ou invalide | ménage | haute |
| GPS imprécis (> 50 m) | ménage | basse |
| Point hors de toutes les zones / hors de la zone assignée | ménage | moyenne |
| Ménage vide, très grand (> 25), taille déclarée ≠ membres saisis | ménage | moyenne / basse |
| Aucun ou plusieurs chefs de ménage | ménage | basse / moyenne |
| Saisie hors des heures de travail (6 h – 21 h), date dans le futur | ménage | basse / haute |
| Âge invraisemblable, chef de moins de 12 ans, écart chef-enfant < 12 ans | personne | moyenne / basse |
| Ménage enregistré moins de 3 minutes après le précédent | agent | moyenne |
| Plus de 40 ménages dans la journée | agent | moyenne |
| 5 ménages ou plus au même point GPS (rayon de 5 m) | agent | haute |
| Âges arrondis (indice de Whipple > 175) | agent | moyenne |
| Rapport hommes/femmes hors de 70–140 pour 100 | agent | basse |
| Moins de 2,5 personnes par ménage en moyenne | agent | basse |

Une anomalie n'est **pas une preuve de fraude**. Plusieurs ménages au même point GPS peuvent par exemple s'expliquer par un immeuble. Le superviseur marque l'anomalie « justifiée » ou « corrigée ».

Tous les seuils se règlent dans `decensio/config.py`, ou par des variables d'environnement `DECENSIO_…`.
