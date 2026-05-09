"""
=============================================================
  PMU NOTIFIER v3 - Messages H-15min avant chaque course
=============================================================
  - Tourne en continu de 11h a 20h (GitHub Actions timeout 9h)
  - Envoie un message 15 minutes AVANT chaque course
  - Attend le bon moment pour chaque course (sleep jusqu a H-15)
  - Format top2 + 3 suivants
=============================================================
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import requests

BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

PAYS_AUTORISES    = {"FRA", "FRANCE"}
DISCIPLINES_GALOP = {"PLAT", "HAIES", "STEEPLE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Notifier/3.0)",
    "Accept": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pmu_notifier.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("pmu_notifier")


# ──────────────────────────────────────────────
#  TELEGRAM
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram non configure")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    morceaux = [texte[i:i+4096] for i in range(0, len(texte), 4096)]
    for morceau in morceaux:
        try:
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": morceau}, timeout=15)
            if r.status_code != 200:
                log.warning(f"Telegram {r.status_code}: {r.text[:100]}")
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"Telegram: {e}")
    return True


# ──────────────────────────────────────────────
#  API PMU
# ──────────────────────────────────────────────
def api_get(path):
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"API {path}: {e}")
        return None


def extraire_cote(partant: dict) -> float:
    for champ in ["dernierRapportDirect", "dernierRapportReference", "cotesPmu"]:
        if partant.get(champ):
            try:
                val = partant[champ].get("rapport", 0)
                if val and float(val) > 0:
                    return float(val)
            except Exception:
                pass
    return 0.0


# ──────────────────────────────────────────────
#  CONSTRUCTION DU PROGRAMME
# ──────────────────────────────────────────────
def get_courses_du_jour(date_str: str) -> list:
    """
    Retourne la liste de toutes les courses du jour
    avec leur heure de depart en timestamp ms.
    Triees par heure de depart.
    """
    programme = api_get(f"/programme/{date_str}")
    if not programme:
        return []

    reunions = programme.get("programme", {}).get("reunions", [])
    courses  = []

    for reunion in reunions:
        pays = reunion.get("pays", {})
        code = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code not in PAYS_AUTORISES:
            continue

        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        terrain_r  = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain_r, dict):
            terrain_r = terrain_r.get("libelle", "") or terrain_r.get("code", "")

        for course in reunion.get("courses", []):
            nc         = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue

            heure_ts = course.get("heureDepart", 0)
            libelle  = course.get("libelle", f"R{nr} C{nc}")
            distance = course.get("distance", 0)

            terrain = course.get("terrain") or course.get("etatSol") or terrain_r
            if isinstance(terrain, dict):
                terrain = terrain.get("libelle", "") or terrain.get("code", "")

            courses.append({
                "nr":         nr,
                "nc":         nc,
                "heure_ts":   heure_ts,
                "hippodrome": hippodrome,
                "libelle":    libelle,
                "discipline": discipline,
                "distance":   distance,
                "terrain":    str(terrain).upper() if terrain else "",
                "notifie":    False,
            })

    courses.sort(key=lambda x: x["heure_ts"])
    log.info(f"{len(courses)} courses chargees.")
    return courses


# ──────────────────────────────────────────────
#  COLLECTE PARTANTS
# ──────────────────────────────────────────────
def get_partants(date_str, nr, nc) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if data and isinstance(data, dict):
        p = data.get("participants", [])
        if p:
            return [x for x in p if x.get("statut") != "NON_PARTANT"]
    return []


# ──────────────────────────────────────────────
#  FORMAT MESSAGE H-15MIN
# ──────────────────────────────────────────────
def formater_message_h15(course: dict, partants: list) -> str:
    nr         = course["nr"]
    nc         = course["nc"]
    heure_ts   = course["heure_ts"]
    hippodrome = course["hippodrome"]
    libelle    = course["libelle"]
    discipline = course["discipline"].replace("_", " ")
    distance   = course["distance"]
    terrain    = course["terrain"]
    trot       = discipline.upper() in ("TROT ATTELE", "TROT MONTE", "ATTELE", "MONTE")

    heure_str = ""
    if heure_ts:
        try:
            heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
        except Exception:
            pass

    terrain_str = f" | {terrain}" if terrain else ""
    dist_str    = f" | {distance}m" if distance else ""

    # Trier par cote
    valides = [p for p in partants if extraire_cote(p) > 0]
    valides.sort(key=lambda x: extraire_cote(x))

    lignes = [
        f"DANS 15 MIN  R{nr} C{nc} | {heure_str} | {discipline}",
        libelle[:50],
        f"HIPPODROME {hippodrome}{terrain_str}{dist_str}",
        "=" * 35,
        "Pronostics non encore disponibles",
        "Classement par cote PMU :",
    ]

    # Top 2
    if len(valides) >= 2:
        lignes.append("")
        lignes.append("--- NOS 2 CHOIX ---")
        for i, p in enumerate(valides[:2]):
            num    = p.get("numPmu") or p.get("numero") or ""
            nom    = p.get("nom", "?")
            cote   = extraire_cote(p)
            corde  = int(p.get("placeCorde") or 0)
            nb_p   = len(valides)
            poids  = int(p.get("handicapPoids") or 0)

            prefix = ">>" if i == 0 else "  "
            lignes.append(f"{prefix} N{num}. {nom} (cote {cote:.1f})")

            if trot and corde:
                av = " AVANTAGE DECISIF" if corde <= 3 else (" AVANTAGE" if corde <= 4 else "")
                lignes.append(f"   Corde {corde}/{nb_p}{av}")
            elif poids:
                lignes.append(f"   Poids: {poids/10:.1f}kg")

    # Classement complet
    lignes.append("")
    disc_label = "TROT" if trot else "GALOP"
    lignes.append(f"--- CLASSEMENT {disc_label} ({len(valides)} partants) ---")

    for p in valides:
        num   = p.get("numPmu") or p.get("numero") or ""
        nom   = p.get("nom", "?")[:24]
        cote  = extraire_cote(p)
        corde = int(p.get("placeCorde") or 0)

        prefix = ">>" if p in valides[:2] else "  "
        corde_str = f" C{corde}" if (trot and corde) else ""
        lignes.append(f"{prefix} N{num:<3} {nom:<26} {cote:>6.1f}{corde_str}")

    lignes.append("=" * 35)
    lignes.append("Outil statistique - Jouer responsable.")

    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today    = datetime.now()
    date_str = today.strftime("%d%m%Y")
    date_aff = today.strftime("%d/%m/%Y")

    log.info("=" * 60)
    log.info(f"  PMU NOTIFIER v3 - {date_aff}")
    log.info(f"  Messages H-15min envoyes AU BON MOMENT")
    log.info("=" * 60)

    telegram_send(f"PMU Notifier v3 demarre - {date_aff}\nMessages H-15min avant chaque course")

    courses = get_courses_du_jour(date_str)
    if not courses:
        telegram_send(f"ERREUR : aucune course trouvee pour {date_aff}")
        return

    # Filtrer les courses de la session actuelle (2h devant nous)
    # Chaque session couvre 2 heures de courses
    maintenant = datetime.now().timestamp() * 1000
    fin_session = maintenant + (2 * 60 * 60 * 1000)  # +2h en ms

    courses_a_faire = []
    for c in courses:
        heure_notif_ts = c["heure_ts"] - (15 * 60 * 1000)  # H-15min en ms
        if heure_notif_ts > maintenant and c["heure_ts"] <= fin_session + (15 * 60 * 1000):
            courses_a_faire.append(c)
        elif heure_notif_ts <= maintenant:
            log.info(f"  Course passee : R{c['nr']} C{c['nc']} — ignoree")
        else:
            log.info(f"  Course hors session : R{c['nr']} C{c['nc']} — couverte par session suivante")

    log.info(f"{len(courses_a_faire)} courses a couvrir")
    telegram_send(f"PMU Notifier {date_aff}\n{len(courses_a_faire)} courses a couvrir\nMessages H-15min avant chaque course")

    # Boucle principale — attendre et envoyer au bon moment
    for course in courses_a_faire:
        nr       = course["nr"]
        nc       = course["nc"]
        heure_ts = course["heure_ts"]

        # Calculer quand envoyer (H-15min)
        heure_notif_ts = heure_ts - (15 * 60 * 1000)
        maintenant_ts  = datetime.now().timestamp() * 1000
        attente_ms     = heure_notif_ts - maintenant_ts

        if attente_ms > 0:
            attente_sec = attente_ms / 1000
            heure_notif = datetime.fromtimestamp(heure_notif_ts / 1000)
            heure_course = datetime.fromtimestamp(heure_ts / 1000)
            log.info(
                f"  Attente {attente_sec:.0f}s jusqu a {heure_notif.strftime('%Hh%M')} "
                f"(course a {heure_course.strftime('%Hh%M')}) — R{nr} C{nc}"
            )

            # Attendre par tranches de 30s pour eviter le timeout
            while attente_sec > 0:
                tranche = min(30, attente_sec)
                time.sleep(tranche)
                attente_sec -= tranche
                maintenant_ts = datetime.now().timestamp() * 1000
                if maintenant_ts >= heure_notif_ts:
                    break

        # Collecter les partants et envoyer
        log.info(f"  Envoi H-15min pour R{nr} C{nc} — {course['libelle']}")
        partants = get_partants(date_str, nr, nc)

        if partants:
            message = formater_message_h15(course, partants)
            telegram_send(message)
            log.info(f"  Message envoye — R{nr} C{nc}")
        else:
            log.warning(f"  Pas de partants pour R{nr} C{nc}")
            telegram_send(
                f"DANS 15 MIN  R{nr} C{nc}\n"
                f"{course['libelle']}\n"
                f"{course['hippodrome']}\n"
                "Partants non disponibles"
            )

        time.sleep(1)

    # Fin
    telegram_send(f"PMU Notifier {date_aff} - Toutes les courses couvertes !")
    log.info("=" * 60)
    log.info("  NOTIFIER v3 TERMINE")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
