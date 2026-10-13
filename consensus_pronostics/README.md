# Consensus quotidien des pronostics — expérience indépendante

Démarrage : 12 octobre 2026. Première journée prospective : 13 octobre 2026.

Le programme est limité **au Quinté français quotidien**, où les sources partagent une même course. Étendre à toutes les courses nécessite d'autres lecteurs vérifiés ; la couverture des sites spécialisés Quinté ne doit pas être présentée comme couvrant toutes les réunions.

## Sources

Huit sélections éditoriales, issues de sept sites collectés directement et du pronostic ZEturf identifié sur Canalturf : Canalturf, ZEturf, Zone-Turf, Stats-Quinté, Turf-Pronostics, Rue des Joueurs, Fréquence Turf, Prono Turf Gratuit. Voir [RECENSEMENT.md](RECENSEMENT.md) pour les 20 candidats et leurs limites.

Les trois premiers choix sont lus dans le bloc explicite de sélection, jamais dans la liste générale des partants ni dans les résultats. Les numéros sont rapprochés des partants PMU officiels. Les noms sont contrôlés lorsqu'ils sont publiés dans le bloc lu. La date et le nom de la course sont contrôlés ; pour Canalturf, la date vient aussi du chemin daté découvert dans son programme, et les numéros réunion/course du bandeau de la page.

Prono Turf Gratuit peut ne publier gratuitement qu'une base et un tocard : choix 2 et 3 restent vides. Turf-Pronostics affiche des groupes : la première chance précède la seconde chance, dans l'ordre affiché. Fréquence Turf ordonne favori, base, tocard, outsider ; son troisième choix peut donc également figurer dans la colonne outsider. Ces modes sont indiqués dans chaque tableau.

Les qualificatifs Outsider, Tocard et Coup de folie restent explicites. Une deuxième chance ou une grosse cote ne devient pas automatiquement un outsider. Une mention absente reste « Non publié ». Les extractions ne lisent pas les pronostics des lecteurs ni les tableaux de presse comme de nouvelles sources : une republication ne crée aucun vote supplémentaire. La dépendance entre rédactions reste possible : le nombre de voix n'est pas une probabilité de gagner.

## Calcul fixé avant l'expérience

- Choix 1 : 3 points ; choix 2 : 2 points ; choix 3 : 1 point. Une source ne cite un cheval qu'une fois dans ce classement.
- Une source partielle contribue uniquement ses choix publiés ; elle ne compte pas parmi les **cinq sources complètes minimales** nécessaires pour évaluer une course.
- Les chevaux non partants restent visibles dans les lignes des sites, mais n'ont aucun point ; le quatrième choix n'est pas promu.
- Outsiders : nombre de rédactions les ayant explicitement désignés, calculé à part. Plusieurs qualificatifs du même site ne donnent qu'une voix.
- Égalités : points, nombre de citations, numéro croissant ; ce dernier critère est arbitraire et sans valeur prédictive.

## Archives et tableau

`data/AAAA-MM-JJ/TABLEAU.md` : tableau quotidien lisible sur GitHub.
`data/AAAA-MM-JJ/TABLEAU.csv` : même tableau importable dans Excel.
`data/AAAA-MM-JJ/RnCm-horodatage.json` : archives immuables des extractions, URLs, heures, empreintes de pages, statuts HTTP, programme PMU et version.
`data/BILAN.md` : bilan quotidien indépendant.

Les lectures du 12 octobre ont eu lieu après le départ : elles servent au contrôle des lecteurs et sont **exclues des simulations**. Aucun ancien pronostic n'est reconstruit après une arrivée pour fabriquer un ROI.

## Bilan prospectif

Dernière archive admissible avant le départ, au moins cinq sources complètes. Simulation uniquement, aucun pari exécuté. Les tableaux sont envoyés sur Telegram à chaque nouvelle sélection avant départ.

Deux stratégies suivies séparément :
1. **Consensus** : 5 € en simple placé sur son premier cheval.
2. **Outsider** : 5 € en simple placé sur l'outsider explicite le plus cité, seulement si au moins deux sources le citent ; même règle de départage par numéro.

Règlement via les rapports définitifs **PMU INTERNET E_SIMPLE_PLACE**. Rapports absents : en attente ; pas de substitution par les rapports réseau. Un non-partant est remboursé. ROI = (retours − mises) / mises. Un groupe avec un pari en attente reste « INCOMPLET ».

## Exécution isolée

Workflow : `.github/workflows/consensus_pronostics.yml`.
Collecte à 07:05, 09:05, 11:05 UTC ; bilan à 05:25 UTC. En octobre avant le changement d'heure : 09:05, 11:05, 13:05 et 07:25 à Paris. Les horaires locaux changent avec l'heure d'hiver. Les retards possibles de GitHub Actions sont contrôlés par l'heure réelle de capture avant départ.

Les confirmations Telegram sont enregistrées dans `data/AAAA-MM-JJ/notifications.json`. Un message identique déjà confirmé n'est pas renvoyé ; une réponse incertaine bloque toute relance automatique. Aucun envoi n'est autorisé après le départ.

Le workflow ne modifie que `consensus_pronostics/data`, dispose de son propre verrou et n'importe aucun module de l'algorithme existant. Les réconciliations Git préservent les commits simultanés de l'autre workflow. Les historiques, ROI et budgets des deux expériences ne sont jamais additionnés.

```sh
pip install -r consensus_pronostics/requirements.txt
python -m unittest discover -s consensus_pronostics/tests -v
python consensus_pronostics/collector.py
python consensus_pronostics/evaluate.py
```

Un échec de site est affiché et ne bloque pas les autres sources. Une panne PMU empêche une collecte valide. L'accès du jour ne garantit pas que le site restera accessible : les statuts sont contrôlés à chaque lecture.

## Correctif exploitation du 13 octobre 2026

L'envoi Telegram quotidien a été branché au workflow de collecte ; le test ponctuel du 12/10 ne constituait pas un envoi quotidien. Les tableaux complets, les choix manquants et les outsiders sont envoyés séparément des conseils du programme principal. Le programme principal démarre désormais à 06:17 UTC (08:17 Paris en été), avec reprises à 06:47, 07:17 et 07:47 UTC. Ces reprises n'envoient pas une nouvelle collecte si un CSV valide du jour est déjà archivé. Les deux programmes gardent leurs journaux et leurs bilans distincts.

## Présentation du Quinté — 13 octobre 2026

Telegram affiche trois messages numérotés : synthèse des cinq chevaux les plus cités dans les cinq choix publiés, cinq choix par pronostiqueur, puis outsiders/tocards/coups de folie par source. Chaque cheval porte son numéro, son nom et la cote PMU de simple gagnant relevée avec l'heure de collecte. Les cotes manquantes sont signalées ; le repli sur une cote de référence est marqué « réf. ». Les non-partants sont indiqués.

Sept sources publient actuellement cinq choix exploitables ; Prono Turf Gratuit reste partiel lorsqu'une seule base est publique. Fréquence Turf affiche favori, base, tocard, outsider, puis ses compléments ; Turf-Pronostics distingue première puis seconde chance. L'ordre de ces rubriques est précisé.

La synthèse visuelle des cinq chevaux classe par nombre de sources les citant parmi leurs cinq choix, puis points 5–4–3–2–1 en cas d'égalité, puis numéro croissant. Elle est une présentation supplémentaire : le suivi prospectif déjà lancé conserve sa règle initiale sur les trois premiers choix (3–2–1), son budget et son règlement. Les historiques et le programme principal ne changent pas.

## Trois variantes figées de cinq chevaux — activées le 13 octobre 2026

Version `trois-selections-v1-2026-10-13`, trois méthodes : citations dans les cinq choix généraux (départage 5–4–3–2–1 puis numéro), cinq plus petites cotes connues parmi tous les partants (départage numéro), trois bases statistiques plus deux outsiders distincts cités par au moins deux sources (départage outsiders : cote puis numéro). Les cotes de référence restent explicitement marquées lorsque le direct manque. Aucun cheval manquant n'est inventé pour compléter la méthode mixte.

Simulation : **2 € par variante complète**, mise fixe, sans Option Max ni augmentation après les pertes. Conditions : cinq sources avec cinq choix publics, cinq chevaux distincts et marché E_QUINTE_PLUS disponible à 2 € de base. Les variantes sont des alternatives comparées à budget égal ; les simulations ne sont pas des paris exécutés.

Les variantes sont ajoutées au premier message Telegram et au tableau GitHub. Chaque archive capture les règles, les cinq numéros, les citations et cotes. Le bilan séparé `data/BILAN_TROIS_SELECTIONS.md` / `.json` ne compare que les courses où les trois variantes complètes ont été confirmées sur Telegram avant départ, en retenant le dernier envoi confirmé admissible. Les collectes sans reçu et les anciens jours sans cette version ne sont pas reconstruits a posteriori.

Le règlement utilise exclusivement E_QUINTE_PLUS définitif PMU INTERNET : ticket dans l'ordre affiché, rapport Ordre s'il correspond exactement, sinon Désordre ou Bonus applicable. On ne cumule pas le rapport principal et les bonus d'un même ticket. Les non-partants et les rapports ambigus restent en attente plutôt que de fabriquer un ROI. La couverture des cinq premiers est affichée séparément du gain payé. Le suivi originel en simple placé et le programme principal restent distincts.
