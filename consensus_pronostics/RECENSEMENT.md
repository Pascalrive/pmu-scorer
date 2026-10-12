# Recensement des sources de pronostics

Contrôle du 12 octobre 2026. Recensement de 20 candidats, sans prétendre couvrir tous les sites existants. Les codes HTTP ci-dessous proviennent de requêtes publiques depuis l'environnement de contrôle ; le journal du workflow apporte séparément la preuve depuis GitHub Actions. Un HTTP 200 seul ne prouve pas que les choix sont extractibles. Aucun contournement de blocage ou abonnement.

## Sources retenues

| Source | URL | Couverture disponible | Contrôle local | Lecture utilisée | Outsider supplémentaire |
|---|---|---|---|---|---|
| Canalturf | https://www.canalturf.com/courses_liste_pronostics.php | Nombreuses courses | 200, sélection exacte vérifiée | Bloc « La sélection de… » | Groupe Outsiders, Coup de folie |
| ZEturf | Page de course Canalturf, bloc attribué ZEturf.fr | Nombreuses courses | 200 via Canalturf | Bloc « La sélection ZEturf.fr » | Non inventé s'il n'est pas indiqué |
| Zone-Turf | https://www.zone-turf.fr/quinte/ | Quinté et autres courses sur le site | 200, sélection vérifiée | Ligne Zone-Turf.fr | Coup de folie |
| Stats-Quinté | https://stats-quinte.com/pronostic-quinte-du-jour/ | Quinté | 200, sélection vérifiée | Base en Or puis Sous Base | Colonnes Outsider du même tableau |
| Turf-Pronostics | https://www.turf-pronostics.com/pronostics-quinte-du-jour-pmu/ | Quinté, autres courses via interface | 200, sélection vérifiée | Première puis seconde chance, ordre affiché | Non publié dans le bloc public testé |
| Rue des Joueurs | https://www.ruedesjoueurs.com/pronostic-quinte.html | Quinté, chevaux du jour | 200, sélection vérifiée | Article quotidien, « Notre Pronostic Quinté+ » | Non publié dans le bloc testé |
| Fréquence Turf | https://frequence-turf.fr/ | Quinté | 200, lecture du 13/10 vérifiée ; article du 12/10 absent (404) | Favori, base, tocard, outsider | Tocard et outsider explicites |
| Prono Turf Gratuit | https://prono-turf-gratuit.fr/pronostic-quinte-pmu/ | Quinté | 200, base et tocard vérifiés | Article quotidien de l'expert | Tocard ; seulement un choix principal public sur les pages testées |

Le programme collecte le Quinté pour comparer ces rédactions sur une même course. ZEturf est une source éditoriale distincte, lue via une page miroir identifiée ; une autre copie ZEturf ne devra jamais donner un second vote.

## Candidats à intégrer après vérification d'un lecteur précis

| Site | URL testée | HTTP local | Décision |
|---|---|---:|---|
| Geny | https://www.geny.com/ | 200 | Nouvelle interface riche en données ; lecteur de sélection explicite à développer, pas de recherche de noms dans toute la page |
| Equidia | https://www.equidia.fr/pronostics | 200 | Données volumineuses ; sélectionner l'auteur et vérifier les republications Turfomania avant intégration |
| Paris-Turf | https://www.paris-turf.com/ | 200, 195 octets | Pas de pronostic exploitable dans la réponse testée |
| Turfoo | https://www.turfoo.fr/pronostics/ | 404 | Cette route n'est pas valide ; cela ne démontre pas que tout le site est inaccessible |
| Coin-Turf | https://www.coin-turf.fr/ | 200 | Distinguer avis propre et revue de presse |
| Turf.fr | https://www.turf.fr/ | 200 | Article Quinté disponible ; lecteur et attribution à vérifier |
| Turf-FR | https://www.turf-fr.com/ | 200 | Distinguer rédaction et concours de lecteurs |
| Outil Turfiste | https://outilturfiste.com/pronostics_presse_quinte.php | 200 | Revue de presse ; utile comme secours, jamais comme une source supplémentaire aux originaux |
| Meilleur Pronostic | https://meilleurpronostic.fr/ | 200 | Base et synthèses ; lecteur d'avis propre à vérifier |
| France Bet | https://www.france-bet.com/turf/index.php | 200 | Actualité de la sélection à vérifier chaque jour avant de compter une voix |

## Accès bloqué lors du contrôle

| Site | URL | Résultat local | Décision |
|---|---|---|---|
| Turfomania | https://www.turfomania.fr/ | 403 Forbidden | Écarté de la collecte directe ; aucun contournement |
| Boturfers | https://www.boturfers.fr/cheval-outsider-du-jour | 403 Forbidden | Écarté ; de plus, distinguer outsider éditorial et simple filtre de cote |

Au total : 20 candidats, 8 sources éditoriales prévues pour l'expérience. La disponibilité et l'absence d'avis sont affichées chaque jour. Rien ne permet de garantir qu'un cumul de recommandations sera rentable : le bilan prospectif sert précisément à le mesurer.

## Vérification réelle depuis GitHub Actions

[Exécution du 12 octobre 2026](https://github.com/Pascalrive/pmu-scorer/actions/runs/38268662396), runner Ubuntu hébergé aux États-Unis : tests, collecte, bilan et archivage réussis. Six sélections complètes récupérées (Canalturf, ZEturf, Zone-Turf, Stats-Quinté, Turf-Pronostics, Rue des Joueurs), plus la base publique de Prono Turf Gratuit. Fréquence Turf : article du 12/10 absent (404), sans substitution par celui du 13/10. Sept avis récupérés, six complets. Cette collecte réelle après départ est exclue du bilan. La prochaine collecte prospective est prévue le 13/10 au matin.
