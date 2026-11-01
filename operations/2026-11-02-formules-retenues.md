# Formules retenues à compter du 2 novembre 2026

Décision prospective validée le 1 novembre. Simulation uniquement. Aucun changement des mises, pertes, reçus ou règles des journées antérieures.

| Programme | Nouvelles simulations | Conditions |
|---|---|---|
| Tony classique (`comparaison_r1`) | Maintenu | R1 française, au moins trois premiers choix concordants sur les quatre sources ; disciplines inchangées |
| Tony 2 | Test secondaire sur le **plat uniquement** | Accord Geny + Canalturf ; trot et obstacles exclus ; discipline officielle manquante = aucune mise |
| Tony 3/5 | Test secondaire sur le **plat uniquement** | Au moins trois votes parmi cinq ; trot et obstacles exclus ; discipline officielle manquante = aucune mise |
| Scorer | **Couplé ordre seulement, 5 €** | Critères existants conservés : aucune conversion d'un couplé placé ou gagnant en ordre |
| Consensus | **Quinté cotes seulement, 2 €** | Sélection complète, marché disponible, reçus Telegram avant départ ; sans Option Max |
| Consensus 2sur4 mixte et outsider | Observation, **0 €** | Messages et résultats descriptifs séparés, aucun retour/net ajouté aux bilans financiers |
| Autres formules scorer/Consensus et ancien Paris Turf | Nouvelles mises suspendues | Historique et règlement des paris antérieurs conservés ; ancien Paris Turf sans programmation automatique |

Les Tony conservent chacun leur compte, la progression 100, 200, 150, 150, 200 €, le retour à 100 € après victoire, l'arrêt après cinq pertes, le plafond de 1 200 € de mises/jour et le repère +200 € sans arrêt au seuil. Genybet reste un secours de Geny, pas un vote supplémentaire. Dates de fin des essais inchangées.

Ne pas comparer directement les résultats toutes disciplines antérieurs au 2 novembre avec ceux du filtre plat. Les petits échantillons historiques ne prouvent pas une amélioration future. Aucun résultat manquant n'est une perte, aucune course manquée ne devient un pari rétrospectif.

## Sessions Actions

Sessions Tony d'environ dix minutes : une passe en cours peut prolonger la session (limite de dix minutes par passe), puis passage de relais explicite par `workflow_dispatch`. Durée maximale du job : 25 minutes, contrôles et installation compris. Archivage après chaque passe et tentative finale même si l'index Git est propre mais qu'un commit local n'a pas été publié. Trois tentatives bornées de synchronisation ; arrêt sur échec, copie des données en artifact.

Le relais n'est demandé que pendant la fenêtre active R1 et la période de l'essai. À chaque push technique, un enfant de contrôle confirme le mécanisme de dispatch sans collecte, sans Telegram et sans mise. Les crons restent un secours : ces mesures ne garantissent pas la ponctualité en cas de panne GitHub, de file d'attente ou de budget épuisé.
