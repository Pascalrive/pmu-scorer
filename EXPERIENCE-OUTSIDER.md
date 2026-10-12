# Contrôle des correctifs du 12 octobre 2026

Contrôle prévu le 22 octobre 2026. Les premières journées complètes comparables
commencent le 13 octobre. La journée du déploiement est une transition : utiliser
la révision et `qualite_version` pour distinguer les données avant et après.

## Qualité des données

- Le nombre de citations provient des sources identifiées, jamais de la note.
- Seul le bloc de sélection du journaliste Canalturf de la bonne date et course
  est retenu. Les anciens parseurs de simples mentions Geny, Zone-Turf et Equidia
  restent hors scoring jusqu'à validation d'un bloc de pronostics explicite.
- Le code officiel de déferrage est conservé. Protection et déferrage sont
  distincts. Une donnée absente est inconnue, avec un score neutre.
- Les types de paris sont lus dans les marchés PMU Internet ouverts. Un couplé
  ordre garde l'ordre des chevaux et ne remplace pas silencieusement un ancien
  conseil de couplé gagnant. Les courses sans simple placé Internet sont exclues.
- Les rapports définitifs règlent aussi les partants connus non classés.
  Les rapports absents, non-partants avec dividende spécifique manquant,
  identités incompatibles et envois incertains ne deviennent pas des pertes.

## Alerte outsider exploratoire, version 2026-10-12-v1

Un cheval est signalé si toutes les conditions sont réunies :

1. Dernière sortie gagnée ou au moins deux victoires dans les trois dernières
   sorties, en lisant la musique de gauche à droite.
2. Cote initiale connue et baisse d'au moins 20 % au contrôle.
3. Cote actualisée strictement supérieure à 6 et au plus égale à 20.
4. Score initial parmi les trois premiers scores des partants actifs.

Ces seuils constituent un protocole de test, pas une méthode validée. Les poids
du score et le classement des conseils restent ceux de la référence. Le message
ajoute au plus deux alertes, sans pari supplémentaire.

Le journal Telegram contient `experience` uniquement lorsque le message concerné
est traité, avec sa révision, son statut d'envoi et ses reçus. La référence doit
correspondre exactement aux chevaux et paris du message effectivement envoyé.
La variante remplace le premier choix par le premier outsider signalé et conserve
le nombre de paris et la mise totale. Si les budgets diffèrent, elle est écartée.

Le bilan règle les deux variantes aux rapports officiels PMU Internet. Les ROI
expérimentaux utilisent uniquement les mêmes courses entièrement réglées dans
les deux groupes. Les comparaisons en attente restent indiquées. Les retours de
la variante ne sont pas ajoutés au bilan des conseils réellement envoyés.

## Mesures au contrôle

- ROI quotidien et cumulé des conseils : somme des retours moins somme des mises,
  divisée par les mises, à 5 € par pari. Éviter la moyenne des ROI quotidiens.
- ROI de la référence et de la variante sur le même sous-ensemble de courses.
- Gagnants et placés du premier choix, alertes gagnantes et fausses alertes.
- Nombre d'envois confirmés avant départ, données manquantes, marchés non proposés
  et identités refusées. Vérifier la régularité réelle des collectes GitHub.
- Effectif de l'essai et répartition plat/trot : dix jours ne garantissent pas
  qu'un écart de rentabilité soit durable.

Les journaux et observations sont archivés dans Git et dans les artefacts de
secours. Aucun pari réel n'est exécuté.
