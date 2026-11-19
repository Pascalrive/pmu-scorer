# Tiercé champ réduit — favori fixé premier, toutes courses françaises admissibles

Deux expériences **virtuelles indépendantes**, activées le 19 novembre 2026. Aucun pari réel.

| Identifiant permanent | Libellé Telegram | Associés | Mise fixe à 100 % |
|---|---|---:|---:|
| `tierce_favori_6_associes_30eur` | TIERCÉ — FAVORI + 6 ASSOCIÉS — 30 € | 4 du classement + 2 outsiders | 30 € |
| `tierce_favori_8_associes_56eur` | TIERCÉ — FAVORI + 8 ASSOCIÉS — 56 € | 6 du classement + 2 outsiders | 56 € |

[Résultats et comptes séparés](data/README.md). Chaque formule est évaluée sur son propre coût total ; aucun ROI global additionné. Quand les deux sont admissibles, **86 € de mises virtuelles par course**, sans enjeu réel ni progression. Il n'y a plus de restriction à une course par jour ni de plafond journalier de 86 € : le montant dépend du nombre de courses effectivement validées.

## Sélection figée séparément pour chaque course

- Toutes les courses françaises de toutes les réunions proposant le **Tiercé Internet à 1 €**, qu'elles soient ou non support du Quinté. Un Quinté n'est pas requis ; un autre type de pari n'est jamais substitué à un Tiercé absent. Les marchés fermés restent visibles dans la couverture mais ne sont pas joués.
- Contrôle entre H−60 et H−2, date de Paris. Les sources doivent dater de moins de 15 minutes. Les cotes sont relues après la collecte, au maximum deux minutes avant la préparation ; chaque cote PMU directe doit elle-même dater de moins de 15 minutes.
- Base : partant ayant la plus petite cote directe de simple gagnant PMU. Égalité : numéro PMU croissant. Toutes les cotes des partants doivent être connues pour affirmer qu'il s'agit du favori. Aucune cote de référence en remplacement.
- Réutilisation des huit parseurs éditoriaux publics de Consensus, **sans modifier ni envoyer les comptes Consensus**. Chaque collecte cible précisément la date, la réunion, la course et les noms des chevaux. Les pronostics du Quinté ne sont jamais réutilisés pour une autre course. Minimum cinq éditeurs distincts avec cinq choix vérifiés. Un éditeur compte une seule fois. Certains sites ne couvrent que le Quinté : si les autres courses n'ont pas assez de sources, elles sont non jouées avec un motif explicite.
- Classement des autres partants : nombre de citations dans les cinq premiers, puis points 5–4–3–2–1, puis numéro croissant.
- Six associés : quatre premiers de ce classement, puis deux outsiders distincts hors base/classement retenu, explicitement cités comme outsiders par au moins deux éditeurs.
- Huit associés : six premiers du même classement, puis deux outsiders distincts hors base/classement retenu. Classement des outsiders : nombre de mentions outsider, citations générales, points, numéro.
- Chaque variante peut être non jouée indépendamment de l'autre. Pour chaque course, dès qu'une variante peut être envoyée, le relevé commun et le favori sont figés pour les deux ; une variante incomplète n'est pas reconstruite avec d'autres choix plus tard. Une course figée ou incomplète ne bloque pas les autres courses. Pas de complément inventé.
- Les deux variantes ne sont pas nécessairement emboîtées : un outsider peut entrer dans les six premiers du classement de la variante large. Leur comparaison est une comparaison de formules, pas un pur effet de deux chevaux supplémentaires.

## Tickets, coûts et rapports

Pour une base B et P associés, générer **B–X–Y pour chaque paire ordonnée distincte** : P × (P−1) tickets de 1 €. La base reste première sur chaque ticket ; les associés occupent les deuxième et troisième positions. 6 × 5 = 30 € ; 8 × 7 = 56 €. Sans Flexi.

Règlement ticket par ticket aux rapports définitifs PMU INTERNET, en centimes :
- Si la base gagne et les deux autres chevaux du podium sont associés : un ticket Ordre et un ticket Désordre.
- Si la base finit deuxième ou troisième et les deux autres chevaux du podium sont associés : deux tickets Désordre.
- Sinon : tickets perdants uniquement après réception d'une arrivée et de rapports cohérents.
- Net = tous les retours moins la **mise totale de la formule**. Un ticket gagnant n'implique pas une formule bénéficiaire.
- Remboursement intégral officiel reconnu ; non-partant sélectionné, ex aequo ou schéma de règlement spécial non pris en charge restent **EN_ATTENTE**, avec motif de contrôle manuel, jamais perdants par défaut.

## Preuve, envois, bilans

Les choix, la liste complète des tickets et la tentative `PENDING` sont archivés sur GitHub **avant** l'appel Telegram. Une réponse ambiguë n'est pas renvoyée automatiquement. Seul un message avec reçu Telegram, heure de début d'envoi et confirmation locale tous strictement avant départ est comptabilisé. Un aperçu ou une collecte seule n'engage aucune mise.

Pas de reconstitution historique. Choix figés dès leur premier envoi confirmé ; les mises ne changent plus avec les cotes. Les autres programmes restent indépendants. Les reçus de la première version limitée au Quinté sont conservés sans double envoi ; chaque sélection archive sa version de protocole. La version `tierce-cr-v2-toutes-courses-2026-11-19` étend seulement la couverture à plusieurs courses et réunions.

- `data/AAAA-MM-JJ/journal.json` : choix figés, preuves des sources, tickets, reçus et résultats.
- `data/AAAA-MM-JJ/RxCy/derniere_collecte.json` : sources contrôlées pour cette course, y compris lors d'une sélection incomplète.
- `data/AAAA-MM-JJ/RxCy/rapports_pmu_internet.json` : réponse officielle utilisée pour le règlement de cette course. Les fichiers de l'ancienne version à la racine du jour sont conservés.
- `data/AAAA-MM-JJ/bilan_du_jour.txt` : journée et cumul par formule, également envoyé sur Telegram après départ, puis actualisé lorsque les résultats arrivent.
- `data/<identifiant>/bilans_par_course.csv`, `bilans_quotidiens.csv` et `bilan_cumule.json` : détail par course, journée et formule des mises engagées/réglées, retours, net, ROI, courses positives/négatives/neutres, tickets gagnants/perdants/remboursés, résultats manquants et envois non confirmés. Montants machine en centimes. Les bilans Telegram longs sont découpés sans supprimer de courses.

## Exécution publique sans services payants

Workflow dédié : **Tierce CR - Favori 6 associes 30 EUR et 8 associes 56 EUR**. Runner GitHub standard `ubuntu-latest`, dépôt public exigé, aucun service IA payant, aucune boucle longue ni relais récursif. Passage toutes les dix minutes toute la journée ; sortie rapide hors fenêtre de collecte. Les sources d'une course sont lues avec quatre requêtes simultanées au maximum. Les courses sont traitées par heure de départ. Après huit minutes, les nouvelles collectes sont reportées au passage suivant, avec motif visible ; après dix minutes les règlements restants sont reportés. Chaque job est limité à douze minutes. GitHub peut retarder un déclenchement : les courses manquées restent signalées et non rejouées.

Les secrets Telegram restent dans GitHub Secrets, jamais dans les fichiers publics. Les résultats sont conservés dans Git ; pas de stockage d'artefacts Actions supplémentaire. La gratuité visée concerne les runners standard sur dépôt public, pas une garantie sur d'autres services du compte.

Contrôle local sans envoi : `python -m tierce_champ_reduit.run --output /tmp/tierce-preview`.

Tests : `python -m unittest discover -s tierce_champ_reduit/tests -v`.
