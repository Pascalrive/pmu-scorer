# Audit du 15 octobre 2026 — version 2026-10-15-v2

## Resultats observes de l'algorithme principal

Simulation de 5 EUR par pari explicitement conseille, derniere selection envoyee
avant depart, rapports PMU INTERNET. Sources : `resultats/bilans/bilan_20261012.json`,
`bilan_20261013.json` et `bilan_20261014.json`.

| Jour | Paris regles | Mises | Retours | Solde | ROI |
|---|---:|---:|---:|---:|---:|
| 12/10 | 42 | 210,00 | 170,25 | -39,75 | -18,93 % |
| 13/10 | 56 | 280,00 | 210,00 | -70,00 | -25,00 % |
| 14/10, sous-total regle | 46 | 230,00 | 160,00 | -70,00 | -30,43 % |

Le 14/10 reste incomplet : R3C3, journal `7584cba5a45e469cb7bd22f8ae537e11`,
ENVOI_INCERTAIN. Une arrivee connue ne prouve pas qu'un conseil a ete recu.
Les 144 paris regles totalisent 720 EUR de mises et 540,25 EUR de retours.
Leur ROI de -24,97 % est un sous-total, pas un ROI global definitif.

Par type sur ces paris regles : simple place 420 -> 305,75 EUR (-27,20 %),
couple place 295 -> 215,50 EUR (-26,95 %), couple ordre 5 -> 19 EUR (un seul pari).
Ces resultats ne justifient ni une augmentation des mises, ni le remplacement
general des simples par des couples ou des outsiders.

## Erreurs corrigees

1. **Fautes au trot** : le fallback convertissait toute la musique en majuscules,
   puis comptait A, D, G, T. Le `a` d'attele dans `1a` devenait un abandon.
   De plus, il lisait les dernieres positions du texte (anciennes sorties),
   et additionnait parfois historique detaille et musique des memes sorties.
   Desormais, on decode rang et discipline separement, sur les cinq sorties de
   gauche ; la musique sert uniquement si aucun historique detaille n'est present.
2. **Entourage** : `nombreCourses` et `nombreVictoires` de /participants sont les
   compteurs du cheval. Ils ne sont plus attribues au driver ou a l'entraineur.
   Sans historique de personnes valide, ces composantes restent neutres (50).
   Les notes de reputation du proprietaire et de l'entraineur sont neutralisees.
   Aucun ELO externe n'a ete integre ni invente.
3. **Identite driver/entraineur** : une initiale ou un fragment de nom commun ne
   suffit plus a donner le bonus de 4 points. Egalite des noms normalises requise ;
   les alias non verifies restent indetermines.
4. **Pourcentages d'aptitude** : suppression d'un facteur 100 superflu qui saturait
   les scores hippodrome/association cheval-jockey a 100. Exemple : 25 % de
   victoires et 50 % de places donnent 35/100 avec les poids 60/40 existants.
5. **Donnees absentes** : neutralite pour une distance non documentee ; aucune
   aptitude au parcours, au terrain ou de fraicheur deduite d'une musique seule.
   Les performances futures ne comptent pas comme forme recente.
   Le CSV indique maintenant la source et le nombre de performances detaillees.

## Verification sur les archives, sans utiliser les arrivees pour regler les poids

Le CSV `resultats/pmu_20261014_0841.csv` contient 348 lignes dont 216 trotteurs.
197 avaient la penalite maximale de -18. Le decodage corrige change la penalite
de 195 trotteurs ; 94 avaient une penalite alors que leurs cinq sorties recentes
decodees ne contiennent aucune faute. KATCHI QUICK faisait notamment partie des
chevaux penalises a -18 sans faute recente decodee (nouvelle penalite : 0).
Cette observation explique un defaut de calcul, pas un gain retrospectif valide.

Quatre anciens rapprochements de noms du CSV ne satisfont plus l'identite stricte,
dont D. THOMAIN / D. TRAVERT et F. OUVRIE / F. JUNG. Les autres rapprochements
ambigus exigent une source d'identite, ils ne sont pas declares faux avec certitude.

La fixture `tests/fixtures/scoring-20261014-r4c2.json` conserve les donnees utiles
d'une observation H60 avant depart avec sa reference et son horodatage. Le test
rejoue l'analyse des 15 partantes actives, sans reseau ni resultat de course.

Les trois exemples de simples places R1C6 du 12 (N8 : 1,50 EUR/EUR), R1C1 du 13
(N16 : 2,30 EUR/EUR), et R1C6 du 14 (N9 : 1,40 EUR/EUR) ont ete recoupes avec les
reponses officielles archivees sous `resultats/officiels/`. L'API PMU n'a pas
repondu depuis cet environnement : aucun nouveau controle exhaustif en direct
des rapports n'est revendique.

## Mise en service et mesure

Les ponderations, les regles de mises et le programme consensus restent inchanges.
Les scores sont corriges au prochain calcul du matin (16/10 pour une exploitation
normale), avec `qualite_version=2026-10-15-v2`. Les scores du CSV matinal du 15
ne sont pas reecrits retrospectivement ; ses actualisations H15 continuent a
utiliser ce CSV. Les bilans avant et apres cette date doivent rester distingues.

Le consensus reste un programme separe : seulement deux Quintes termines les
13-14/10. Ses six tickets statistiques/cotes/mix (2 EUR chacun) ont retourne 0 EUR.
Le simple place consensus (5 EUR/course) a retourne 12 EUR pour 10 EUR de mises ;
l'outsider 0 pour 10. Ces deux courses ne permettent pas d'optimiser les poids.

Validation : tests de regression du scoring, du journal et du bilan, plus les
tests separes du consensus. Aucune amelioration du ROI futur n'est encore mesuree.
