"""
Module de selection a 3 niveaux (a integrer dans pmu_scorer.py v15.2)

=== MODIF 26/05/2026 : recentrage sur la COTE BASSE ===
Analyse de 401 courses + cas reels (CELAGO, AMARIS, STEALITWITHAKISS) ont montre :
  - Au GALOP, le placement du N1 depend ENORMEMENT de sa cote :
      favori <2.5 place ~100% | 2.5-4 ~79% | 4-6 ~44% | 6-8 ~28% | >8 tres faible
  - Le critere le PLUS fiable = la cote basse. Les autres (score, ecart) sont
    moins fiables (certains sous-scores etaient morts).
  - Probleme constate : l'ancien filtre cote 2-8 laissait passer des N1 a 6-8
    (voire le score poussait des outsiders), qui placent peu.
DECISION : resserrer la fenetre de cote pour privilegier les favoris.
  COTE_MAX 8.0 -> 5.0 (au-dela, le placement s'effondre).
  Ajout d'un sous-niveau PEPITE pour les tres bas (<=4) = coeur de cible.
Ancienne valeur conservee en commentaire pour pouvoir revenir en arriere.

NIVEAUX (apres modif) :
  PEPITE  💎 : cote 2-4   + partants <=10                (coeur de cible, place le +)
  SOLIDE  🟢 : cote 2-5   + partants <=10 + ecart>=2
  CORRECT 🔵 : cote 2-5   + partants <=12
  (rien)     : cote >5 ou <2  = non affiche
"""

# Seuils des niveaux
COTE_MIN = 1.3          # MODIF 26/05 : etait 2.0 — un favori a 1.5-2.0 place ~100%,
                        # il ne faut SURTOUT pas le rejeter (cas STEALITWITHAKISS 1.5).
COTE_MAX = 5.0          # MODIF 26/05 : etait 8.0 (au-dela de 5, placement s'effondre)

PEPITE_COTE_MAX     = 4.0   # MODIF 26/05 : nouveau, coeur de cible "favori"
PEPITE_PARTANTS_MAX = 14    # MODIF 26/05 : etait 8 (assoupli, la cote basse prime sur le nb)
PEPITE_ECART_MIN    = 0.0   # MODIF 26/05 : etait 3.0 (la cote prime sur l'ecart)
PEPITE_SCORE_MIN    = 0.0   # MODIF 26/05 : etait 45.0 (score peu fiable, desactive)

SOLIDE_PARTANTS_MAX = 10
SOLIDE_ECART_MIN    = 2.0   # MODIF 26/05 : etait 3.0

CORRECT_PARTANTS_MAX = 12   # MODIF 26/05 : etait 10


def classer_niveau_course(course: dict) -> dict:
    """
    Classe une course dans un niveau selon son N1.
    Renvoie {'niveau': 'PEPITE'|'SOLIDE'|'CORRECT'|None, 'emoji': ..., 'raison': ...}
    """
    top5 = course.get("top5", [])
    if len(top5) < 1:
        return {"niveau": None, "emoji": "", "raison": "pas de top5"}

    n1 = top5[0]
    n2 = top5[1] if len(top5) > 1 else {}

    cote_n1     = n1.get("cote_jour", 0) or 0
    score_n1    = n1.get("score_total", 0) or 0
    score_n2    = n2.get("score_total", 0) or 0
    ecart       = score_n1 - score_n2
    nb_partants = n1.get("nb_partants", 0) or 0

    # Filtre eliminatoire : la cote DOIT etre dans 2-8
    if cote_n1 < COTE_MIN or cote_n1 > COTE_MAX:
        return {"niveau": None, "emoji": "",
                "raison": f"cote {cote_n1:.1f} hors {COTE_MIN}-{COTE_MAX}"}
    if nb_partants == 0 or nb_partants > CORRECT_PARTANTS_MAX:
        return {"niveau": None, "emoji": "",
                "raison": f"partants {nb_partants} > {CORRECT_PARTANTS_MAX}"}

    # PEPITE = coeur de cible : cote basse (favori). La cote prime.
    if (cote_n1 <= PEPITE_COTE_MAX
            and nb_partants <= PEPITE_PARTANTS_MAX
            and ecart >= PEPITE_ECART_MIN
            and score_n1 >= PEPITE_SCORE_MIN):
        return {"niveau": "PEPITE", "emoji": "💎",
                "raison": f"cote {cote_n1:.1f} (favori), {nb_partants} part."}

    # SOLIDE
    if (nb_partants <= SOLIDE_PARTANTS_MAX
            and ecart >= SOLIDE_ECART_MIN):
        return {"niveau": "SOLIDE", "emoji": "🟢",
                "raison": f"cote {cote_n1:.1f}, {nb_partants} part., ecart {ecart:.1f}"}

    # CORRECT
    return {"niveau": "CORRECT", "emoji": "🔵",
            "raison": f"cote {cote_n1:.1f}, {nb_partants} part."}


def identifier_couple_c(course: dict) -> dict:
    """
    Couple variante C : N1 (du scoring) + 2e favori du MARCHE
    (le cheval avec la 2e cote la plus basse, hors N1).
    Renvoie {'n1': {...}, 'fav2_marche': {...}} ou None si impossible.
    """
    tous = course.get("tous_resultats", []) or course.get("top5", [])
    if len(tous) < 2:
        return None

    n1 = course["top5"][0]
    n1_num = n1.get("num_partant")

    # Chevaux avec cote valide, hors N1
    avec_cote = [
        c for c in tous
        if (c.get("cote_jour", 0) or 0) > 0 and c.get("num_partant") != n1_num
    ]
    if not avec_cote:
        return None

    # Le 2e favori marche = plus basse cote parmi les autres
    fav2 = sorted(avec_cote, key=lambda c: c.get("cote_jour", 999))[0]

    return {"n1": n1, "fav2_marche": fav2}


def choisir_cheval_a_jouer(course: dict, ecart_cote_max: float = 6.0) -> dict:
    """
    MODIF 26/05/2026 — RÈGLE LA MIEUX VALIDÉE (sur 401 courses) :
    Entre nos 2 meilleurs choix (top5[0] et top5[1]), JOUER CELUI DONT LA COTE
    EST LA PLUS BASSE. Mesure : jouer la cote la + basse place +6 a +10 points
    de plus que jouer le N1 par defaut (galop 49% vs 40%, trot 34% vs 27%).

    Renvoie le cheval recommande a jouer en simple place, avec la raison.
    ecart_cote_max : si les 2 cotes sont tres eloignees, on fait quand meme
    confiance a la cote basse (la regle tient a tous les ecarts mesures).

    N'ALTERE PAS le scoring : c'est une aide a la DECISION, calculee a part.
    A utiliser dans le notifier pour afficher "cheval conseille".
    """
    top5 = course.get("top5", [])
    if not top5:
        return {}
    n1 = top5[0]
    n2 = top5[1] if len(top5) > 1 else None
    c1 = n1.get("cote_jour", 0) or 0
    if not n2:
        return {"cheval": n1, "raison": "seul choix"}
    c2 = n2.get("cote_jour", 0) or 0
    # On joue la cote la plus basse (si dispo)
    if c2 > 0 and (c1 <= 0 or c2 < c1):
        return {"cheval": n2, "raison": f"cote plus basse ({c2:.1f} < {c1:.1f}) = +fiable",
                "inverse": True}
    return {"cheval": n1, "raison": f"cote la plus basse ({c1:.1f})", "inverse": False}


# ──────────────────────────────────────────────
#  TEST
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # Jeux de test
    tests = [
        {
            "nom": "PEPITE attendue",
            "top5": [
                {"cote_jour": 4.5, "score_total": 48, "nb_partants": 7, "num_partant": "3"},
                {"cote_jour": 8.0, "score_total": 40, "nb_partants": 7, "num_partant": "5"},
            ],
            "tous_resultats": [
                {"cote_jour": 4.5, "score_total": 48, "num_partant": "3"},
                {"cote_jour": 3.2, "score_total": 40, "num_partant": "5"},
                {"cote_jour": 6.0, "score_total": 35, "num_partant": "8"},
            ],
        },
        {
            "nom": "SOLIDE attendue (12 part -> non, 10 ok)",
            "top5": [
                {"cote_jour": 5.0, "score_total": 42, "nb_partants": 10, "num_partant": "1"},
                {"cote_jour": 7.0, "score_total": 38, "nb_partants": 10, "num_partant": "2"},
            ],
            "tous_resultats": [
                {"cote_jour": 5.0, "score_total": 42, "num_partant": "1"},
                {"cote_jour": 4.0, "score_total": 38, "num_partant": "2"},
            ],
        },
        {
            "nom": "CORRECT attendue (ecart faible)",
            "top5": [
                {"cote_jour": 6.0, "score_total": 40, "nb_partants": 9, "num_partant": "4"},
                {"cote_jour": 7.0, "score_total": 39, "nb_partants": 9, "num_partant": "6"},
            ],
            "tous_resultats": [
                {"cote_jour": 6.0, "score_total": 40, "num_partant": "4"},
                {"cote_jour": 5.5, "score_total": 39, "num_partant": "6"},
            ],
        },
        {
            "nom": "REJET (cote 15 hors zone)",
            "top5": [
                {"cote_jour": 15.0, "score_total": 50, "nb_partants": 7, "num_partant": "9"},
                {"cote_jour": 20.0, "score_total": 30, "nb_partants": 7, "num_partant": "10"},
            ],
            "tous_resultats": [],
        },
        {
            "nom": "REJET (16 partants)",
            "top5": [
                {"cote_jour": 5.0, "score_total": 50, "nb_partants": 16, "num_partant": "11"},
                {"cote_jour": 7.0, "score_total": 40, "nb_partants": 16, "num_partant": "12"},
            ],
            "tous_resultats": [],
        },
    ]

    print("=== TEST classer_niveau_course ===\n")
    for t in tests:
        res = classer_niveau_course(t)
        niveau = res["niveau"] or "REJET"
        print(f"{t['nom']:40} -> {res['emoji']} {niveau:8} ({res['raison']})")

    print("\n=== TEST identifier_couple_c ===\n")
    for t in tests[:3]:
        cpl = identifier_couple_c(t)
        if cpl:
            n1 = cpl["n1"]
            f2 = cpl["fav2_marche"]
            print(f"{t['nom']:40} -> Couple N{n1.get('num_partant')} (cote {n1.get('cote_jour')}) "
                  f"+ N{f2.get('num_partant')} (cote {f2.get('cote_jour')}, 2e fav marche)")
        else:
            print(f"{t['nom']:40} -> pas de couple possible")
