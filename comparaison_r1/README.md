# Comparaison prospective R1 — 16 octobre au 15 décembre 2026

Programme indépendant du scorer, du consensus Quinté et de Tony Artillan.
Simulation uniquement : simples gagnants PMU INTERNET, mises progressives.

## Règle financière confirmée

Un seul compte actif : **majorité 3 ou 4/4**. Un unique simple gagnant par
course lorsque trois ou quatre sites donnent le même premier choix.
Les sites individuels, paires et combinaisons n'engagent aucune mise.
Les quatre choix doivent être disponibles et jouables. Par jour :

- Suite après pertes successives : **100, 200, 150, 150, 200 EUR**, puis arrêt.
- Après un gain, retour à 100 EUR, même si les pertes précédentes ne sont pas récupérées.
- Après remboursement, même prochaine mise. Les mises remboursées comptent dans le plafond.
- Arrêt dès que le bénéfice NET réglé atteint ou dépasse 500 EUR.
- Plafond de 800 EUR de mises ENGAGÉES cumulées, pas de recyclage des gains dans ce plafond.
- Si la prochaine mise dépasse le reste, arrêt sans réduire ni plafonner la mise.
- Un pari à la fois sur le compte commun ; résultat précédent obligatoire.
- Remise à zéro chaque jour, aucun report de pertes ou gains.

Exemple : cinq pertes => 100+200+150+150+200 = **800 EUR**, arrêt.
Un gain remet la progression à son premier palier, sans remettre le compteur
des mises quotidiennes à zéro. Un remboursement ne change pas le palier.
Les paris sont engagés virtuellement au plus tôt 30 minutes avant départ,
à partir des choix préalablement figés et de l’identité/statut PMU vérifiés.
Chaque engagement est immuable et horodaté avant départ.

Toutes les courses de la réunion française R1 sont observées, même si elle
ne compte pas huit courses. Aucune autre réunion ne la remplace.

## Sources et protocole figé

- Turfin : cheval principal public de la fiche course. Il s'agit d'un test du
  classement systématique, y compris lorsque le site recommande de s'abstenir.
- Canalturf : premier de la sélection éditoriale de la fiche course.
- ZEturf : premier de sa rubrique explicitement attribuée à ZEturf sur
  Canalturf. Deux éditeurs mais un hébergeur commun : leurs erreurs d'accès
  peuvent être corrélées. Aucun double vote d'un même éditeur.
- Geny : premier de listeBase du pronostic éditorial Geny fourni dans le HTML
  public, distinct des choix des journalistes individuels et de la presse.

Première capture valide dans les 60 minutes avant le départ, définitivement
figée par site. Contrôle de date, réunion, course, titre, numéro et nom du
cheval avec le programme PMU. Aucun rattrapage de pronostic après départ.
Un changement d'horaire est accepté et journalisé seulement si l'identité reste identique et si ancien et nouveau départs sont encore futurs. Une fenêtre déjà passée n'est jamais rouverte.
Chaque preuve HTML est conservée compressée et identifiée par SHA256 ; les
cotes sont indicatives, jamais utilisées comme rapports de paiement.
Les sources ne sont pas nécessairement capturées à la même seconde. Leurs
horodatages permettent de contrôler cet écart. Les notes Turfin sont annoncées
figées à 10h par l'éditeur ; notre preuve est l'heure de notre propre capture.

NP déjà connu : premier choix conservé, non joué, sans promouvoir le suivant.
NP après capture : remboursement seulement avec table définitive SG connue.
Rapport inconnu/incohérent : EN_ATTENTE, jamais PERDU par défaut.
Définitifs PMU INTERNET ; dividendePourUnEuro exprimé en centimes pour 1 EUR.
Mises et retours incluent les remboursements ; taux de victoire les exclut.

## Accords

Quatre choix valides et jouables exigés. Le groupe est figé avant départ.

| Catégorie exclusive | Répartition | Action virtuelle |
| --- | --- | --- |
| Accord 2/4 | 2–1–1 | Aucun pari |
| Accord 3/4 | 3–1 | Un seul pari sur le compte majorité |
| Accord 4/4 | 4–0 | Un seul pari sur le compte majorité |
| Égalité | 2–2 | Aucun pari de groupe |
| Dispersion/manque | 1–1–1–1 ou source absente | Aucun pari de groupe |

La majorité stricte réunit les cas 3/4 et 4/4 dans la même progression et le
même plafond. Les courses exclues ne consomment aucune mise ni palier.
Les catégories d'accord et combinaisons exactes restent des statistiques
sans mise, afin de comparer la qualité des choix. Les anciens comptes sont
conservés pour audit et règlement éventuel mais ne reçoivent plus de paris.

## Bilans et interprétation

Classement financier principal par bénéfice net réellement simulé, ROI et
nombre de journées à objectif atteint, avec jours actifs et couverture.
Les arrêts peuvent produire des séries de courses jouées différentes :
le taux de victoire des prévisions des quatre sites est aussi comparé sur
leurs mêmes courses communes réglées, y compris après arrêt des mises.
Les prévisions observées ont une mise nulle : leurs taux décrivent la qualité
des choix ; elles ne sont jamais additionnées aux simulations financières.
Les groupes sont comparés aux choix individuels sur leurs propres courses
communes (`same_race_baselines`). Les combinaisons exactes restent uniquement descriptives.

Chaque bilan fournit mises, retours bruts, net, ROI, gagnants/perdants/remboursés,
série de pertes observée et intervalle descriptif Wilson à 95 % du taux de
victoire. Une attente coupe la série observée : elle est une borne inférieure
tant que l'historique n'est pas complètement réglé. Les confrontations appariées
comptent les courses où A gagne et B perd, et l'inverse. Pas de conclusion
automatique de supériorité : petits sous-groupes, dépendance et comparaisons
multiples exigent une analyse au contrôle final.

`data/BILAN.json` : cumuls ; `BILANS_JOURNALIERS.json` : par jour ;
`data/DATE/state.json` : captures, accords, états, preuves et erreurs ;
`rapport.txt` : bilan lisible ; `notifications.json` : reçus Telegram.
Les Telegram annoncent les choix figés, le suivi des mises et résultats de
du compte majorité dès changement, puis le bilan cumulé le soir, avec
déduplication. Un envoi incertain n'est pas renvoyé automatiquement.

## Exécution

```
pip install -r comparaison_r1/requirements.txt
python -m unittest discover -s comparaison_r1/tests -v
python -m comparaison_r1.main --probe --dry-run
python -m comparaison_r1.main
```

Workflow propre toutes les cinq minutes (06h–22h UTC) et reprise le matin,
arrêt de nouvelles captures après le 15 décembre. Règlements encore repris
jusqu'au 22 décembre, sans nouveau pari. La ponctualité GitHub n'est pas
garantie : toute course manquée est visible dans la couverture.
Le diagnostic du 15 octobre est hors échantillon. Contrôle final programmé
le 16 décembre 2026 après-midi dans ChatGPT.

## Aperçu matinal

Dès le passage du matin, un aperçu des courses encore à venir présente
Turfin, Canalturf, ZEturf et Geny, avec numéro, nom et cote PMU indicative.
Une source manquante est nommée explicitement ; nouvelle tentative après une
heure tant que la couverture est incomplète. L’aperçu est archivé séparément
dans morning_preview et apercu.txt : il ne fige aucune sélection et n’engage
aucune mise. La capture définitive reste dans la dernière heure, puis les
mises dans les 30 dernières minutes suivant le règlement précédent.

Les aperçus sont rafraîchis au plus une fois par heure à partir de 7h (Paris), y compris lorsque les quatre sources sont déjà présentes, afin de mettre à jour cotes et statuts PMU. Les sélections provisoires conservées gardent leur horodatage initial. Les courses non jouées sont expliquées dans le suivi. Les horaires GitHub restent indicatifs ; aucun pari rétroactif ne compense un passage tardif.
