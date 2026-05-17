"""
=============================================================
  PMU NOTIFIER v4 - Messages H-15min avec recalcul leger
=============================================================
  Changements v3 -> v4 :
    - Charge le CSV du matin (genere par pmu_scorer.py)
    - Re-recupere la cote actuelle juste avant H-15min
    - Re-scrape les pronostics frais (Geny, Zone-Turf, etc.)
    - VERDICT : CONFIRME / RENFORCE / ATTENTION / CHANGEMENT
    - Garde le timing intelligent : attend jusqu a H-15min
    - 🔴 emoji devant numero de cheval (Top1 et Top2)

  Architecture B : 4 sessions/jour, chacune couvre ~2h de courses.
  Cron du workflow : 11h23, 13h23, 15h23, 17h23 (Paris).
=============================================================
"""

import csv
import glob
import json
import logging
import os
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo('Europe/Paris')
except ImportError:
    from datetime import timezone, timedelta
    TZ_PARIS = timezone(timedelta(hours=2))

import requests

# v4 : reutilise le module de scraping gratuit
try:
    from pronos_gratuit import get_pronostics_gratuit
    SCRAPING_DISPO = True
except ImportError:
    SCRAPING_DISPO = False

# v4 : reutilise le module de patterns historiques
try:
    from patterns_historiques import detecter_pattern_gagnant, calculer_score_opportunite
    PATTERNS_DISPO = True
except ImportError:
    PATTERNS_DISPO = False
    def detecter_pattern_gagnant(*args, **kwargs): return False
    def calculer_score_opportunite(*args, **kwargs): return 0.0

BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
OUTPUT_DIR     = "resultats"

PAYS_AUTORISES    = {"FRA", "FRANCE"}
DISCIPLINES_GALOP = {"PLAT", "HAIES", "STEEPLE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

# Duree d'une session : 2h ; on couvre les courses dans cet intervalle
SESSION_DUREE_H = 2

HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Notifier/4.0)",
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


def get_partants(date_str, nr, nc) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if data and isinstance(data, dict):
        p = data.get("participants", [])
        if p:
            return [x for x in p if x.get("statut") != "NON_PARTANT"]
    return []


# ──────────────────────────────────────────────
#  CHARGEMENT DU CSV DU MATIN (v4)
# ──────────────────────────────────────────────
def charger_pronos_matin(date_str_fich: str) -> dict:
    """
    Charge le dernier CSV genere par pmu_scorer.py du matin.
    Retourne un dict {(reunion, course): [top5 sorted by score]}
    """
    pattern  = os.path.join(OUTPUT_DIR, f"pmu_{date_str_fich}_*.csv")
    fichiers = sorted(glob.glob(pattern))
    if not fichiers:
        log.warning(f"Aucun CSV matin trouve pour {date_str_fich}")
        return {}

    fichier = fichiers[-1]
    log.info(f"Chargement CSV matin : {fichier}")

    courses = {}
    try:
        with open(fichier, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        grouped = {}
        for row in rows:
            cle = (row.get("reunion", ""), row.get("course", ""))
            grouped.setdefault(cle, []).append(row)

        for cle, partants in grouped.items():
            tries = sorted(
                partants,
                key=lambda x: float(x.get("score_total", 0) or 0),
                reverse=True,
            )
            courses[cle] = [
                {
                    "nom_cheval":     r.get("nom_cheval", ""),
                    "num_partant":    r.get("num_partant", ""),
                    "cote_jour":      float(r.get("cote_jour", 0) or 0),
                    "score_total":    float(r.get("score_total", 0) or 0),
                    "nb_pronostics":  int(float(r.get("nb_pronostics", 0) or 0)),
                    "nb_sources":     int(float(r.get("nb_sources_total", 0) or 0)),
                    "consensus_fort": r.get("consensus_fort", "False") == "True",
                    "value_bet":      r.get("value_bet", "False") == "True",
                    "jockey":         r.get("jockey", ""),
                    "discipline":     r.get("discipline", ""),
                    "type_course":    r.get("type_course_details", ""),
                    "libelle":        r.get("libelle", ""),
                    "hippodrome":     r.get("hippodrome", ""),
                    "terrain":        r.get("terrain", ""),
                    "distance_m":     r.get("distance_m", ""),
                    "nb_partants":    int(float(r.get("nb_partants", 0) or 0)),
                }
                for r in tries[:5]
            ]
    except Exception as e:
        log.error(f"Lecture CSV matin : {e}")
        return {}

    log.info(f"{len(courses)} courses chargees du matin")
    return courses


# ──────────────────────────────────────────────
#  RECALCUL LEGER A H-15MIN (v4)
# ──────────────────────────────────────────────
def actualiser_course(course_matin_top5: list, date_iso: str,
                      nr: int, nc: int, libelle: str,
                      partants_actuels: list) -> dict:
    """
    Compare l'etat actuel avec le pronostic du matin.

    Renvoie un dict :
      {
        "verdict":     "CONFIRME" | "RENFORCE" | "ATTENTION" | "CHANGEMENT",
        "n1_matin":    nom du N1 du matin,
        "n1_actuel":   nom du nouveau N1 (peut differer),
        "details":     liste de strings explicatives,
        "top2_final":  les 2 chevaux a parier maintenant (avec cotes fraiches),
      }
    """
    if not course_matin_top5:
        return {"verdict": "INDISPONIBLE", "details": ["CSV matin vide"]}

    # 1. Index par numero/nom des partants actuels
    partants_par_nom = {}
    for p in partants_actuels:
        nom_up = (p.get("nom") or "").upper().strip()
        if nom_up:
            partants_par_nom[nom_up] = p

    # 2. Detecter les non-partants depuis le matin
    non_partants_matin = []
    for ch in course_matin_top5:
        nom_up = ch["nom_cheval"].upper().strip()
        if nom_up not in partants_par_nom:
            non_partants_matin.append(ch["nom_cheval"])

    # 3. Recuperer les pronos frais (scraping)
    pronos_frais = {"scores": {}, "nb_sources": 0}
    if SCRAPING_DISPO:
        try:
            partants_pour_scraper = [
                {"nom": p.get("nom", ""), "num": p.get("numPmu") or p.get("numero")}
                for p in partants_actuels if p.get("nom")
            ]
            res = get_pronostics_gratuit(
                date_str=date_iso, reunion_num=nr, course_num=nc,
                nom_course=libelle, partants=partants_pour_scraper,
            )
            pronos_frais = res
        except Exception as e:
            log.debug(f"Scraping H-15 echoue R{nr}C{nc}: {e}")

    # 4. Pour chaque cheval du Top5 matin, recuperer cote actuelle + pronos
    chevaux_actualises = []
    for ch in course_matin_top5:
        nom_up = ch["nom_cheval"].upper().strip()
        p_actuel = partants_par_nom.get(nom_up)
        if not p_actuel:
            continue  # non-partant, ignore

        cote_matin   = ch["cote_jour"]
        cote_actuel  = extraire_cote(p_actuel)
        variation    = 0.0
        if cote_matin > 0 and cote_actuel > 0:
            variation = (cote_matin - cote_actuel) / cote_matin * 100

        # Score frais des pronos scrapes
        score_pronos_frais = pronos_frais.get("scores", {}).get(nom_up, 0)

        chevaux_actualises.append({
            **ch,
            "cote_actuel":       cote_actuel,
            "variation_cote_pc": round(variation, 1),
            "score_pronos_frais": score_pronos_frais,
        })

    if not chevaux_actualises:
        return {"verdict": "INDISPONIBLE", "details": ["Aucun cheval Top5 retrouve"]}

    # 5. Tri final (score combine : score matin + boost si pronos frais confirment)
    def score_combine(c):
        boost = c["score_pronos_frais"] * 0.2  # max 20 pts de boost
        return c["score_total"] + boost

    chevaux_actualises.sort(key=score_combine, reverse=True)

    n1_matin   = course_matin_top5[0]["nom_cheval"]
    n1_actuel  = chevaux_actualises[0]["nom_cheval"]
    n1_data    = chevaux_actualises[0]

    # 6. Verdict
    details = []
    if non_partants_matin:
        details.append(f"FORFAITS : {', '.join(non_partants_matin)}")

    if n1_matin != n1_actuel:
        verdict = "CHANGEMENT"
        details.append(f"Nouveau favori : {n1_actuel} (etait {n1_matin})")
    else:
        # Meme N1 : analyser la cote pour affiner
        var = n1_data["variation_cote_pc"]
        pronos_frais_bonus = n1_data["score_pronos_frais"]

        if var >= 15 or pronos_frais_bonus >= 60:
            verdict = "RENFORCE"
            if var >= 15:
                details.append(f"Cote en baisse de {var:.0f}% (marche favorable)")
            if pronos_frais_bonus >= 60:
                details.append(f"Confirme par pronostics frais ({pronos_frais.get('nb_sources', 0)} sources)")
        elif var <= -25:
            verdict = "ATTENTION"
            details.append(f"CHUTE cote {var:.0f}% (signal negatif)")
        elif var <= -15:
            verdict = "ATTENTION"
            details.append(f"Cote remonte de {abs(var):.0f}% (prudence)")
        else:
            verdict = "CONFIRME"
            details.append(f"Cote stable ({var:+.0f}%)")

    return {
        "verdict":     verdict,
        "n1_matin":    n1_matin,
        "n1_actuel":   n1_actuel,
        "details":     details,
        "top2_final":  chevaux_actualises[:2],
        "tous_top5":   chevaux_actualises,
        "non_partants": non_partants_matin,
        "nb_sources_frais": pronos_frais.get("nb_sources", 0),
    }


# ──────────────────────────────────────────────
#  CONSTRUCTION DU PROGRAMME
# ──────────────────────────────────────────────
def get_courses_du_jour(date_str: str) -> list:
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
            })

    courses.sort(key=lambda x: x["heure_ts"])
    log.info(f"{len(courses)} courses au programme du jour")
    return courses


# ──────────────────────────────────────────────
#  FORMAT MESSAGE H-15MIN (v4)
# ──────────────────────────────────────────────
def formater_message_h15(course: dict, partants: list,
                          maj: dict) -> str:
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
            heure_str = datetime.fromtimestamp(heure_ts / 1000, tz=TZ_PARIS).strftime("%Hh%M")
        except Exception:
            pass

    terrain_str = f" | {terrain}" if terrain else ""
    dist_str    = f" | {distance}m" if distance else ""

    verdict = maj.get("verdict", "INDISPONIBLE")

    # Emoji du verdict (impact visuel immediat)
    verdict_emoji = {
        "CONFIRME":     "✅",
        "RENFORCE":     "🔥",
        "ATTENTION":    "⚠️",
        "CHANGEMENT":   "🔄",
        "INDISPONIBLE": "❓",
    }.get(verdict, "")

    lignes = [
        f"{verdict_emoji} DANS 15 MIN  R{nr} C{nc} | {heure_str} | {discipline}",
        libelle[:50],
        f"HIPPODROME {hippodrome}{terrain_str}{dist_str}",
        "=" * 35,
        f"VERDICT : {verdict}",
    ]

    for d in maj.get("details", []):
        lignes.append(f"  -> {d}")

    if maj.get("non_partants"):
        lignes.append("")
        lignes.append(f"FORFAITS : {', '.join(maj['non_partants'])}")

    # Top 2 final (avec cote actuelle)
    top2 = maj.get("top2_final", [])
    if top2:
        lignes.append("")
        lignes.append("--- NOS 2 CHOIX FINAUX ---")
        for i, ch in enumerate(top2):
            num         = ch.get("num_partant", "")
            nom         = ch.get("nom_cheval", "?")
            cote_a      = ch.get("cote_actuel", 0)
            cote_m      = ch.get("cote_jour", 0)
            var         = ch.get("variation_cote_pc", 0)
            score       = ch.get("score_total", 0)
            nb_src      = ch.get("nb_sources", 0)
            nb_p        = ch.get("nb_pronostics", 0)

            prefix = ">>" if i == 0 else "  "
            # 🔴 sur le numero du cheval
            nom_aff = f"🔴 N{num}. {nom}" if num else f"🔴 {nom}"

            mvt_str = ""
            if abs(var) >= 5:
                mvt_str = f" [{var:+.0f}%]"
                if var >= 15:
                    mvt_str += " 📉baisse"
                elif var <= -15:
                    mvt_str += " 📈monte"

            lignes.append(f"{prefix} {i+1}. {nom_aff}")
            lignes.append(f"   Cote matin {cote_m:.1f} -> actuelle {cote_a:.1f}{mvt_str}")
            lignes.append(f"   Score matin : {score:.1f}% | {nb_p}/{nb_src} sources")

    # Top5 actualise (rappel rapide)
    lignes.append("")
    lignes.append("--- TOP 5 ACTUALISE ---")
    for i, ch in enumerate(maj.get("tous_top5", [])[:5]):
        num    = ch.get("num_partant", "")
        nom    = ch.get("nom_cheval", "?")[:22]
        cote_a = ch.get("cote_actuel", 0)
        var    = ch.get("variation_cote_pc", 0)
        var_str = f" {var:+.0f}%" if abs(var) >= 5 else ""
        prefix = ">>" if i < 2 else "  "
        lignes.append(f"{prefix} {i+1}. N{num} {nom} | cote {cote_a:.1f}{var_str}")

    if maj.get("nb_sources_frais"):
        lignes.append("")
        lignes.append(f"Pronostics frais : {maj['nb_sources_frais']} source(s) consultee(s)")

    lignes.append("=" * 35)
    lignes.append("Outil statistique - Jouer responsable.")

    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today    = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_iso      = today.strftime("%Y-%m-%d")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")

    log.info("=" * 60)
    log.info(f"  PMU NOTIFIER v4 - {date_aff}")
    log.info(f"  Messages H-15min : recalcul leger + verdict")
    log.info(f"  Scraping : {'OK' if SCRAPING_DISPO else 'NON'}")
    log.info(f"  Patterns : {'OK' if PATTERNS_DISPO else 'NON'}")
    log.info("=" * 60)

    # 1. Charger le CSV du matin
    pronos_matin = charger_pronos_matin(date_str_fich)
    if not pronos_matin:
        msg = f"PMU Notifier {date_aff} - ERREUR : pas de CSV matin"
        log.error(msg)
        telegram_send(msg)
        return

    # 2. Charger le programme du jour
    courses = get_courses_du_jour(date_str)
    if not courses:
        telegram_send(f"PMU Notifier {date_aff} - Aucune course")
        return

    # 3. Filtrer les courses de la session actuelle (2h devant nous)
    maintenant = datetime.now(tz=TZ_PARIS).timestamp() * 1000
    fin_session = maintenant + (SESSION_DUREE_H * 60 * 60 * 1000)

    courses_a_faire = []
    for c in courses:
        heure_notif_ts = c["heure_ts"] - (15 * 60 * 1000)
        if heure_notif_ts > maintenant and c["heure_ts"] <= fin_session + (15 * 60 * 1000):
            courses_a_faire.append(c)

    if not courses_a_faire:
        log.info("Aucune course dans cette session")
        telegram_send(
            f"PMU Notifier {date_aff}\n"
            "Pas de course dans les 2 prochaines heures.\n"
            "Prochain notifier dans 2h."
        )
        return

    log.info(f"{len(courses_a_faire)} courses a couvrir dans cette session")
    telegram_send(
        f"PMU Notifier v4 - {date_aff}\n"
        f"Session : {len(courses_a_faire)} courses\n"
        f"Verdict H-15min : CONFIRME / RENFORCE / ATTENTION / CHANGEMENT"
    )

    # 4. Boucle principale
    for course in courses_a_faire:
        nr       = course["nr"]
        nc       = course["nc"]
        heure_ts = course["heure_ts"]

        heure_notif_ts = heure_ts - (15 * 60 * 1000)
        maintenant_ts  = datetime.now().timestamp() * 1000
        attente_ms     = heure_notif_ts - maintenant_ts

        if attente_ms > 0:
            attente_sec = attente_ms / 1000
            heure_notif  = datetime.fromtimestamp(heure_notif_ts / 1000)
            heure_course = datetime.fromtimestamp(heure_ts / 1000)
            log.info(
                f"  Attente {attente_sec:.0f}s jusqu a {heure_notif.strftime('%Hh%M')} "
                f"(course a {heure_course.strftime('%Hh%M')}) - R{nr} C{nc}"
            )
            # Attente par tranches de 30s pour eviter le timeout
            while attente_sec > 0:
                tranche = min(30, attente_sec)
                time.sleep(tranche)
                attente_sec -= tranche
                if datetime.now().timestamp() * 1000 >= heure_notif_ts:
                    break

        # Recuperation H-15min : partants frais + actualisation
        log.info(f"  Recalcul H-15min R{nr} C{nc} - {course['libelle']}")
        partants_actuels = get_partants(date_str, nr, nc)

        if not partants_actuels:
            log.warning(f"  Partants indisponibles R{nr}C{nc}")
            telegram_send(
                f"⚠️ DANS 15 MIN  R{nr} C{nc}\n"
                f"{course['libelle']}\n"
                f"{course['hippodrome']}\n"
                "Partants non disponibles a H-15min"
            )
            continue

        # Recuperer le pronostic du matin
        course_matin = pronos_matin.get((f"R{nr}", f"C{nc}"), [])
        if not course_matin:
            log.warning(f"  Pas de prono matin pour R{nr}C{nc}")
            telegram_send(
                f"❓ DANS 15 MIN  R{nr} C{nc}\n"
                f"{course['libelle']}\n"
                "Pas de pronostic matin disponible"
            )
            continue

        # Actualisation
        maj = actualiser_course(
            course_matin_top5=course_matin,
            date_iso=date_iso,
            nr=int(nr), nc=int(nc),
            libelle=course["libelle"],
            partants_actuels=partants_actuels,
        )

        # Envoi message
        message = formater_message_h15(course, partants_actuels, maj)
        telegram_send(message)
        log.info(f"  Envoye R{nr}C{nc} : {maj.get('verdict', '?')}")
        time.sleep(1)

    # Fin de session
    telegram_send(f"PMU Notifier {date_aff} - Session terminee.")
    log.info("=" * 60)
    log.info("  NOTIFIER v4 TERMINE")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
