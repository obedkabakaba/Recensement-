# Projet : outil de couverture et de contrôle qualité pour l'identification et le recensement (RDC)

## Contexte
- Porteur : Obed, entrepreneur congolais (Kinshasa), étudiant à HEC Kinshasa. Réponses en **français**.
- Idée de départ : une app de recensement qui compte chaque habitant une seule fois, sans doublons ni oubliés.

## Ce qu'on a établi (novembre 2026)
- **Signature unique** : la chaleur corporelle et le Wi-Fi ne permettent pas d'identifier une personne. Les signatures réalistes sont le visage (facile, sans contact) et l'iris (la plus unique). Les empreintes et les veines de la paume sont des alternatives. La biométrie en production passe par des fournisseurs certifiés : on la simule seulement dans la démo.
- **Ce qui existe déjà** :
  - RGPH-2 (recensement) : dénombrement exhaustif prévu en juillet 2027. Saisie sur tablettes (méthode CAPI) avec CSPro/CSEntry, hors ligne, puis synchronisation vers le BCR/INS.
  - CENI : enrôlement biométrique depuis 2005-2006, dédoublonnage par empreintes et visage (MegaMatcher ABIS).
  - ONIP : autorité de l'identité légale (Fichier Général de la Population, NIN, carte d'identité). La CENI lui a remis le fichier électoral 2022 le 19/02/2026. Identification de masse annoncée pour mi-décembre 2026, avec Kinshasa comme province pilote.
  - GRID3 / WorldPop : estimations de population par cellules d'environ 100 m pour la province de Kinshasa (v4.4, déc. 2025), calculées à partir des bâtiments vus par satellite et de micro-recensements.
- **Positionnement retenu** : ne pas concurrencer CSPro ni les fournisseurs de biométrie. Construire un **module de couverture et de contrôle qualité** qui :
  1. compare, quartier par quartier, la population estimée (GRID3, puis RGPH-2) aux personnes déjà enrôlées ou recensées, et met en **rouge** les zones sous-couvertes et en **vert** les zones cohérentes ;
  2. détecte les doublons au moment de la synchronisation (GPS, composition du ménage, noms proches ; biométrie en option là où la loi le permet) ;
  3. repère les saisies suspectes.
- **Cible prioritaire** : l'ONIP (pilote à Kinshasa) plutôt que la CENI, qui est politiquement plus sensible. La protection des données sert d'argument de vente, car le cadre légal en RDC est jugé insuffisant.
- **Vision long terme** : prouver le concept en RDC, obtenir la caution d'un partenaire (UNFPA, GRID3, INS), puis s'étendre à l'Afrique francophone. Modèle compatible avec CSPro, éventuellement open source ; revenus tirés de la mise en place, de la formation et du support.

## Plan de construction
1. **Démo « carte de couverture »** sur Kinshasa ou une commune (ex. N'djili) avec les données GRID3. Obed doit télécharger les fichiers GRID3 et les fournir, car le réseau du bac à sable est limité.
2. **Maquette de l'app agent** : enregistrement d'un ménage, alerte doublon, statut vert ou rouge.
3. **Prototype technique** : base de données sur Supabase, déploiement sur Render.
4. **Dossier de présentation pour l'ONIP** : problème, solution, démo, plan du pilote, protection des données.

## Prochaine étape
Commencer par l'étape 1 : la démo de la carte de couverture.
