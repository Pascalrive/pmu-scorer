# Bilan des conseils Telegram

Depuis le 29 septembre 2026, le bilan utilise la derniere selection effectivement envoyee avant l'heure de depart annoncee. Le classement des chevaux reste inchange. Les conseils du matin et leurs actualisations sont conserves dans `resultats/journal/`, avec texte, date, version du code et recus Telegram. Une actualisation remplace les conseils precedents pour la simulation ; cela ne presume pas qu'un pari reel ait ete modifie.

Le simple place et le couple portent sur les chevaux explicitement affiches. Depuis le 12 octobre, le type du couple vient des marches PMU INTERNET ouverts : place, ordre ou gagnant selon la disponibilite reelle. Le couple ordre conserve exactement l'ordre affiche. Aucun pari n'est deduit du seul nombre de partants. Les mises sont **simulees : 5 EUR par pari**, aucun pari n'est execute par ce programme.

Les rapports proviennent exclusivement de l'API PMU `rapports-definitifs?specialisation=INTERNET`, par type de pari et numero/combinaison. `dividendePourUnEuro` est converti de centimes en euros, sans heuristique. Un gagnant joue en simple place est regle au rapport place de ce cheval. Les donnees sources sont archivees dans `resultats/officiels/`.

Les non-partants simples sont rembourses ; un couple avec non-partant requiert son rapport specifique. Un partant connu non classe peut etre regle lorsque les rapports definitifs sont presents. Les envois incertains, rapports manquants et statuts inconnus restent en attente. Les anciens paris non proposes sur INTERNET sont identifies et exclus des mises, sans remboursement fictif. Aucun ROI global n'est publie tant que le perimetre journalise contient un cas non resolu. Les selections absentes du journal ne sont jamais reconstruites depuis les CSV ni comptees comme des echecs. Le bilan concerne uniquement les messages journalises, pas toutes les courses de la journee.

Les alertes outsider et leur variante simulee sont documentees dans `EXPERIENCE-OUTSIDER.md`. Elles sont conservees dans les recus Telegram et comparees sur les memes courses et les memes mises, separement du bilan des paris effectivement conseilles.

Les scripts sauvegardent le journal en Git apres chaque execution ; les jobs disposent aussi d'un artefact de secours de 90 jours. Une erreur de sauvegarde fait echouer le job : recuperer l'artefact avant de valider un bilan de cette date. Ne pas melanger les anciens `audit_*.csv` estimes avec `resultats/bilans/bilan_*.json`.

Dans Actions / PMU Daily :
- `verification` lance les tests sans Telegram et sans API PMU.
- `results`, `date_bilan=AAAAMMJJ`, `dry_run=true` recalcule une date sans envoyer de message, et sauvegarde le rapport en artefact.
- `results` sans date traite aujourd'hui (Europe/Paris) ; `dry_run=false` envoie le bilan habituel.
- Un resultat en attente peut etre recalcule en relancant `results` pour la meme date.

Les jours anterieurs a la journalisation n'ont pas de preuve complete d'envoi. Le programme le signale au lieu de reproduire les profits de l'ancien simulateur.

Tests locaux : `python -m unittest -v test_pmu_tracking.py`.

