# Correction du suivi Tony — 6 novembre 2026

Les règles de choix, disciplines, mises, plafonds et seuils restent inchangées.
Aucun pari passé n'est recréé, aucun résultat financier historique n'est ajouté.

- La majorité est calculée après chaque vote validé avant départ. Dans les deux
  dernières minutes, un accord admissible suffit pour rendre la main à la
  réservation sans attendre une source supplémentaire. Les réponses tardives
  restent exclues. Tony 2 exige toujours ses deux sources.
- Le règlement des mises en attente passe avant la collecte des pronostiqueurs.
  La course imminente passe avant les autres contrôles, et les mises du jour
  avant le retraitement de l'historique. Les aperçus sont différés dans les dix
  minutes précédant un départ.
- Après échec d'archivage, le worker peut demander un seul relais de récupération
  automatique. Le groupe de concurrence maintient la sérialisation des runs.
  Le successeur récupère l'artifact du run interrompu avant toute collecte/envoi,
  conserve les reçus et règlements déjà publiés et archive l'état récupéré.
  Artifact absent, divergence financière ou échec de synchronisation : aucune
  nouvelle mise. Les crons restent un secours ; une indisponibilité de GitHub
  peut toujours empêcher la reprise.
- Les contrôles incomplets ne sont plus présentés comme un simple désaccord.

Validation locale : 82 tests classique/récupération, 14 Tony 2, 10 Tony 3/5.
Les scénarios incluent vote tardif, majorité partielle, priorité aux règlements,
conflit de registre, restauration des reçus, traversée de chemins refusée,
limitation à un relais de récupération et environnement GitHub simulé.
Syntaxe des trois workflows YAML et compilation Python vérifiées.
