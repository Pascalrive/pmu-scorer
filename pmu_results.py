"""
=============================================================
  PMU RESULTS v7 - Bilan + 4 strategies en parallele
=============================================================
  Changements v6 -> v7 :
    - Simule 4 strategies en parallele :
        P1 : Simple Place 5e brut (baseline, tous les N1)
        V2A : Simple Place 5e si V2 ACTUEL = PRUDENT/FORT
        V2N : Simple Place 5e si V2 NOUVEAU (Cote 3-8 + Partants <= 10)
        V2N+C : Simple 5e + Couple 5e (10e/course retenue) sur V2 NOUVEAU
                Couple Gagnant si partants <= 7
                Couple Place si partants >= 8
    - CSV audit etendu avec colonnes des 4 strategies
    - Bilan Telegram avec tableau comparatif

  Base sur l'analyse des 200 paris du 12-18/05/2026 :
  - Cote 3-8 : 57% places, ROI +37%
  - Partants <= 10 : 67% places, ROI +89% (sur petit echantillon)
=============================================================
"""

import csv
import glob
import logging
import os
import time
from datetime import datetime

import requests

BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
OUTPUT_DIR     = "resultats"

# Mises (v7 : 5e Simple + 5e Couple si applicable = 10e/course retenue)
MISE_SIMPLE = 5.00
MISE_COUPLE = 5.00

# ── V2 ACTUEL (depuis v6) ─────────────────────────────
V2A_SCORE_MIN_PRUDENT = 40.0
V2A_SCORE_MIN_FORT    = 50.0
V2A_ECART_MIN_PRUDENT = 2.0
V2A_ECART_MIN_FORT    = 5.0
V2A_COTE_MIN          = 1.8
V2A_COTE_MAX          = 15.0
V2A_PARTANTS_MAX      = 15
V2A_SOURCES_MIN_FORT  = 2

# ── V2 NOUVEAU (issu de l'analyse 200 paris) ──────────
# Filtre principal : Cote 3-8 + Partants <= 10 (les 2 plus gros signaux)
# Garde-fou : Score >= 35 et Ecart >= 1 (basiques)
V2N_COTE_MIN          = 3.0
V2N_COTE_MAX          = 8.0
V2N_PARTANTS_MAX      = 10
V2N_PARTANTS_MAX_PRUDENT = 13
V2N_SCORE_MIN         = 35.0
V2N_ECART_MIN         = 1.0
V2N_SCORE_FORT        = 45.0
V2N_PARTANTS_FORT     = 8

# Rapports estimes en l'absence de rapports reels
RAPPORT_COUPLE_GAGNANT_FORFAIT = 8.0
RAPPORT_COUPLE_PLACE_FORFAIT   = 4.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pmu_results.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("pmu_results")

HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/7.0)",
    "Accept": "application/json",
}


# ──────────────────────────────────────────────
#  TELEGRAM
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    morceaux = [texte[i:i+4096] for i in range(0, len(texte), 4096)]
    succes = True
    for morceau in morceaux:
        try:
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": morceau}, timeout=15)
            if r.status_code != 200:
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Telegram: {e}")
            succes = False
    return succes


def api_get(path: str):
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Reseau: {e}")
        return None


def get_resultats_course(date_str, nr, nc) -> dict:
    """Renvoie {nom_upper: position, num_str: position}"""
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if not data or not isinstance(data, dict):
        return {}
    res = {}
    for p in data.get("participants", []):
        num   = p.get("numPmu") or p.get("numero")
        nom   = p.get("nom", "")
        place = p.get("ordreArrivee") or p.get("place")
        if num and place:
            try: res[str(num)] = int(place)
            except: pass
        if nom and place:
            try: res[nom.upper()] = int(place)
            except: pass
    return res


def get_rapports(date_str, nr, nc) -> dict:
    """Rapports reels PMU."""
    r = {
        "simple_gagnant": 0.0,
        "simple_place": 0.0,
        "couple_gagnant": 0.0,
        "couple_place": 0.0,
    }
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/rapports-definitifs")
    if not data:
        return r
    try:
        for rap in (data.get("rapports", []) if isinstance(data, dict) else []):
            tp     = rap.get("typePari", "").upper()
            combis = rap.get("combinaisons", [])
            if not combis:
                continue
            val = float(combis[0].get("rapport", 0) or 0) / 100
            if "SIMPLE_GAGNANT" in tp:
                r["simple_gagnant"] = val
            elif "SIMPLE_PLACE" in tp and r["simple_place"] == 0:
                r["simple_place"] = val
            elif "COUPLE_GAGNANT" in tp and r["couple_gagnant"] == 0:
                r["couple_gagnant"] = val
            elif "COUPLE_PLACE" in tp and r["couple_place"] == 0:
                r["couple_place"] = val
    except Exception as e:
        log.warning(f"Rapports: {e}")
    return r


def get_nb_partants(date_str, nr, nc) -> int:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if not data or not isinstance(data, dict):
        return 0
    return len([p for p in data.get("participants", [])
                if p.get("statut") != "NON_PARTANT"])


def lire_pronostics_du_jour(date_str_fichier: str) -> dict:
    pattern  = os.path.join(OUTPUT_DIR, f"pmu_{date_str_fichier}_*.csv")
    fichiers = sorted(glob.glob(pattern))
    if not fichiers:
        log.warning(f"Aucun CSV pour {date_str_fichier}")
        return {}
    fichier = fichiers[-1]
    log.info(f"Lecture : {fichier}")
    courses = {}
    try:
        with open(fichier, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        grouped = {}
        for row in rows:
            cle = (row.get("reunion", ""), row.get("course", ""))
            grouped.setdefault(cle, []).append(row)
        for cle, partants in grouped.items():
            tries = sorted(partants,
                           key=lambda x: float(x.get("score_total", 0) or 0),
                           reverse=True)
            courses[cle] = [
                {
                    "reunion":        r.get("reunion", ""),
                    "course":         r.get("course", ""),
                    "hippodrome":     r.get("hippodrome", ""),
                    "terrain":        r.get("terrain", ""),
                    "libelle":        r.get("libelle", ""),
                    "discipline":     r.get("discipline", ""),
                    "type_course":    r.get("type_course_details", ""),
                    "distance_m":     r.get("distance_m", ""),
                    "nb_partants":    int(float(r.get("nb_partants", 0) or 0)),
                    "nom_cheval":     r.get("nom_cheval", ""),
                    "num_partant":    r.get("num_partant", ""),
                    "cote_jour":      float(r.get("cote_jour", 0) or 0),
                    "cote_veille":    float(r.get("cote_veille", 0) or 0),
                    "variation_cote": r.get("variation_cote_%", ""),
                    "score_total":    float(r.get("score_total", 0) or 0),
                    "nb_pronostics":  int(float(r.get("nb_pronostics", 0) or 0)),
                    "pct_pronostics": float(r.get("pct_pronostics", 0) or 0),
                    "nb_sources":     int(float(r.get("nb_sources_total", 0) or 0)),
                    "value_bet":      r.get("value_bet", "False") == "True",
                    "consensus_fort": r.get("consensus_fort", "False") == "True",
                    "jockey":         r.get("jockey", ""),
                    "entraineur":     r.get("entraineur", ""),
                    "rang":           i + 1,
                    "nr":             r.get("reunion", "R0").replace("R", ""),
                    "nc":             r.get("course", "C0").replace("C", ""),
                }
                for i, r in enumerate(tries[:5])
            ]
    except Exception as e:
        log.error(f"Lecture CSV: {e}")
    log.info(f"{len(courses)} courses chargees.")
    return courses


def get_place(cheval, resultats):
    if not cheval:
        return None
    return (resultats.get(cheval["nom_cheval"].upper())
            or resultats.get(str(cheval["num_partant"])))


# ──────────────────────────────────────────────
#  SIMULATEURS DE STRATEGIES
# ──────────────────────────────────────────────
def simuler_simple_place(place_n1, nb_partants, rapports, mise):
    """Simule un Simple Place sur N1. Renvoie (gain, label)."""
    if not place_n1:
        return 0.0, "Non disponible"
    limite = 2 if nb_partants <= 7 else 3
    if place_n1 == 1:
        rap = rapports["simple_gagnant"]
        gain = rap * mise if rap > 0 else mise * 3.5
        label = (f"GAGNANT — {rap:.1f}x → +{gain:.2f}e"
                 if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e")
        return gain, label
    elif place_n1 <= limite:
        rap = rapports["simple_place"]
        gain = rap * mise if rap > 0 else mise * 1.3
        label = (f"PLACE ({place_n1}e) — {rap:.1f}x → +{gain:.2f}e"
                 if rap > 0 else f"PLACE ({place_n1}e) — estim. +{gain:.2f}e")
        return gain, label
    return 0.0, f"Rate ({place_n1}e) — 0e"


def simuler_couple(place_n1, place_n2, nb_partants, rapports, mise):
    """
    Simule un Couple :
      - Si nb_partants <= 7 : Couple Gagnant (les 2 dans le top 2)
      - Si nb_partants >= 8 : Couple Place (les 2 dans le top 3)

    Renvoie (gain, label, type_couple).
    """
    if not place_n1 or not place_n2:
        type_c = "G" if nb_partants <= 7 else "P"
        return 0.0, "Non disponible", type_c

    if nb_partants <= 7:
        # Couple Gagnant : les 2 chevaux doivent etre dans le top 2
        type_c = "G"
        if place_n1 <= 2 and place_n2 <= 2:
            rap = rapports["couple_gagnant"]
            gain = rap * mise if rap > 0 else mise * RAPPORT_COUPLE_GAGNANT_FORFAIT
            label = (f"GAGNANT — {rap:.1f}x → +{gain:.2f}e"
                     if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e")
            return gain, label, type_c
        return 0.0, f"Rate (N1:{place_n1}e, N2:{place_n2}e) — 0e", type_c
    else:
        # Couple Place : les 2 chevaux doivent etre dans le top 3
        type_c = "P"
        if place_n1 <= 3 and place_n2 <= 3:
            rap = rapports["couple_place"]
            gain = rap * mise if rap > 0 else mise * RAPPORT_COUPLE_PLACE_FORFAIT
            label = (f"GAGNANT ({place_n1}e+{place_n2}e) — {rap:.1f}x → +{gain:.2f}e"
                     if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e")
            return gain, label, type_c
        return 0.0, f"Rate (N1:{place_n1}e, N2:{place_n2}e) — 0e", type_c


# ──────────────────────────────────────────────
#  DECISIONS V2 (ANCIEN ET NOUVEAU)
# ──────────────────────────────────────────────
def decision_v2_actuel(score_n1, score_n2, ecart, cote_n1, nb_partants, nb_sources):
    """V2 actuel (depuis v6) : PARI FORT / PRUDENT / NO BET."""
    manquant = []
    if score_n2 is None or score_n2 <= 0: manquant.append("score_n2")
    if cote_n1 is None or cote_n1 <= 0:   manquant.append("cote_n1")
    if nb_partants is None or nb_partants <= 0: manquant.append("nb_partants")
    if manquant:
        return "DONNEES INSUFFISANTES", f"Manque: {','.join(manquant)}"

    if score_n1 < V2A_SCORE_MIN_PRUDENT:
        return "NO BET", f"Score < {V2A_SCORE_MIN_PRUDENT}"
    if ecart < V2A_ECART_MIN_PRUDENT:
        return "NO BET", f"Ecart < {V2A_ECART_MIN_PRUDENT}"
    if cote_n1 < V2A_COTE_MIN or cote_n1 > V2A_COTE_MAX:
        return "NO BET", f"Cote hors {V2A_COTE_MIN}-{V2A_COTE_MAX}"
    if nb_partants > V2A_PARTANTS_MAX:
        return "NO BET", f"Trop de partants"
    if nb_sources == 0:
        return "NO BET", "0 source"

    if (score_n1 >= V2A_SCORE_MIN_FORT
            and ecart >= V2A_ECART_MIN_FORT
            and nb_sources >= V2A_SOURCES_MIN_FORT):
        return "PARI FORT", f"Score {score_n1:.1f}, ecart {ecart:.1f}"
    return "PARI PRUDENT", f"OK score {score_n1:.1f}"


def decision_v2_nouveau(score_n1, score_n2, ecart, cote_n1, nb_partants):
    """
    V2 nouveau, base sur l'analyse de 200 paris reels :
      - Cote 3-8 = +37% ROI confirme
      - Partants <= 10 = +89% ROI (petit echantillon mais signal fort)

    PARI FORT : cote 3-8 + partants <= 8 + score >= 45 + ecart >= 1
    PARI PRUDENT : cote 3-8 + partants <= 13 + score >= 35 + ecart >= 1
    """
    if cote_n1 is None or cote_n1 <= 0:
        return "DONNEES INSUFFISANTES", "cote_n1=0"
    if nb_partants is None or nb_partants <= 0:
        return "DONNEES INSUFFISANTES", "nb_partants=0"

    # Filtre principal : la cote (le plus discriminant selon l'analyse)
    if cote_n1 < V2N_COTE_MIN or cote_n1 > V2N_COTE_MAX:
        return "NO BET", f"Cote hors {V2N_COTE_MIN}-{V2N_COTE_MAX}"

    # Garde-fous
    if score_n1 < V2N_SCORE_MIN:
        return "NO BET", f"Score < {V2N_SCORE_MIN}"
    if ecart < V2N_ECART_MIN:
        return "NO BET", f"Ecart < {V2N_ECART_MIN}"
    if nb_partants > V2N_PARTANTS_MAX_PRUDENT:
        return "NO BET", f"Partants > {V2N_PARTANTS_MAX_PRUDENT}"

    # FORT vs PRUDENT
    if (nb_partants <= V2N_PARTANTS_FORT
            and score_n1 >= V2N_SCORE_FORT):
        return "PARI FORT", (
            f"Cote {cote_n1:.1f}, partants {nb_partants}, score {score_n1:.1f}"
        )
    return "PARI PRUDENT", (
        f"Cote {cote_n1:.1f}, partants {nb_partants}"
    )


def position_dans_top_payant(position, nb_partants):
    if position is None:
        return None
    limite = 2 if nb_partants <= 7 else 3
    return position <= limite


# ──────────────────────────────────────────────
#  PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")
    heure_run     = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS v7 - Bilan du {date_aff} - {heure_run}")
    log.info(f"  Strategies : P1 + V2A + V2N + V2N+Couple")
    log.info("=" * 70)

    telegram_send(
        f"PMU Bilan v7 - {date_aff} {heure_run}\n"
        f"4 strategies en parallele\n"
        "Comparaison pronostics + simulation gains..."
    )

    courses = lire_pronostics_du_jour(date_str_fich)
    if not courses:
        telegram_send(f"PMU Bilan {date_aff} - Aucun pronostic du jour trouve.")
        return

    lignes_res = []
    lignes_sim = []
    nb_courses = nb_g1 = nb_pl1 = 0

    # 4 compteurs de strategies
    sim = {
        "P1":    {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},
        "V2A":   {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},
        "V2N":   {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},
        "V2N_S": {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},  # part simple du V2N+C
        "V2N_C": {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},  # part couple du V2N+C
    }

    # Compteurs decision V2 (pour info)
    cnt_v2a = {"PARI FORT": 0, "PARI PRUDENT": 0, "NO BET": 0, "DONNEES INSUFFISANTES": 0}
    cnt_v2n = {"PARI FORT": 0, "PARI PRUDENT": 0, "NO BET": 0, "DONNEES INSUFFISANTES": 0}

    audit_rows = []

    for (reunion, course), chevaux in sorted(courses.items()):
        nr, nc = chevaux[0]["nr"], chevaux[0]["nc"]
        n1 = chevaux[0]
        n2 = chevaux[1] if len(chevaux) > 1 else None
        disc = n1.get("discipline", "").replace("_", " ")
        libelle  = n1.get("libelle", "")
        terrain  = n1.get("terrain", "")
        hippodrome = n1.get("hippodrome", "")
        type_course = n1.get("type_course", "")

        resultats = get_resultats_course(date_str, nr, nc)
        rapports  = get_rapports(date_str, nr, nc)
        nb_part   = get_nb_partants(date_str, nr, nc)
        time.sleep(0.5)

        terrain_str = f" | {terrain}" if terrain else ""
        lignes_res.append(f"\n{reunion} {course} | {disc}{terrain_str}")
        if libelle:    lignes_res.append(f"  {libelle[:45]}")
        if hippodrome: lignes_res.append(f"  {hippodrome}")

        if not resultats:
            lignes_res.append("  Resultats non encore disponibles")
            continue

        nb_courses += 1
        limite = 2 if nb_part <= 7 else 3

        p1_place = get_place(n1, resultats)
        p2_place = get_place(n2, resultats) if n2 else None

        # Statut N1 pour le rapport
        if p1_place == 1:
            s1 = "GAGNANT !!!"
            nb_g1 += 1
            nb_pl1 += 1
        elif p1_place and p1_place <= limite:
            s1 = f"{p1_place}e - Place"
            nb_pl1 += 1
        elif p1_place:
            s1 = f"{p1_place}e - Rate"
        else:
            s1 = "Non disponible"

        nb_src = n1.get("nb_sources", 0)
        lignes_res.append(f"  1. {n1['nom_cheval']} (cote {n1['cote_jour']:.1f}) -> {s1}")
        lignes_res.append(f"     Score: {n1['score_total']:.1f}% | {nb_src} sources")
        if rapports["simple_gagnant"] > 0:
            lignes_res.append(f"     Rapports : SG {rapports['simple_gagnant']:.1f}x | SP {rapports['simple_place']:.1f}x")
        if rapports["couple_gagnant"] > 0 or rapports["couple_place"] > 0:
            cg = rapports["couple_gagnant"]
            cp = rapports["couple_place"]
            cg_str = f"CG {cg:.1f}x" if cg > 0 else ""
            cp_str = f"CP {cp:.1f}x" if cp > 0 else ""
            lignes_res.append(f"     {cg_str} {cp_str}".strip())

        if n2:
            s2 = "non disp."
            if p2_place == 1: s2 = "1er"
            elif p2_place and p2_place <= limite: s2 = f"{p2_place}e Place"
            elif p2_place: s2 = f"{p2_place}e"
            lignes_res.append(f"  2. {n2['nom_cheval']} (cote {n2['cote_jour']:.1f}) -> {s2}")

        # ── Variables communes pour les decisions
        score_n1 = n1.get("score_total", 0)
        score_n2 = n2.get("score_total", 0) if n2 else 0
        ecart    = score_n1 - score_n2
        cote_n1  = n1.get("cote_jour", 0)

        # ── 1. STRATEGIE P1 (baseline brute) ─────────────────
        gain_p1, label_p1 = simuler_simple_place(p1_place, nb_part, rapports, MISE_SIMPLE)
        sim["P1"]["investi"] += MISE_SIMPLE
        sim["P1"]["retour"]  += gain_p1
        sim["P1"]["nb"]      += 1
        if gain_p1 > 0: sim["P1"]["gagnes"] += 1

        # ── 2. DECISION V2 ACTUEL ──────────────────────────────
        dec_v2a, raison_v2a = decision_v2_actuel(
            score_n1, score_n2, ecart, cote_n1, nb_part, nb_src
        )
        cnt_v2a[dec_v2a] += 1
        gain_v2a = 0.0
        if dec_v2a in ("PARI FORT", "PARI PRUDENT"):
            sim["V2A"]["investi"] += MISE_SIMPLE
            sim["V2A"]["nb"]      += 1
            if gain_p1 > 0:
                sim["V2A"]["retour"] += gain_p1
                sim["V2A"]["gagnes"] += 1
                gain_v2a = gain_p1

        # ── 3. DECISION V2 NOUVEAU ─────────────────────────────
        dec_v2n, raison_v2n = decision_v2_nouveau(
            score_n1, score_n2, ecart, cote_n1, nb_part
        )
        cnt_v2n[dec_v2n] += 1

        gain_v2n_simple = 0.0
        gain_couple_brut = 0.0
        type_couple = ""
        if dec_v2n in ("PARI FORT", "PARI PRUDENT"):
            # Strategie V2N : Simple Place seul
            sim["V2N"]["investi"] += MISE_SIMPLE
            sim["V2N"]["nb"]      += 1
            if gain_p1 > 0:
                sim["V2N"]["retour"] += gain_p1
                sim["V2N"]["gagnes"] += 1
                gain_v2n_simple = gain_p1

            # Strategie V2N + Couple : Simple + Couple
            # Part Simple (deja calculee, on duplique le compteur)
            sim["V2N_S"]["investi"] += MISE_SIMPLE
            sim["V2N_S"]["nb"]      += 1
            if gain_p1 > 0:
                sim["V2N_S"]["retour"] += gain_p1
                sim["V2N_S"]["gagnes"] += 1

            # Part Couple
            gain_couple_brut, label_couple, type_couple = simuler_couple(
                p1_place, p2_place, nb_part, rapports, MISE_COUPLE
            )
            sim["V2N_C"]["investi"] += MISE_COUPLE
            sim["V2N_C"]["nb"]      += 1
            if gain_couple_brut > 0:
                sim["V2N_C"]["retour"] += gain_couple_brut
                sim["V2N_C"]["gagnes"] += 1

        # ── Bloc simulation pour Telegram ──────────────────────
        sim_block = [f"\n{reunion} {course} | {libelle[:35]}"]
        sim_block.append(f"  V2A: {dec_v2a} | V2N: {dec_v2n}")
        sim_block.append(
            f"  P1 Simple {MISE_SIMPLE:.0f}e {n1['nom_cheval'][:18]}: "
            f"{label_p1}"
        )
        if dec_v2n in ("PARI FORT", "PARI PRUDENT"):
            sim_block.append(
                f"  V2N+C Couple {type_couple} {MISE_COUPLE:.0f}e: {label_couple}"
            )
        lignes_sim.extend(sim_block)

        # ── Ligne audit (1 par course) ─────────────────────────
        audit_rows.append({
            "date":             date_aff,
            "reunion":          reunion,
            "course":           course,
            "hippodrome":       hippodrome,
            "discipline":       disc,
            "type_course":      type_course,
            "terrain":          terrain,
            "distance_m":       n1.get("distance_m", ""),
            "nb_partants":      nb_part,
            "limite_place":     limite,
            "n1_nom":           n1.get("nom_cheval", ""),
            "n1_num":           n1.get("num_partant", ""),
            "n1_score":         round(score_n1, 1),
            "n1_cote":          round(cote_n1, 2),
            "n1_position":     p1_place if p1_place else "",
            "n1_a_place":       1 if (p1_place and p1_place <= limite) else 0,
            "n1_a_gagne":       1 if p1_place == 1 else 0,
            "n2_nom":           n2.get("nom_cheval", "") if n2 else "",
            "n2_score":         round(score_n2, 1),
            "n2_cote":          round(n2.get("cote_jour", 0), 2) if n2 else 0,
            "n2_position":      p2_place if p2_place else "",
            "n2_a_place":       1 if (p2_place and p2_place <= limite) else 0,
            "ecart_n1_n2":      round(ecart, 1),
            "nb_sources":       nb_src,
            "rapport_simple_gagnant": round(rapports["simple_gagnant"], 2),
            "rapport_simple_place":   round(rapports["simple_place"], 2),
            "rapport_couple_gagnant": round(rapports["couple_gagnant"], 2),
            "rapport_couple_place":   round(rapports["couple_place"], 2),
            # Strategies
            "p1_mise":          MISE_SIMPLE,
            "p1_gain":          round(gain_p1, 2),
            "v2a_decision":     dec_v2a,
            "v2a_gain":         round(gain_v2a, 2),
            "v2n_decision":     dec_v2n,
            "v2n_gain":         round(gain_v2n_simple, 2),
            "couple_type":      type_couple,
            "couple_gain":      round(gain_couple_brut, 2),
        })

        time.sleep(0.3)

    # ── Export CSV audit ─────────────────────────────────
    chemin_audit = os.path.join(OUTPUT_DIR, f"audit_{date_str_fich}.csv")
    if audit_rows:
        colonnes = list(audit_rows[0].keys())
        with open(chemin_audit, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=colonnes)
            w.writeheader()
            w.writerows(audit_rows)
        log.info(f"CSV audit : {chemin_audit} ({len(audit_rows)} lignes)")

    # ── Bilan Telegram ───────────────────────────────────
    bilan = ["", "=" * 38, f"BILAN RESULTATS - {date_aff}"]
    if nb_courses > 0:
        bilan += [
            f"  Courses : {nb_courses}",
            f"  N1 1er : {nb_g1}/{nb_courses} ({nb_g1/nb_courses*100:.0f}%)",
            f"  N1 Place : {nb_pl1}/{nb_courses} ({nb_pl1/nb_courses*100:.0f}%)",
        ]

    def bloc_strategie(label, s):
        if s["nb"] == 0:
            return [f"  {label} : 0 pari"]
        profit = s["retour"] - s["investi"]
        roi = profit / s["investi"] * 100 if s["investi"] > 0 else 0
        sgn = "+" if profit >= 0 else ""
        taux = s["gagnes"] / s["nb"] * 100
        return [
            f"  {label}",
            f"    {s['nb']} paris | {s['gagnes']} gagnes ({taux:.0f}%)",
            f"    Inv {s['investi']:.0f}e | Ret {s['retour']:.2f}e | "
            f"Pft {sgn}{profit:.2f}e | ROI {sgn}{roi:.0f}%",
        ]

    bilan += ["", "=" * 38, f"SIMULATION 4 STRATEGIES - {date_aff}", ""]

    bilan += bloc_strategie("P1 - Simple Place 5e (baseline brut)", sim["P1"])
    bilan += [""]
    bilan += bloc_strategie("V2A - Simple Place 5e (V2 actuel)", sim["V2A"])
    bilan += [""]
    bilan += bloc_strategie("V2N - Simple Place 5e (V2 nouveau)", sim["V2N"])
    bilan += [""]

    # V2N+C : combinaison Simple + Couple sur memes courses
    bilan.append("  V2N+C - Simple 5e + Couple 5e")
    if sim["V2N_S"]["nb"] == 0:
        bilan.append("    0 pari retenu par V2N")
    else:
        invest_total = sim["V2N_S"]["investi"] + sim["V2N_C"]["investi"]
        retour_total = sim["V2N_S"]["retour"] + sim["V2N_C"]["retour"]
        profit_total = retour_total - invest_total
        roi_total = profit_total / invest_total * 100 if invest_total > 0 else 0
        sgn_t = "+" if profit_total >= 0 else ""
        bilan += [
            f"    {sim['V2N_S']['nb']} courses (Simple+Couple cumules)",
            f"    Part Simple : {sim['V2N_S']['gagnes']}/{sim['V2N_S']['nb']} gagnes, "
            f"profit {sim['V2N_S']['retour']-sim['V2N_S']['investi']:+.2f}e",
            f"    Part Couple : {sim['V2N_C']['gagnes']}/{sim['V2N_C']['nb']} gagnes, "
            f"profit {sim['V2N_C']['retour']-sim['V2N_C']['investi']:+.2f}e",
            f"    TOTAL : Inv {invest_total:.0f}e | Ret {retour_total:.2f}e | "
            f"Pft {sgn_t}{profit_total:.2f}e | ROI {sgn_t}{roi_total:.0f}%",
        ]

    bilan += [
        "", "=" * 38,
        "DECISIONS V2 (info)",
        f"  V2A : FORT={cnt_v2a['PARI FORT']} | PRUDENT={cnt_v2a['PARI PRUDENT']} | "
        f"NO BET={cnt_v2a['NO BET']} | INSUF={cnt_v2a['DONNEES INSUFFISANTES']}",
        f"  V2N : FORT={cnt_v2n['PARI FORT']} | PRUDENT={cnt_v2n['PARI PRUDENT']} | "
        f"NO BET={cnt_v2n['NO BET']} | INSUF={cnt_v2n['DONNEES INSUFFISANTES']}",
        "",
        f"CSV audit : audit_{date_str_fich}.csv",
        "",
        "Outil statistique - Jouer responsable.",
    ]

    # Envoi en 3 messages
    msg1 = (f"PMU France - Bilan du {date_aff}\n"
            f"Pronostics vs Resultats\n" + "=" * 38
            + "\n".join(lignes_res))
    telegram_send(msg1)
    time.sleep(1)

    if lignes_sim:
        msg2 = (f"SIMULATION DETAILLEE - {date_aff}\n"
                f"(P1 + V2A + V2N + V2N+Couple)\n" + "=" * 38
                + "\n".join(lignes_sim))
        telegram_send(msg2)
        time.sleep(1)

    telegram_send("\n".join(bilan))

    log.info("Bilan v7 envoye.")
    log.info("=" * 70)
    log.info("  RESULTS v7 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
