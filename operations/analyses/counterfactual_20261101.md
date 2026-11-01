# Hypothèse du 1 novembre 2026 — point à 18 h 17, Paris

**Ce recalcul ne constitue aucun engagement. Il ne modifie aucun compte.**

Source des choix : derniers aperçus envoyés sur Telegram avant chaque départ,
conservés dans les trois `data/notifications.json` au commit
`cee315a47a064b168bec99857369498911e7f451`.
Hypothèses : mêmes premiers choix au contrôle final, sources/chevaux encore
disponibles, rapports précédents disponibles avant la course admissible suivante.
Ces conditions n'ont pas toutes été vérifiées à l'époque : les contrôles ont
manqué. Il ne s'agit donc pas de paris historiquement confirmés.

Progression après pertes : 100, 200, 150, 150, 200 euros, puis arrêt ; plafond
1 200 euros. Victoire : retour au palier 100 euros. +200 euros sans arrêt.

## Toute la journée, depuis C1

| Course | Premier choix admissible | Tony classique | Tony 2 | Tony 3/5 | Résultat du choix |
|---|---|---:|---:|---:|---|
| C1 | 3 MASSA DAIRPET (3/5 seulement) | — | — | 100 € | 4e, perdu SG |
| C2 | Aucun accord suffisant | — | — | — | Non joué |
| C3 | 5 MILAN SAN REMO | 100 € | 100 € | 200 € | Disqualifié, perdu |
| C4 | 4 LAROZE DU GERS | 200 € | 200 € | 150 € | Disqualifié, perdu |
| C5 | 7 KOH LANTA (3/5 seulement) | — | — | 150 € | 3e, perdu SG |
| C6 | 10 LASKO DES BROUSSES | 150 € | 150 € | 200 € | Disqualifié, perdu |
| C7 | 16 LINNA DE VANDEL | 150 € | 150 € | Arrêt | Disqualifié, perdu |
| C8 | 8 MISTRAL EXPRESS (3/5 seulement) | — | — | Arrêt | 5e |
| C9 | 16 IMAGINE GIRL | 200 € potentiels | 200 € potentiels | Arrêt | À venir à 18 h 17 |

Tony 3/5 aurait terminé à **−800 €**, cinq pertes consécutives à C6, retours
0 €, ROI −100 %. Aucun pari hypothétique C7/C8/C9 après cet arrêt.

Tony classique et Tony 2 seraient chacun à **−600 €** avant C9, pour 600 €
réglés et zéro retour. C9 reste une mise potentielle de 200 € : si le n°16 perd,
le résultat hypothétique sera −800 € ; s'il gagne à un rapport brut D pour 1 €,
il sera 200 × D − 800 €. Aucun rapport n'est remplacé par une cote indicative.

## Seulement la séquence C4–C9 citée par l'utilisateur

En démarrant Tony 3/5 à zéro avant C4, les mises auraient été 100 € sur C4,
200 € sur C5, 150 € sur C6, 150 € sur C7, 200 € sur C8 : cinq paris perdants,
**−800 €**, puis arrêt avant C9. Ainsi, même dans ce périmètre plus restreint,
les paris manqués n'auraient pas créé de gain.

## Preuve et reproduction

`officials_20261101_1817.json` est une extraction des participants et rapports SG
PMU Internet consultés ; les URL sources y figurent. C9 est encore non réglée.
`counterfactual_20261101_1817.json` conserve les mises, résultats, identifiants
Telegram et empreintes des messages utilisés, séparément des fichiers `data`.

Recalcul en lecture seule :

```sh
python operations/analyses/replay_previews_20261101.py operations/analyses/officials_20261101_1817.json
```

Les paris effectivement envoyés après réparation sont distincts : C9 n°16,
100 € classique (reçu 6913), 200 € Tony 2 (6910), 200 € Tony 3/5 (6909),
confirmés vers 18 h 14 avant le départ annoncé de 18 h 25. Ces montants partent
des comptes réels de la simulation, sans intégrer les mises manquées.
