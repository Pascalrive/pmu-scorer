"""
=============================================================
  PMU RESULTS v2 - Bilan du soir
=============================================================
  Compare les pronostics du matin avec les resultats reels.
  Affiche les probabilites et le taux de reussite.
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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/2.0)",
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


def lire_pronostics_du_jour(date_str_fichier: str) -> list:
    pattern  = os.path.join(OUTPUT_DIR, f"pmu_{date_str_fichier}_*.csv")
    fichiers = sorted(glob.glob(pattern))

    if not fichiers:
        log.warning(f"Aucun fichier CSV trouve pour {date_str_fichier}")
        return []

    fichier = fichiers[-1]
    log.info(f"Lecture : {fichier}")

    pronostics = []
    vus        = set()

    try:
        with open(fichier, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows   = list(reader)

        # Grouper par course et garder le top 2
        courses = {}
        for row in rows:
            cle = (row.get("reunion", ""), row.get("course", ""))
            if cle not in courses:
                courses[cle] = []
            courses[cle].append(row)

        for cle, partants in courses.items():
            partants_tries = sorted(
                partants,
                key=lambda x: float(x.get("score_total", 0) or 0),
                reverse=True
            )
            for rang, row in enumerate(partants_tries[:2], 1):
                pronostics.append({
                    "reunion":       row.get("reunion", ""),
                    "course":        row.get("course", ""),
                    "hippodrome":    row.get("hippodrome", ""),
                    "libelle":       row.get("libelle", ""),
                    "discipline":    row.get("discipline", ""),
                    "nom_cheval":    row.get("nom_cheval", ""),
                    "num_partant":   row.get("num_partant", ""),
                    "cote_jour":     float(row.get("cote_jour", 0) or 0),
                    "score_total":   float(row.get("score_total", 0) or 0),
                    "nb_pronostics": int(float(row.get("nb_pronostics", 0) or 0)),
                    "pct_pronostics": float(row.get("pct_pronostics", 0) or 0),
                    "nb_sources":    int(float(row.get("nb_sources_total", 0) or 0)),
                    "jockey":        row.get("jockey", ""),
                    "rang_prono":    rang,
                    "nr":            row.get("reunion", "R0").replace("R", ""),
                    "nc":            row.get("course", "C0").replace("C", ""),
                })

    except Exception as e:
        log.error(f"Erreur lecture CSV: {e}")

    log.info(f"{len(pronostics)} pronostics charges.")
    return pronostics


def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")
    heure_run     = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS v2 - Bilan du {date_aff} - {heure_run}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Bilan du soir - {date_aff} {heure_run}\nComparaison pronostics vs resultats...")

    pronostics = lire_pronostics_du_jour(date_str_fich)
    if not pronostics:
        msg = f"PMU Bilan {date_aff} - Aucun pronostic trouve."
        telegram_send(msg)
        return

    # Grouper par course pour afficher les 2 chevaux ensemble
    courses_dict = {}
    for p in pronostics:
        cle = (p["reunion"], p["course"])
        if cle not in courses_dict:
            courses_dict[cle] = []
        courses_dict[cle].append(p)

    lignes_bilan = [
        f"PMU France - Bilan du {date_aff}",
        "Pronostics vs Resultats reels",
        "=" * 38,
    ]

    nb_gagnants_1  = 0   # 1er exact
    nb_places      = 0   # top 3
    nb_top2_ok     = 0   # gagnant dans notre top 2
    nb_courses     = 0
    gains_theoriques = 0.0

    for (reunion, course), chevaux in sorted(courses_dict.items()):
        nr = chevaux[0]["nr"]
        nc = chevaux[0]["nc"]

        resultats_course = get_resultats_course(date_str, nr, nc)
        time.sleep(0.5)

        disc    = chevaux[0].get("discipline", "").replace("_", " ")
        libelle = chevaux[0].get("libelle", "")

        lignes_bilan.append("")
        lignes_bilan.append(f"{reunion} {course} | {disc}")
        if libelle:
            lignes_bilan.append(f"  {libelle[:45]}")

        if not resultats_course:
            lignes_bilan.append("  Course non encore disputee ou resultats non disponibles")
            continue

        nb_courses += 1
        gagnant_dans_top2 = False

        for cheval in chevaux:
            nom       = cheval["nom_cheval"]
            cote      = cheval["cote_jour"]
            score     = cheval["score_total"]
            nb_prono  = cheval["nb_pronostics"]
            nb_src    = cheval["nb_sources"]
            pct_prono = cheval["pct_pronostics"]
            rang      = cheval["rang_prono"]

            place = (
                resultats_course.get(nom.upper())
                or resultats_course.get(str(cheval["num_partant"]))
            )

            # Statut
            if place == 1:
                statut = "GAGNANT !!!"
                if rang == 1:
                    nb_gagnants_1 += 1
                gagnant_dans_top2 = True
                rapport = get_rapport_gagnant(date_str, nr, nc)
                if rapport > 0:
                    gains_theoriques += rapport
            elif place and place <= 3:
                statut = f"{place}eme - Place"
                if rang == 1:
                    nb_places += 1
            elif place:
                statut = f"{place}eme - Rate"
            else:
                statut = "Position non disponible"

            prefixe = "  1." if rang == 1 else "  2."
            lignes_bilan.append(f"{prefixe} {nom} (cote {cote:.1f}) -> {statut}")
            if nb_src > 0:
                lignes_bilan.append(
                    f"     {nb_prono} source(s) sur {nb_src} donnaient ce cheval gagnant ({pct_prono:.0f}%)"
                )
            lignes_bilan.append(f"     Score: {score:.1f}%")

        if gagnant_dans_top2:
            nb_top2_ok += 1

        time.sleep(0.3)

    # Bilan global
    lignes_bilan.append("")
    lignes_bilan.append("=" * 38)
    lignes_bilan.append(f"BILAN DU JOUR - {date_aff}")
    lignes_bilan.append(f"  Courses analysees       : {nb_courses}")
    lignes_bilan.append(f"  1er exact (choix n1)    : {nb_gagnants_1}/{nb_courses}")
    lignes_bilan.append(f"  Gagnant dans notre top2 : {nb_top2_ok}/{nb_courses}")
    lignes_bilan.append(f"  Places (1er-3eme, n1)   : {nb_places}/{nb_courses}")
    if nb_courses > 0:
        lignes_bilan.append(f"  Taux 1er exact          : {nb_gagnants_1/nb_courses*100:.0f}%")
        lignes_bilan.append(f"  Taux top2 gagnant       : {nb_top2_ok/nb_courses*100:.0f}%")
    if gains_theoriques > 0:
        lignes_bilan.append(f"  Gains theoriques        : {gains_theoriques:.1f}x (pour 1 euro/course)")
    lignes_bilan.append("")
    lignes_bilan.append("Outil statistique - Jouer responsable.")

    message = "\n".join(lignes_bilan)
    log.info(message)

    if telegram_send(message):
        log.info("Bilan Telegram envoye.")
    else:
        log.warning("Envoi Telegram echoue.")

    log.info("\n" + "=" * 70)
    log.info("  RESULTS v2 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
