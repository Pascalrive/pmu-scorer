"""
=============================================================
  PMU RESULTS - Bilan du soir
=============================================================
  Compare les pronostics du matin avec les resultats reels.
  A lancer le soir vers 20h00 apres les dernieres courses.
=============================================================
"""

import csv
import glob
import logging
import os
import time
from datetime import datetime

import requests

# ──────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────
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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Results/1.0)",
    "Accept": "application/json",
}


# ──────────────────────────────────────────────
#  TELEGRAM
# ──────────────────────────────────────────────
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


# ──────────────────────────────────────────────
#  API PMU - RESULTATS
# ──────────────────────────────────────────────
def api_get(path: str):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Erreur reseau: {e}")
        return None


def get_resultats_course(date_str: str, nr, nc) -> dict:
    """
    Recupere les resultats officiels d'une course.
    Retourne un dict {num_partant: place_arrivee}.
    """
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if not data or not isinstance(data, dict):
        return {}

    resultats = {}
    for partant in data.get("participants", []):
        num   = partant.get("numPmu") or partant.get("numero")
        nom   = partant.get("nom", "")
        place = None

        # Chercher la place dans les rapports definitifs
        if partant.get("ordreArrivee"):
            place = partant["ordreArrivee"]
        elif partant.get("place"):
            place = partant["place"]

        if num and place:
            try:
                resultats[str(num)] = int(place)
            except (ValueError, TypeError):
                pass

        # Stocker aussi par nom
        if nom and place:
            try:
                resultats[nom.upper()] = int(place)
            except (ValueError, TypeError):
                pass

    return resultats


def get_rapport_gagnant(date_str: str, nr, nc) -> float:
    """Recupere le rapport gagnant (rapport simple gagnant)."""
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


# ──────────────────────────────────────────────
#  LECTURE DU CSV DE PRONOSTICS
# ──────────────────────────────────────────────
def lire_pronostics_du_jour(date_str_fichier: str) -> list:
    """
    Lit le CSV de pronostics du jour.
    date_str_fichier : format YYYYMMDD
    Retourne la liste des chevaux recommandes (1 par course).
    """
    pattern = os.path.join(OUTPUT_DIR, f"pmu_{date_str_fichier}_*.csv")
    fichiers = sorted(glob.glob(pattern))

    if not fichiers:
        log.warning(f"Aucun fichier CSV trouve pour {date_str_fichier}")
        return []

    # Prendre le dernier fichier du jour (analyse la plus recente)
    fichier = fichiers[-1]
    log.info(f"Lecture du fichier : {fichier}")

    pronostics = []
    vus = set()

    try:
        with open(fichier, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = sorted(reader, key=lambda x: float(x.get("score_total", 0)), reverse=True)

            for row in rows:
                cle = (row.get("reunion", ""), row.get("course", ""))
                if cle not in vus:
                    vus.add(cle)
                    pronostics.append({
                        "reunion":      row.get("reunion", ""),
                        "course":       row.get("course", ""),
                        "hippodrome":   row.get("hippodrome", ""),
                        "libelle":      row.get("libelle", ""),
                        "discipline":   row.get("discipline", ""),
                        "nom_cheval":   row.get("nom_cheval", ""),
                        "num_partant":  row.get("num_partant", ""),
                        "cote_jour":    float(row.get("cote_jour", 0) or 0),
                        "score_total":  float(row.get("score_total", 0) or 0),
                        "jockey":       row.get("jockey", ""),
                        "nr":           row.get("reunion", "R0").replace("R", ""),
                        "nc":           row.get("course", "C0").replace("C", ""),
                    })
    except Exception as e:
        log.error(f"Erreur lecture CSV: {e}")

    log.info(f"{len(pronostics)} courses trouvees dans le CSV.")
    return pronostics


# ──────────────────────────────────────────────
#  PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today          = datetime.now()
    date_str       = today.strftime("%d%m%Y")
    date_str_fich  = today.strftime("%Y%m%d")
    date_aff       = today.strftime("%d/%m/%Y")
    heure_run      = today.strftime("%Hh%M")

    log.info("=" * 70)
    log.info(f"  PMU RESULTS - Bilan du {date_aff} - {heure_run}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Bilan du soir - {date_aff} {heure_run}\nComparaison pronostics vs resultats...")

    # Lire les pronostics du matin
    pronostics = lire_pronostics_du_jour(date_str_fich)
    if not pronostics:
        msg = f"PMU Bilan {date_aff} - Aucun pronostic trouve pour aujourd'hui."
        log.warning(msg)
        telegram_send(msg)
        return

    # Comparer avec les resultats reels
    lignes_bilan = [
        f"PMU France - Bilan du {date_aff}",
        "Pronostics vs Resultats reels",
        "=" * 35,
    ]

    nb_gagnants   = 0
    nb_places     = 0   # 1er, 2eme ou 3eme
    nb_courses    = 0
    nb_non_couru  = 0
    gains_theoriques = 0.0

    for prono in pronostics:
        nr  = prono["nr"]
        nc  = prono["nc"]
        nom = prono["nom_cheval"]
        cote = prono["cote_jour"]
        disc = prono["discipline"].replace("_", " ")

        # Recuperer les resultats officiels
        resultats_course = get_resultats_course(date_str, nr, nc)
        time.sleep(0.5)

        if not resultats_course:
            nb_non_couru += 1
            lignes_bilan.append("")
            lignes_bilan.append(f"{prono['reunion']} {prono['course']} - {disc}")
            lignes_bilan.append(f"  Notre choix : {nom} (cote {cote:.1f})")
            lignes_bilan.append(f"  Resultat    : Course non encore disputee ou non disponible")
            continue

        nb_courses += 1

        # Chercher la place de notre cheval
        place = resultats_course.get(nom.upper()) or resultats_course.get(str(prono["num_partant"]))

        lignes_bilan.append("")
        lignes_bilan.append(f"{prono['reunion']} {prono['course']} | {disc}")
        if prono["libelle"]:
            lignes_bilan.append(f"  {prono['libelle'][:45]}")
        lignes_bilan.append(f"  Notre choix : {nom} (cote {cote:.1f})")

        if place is None:
            lignes_bilan.append(f"  Resultat    : Position non disponible")
        elif place == 1:
            nb_gagnants += 1
            nb_places   += 1
            rapport = get_rapport_gagnant(date_str, nr, nc)
            gains_theoriques += rapport if rapport > 0 else cote
            lignes_bilan.append(f"  Resultat    : 1er !!! GAGNANT")
            if rapport > 0:
                lignes_bilan.append(f"  Rapport     : {rapport:.1f} (pour 1 euro mise)")
        elif place <= 3:
            nb_places += 1
            lignes_bilan.append(f"  Resultat    : {place}eme - Place")
        else:
            lignes_bilan.append(f"  Resultat    : {place}eme - Rate")

        log.info(f"R{nr} C{nc} - {nom} -> place {place}")
        time.sleep(0.5)

    # Bilan global
    lignes_bilan.append("")
    lignes_bilan.append("=" * 35)
    lignes_bilan.append(f"BILAN DU JOUR - {date_aff}")
    lignes_bilan.append(f"  Courses analysees : {nb_courses}")
    lignes_bilan.append(f"  Gagnants (1er)    : {nb_gagnants}/{nb_courses}")
    lignes_bilan.append(f"  Places (1er-3eme) : {nb_places}/{nb_courses}")
    if nb_courses > 0:
        taux_gagnant = (nb_gagnants / nb_courses) * 100
        taux_place   = (nb_places / nb_courses) * 100
        lignes_bilan.append(f"  Taux gagnant      : {taux_gagnant:.0f}%")
        lignes_bilan.append(f"  Taux place        : {taux_place:.0f}%")
    if gains_theoriques > 0:
        lignes_bilan.append(f"  Gains theoriques  : {gains_theoriques:.1f}x (sans mise reelle)")
    lignes_bilan.append("")
    lignes_bilan.append("Rappel : outil statistique - jouer responsable.")

    message = "\n".join(lignes_bilan)
    log.info(message)

    if telegram_send(message):
        log.info("Bilan Telegram envoye.")
    else:
        log.warning("Envoi Telegram echoue.")

    log.info("\n" + "=" * 70)
    log.info("  RESULTS TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
