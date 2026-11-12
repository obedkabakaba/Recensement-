# Protection des données

Le recensement et l'identification touchent aux données les plus sensibles qu'un État détient sur ses citoyens. La RDC n'a pas encore d'autorité de protection des données pleinement opérationnelle. Decensio applique donc d'emblée les principes des cadres de référence : Convention de l'Union africaine sur la cybersécurité et la protection des données (Malabo), RGPD européen, principes de l'ONU pour les statistiques officielles.

## Ce que fait Decensio

| Principe | Mise en œuvre |
|---|---|
| **Minimisation** | Seules les données utiles aux trois contrôles sont gardées : composition du ménage, sexe, naissance, lien, position du ménage. Pas de religion, d'ethnie ni d'appartenance politique. |
| **Pseudonymisation des noms** | Par défaut (`DECENSIO_STOCKER_NOMS=0`), les noms ne sont **pas stockés**. Decensio garde des clés phonétiques, qui suffisent à comparer les fiches, et des empreintes HMAC-SHA256 calculées avec une clé secrète. Les vérificateurs voient la clé phonétique et les autres informations de la fiche. |
| **NIN jamais en clair** | Le numéro d'identification national n'est conservé que sous forme d'empreinte HMAC. On peut vérifier que deux fiches portent le même NIN sans pouvoir le lire. |
| **Biométrie confiée à un ABIS certifié** | Le visage, les empreintes et l'iris sont comparés par un système certifié (ABIS, par exemple celui de l'ONIP). Decensio transmet les captures et conserve seulement la référence ABIS de la personne et le résultat de la comparaison, jamais les gabarits biométriques. Dans la démonstration, la biométrie est simulée. |
| **Contrôle d'accès** | Toute écriture (import, synchronisation, décision) exige une clé d'API. |
| **Traçabilité** | Chaque écriture est inscrite au journal d'audit : qui, quoi, quand. Les décisions sur les doublons gardent le nom du vérificateur. |
| **Décision humaine** | Aucune fiche n'est supprimée automatiquement. Les doublons et anomalies sont des **signaux** qu'une personne habilitée tranche. |
| **Hébergement** | Base PostgreSQL au choix de l'institution : Supabase pour un pilote, ou serveur hébergé en RDC (datacenter de l'État ou d'un opérateur national) en production. |

## À compléter avant la mise en production

- [ ] Rôles distincts (agent, superviseur, vérificateur, administrateur) avec comptes nominatifs, à la place de la clé d'API unique.
- [ ] Chiffrement de la base au repos (activé par défaut chez Supabase) et sauvegardes chiffrées.
- [ ] Rotation du secret de pseudonymisation : prévoir une procédure, car changer le secret oblige à recalculer les empreintes.
- [ ] Convention de traitement des données signée avec l'institution (ONIP, INS) : finalité, durée de conservation, destruction en fin de mission.
- [ ] Analyse d'impact (AIPD) avant le pilote, en particulier pour la biométrie.
- [ ] Base légale de la collecte biométrique (texte de l'ONIP) et consentement éclairé des personnes.
- [ ] Hébergement des données sur le territoire national si l'institution l'exige.
