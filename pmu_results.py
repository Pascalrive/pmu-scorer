"""
=============================================================
  PMU RESULTS v4 - Bilan du soir + Simulation des gains
=============================================================
  Nouveautes v4 :
    - Simulation 3 strategies de jeu :
        P1 : Simple Place 1.50e sur N1 (CONSENSUS FORT)
        P2 : Couple Place 1.50e N1+N2 (score N1 > 50%)
        P3 : 2sur4 3e avec N1+N2 fixes (top5 coherent)
    - Rapport reel recupere via API PMU
    - Affichage : "Pour X euros investi vous auriez gagne X euros"
    - Bilan financier cumule sur la journee
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

# Mises par strategie
MISE_P1 = 1.50
MISE_P2 = 1.50
MISE_P3 = 3.00

# Seuils de declenchement
SEUIL_P1_SCORE   = 40.0
SEUIL_P1_SOURCES = 1
SEUIL_P2_SCORE   = 50.0
SEUIL_P3_ECART   = 3.0

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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/4.0)",
    "Accept": "application/json",
}


def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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
    r = {
        "simple_gagnant": 0.0, "simple_place": 0.0,
        "couple_gagnant": 0.0, "couple_place": 0.0,
        "deux_sur_quatre": 0.0,
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
            elif "COUPLE_GAGNANT" in tp:
                r["couple_gagnant"] = val
            elif "COUPLE_PLACE" in tp:
                r["couple_place"] = val
            elif "DEUX_SUR_QUATRE" in tp or "2SUR4" in tp:
                r["deux_sur_quatre"] = val
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
                    "libelle":        r.get("libelle", ""),
                    "discipline":     r.get("discipline", ""),
                    "nom_cheval":     r.get("nom_cheval", ""),
                    "num_partant":    r.get("num_partant", ""),
                    "cote_jour":      float(r.get("cote_jour", 0) or 0),
                    "score_total":    float(r.get("score_total", 0) or 0),
                    "nb_pronostics":  int(float(r.get("nb_pronostics", 0) or 0)),
                    "pct_pronostics": float(r.get("pct_pronostics", 0) or 0),
                    "nb_sources":     int(float(r.get("nb_sources_total", 0) or 0)),
                    "value_bet":      r.get("value_bet", "False") == "True",
                    "consensus_fort": r.get("consensus_fort", "False") == "True",
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


def evaluer_strategies(chevaux) -> dict:
    if not chevaux or len(chevaux) < 2:
        return {}
    n1, n2 = chevaux[0], chevaux[1]
    n3 = chevaux[2] if len(chevaux) > 2 else None
    n4 = chevaux[3] if len(chevaux) > 3 else None
    strategies = {}

    # P1 - Simple Place
    if (n1.get("consensus_fort") or
            (n1["score_total"] >= SEUIL_P1_SCORE
             and n1["nb_pronostics"] >= SEUIL_P1_SOURCES)):
        raison = ("CONSENSUS FORT" if n1.get("consensus_fort")
                  else f"Score {n1['score_total']:.1f}% + {n1['nb_pronostics']} source(s)")
        strategies["P1"] = {
            "label": "Simple Place N1", "mise": MISE_P1,
            "cheval1": n1["nom_cheval"], "raison": raison,
        }

    # P2 - Couple Place
    if n1["score_total"] >= SEUIL_P2_SCORE and n1["nb_sources"] > 0:
        strategies["P2"] = {
            "label": "Couple Place N1+N2", "mise": MISE_P2,
            "cheval1": n1["nom_cheval"], "cheval2": n2["nom_cheval"],
            "raison": f"Score N1 {n1['score_total']:.1f}% + pronostics confirmes",
        }

    # P3 - 2sur4
    if n3 and n4 and (n3["score_total"] - n4["score_total"]) >= SEUIL_P3_ECART:
        strategies["P3"] = {
            "label": "2sur4 N1+N2 fixes", "mise": MISE_P3,
            "cheval1": n1["nom_cheval"], "cheval2": n2["nom_cheval"],
            "raison": f"Top5 coherent | ecart N3-N4: {n3['score_total']-n4['score_total']:.1f} pts",
        }
    return strategies


def get_place(cheval, resultats):
    if not cheval:
        return None
    return (resultats.get(cheval["nom_cheval"].upper())
            or resultats.get(str(cheval["num_partant"])))


def simuler_p1(place_n1, nb_partants, rapports, mise):
    if not place_n1:
        return 0.0, "Non disponible"
    limite = 2 if nb_partants <= 7 else 3
    if place_n1 == 1:
        rap = rapports["simple_gagnant"]
        gain = rap * mise if rap > 0 else mise * 3.5
        label = f"GAGNANT — {rap:.1f}x → +{gain:.2f}e" if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e"
        return gain, label
    elif place_n1 <= limite:
        rap = rapports["simple_place"]
        gain = rap * mise if rap > 0 else mise * 1.3
        label = f"PLACE ({place_n1}e) — {rap:.1f}x → +{gain:.2f}e" if rap > 0 else f"PLACE ({place_n1}e) — estim. +{gain:.2f}e"
        return gain, label
    return 0.0, f"Rate ({place_n1}e) — 0e"


def simuler_p2(place_n1, place_n2, nb_partants, rapports, mise):
    if nb_partants < 8:
        return None, f"Non dispo ({nb_partants} partants < 8)"
    if not place_n1 or not place_n2:
        return 0.0, "Non disponible"
    if place_n1 <= 3 and place_n2 <= 3:
        rap = rapports["couple_place"]
        gain = rap * mise if rap > 0 else mise * 4.0
        label = f"GAGNANT ({place_n1}e+{place_n2}e) — {rap:.1f}x → +{gain:.2f}e" if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e"
        return gain, label
    return 0.0, f"Rate ({place_n1}e/{place_n2}e) — 0e"


def simuler_p3(places, rapports, mise):
    if not places or len(places) < 2 or not places[0] or not places[1]:
        return 0.0, "Non disponible"
    if places[0] <= 4 and places[1] <= 4:
        rap = rapports["deux_sur_quatre"]
        gain = rap * mise if rap > 0 else mise * 3.0
        label = f"GAGNANT (top4) — {rap:.1f}x → +{gain:.2f}e" if rap > 0 else f"GAGNANT — estim. +{gain:.2f}e"
        return gain, label
    return 0.0, f"Rate (N1:{places[0]}e, N2:{places[1]}e) — 0e"


def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")
    heure_run     = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS v4 - Bilan du {date_aff} - {heure_run}")
    log.info("=" * 70)

    telegram_send(
        f"PMU Bilan du soir - {date_aff} {heure_run}\n"
        "Comparaison pronostics + simulation gains..."
    )

    courses = lire_pronostics_du_jour(date_str_fich)
    if not courses:
        telegram_send(f"PMU Bilan {date_aff} - Aucun pronostic du jour trouve.")
        return

    lignes_res  = []
    lignes_sim  = []
    nb_courses  = nb_g1 = nb_pl1 = nb_top2 = 0
    sim = {k: {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0}
           for k in ("P1", "P2", "P3")}

    for (reunion, course), chevaux in sorted(courses.items()):
        nr, nc   = chevaux[0]["nr"], chevaux[0]["nc"]
        n1       = chevaux[0]
        n2       = chevaux[1] if len(chevaux) > 1 else None
        disc     = n1.get("discipline", "").replace("_", " ")
        libelle  = n1.get("libelle", "")
        terrain  = n1.get("terrain", "")
        hippodrome = n1.get("hippodrome", "")

        resultats = get_resultats_course(date_str, nr, nc)
        rapports  = get_rapports(date_str, nr, nc)
        nb_part   = get_nb_partants(date_str, nr, nc)
        time.sleep(0.5)

        terrain_str = f" | {terrain}" if terrain else ""
        lignes_res.append(f"\n{reunion} {course} | {disc}{terrain_str}")
        if libelle:
            lignes_res.append(f"  {libelle[:45]}")
        if hippodrome:
            lignes_res.append(f"  {hippodrome}")

        if not resultats:
            lignes_res.append("  Resultats non encore disponibles")
            continue

        nb_courses += 1
        limite = 2 if nb_part <= 7 else 3

        p1_place = get_place(n1, resultats)
        p2_place = get_place(n2, resultats) if n2 else None
        places5  = [get_place(ch, resultats) for ch in chevaux[:5]]

        # Statut N1
        if p1_place == 1:
            s1 = "GAGNANT !!!"
            nb_g1 += 1
        elif p1_place and p1_place <= limite:
            s1 = f"{p1_place}e - Place"
            nb_pl1 += 1
        elif p1_place:
            s1 = f"{p1_place}e - Rate"
        else:
            s1 = "Non disponible"

        if p1_place == 1 or p2_place == 1:
            nb_top2 += 1

        vb = " [VALUE BET]" if n1.get("value_bet") else ""
        cf = " [CONSENSUS]" if n1.get("consensus_fort") else ""
        nb_src = n1.get("nb_sources", 0)

        lignes_res.append(f"  1. {n1['nom_cheval']} (cote {n1['cote_jour']:.1f}){vb}{cf} -> {s1}")
        if nb_src > 0:
            lignes_res.append(f"     {n1['nb_pronostics']}/{nb_src} sources | Score: {n1['score_total']:.1f}%")
        else:
            lignes_res.append(f"     Score: {n1['score_total']:.1f}%")
        if rapports["simple_gagnant"] > 0:
            lignes_res.append(f"     Rapport gagnant: {rapports['simple_gagnant']:.1f}x")

        if n2:
            if p2_place == 1:   s2 = "GAGNANT !!!"
            elif p2_place and p2_place <= limite: s2 = f"{p2_place}e - Place"
            elif p2_place:      s2 = f"{p2_place}e - Rate"
            else:               s2 = "Non disponible"
            lignes_res.append(f"  2. {n2['nom_cheval']} (cote {n2['cote_jour']:.1f}) -> {s2}")
            lignes_res.append(f"     Score: {n2['score_total']:.1f}%")

        # Simulation
        strats = evaluer_strategies(chevaux)
        if strats:
            sim_block = [f"\n{reunion} {course} | {libelle[:35]}"]

            if "P1" in strats:
                st = strats["P1"]
                gain, detail = simuler_p1(p1_place, nb_part, rapports, st["mise"])
                sim["P1"]["investi"] += st["mise"]
                sim["P1"]["retour"]  += gain
                sim["P1"]["nb"]      += 1
                if gain > 0: sim["P1"]["gagnes"] += 1
                sim_block.append(
                    f"  P1 Simple Place {st['mise']:.2f}e"
                    f" sur {st['cheval1'][:20]} : {detail}"
                )
                sim_block.append(f"     > {st['raison']}")

            if "P2" in strats and n2:
                st = strats["P2"]
                gain, detail = simuler_p2(p1_place, p2_place, nb_part, rapports, st["mise"])
                if gain is not None:
                    sim["P2"]["investi"] += st["mise"]
                    sim["P2"]["retour"]  += gain
                    sim["P2"]["nb"]      += 1
                    if gain > 0: sim["P2"]["gagnes"] += 1
                    sim_block.append(
                        f"  P2 Couple Place {st['mise']:.2f}e"
                        f" ({st['cheval1'][:14]}+{st['cheval2'][:14]}) : {detail}"
                    )
                    sim_block.append(f"     > {st['raison']}")

            if "P3" in strats:
                st = strats["P3"]
                gain, detail = simuler_p3(places5, rapports, st["mise"])
                sim["P3"]["investi"] += st["mise"]
                sim["P3"]["retour"]  += gain
                sim["P3"]["nb"]      += 1
                if gain > 0: sim["P3"]["gagnes"] += 1
                sim_block.append(
                    f"  P3 2sur4 {st['mise']:.2f}e : {detail}"
                )
                sim_block.append(f"     > {st['raison']}")

            lignes_sim.extend(sim_block)

        time.sleep(0.3)

    # ── Bilan ─────────────────────────────────────────────
    bilan = [
        "", "=" * 38,
        f"BILAN RESULTATS - {date_aff}",
        f"  Courses analysees  : {nb_courses}",
        f"  1er exact (N1)     : {nb_g1}/{nb_courses}  ({nb_g1/nb_courses*100:.0f}%)" if nb_courses else "  1er exact (N1) : 0",
        f"  Places top3 (N1)   : {nb_pl1}/{nb_courses}" if nb_courses else "",
        f"  Gagnant top2       : {nb_top2}/{nb_courses}  ({nb_top2/nb_courses*100:.0f}%)" if nb_courses else "",
        "", "=" * 38,
        f"SIMULATION GAINS - {date_aff}",
        "(Si vous aviez joue selon nos 3 strategies)", "",
    ]

    total_i = total_r = 0.0
    for code, label in [("P1","P1 Simple Place  1.50e"),
                         ("P2","P2 Couple Place  1.50e"),
                         ("P3","P3 2sur4         3.00e")]:
        s = sim[code]
        if s["nb"] == 0:
            bilan.append(f"  {label} : aucun signal aujourd hui")
            continue
        profit = s["retour"] - s["investi"]
        roi    = profit / s["investi"] * 100 if s["investi"] > 0 else 0
        sgn    = "+" if profit >= 0 else ""
        bilan += [
            f"  {label}",
            f"    {s['nb']} pari(s) | {s['gagnes']} gagne(s)",
            f"    Investi : {s['investi']:.2f}e   Retour : {s['retour']:.2f}e",
            f"    Profit  : {sgn}{profit:.2f}e   ROI {sgn}{roi:.0f}%",
            "",
        ]
        total_i += s["investi"]
        total_r += s["retour"]

    tp = total_r - total_i
    sgn_t = "+" if tp >= 0 else ""
    roi_t = tp / total_i * 100 if total_i > 0 else 0
    bilan += [
        "─" * 35,
        f"  TOTAL INVESTI  : {total_i:.2f}e",
        f"  TOTAL RETOUR   : {total_r:.2f}e",
        f"  PROFIT NET     : {sgn_t}{tp:.2f}e",
        f"  ROI GLOBAL     : {sgn_t}{roi_t:.0f}%",
        "", "Outil statistique - Jouer responsable.",
    ]

    # Envoi en 3 messages
    msg1 = (f"PMU France - Bilan du {date_aff}\n"
            f"Pronostics vs Resultats\n" + "=" * 38
            + "\n".join(lignes_res))
    telegram_send(msg1)
    time.sleep(1)

    if lignes_sim:
        msg2 = (f"SIMULATION DETAILLEE - {date_aff}\n" + "=" * 38
                + "\n".join(lignes_sim))
        telegram_send(msg2)
        time.sleep(1)

    telegram_send("\n".join(bilan))

    log.info("Bilan v4 envoye.")
    log.info("=" * 70)
    log.info("  RESULTS v4 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
