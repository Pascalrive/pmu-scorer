"""
=============================================================
  PMU RESULTS v6 - Bilan du soir + CSV d'AUDIT enrichi
=============================================================
  Changements v5 -> v6 :
    - Conservation strategie Simple Place N1 a 5 EUR
    - NOUVEAU : export d'un CSV d'audit complet par pari avec
      les variables manquantes identifiees dans l'analyse :
        - cote_n1, cote_n2 (cotes reelles)
        - score_n1, score_n2, ecart_n1_n2
        - nb_partants
        - discipline, type_course
        - position_n1, position_n2
        - rapport_place_reel, rapport_gagnant_reel
        - nb_sources_externes
        - hippodrome, terrain
        - n2_aurait_gagne_place (info contrefactuelle)
        - decision_v2_simulee (PARI FORT / PRUDENT / NO BET)

  Objectif : alimenter une base de 200-300 paris pour valider
  des filtres avant de toucher au scoring ou a la strategie.

  Fichier produit :
    resultats/audit_YYYYMMDD.csv (1 ligne par course analysee)
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

# v6 : une seule strategie active
MISE_P1 = 5.00  # Simple Place N1, mise unique 5 EUR

# v6 : seuils de la regle de decision V2 (a tester, pas a activer en prod)
V2_SCORE_MIN_PARI_PRUDENT = 40.0
V2_SCORE_MIN_PARI_FORT    = 50.0
V2_ECART_MIN_PRUDENT      = 2.0
V2_ECART_MIN_FORT         = 5.0
V2_COTE_MIN               = 1.8
V2_COTE_MAX               = 15.0
V2_PARTANTS_MAX           = 15
V2_SOURCES_MIN_FORT       = 2

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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/6.0)",
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
    """Renvoie {nom_cheval_upper: position, num_pmu_str: position}."""
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
    """v6 : recupere rapports reels simple_gagnant et simple_place."""
    r = {"simple_gagnant": 0.0, "simple_place": 0.0}
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


def simuler_p1(place_n1, nb_partants, rapports, mise):
    """Simule un pari Simple Place sur N1."""
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


def decision_v2(score_n1, score_n2, ecart, cote_n1, nb_partants, nb_sources):
    """
    v6 : applique la regle de decision V2 (simulee, non active en prod).

    Renvoie un tuple (decision, raison) parmi :
      - "PARI FORT", "PARI PRUDENT", "NO BET", "DONNEES INSUFFISANTES"
    """
    # Donnees indispensables
    manquant = []
    if score_n2 is None or score_n2 <= 0:
        manquant.append("score_n2")
    if cote_n1 is None or cote_n1 <= 0:
        manquant.append("cote_n1")
    if nb_partants is None or nb_partants <= 0:
        manquant.append("nb_partants")
    if manquant:
        return "DONNEES INSUFFISANTES", f"Manque: {','.join(manquant)}"

    # Filtres NO BET
    if score_n1 < V2_SCORE_MIN_PARI_PRUDENT:
        return "NO BET", f"Score trop faible ({score_n1:.1f} < {V2_SCORE_MIN_PARI_PRUDENT})"
    if ecart < V2_ECART_MIN_PRUDENT:
        return "NO BET", f"Ecart N1/N2 trop faible ({ecart:.1f} < {V2_ECART_MIN_PRUDENT})"
    if cote_n1 < V2_COTE_MIN:
        return "NO BET", f"Cote trop courte ({cote_n1:.1f} < {V2_COTE_MIN})"
    if cote_n1 > V2_COTE_MAX:
        return "NO BET", f"Cote trop longue ({cote_n1:.1f} > {V2_COTE_MAX})"
    if nb_partants > V2_PARTANTS_MAX:
        return "NO BET", f"Trop de partants ({nb_partants} > {V2_PARTANTS_MAX})"
    if nb_sources == 0:
        return "NO BET", "Aucune source externe"

    # Classification PARI FORT vs PRUDENT
    if (score_n1 >= V2_SCORE_MIN_PARI_FORT
            and ecart >= V2_ECART_MIN_FORT
            and nb_sources >= V2_SOURCES_MIN_FORT):
        return "PARI FORT", f"Score {score_n1:.1f}, ecart {ecart:.1f}, {nb_sources} sources"
    return "PARI PRUDENT", f"Criteres mini OK (score {score_n1:.1f}, ecart {ecart:.1f})"


def position_dans_top_payant(position, nb_partants):
    """v6 : True si la position est dans le top payant (Place)."""
    if position is None:
        return None
    limite = 2 if nb_partants <= 7 else 3
    return position <= limite


def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")
    heure_run     = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS v6 - Bilan du {date_aff} - {heure_run}")
    log.info(f"  Strategie unique : Simple Place N1 a {MISE_P1:.2f} EUR")
    log.info(f"  Mode AUDIT : export CSV enrichi pour analyse")
    log.info("=" * 70)

    telegram_send(
        f"PMU Bilan du soir - {date_aff} {heure_run}\n"
        f"Strategie : Simple Place N1 a {MISE_P1:.2f}e/course\n"
        "Comparaison pronostics + audit V2..."
    )

    courses = lire_pronostics_du_jour(date_str_fich)
    if not courses:
        telegram_send(f"PMU Bilan {date_aff} - Aucun pronostic du jour trouve.")
        return

    lignes_res  = []
    lignes_sim  = []
    nb_courses  = nb_g1 = nb_pl1 = 0
    sim_p1 = {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0}

    # v6 : compteurs par decision V2
    sim_v2 = {
        "PARI FORT":     {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},
        "PARI PRUDENT":  {"investi": 0.0, "retour": 0.0, "nb": 0, "gagnes": 0},
        "NO BET":        {"nb": 0, "aurait_gagne": 0},
        "DONNEES INSUFFISANTES": {"nb": 0},
    }

    # v6 : accumulateur pour le CSV d'audit
    audit_rows = []

    for (reunion, course), chevaux in sorted(courses.items()):
        nr, nc   = chevaux[0]["nr"], chevaux[0]["nc"]
        n1       = chevaux[0]
        n2       = chevaux[1] if len(chevaux) > 1 else None
        disc     = n1.get("discipline", "").replace("_", " ")
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

        # Statut N1
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
        if rapports["simple_place"] > 0:
            lignes_res.append(f"     Rapport place  : {rapports['simple_place']:.1f}x")

        # Info N2 (sans pari dessus)
        if n2:
            if p2_place == 1:   s2 = "GAGNANT"
            elif p2_place and p2_place <= limite: s2 = f"{p2_place}e - Place"
            elif p2_place:      s2 = f"{p2_place}e"
            else:               s2 = "Non disponible"
            lignes_res.append(f"  2. {n2['nom_cheval']} (cote {n2['cote_jour']:.1f}) -> {s2} (info)")

        # Simulation P1 reelle (strategie en prod)
        gain, detail = simuler_p1(p1_place, nb_part, rapports, MISE_P1)
        sim_p1["investi"] += MISE_P1
        sim_p1["retour"]  += gain
        sim_p1["nb"]      += 1
        if gain > 0:
            sim_p1["gagnes"] += 1

        sim_block = [f"\n{reunion} {course} | {libelle[:35]}"]
        sim_block.append(
            f"  P1 Simple Place {MISE_P1:.2f}e"
            f" sur {n1['nom_cheval'][:20]} : {detail}"
        )
        raison = ("CONSENSUS FORT" if n1.get("consensus_fort")
                  else f"Score {n1['score_total']:.1f}%")
        sim_block.append(f"     > {raison}")
        lignes_sim.extend(sim_block)

        # v6 : simulation V2 (decision contrefactuelle, pas de mise reelle)
        score_n1 = n1.get("score_total", 0)
        score_n2 = n2.get("score_total", 0) if n2 else 0
        ecart    = score_n1 - score_n2
        cote_n1  = n1.get("cote_jour", 0)
        decision, raison_v2 = decision_v2(
            score_n1=score_n1, score_n2=score_n2, ecart=ecart,
            cote_n1=cote_n1, nb_partants=nb_part, nb_sources=nb_src,
        )

        # Aurait-on gagne avec la decision V2 ?
        gagne_place = position_dans_top_payant(p1_place, nb_part)
        n1_a_gagne = gagne_place is True
        n2_aurait_place = position_dans_top_payant(p2_place, nb_part)

        if decision in ("PARI FORT", "PARI PRUDENT"):
            sim_v2[decision]["investi"] += MISE_P1
            sim_v2[decision]["nb"]      += 1
            if n1_a_gagne:
                sim_v2[decision]["gagnes"] += 1
                sim_v2[decision]["retour"] += gain
        elif decision == "NO BET":
            sim_v2["NO BET"]["nb"] += 1
            if n1_a_gagne:
                sim_v2["NO BET"]["aurait_gagne"] += 1
        else:
            sim_v2["DONNEES INSUFFISANTES"]["nb"] += 1

        # v6 : ligne d'audit (1 par course)
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
            "n1_cote_veille":   round(n1.get("cote_veille", 0), 2),
            "n1_variation_cote": n1.get("variation_cote", ""),
            "n1_position":      p1_place if p1_place else "",
            "n1_a_place":       1 if n1_a_gagne else 0,
            "n1_a_gagne":       1 if p1_place == 1 else 0,
            "n2_nom":           n2.get("nom_cheval", "") if n2 else "",
            "n2_score":         round(score_n2, 1),
            "n2_cote":          round(n2.get("cote_jour", 0), 2) if n2 else 0,
            "n2_position":      p2_place if p2_place else "",
            "n2_a_place":       1 if n2_aurait_place else 0,
            "ecart_n1_n2":      round(ecart, 1),
            "nb_sources":       nb_src,
            "consensus_fort":   1 if n1.get("consensus_fort") else 0,
            "value_bet":        1 if n1.get("value_bet") else 0,
            "rapport_gagnant":  round(rapports["simple_gagnant"], 2),
            "rapport_place":    round(rapports["simple_place"], 2),
            "jockey":           n1.get("jockey", ""),
            "entraineur":       n1.get("entraineur", ""),
            "p1_mise":          MISE_P1,
            "p1_gain":          round(gain, 2),
            "p1_profit":        round(gain - MISE_P1, 2),
            "v2_decision":      decision,
            "v2_raison":        raison_v2,
        })

        time.sleep(0.3)

    # ── Export du CSV d'audit ────────────────────────────
    chemin_audit = os.path.join(OUTPUT_DIR, f"audit_{date_str_fich}.csv")
    if audit_rows:
        colonnes_audit = list(audit_rows[0].keys())
        with open(chemin_audit, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=colonnes_audit)
            w.writeheader()
            w.writerows(audit_rows)
        log.info(f"CSV audit : {chemin_audit} ({len(audit_rows)} lignes)")

    # ── Bilan Telegram ───────────────────────────────────
    bilan = ["", "=" * 38, f"BILAN RESULTATS - {date_aff}"]
    if nb_courses > 0:
        bilan += [
            f"  Courses analysees  : {nb_courses}",
            f"  1er exact (N1)     : {nb_g1}/{nb_courses}  ({nb_g1/nb_courses*100:.0f}%)",
            f"  Places (N1 top2/3) : {nb_pl1}/{nb_courses}  ({nb_pl1/nb_courses*100:.0f}%)",
        ]
    else:
        bilan.append("  Aucune course exploitable")

    bilan += [
        "", "=" * 38,
        f"SIMULATION GAINS - {date_aff}",
        f"(Simple Place N1, {MISE_P1:.2f}e par course)", "",
    ]

    s = sim_p1
    if s["nb"] == 0:
        bilan.append("  Aucun pari simule (pas de resultat).")
    else:
        profit = s["retour"] - s["investi"]
        roi    = profit / s["investi"] * 100 if s["investi"] > 0 else 0
        sgn    = "+" if profit >= 0 else ""
        verdict = "BENEFICE" if profit > 0 else ("EQUILIBRE" if profit == 0 else "PERTE")
        taux_g = s["gagnes"] / s["nb"] * 100 if s["nb"] > 0 else 0
        bilan += [
            f"  P1 Simple Place {MISE_P1:.2f}e sur N1",
            f"    {s['nb']} pari(s) | {s['gagnes']} gagne(s) ({taux_g:.0f}%)",
            f"    Investi : {s['investi']:.2f}e",
            f"    Retour  : {s['retour']:.2f}e",
            f"    Profit  : {sgn}{profit:.2f}e   ROI {sgn}{roi:.0f}%",
            "",
            "─" * 35,
            f"  TOTAL INVESTI : {s['investi']:.2f}e",
            f"  TOTAL RETOUR  : {s['retour']:.2f}e",
            f"  GAIN / PERTE  : {sgn}{profit:.2f}e  [{verdict}]",
            f"  ROI GLOBAL    : {sgn}{roi:.0f}%",
            "",
            f"  Investissement - Gains = {s['investi']:.2f}e - {s['retour']:.2f}e = {sgn}{profit:.2f}e",
        ]

    # v6 : bloc audit V2 (apercu, sans investissement reel)
    bilan += [
        "", "=" * 38,
        "AUDIT V2 (simulation, non joue)", "",
    ]
    for niveau in ("PARI FORT", "PARI PRUDENT"):
        b = sim_v2[niveau]
        if b["nb"] > 0:
            profit_v2 = b["retour"] - b["investi"]
            roi_v2 = profit_v2 / b["investi"] * 100 if b["investi"] > 0 else 0
            sgn_v2 = "+" if profit_v2 >= 0 else ""
            taux = b["gagnes"] / b["nb"] * 100
            bilan += [
                f"  {niveau} : {b['nb']} pari(s), {b['gagnes']} gagne(s) ({taux:.0f}%)",
                f"    Profit simule : {sgn_v2}{profit_v2:.2f}e   ROI {sgn_v2}{roi_v2:.0f}%",
            ]
        else:
            bilan.append(f"  {niveau} : 0 pari (aucun signal)")

    nb_nobet = sim_v2["NO BET"]["nb"]
    rates_nobet = sim_v2["NO BET"]["aurait_gagne"]
    bilan.append(f"  NO BET : {nb_nobet} (dont {rates_nobet} qui auraient place)")

    nb_insuf = sim_v2["DONNEES INSUFFISANTES"]["nb"]
    if nb_insuf > 0:
        bilan.append(f"  DONNEES INSUFFISANTES : {nb_insuf}")

    bilan += [
        "",
        f"  CSV audit : audit_{date_str_fich}.csv",
        f"  -> dans /resultats sur GitHub",
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
                f"(Simple Place N1, {MISE_P1:.2f}e/course)\n" + "=" * 38
                + "\n".join(lignes_sim))
        telegram_send(msg2)
        time.sleep(1)

    telegram_send("\n".join(bilan))

    log.info("Bilan v6 envoye.")
    log.info("=" * 70)
    log.info("  RESULTS v6 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
