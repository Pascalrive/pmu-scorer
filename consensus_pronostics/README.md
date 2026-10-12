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

Dernière archive admissible avant le départ, au moins cinq sources complètes. Simulation uniquement, aucun pari exécuté et aucun message Telegram envoyé.

Deux stratégies suivies séparément :
1. **Consensus** : 5 € en simple placé sur son premier cheval.
2. **Outsider** : 5 € en simple placé sur l'outsider explicite le plus cité, seulement si au moins deux sources le citent ; même règle de départage par numéro.

Règlement via les rapports définitifs **PMU INTERNET E_SIMPLE_PLACE**. Rapports absents : en attente ; pas de substitution par les rapports réseau. Un non-partant est remboursé. ROI = (retours − mises) / mises. Un groupe avec un pari en attente reste « INCOMPLET ».

## Exécution isolée

Workflow : `.github/workflows/consensus_pronostics.yml`.
Collecte à 07:05, 09:05, 11:05 UTC ; bilan à 05:25 UTC. En octobre avant le changement d'heure : 09:05, 11:05, 13:05 et 07:25 à Paris. Les horaires locaux changent avec l'heure d'hiver. Les retards possibles de GitHub Actions sont contrôlés par l'heure réelle de capture avant départ.

Le workflow ne modifie que `consensus_pronostics/data`, dispose de son propre verrou et n'importe aucun module de l'algorithme existant. Les réconciliations Git préservent les commits simultanés de l'autre workflow. Les historiques, ROI et budgets des deux expériences ne sont jamais additionnés.

```sh
pip install -r consensus_pronostics/requirements.txt
python -m unittest discover -s consensus_pronostics/tests -v
python consensus_pronostics/collector.py
python consensus_pronostics/evaluate.py
```

Un échec de site est affiché et ne bloque pas les autres sources. Une panne PMU empêche une collecte valide. L'accès du jour ne garantit pas que le site restera accessible : les statuts sont contrôlés à chaque lecture.
