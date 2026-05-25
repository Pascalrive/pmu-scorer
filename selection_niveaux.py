"""
Module de selection a 3 niveaux (a integrer dans pmu_scorer.py v15.2)
Base sur l'analyse de 401 paris (12-24/05/2026) :
  - Cote 2-8 = zone rentable (ROI +37 a +71%)
  - Partants <= 10 (ideal <=8) = ROI +62 a +89%
  - Ecart N1/N2 >= 3 = meilleure separation
  - Score N1 >= 45 = signal solide

NIVEAUX :
  PEPITE  💎 : cote 2-8 + partants <=8  + ecart>=3 + score>=45
  SOLIDE  🟢 : cote 2-8 + partants <=10 + ecart>=3
  CORRECT 🔵 : cote 2-8 + partants <=10
  (rien)     : tout le reste = non affiche
"""

# Seuils des niveaux
COTE_MIN = 2.0
COTE_MAX = 8.0

PEPITE_PARTANTS_MAX = 8
PEPITE_ECART_MIN    = 3.0
PEPITE_SCORE_MIN    = 45.0

SOLIDE_PARTANTS_MAX = 10
SOLIDE_ECART_MIN    = 3.0

CORRECT_PARTANTS_MAX = 10


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

    # PEPITE
    if (nb_partants <= PEPITE_PARTANTS_MAX
            and ecart >= PEPITE_ECART_MIN
            and score_n1 >= PEPITE_SCORE_MIN):
        return {"niveau": "PEPITE", "emoji": "💎",
                "raison": f"cote {cote_n1:.1f}, {nb_partants} part., ecart {ecart:.1f}, score {score_n1:.0f}"}

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
