"""
=============================================================
  PMU RESULTS v3 - Bilan du soir
=============================================================
  Lit le CSV depuis le depot Git (plus fiable que les artifacts).
  Compare pronostics top2 avec resultats reels.
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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/3.0)",
    "Accept": "application/json",
}


def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limite   = 4096
    morceaux = [texte[i:i+limite] for i in range(0, len(texte), limite)]
    succes = True
    for morceau in morceaux:
        try:
            r = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT, "text": morceau},
                timeout=15,
            )
            if r.status_code != 200:
                log.warning(f"Telegram HTTP {r.status_code}")
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Erreur Telegram: {e}")
            succes = False
    return succes


def api_get(path: str):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Erreur reseau: {e}")
        return None


def get_resultats_course(date_str: str, nr, nc) -> dict:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if not data or not isinstance(data, dict):
        return {}
    resultats = {}
    for partant in data.get("participants", []):
        num   = partant.get("numPmu") or partant.get("numero")
        nom   = partant.get("nom", "")
        place = partant.get("ordreArrivee") or partant.get("place")
        if num and place:
            try:
                resultats[str(num)] = int(place)
            except (ValueError, TypeError):
                pass
        if nom and place:
            try:
                resultats[nom.upper()] = int(place)
            except (ValueError, TypeError):
                pass
    return resultats


def get_rapport_gagnant(date_str: str, nr, nc) -> float:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/rapports-definitifs")
    if not data:
        return 0.0
    try:
        rapports = data.get("rapports", []) if isinstance(data, dict) else []
        for r in rapports:
            if r.get("typePari") in ("SIMPLE_GAGNANT", "E_SIMPLE_GAGNANT"):
                combinaisons = r.get("combinaisons", [])
                if combinaisons:
                    return float(combinaisons[0].get("rapport", 0) or 0) / 100
    except Exception:
        pass
    return 0.0


def lire_pronostics_du_jour(date_str_fichier: str) -> dict:
    """
    Lit le CSV du jour depuis le dossier resultats/.
    Retourne un dict {(reunion, course): [top1, top2]}
    """
    # Chercher tous les CSV du jour
    pattern  = os.path.join(OUTPUT_DIR, f"pmu_{date_str_fichier}_*.csv")
    fichiers = sorted(glob.glob(pattern))

    if not fichiers:
        log.warning(f"Aucun fichier CSV trouve pour {date_str_fichier} dans {OUTPUT_DIR}/")
        log.info(f"Fichiers disponibles : {os.listdir(OUTPUT_DIR) if os.path.exists(OUTPUT_DIR) else 'dossier absent'}")
        return {}

    fichier = fichiers[-1]
    log.info(f"Lecture : {fichier}")

    courses = {}
    try:
        with open(fichier, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows   = list(reader)

        # Grouper par course
        grouped = {}
        for row in rows:
            cle = (row.get("reunion", ""), row.get("course", ""))
            if cle not in grouped:
                grouped[cle] = []
            grouped[cle].append(row)

        # Garder le top 2 par course
        for cle, partants in grouped.items():
            tries = sorted(
                partants,
                key=lambda x: float(x.get("score_total", 0) or 0),
                reverse=True
            )
            courses[cle] = [
                {
                    "reunion":       r.get("reunion", ""),
                    "course":        r.get("course", ""),
                    "hippodrome":    r.get("hippodrome", ""),
                    "terrain":       r.get("terrain", ""),
                    "libelle":       r.get("libelle", ""),
                    "discipline":    r.get("discipline", ""),
                    "nom_cheval":    r.get("nom_cheval", ""),
                    "num_partant":   r.get("num_partant", ""),
                    "cote_jour":     float(r.get("cote_jour", 0) or 0),
                    "score_total":   float(r.get("score_total", 0) or 0),
                    "probabilite":   0.0,
                    "nb_pronostics": int(float(r.get("nb_pronostics", 0) or 0)),
                    "pct_pronostics": float(r.get("pct_pronostics", 0) or 0),
                    "nb_sources":    int(float(r.get("nb_sources_total", 0) or 0)),
                    "value_bet":     r.get("value_bet", "False") == "True",
                    "jockey":        r.get("jockey", ""),
                    "rang":          i + 1,
                    "nr":            r.get("reunion", "R0").replace("R", ""),
                    "nc":            r.get("course", "C0").replace("C", ""),
                }
                for i, r in enumerate(tries[:2])
            ]

    except Exception as e:
        log.error(f"Erreur lecture CSV: {e}")

    log.info(f"{len(courses)} courses chargees.")
    return courses


def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")
    heure_run     = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS v3 - Bilan du {date_aff} - {heure_run}")
    log.info("=" * 70)

    telegram_send(f"PMU Bilan du soir - {date_aff} {heure_run}\nComparaison pronostics vs resultats...")

    courses = lire_pronostics_du_jour(date_str_fich)
    if not courses:
        msg = f"PMU Bilan {date_aff} - Aucun pronostic du jour trouve.\nVerifiez que le script du matin a bien tourne."
        log.warning(msg)
        telegram_send(msg)
        return

    lignes = [
        f"PMU France - Bilan du {date_aff}",
        "Pronostics vs Resultats reels",
        "=" * 38,
    ]

    nb_gagnants_1  = 0
    nb_places      = 0
    nb_top2_ok     = 0
    nb_courses     = 0
    gains          = 0.0
    value_bets_ok  = 0
    value_bets_tot = 0

    for (reunion, course), chevaux in sorted(courses.items()):
        nr = chevaux[0]["nr"]
        nc = chevaux[0]["nc"]

        resultats_course = get_resultats_course(date_str, nr, nc)
        time.sleep(0.5)

        disc    = chevaux[0].get("discipline", "").replace("_", " ")
        libelle = chevaux[0].get("libelle", "")
        terrain = chevaux[0].get("terrain", "")

        terrain_str = f" | {terrain}" if terrain else ""
        lignes.append("")
        lignes.append(f"{reunion} {course} | {disc}{terrain_str}")
        if libelle:
            lignes.append(f"  {libelle[:45]}")

        if not resultats_course:
            lignes.append("  Resultats non encore disponibles")
            continue

        nb_courses += 1
        gagnant_dans_top2 = False
        rapport = 0.0

        for cheval in chevaux:
            nom       = cheval["nom_cheval"]
            cote      = cheval["cote_jour"]
            score     = cheval["score_total"]
            nb_prono  = cheval["nb_pronostics"]
            nb_src    = cheval["nb_sources"]
            pct_prono = cheval["pct_pronostics"]
            rang      = cheval["rang"]
            value     = cheval["value_bet"]

            place = (
                resultats_course.get(nom.upper())
                or resultats_course.get(str(cheval["num_partant"]))
            )

            # Compter les value bets
            if rang == 1 and value:
                value_bets_tot += 1

            if place == 1:
                statut = "GAGNANT !!!"
                gagnant_dans_top2 = True
                rapport = get_rapport_gagnant(date_str, nr, nc)
                if rapport > 0:
                    gains += rapport
                if rang == 1:
                    nb_gagnants_1 += 1
                    if value:
                        value_bets_ok += 1
            elif place and place <= 3:
                statut = f"{place}eme - Place"
                if rang == 1:
                    nb_places += 1
            elif place:
                statut = f"{place}eme - Rate"
            else:
                statut = "Non disponible"

            vb_str = " [VALUE BET]" if value else ""
            prefixe = "  1." if rang == 1 else "  2."
            lignes.append(f"{prefixe} {nom} (cote {cote:.1f}){vb_str} -> {statut}")

            if nb_src > 0:
                lignes.append(f"     {nb_prono}/{nb_src} sources ({pct_prono:.0f}%) | Score: {score:.1f}%")
            else:
                lignes.append(f"     Score: {score:.1f}%")

            if place == 1 and rapport > 0:
                lignes.append(f"     Rapport gagnant: {rapport:.1f}x")

        if gagnant_dans_top2:
            nb_top2_ok += 1

        time.sleep(0.3)

    # Bilan global
    lignes.append("")
    lignes.append("=" * 38)
    lignes.append(f"BILAN DU JOUR - {date_aff}")
    lignes.append(f"  Courses analysees       : {nb_courses}")
    lignes.append(f"  1er exact (choix n1)    : {nb_gagnants_1}/{nb_courses}")
    lignes.append(f"  Gagnant dans notre top2 : {nb_top2_ok}/{nb_courses}")
    lignes.append(f"  Places top3 (choix n1)  : {nb_places}/{nb_courses}")
    if nb_courses > 0:
        lignes.append(f"  Taux 1er exact          : {nb_gagnants_1/nb_courses*100:.0f}%")
        lignes.append(f"  Taux top2 gagnant       : {nb_top2_ok/nb_courses*100:.0f}%")
    if value_bets_tot > 0:
        lignes.append(f"  Value bets              : {value_bets_ok}/{value_bets_tot} gagnants")
    if gains > 0:
        lignes.append(f"  Gains theoriques        : {gains:.1f}x (pour 1 euro/course)")
    lignes.append("")
    lignes.append("Outil statistique - Jouer responsable.")

    message = "\n".join(lignes)
    log.info(message)

    if telegram_send(message):
        log.info("Bilan envoye sur Telegram.")
    else:
        log.warning("Envoi Telegram echoue.")

    log.info("\n" + "=" * 70)
    log.info("  RESULTS v3 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
