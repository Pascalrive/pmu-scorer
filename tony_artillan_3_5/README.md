# Tony Artillan 3/5

Test virtuel indépendant du 25 octobre au 24 novembre 2026 inclus.
Bilan final à partir du 25 novembre ; reprises des règlements jusqu'au
1er décembre inclus. Aucune reconstitution rétroactive.

## Règles fixes pendant le mois

- Toutes les courses de R1 française sont observées, même sans pari.
- Cinq premiers choix éditoriaux : Turfin, Canalturf, ZEturf (rubrique sur
  Canalturf), Geny et Zone-Turf. Genybet est uniquement le secours de Geny.
- Un simple gagnant si au moins trois sources valides désignent le même
  cheval. Les sources manquantes ne votent pas ; trois voix concordantes
  suffisent, même si les deux autres sont indisponibles. Aucun départage par cote.
- Mises successives après pertes : 100, 200, 150, 150, 200 EUR, puis arrêt.
  Gain : retour à 100 EUR ; remboursement : palier conservé.
- Compte et plafond propres : 1 200 EUR engagés par jour, remboursements inclus.
  Les retours ne rechargent pas le plafond. Aucune mise réduite pour le contourner.
- Repère +200 EUR net sans arrêt ; remise à zéro quotidienne.
- Capture pendant la dernière heure ; engagement pendant les 30 dernières
  minutes, seulement après règlement du pari précédent et reçu Telegram
  confirmé avant départ. Un aperçu ne constitue jamais une mise.
- Numéro, nom, réunion, date et course validés ; contrôle des non-partants.
  Zone-Turf exige la concordance de la liste complète des partants, sans
  remplacer un premier choix manquant par une « Top chance ».
- Rapports définitifs PMU INTERNET uniquement. Donnée manquante : attente.
- Cotes PMU SG avec leur propre horodatage ; elles ne servent pas au règlement.
- Aucun pari placé activé. La question 50/50 est une analyse rétrospective,
  pas une modification de cette stratégie SG.

Les fichiers, preuves compressées, reçus Telegram, progression et bilans sont
isolés dans `tony_artillan_3_5/data`. Tony Artillan, Tony Artillan 2, Consensus
et l'ancien Paris Turf ne changent pas. Les parseurs des quatre sources
existantes et le secours Genybet sont réutilisés.

Telegram : lancement, aperçu des cinq sources, choix, mise confirmée,
suivi, bilan quotidien course par course et cumul ; déduplication par contenu.
Le bilan distingue mises, retours, net, ROI, gagnants/perdants, remboursements,
attentes, seuil de +200 EUR, sommet, recul maximal et raisons de non-jeu.
Les retards GitHub peuvent faire manquer une course : ne jamais la rejouer.

Exécution : `python -m tony_artillan_3_5.main`.
Diagnostic sans message ni écriture de données de production :
`python -m tony_artillan_3_5.main --dry-run --probe`.
Tests : `python -m unittest discover -s tony_artillan_3_5/tests -v`.
