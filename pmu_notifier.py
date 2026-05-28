"""
=============================================================
  PMU NOTIFIER v5 - Version ECONOME (ponctuelle)
=============================================================
  Changement MAJEUR v4 -> v5 :
    - SUPPRESSION de l'attente active (time.sleep de 2h)
    - Le notifier regarde les courses dont H-15min tombe
      dans une FENETRE de [FENETRE_MIN] minutes a partir de
      maintenant, envoie les notifs, puis S'ARRETE.
    - Duree d'execution : ~30 secondes au lieu de 2h.
    - Doit etre appele frequemment (toutes les 15-20 min)
      par cron-job.org entre ~11h et ~20h.

  ECONOMIE : passe de ~8h/jour de runtime a ~10 min/jour.

  Tout le reste (verdict, scraping frais, formatage) est
  identique a la v4.
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

# ── v5 : FENETRE PONCTUELLE ───────────────────────────────
# On notifie les courses dont l'heure de depart tombe entre
# (maintenant + MARGE_MIN_MIN) et (maintenant + FENETRE_MIN).
# Avec un appel cron toutes les 15-20 min, ca couvre tout.
#
# Exemple : FENETRE_MIN=22, MARGE_MIN_MIN=3
#   -> on notifie les courses qui partent entre 3 et 22 min.
#   -> a H-15min en moyenne, comme avant.
FENETRE_MIN     = 22   # borne haute : courses partant dans <= 22 min
MARGE_MIN_MIN   = 2    # borne basse : courses partant dans >= 2 min
# Anti-doublon : on note les courses deja notifiees dans un
# petit fichier JSON du jour (evite de re-notifier au prochain
# reveil cron si la course est encore dans la fenetre).
ETAT_FICHIER    = os.path.join(OUTPUT_DIR, "notifier_etat_{date}.json")

HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Notifier/5.0)",
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
#  ETAT (anti-doublon) - v5
# ──────────────────────────────────────────────
def charger_etat(date_str_fich: str) -> set:
    """Renvoie l'ensemble des cles 'R{nr}C{nc}' deja notifiees aujourd'hui."""
    chemin = ETAT_FICHIER.format(date=date_str_fich)
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("notifiees", []))
    except Exception:
        return set()


def sauver_etat(date_str_fich: str, notifiees: set):
    chemin = ETAT_FICHIER.format(date=date_str_fich)
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"notifiees": sorted(notifiees)}, f)
    except Exception as e:
        log.warning(f"Sauvegarde etat: {e}")


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
            # MODIF 27/05/2026 : CORRECTION BUG du top5-par-score.
            # AVANT : on triait par score_total et on gardait tries[:5].
            #   -> les vrais FAVORIS (cote basse) ont souvent un score faible,
            #      donc ils tombaient HORS du top5 et le notifier ne les voyait pas.
            #      Resultat : le filtre cote basse ne pouvait choisir que parmi des
            #      outsiders (ex Prix de Dax 26/05 : N1 BAKENEKO 13/1 alors que
            #      IMPERIAL CHOPE 3.8 et DECLA 2.8 gagnaient, hors top5 score).
            # APRES : on trie par COTE CROISSANTE (favori d'abord) et on garde TOUS
            #   les partants. Le filtre cote basse de actualiser_course() peut alors
            #   voir et choisir les vrais favoris. Coherent avec la regle validee.
            tries = sorted(
                partants,
                key=lambda x: (float(x.get("cote_jour", 0) or 0) <= 0,   # cotes 0/absentes a la fin
                               float(x.get("cote_jour", 0) or 9999)),    # puis cote croissante
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
                for r in tries   # MODIF 27/05 : TOUS les partants (etait tries[:5])
            ]
    except Exception as e:
        log.error(f"Lecture CSV matin : {e}")
        return {}

    log.info(f"{len(courses)} courses chargees du matin")
    return courses


# ──────────────────────────────────────────────
#  RECALCUL LEGER A H-15MIN (v4 - inchange)
# ──────────────────────────────────────────────
def actualiser_course(course_matin_top5: list, date_iso: str,
                      nr: int, nc: int, libelle: str,
                      partants_actuels: list) -> dict:
    if not course_matin_top5:
        return {"verdict": "INDISPONIBLE", "details": ["CSV matin vide"]}

    partants_par_nom = {}
    for p in partants_actuels:
        nom_up = (p.get("nom") or "").upper().strip()
        if nom_up:
            partants_par_nom[nom_up] = p

    non_partants_matin = []
    for ch in course_matin_top5:
        nom_up = ch["nom_cheval"].upper().strip()
        if nom_up not in partants_par_nom:
            non_partants_matin.append(ch["nom_cheval"])

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

    chevaux_actualises = []
    for ch in course_matin_top5:
        nom_up = ch["nom_cheval"].upper().strip()
        p_actuel = partants_par_nom.get(nom_up)
        if not p_actuel:
            continue

        cote_matin   = ch["cote_jour"]
        cote_actuel  = extraire_cote(p_actuel)
        variation    = 0.0
        if cote_matin > 0 and cote_actuel > 0:
            variation = (cote_actuel - cote_matin) / cote_matin * 100

        score_pronos_frais = pronos_frais.get("scores", {}).get(nom_up, 0)

        chevaux_actualises.append({
            **ch,
            "cote_actuel":       cote_actuel,
            "variation_cote_pc": round(variation, 1),
            "score_pronos_frais": score_pronos_frais,
        })

    if not chevaux_actualises:
        return {"verdict": "INDISPONIBLE", "details": ["Aucun cheval Top5 retrouve"]}

    # MODIF 28/05/2026 : SCORE COMBINÉ (cote + score enrichi).
    # Objectif (choix utilisateur) : laisser le SCORE ENRICHI (forme, déferrage,
    # progression... = notre recherche subtile) s'exprimer, MAIS en gardant un poids
    # MODÉRÉ sur la cote comme garde-fou (ne pas retomber sur des outsiders à 43/1).
    # Méthode :
    #   1. Garde-fou dur : on écarte les cotes > COTE_MAX_NOTIFIER (aberrations).
    #   2. On classe par une note combinée :
    #        note = POIDS_COTE * note_cote + POIDS_SCORE * note_score
    #      où note_cote favorise les cotes basses, note_score le score enrichi.
    # NON VALIDÉ (journée expérimentale) : poids à ajuster selon les résultats.
    COTE_MAX_NOTIFIER = 6.0    # garde-fou dur : pas de N1 outsider aberrant
    POIDS_COTE   = 0.55        # la cote reste le garde-fou principal (modéré)
    POIDS_SCORE  = 0.45        # mais le score enrichi pèse presque autant

    def _cote_ok(c):
        ca = c.get("cote_actuel", 0) or 0
        return 0 < ca <= COTE_MAX_NOTIFIER

    _raisonnables = [c for c in chevaux_actualises if _cote_ok(c)]
    _pool = _raisonnables if _raisonnables else chevaux_actualises

    # note_cote : basée sur la VALEUR de la cote (pas une normalisation relative qui
    # écrasait tout). cote 1.5 -> ~100, cote 6 -> ~0. Dégressif doux.
    def _note_cote(c):
        ca = c.get("cote_actuel", 0) or 999
        if ca <= 0:
            return 0.0
        # 100 a cote 1.5, decroit lineairement jusqu'a 0 vers cote 7
        return max(0.0, min(100.0, 100.0 * (7.0 - ca) / (7.0 - 1.5)))

    def _note_combinee(c):
        nc = _note_cote(c)
        ns = c.get("score_total", 0) or 0       # score enrichi (0-100)
        ns += c.get("score_pronos_frais", 0) * 0.2
        return POIDS_COTE * nc + POIDS_SCORE * ns

    _pool.sort(key=_note_combinee, reverse=True)   # meilleure note d'abord
    chevaux_actualises = _pool

    n1_matin   = course_matin_top5[0]["nom_cheval"]
    n1_actuel  = chevaux_actualises[0]["nom_cheval"]
    n1_data    = chevaux_actualises[0]

    details = []
    if non_partants_matin:
        details.append(f"FORFAITS : {', '.join(non_partants_matin)}")

    if n1_matin != n1_actuel:
        verdict = "CHANGEMENT"
        details.append(f"Nouveau favori : {n1_actuel} (etait {n1_matin})")
    else:
        var = n1_data["variation_cote_pc"]
        pronos_frais_bonus = n1_data["score_pronos_frais"]

        # v5 : variation = (cote_actuel - cote_matin)/cote_matin
        #   var < 0  => cote BAISSE (marche favorable) => RENFORCE
        #   var > 0  => cote MONTE (marche delaisse)   => ATTENTION
        if var <= -15 or pronos_frais_bonus >= 60:
            verdict = "RENFORCE"
            if var <= -15:
                details.append(f"Cote en baisse de {abs(var):.0f}% (marche favorable)")
            if pronos_frais_bonus >= 60:
                details.append(f"Confirme par pronostics frais ({pronos_frais.get('nb_sources', 0)} sources)")
        elif var >= 25:
            verdict = "ATTENTION"
            details.append(f"Cote monte de {var:.0f}% (signal negatif)")
        elif var >= 15:
            verdict = "ATTENTION"
            details.append(f"Cote monte de {var:.0f}% (prudence)")
        else:
            verdict = "CONFIRME"
            details.append(f"Cote stable ({var:+.0f}%)")

    return {
        "verdict":     verdict,
        "n1_matin":    n1_matin,
        "n1_actuel":   n1_actuel,
        "details":     details,
        "top2_final":  chevaux_actualises[:5],  # MODIF 28/05 : 5 choix (était 2)
        "tous_top5":   chevaux_actualises,
        "non_partants": non_partants_matin,
        "nb_sources_frais": pronos_frais.get("nb_sources", 0),
    }


# ──────────────────────────────────────────────
#  CONSTRUCTION DU PROGRAMME (v4 - inchange)
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
#  FORMAT MESSAGE H-15MIN (v4 - inchange sauf emoji mvt)
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

    heure_str = ""
    if heure_ts:
        try:
            heure_str = datetime.fromtimestamp(heure_ts / 1000, tz=TZ_PARIS).strftime("%Hh%M")
        except Exception:
            pass

    terrain_str = f" | {terrain}" if terrain else ""
    dist_str    = f" | {distance}m" if distance else ""

    verdict = maj.get("verdict", "INDISPONIBLE")

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

    top2 = maj.get("top2_final", [])
    if top2:
        lignes.append("")
        # MODIF 28/05 : titre dynamique selon le nombre réel de chevaux affichés.
        nb_choix = len(top2)
        if nb_choix == 1:
            lignes.append("--- NOTRE CHOIX FINAL ---")
        else:
            lignes.append(f"--- NOS {nb_choix} CHEVAUX (classes) ---")
        for i, ch in enumerate(top2):
            num         = ch.get("num_partant", "")
            nom         = ch.get("nom_cheval", "?")
            cote_a      = ch.get("cote_actuel", 0)
            cote_m      = ch.get("cote_jour", 0)
            var         = ch.get("variation_cote_pc", 0)
            score       = ch.get("score_total", 0)
            nb_src      = ch.get("nb_sources", 0)
            nb_p        = ch.get("nb_pronostics", 0)

            # >> sur les 2 premiers (choix principaux), espace sur les suivants
            prefix = ">>" if i < 2 else "  "
            nom_aff = f"🔴 N{num}. {nom}" if num else f"🔴 {nom}"

            # v5 : var = (actuel - matin)/matin
            #   var < 0 => cote baisse (favorable) => 📉
            #   var > 0 => cote monte => 📈
            mvt_str = ""
            if abs(var) >= 5:
                mvt_str = f" [{var:+.0f}%]"
                if var <= -15:
                    mvt_str += " 📉 baisse (favorable)"
                elif var >= 15:
                    mvt_str += " 📈 monte"

            lignes.append(f"{prefix} {i+1}. {nom_aff}")
            lignes.append(f"   Cote matin {cote_m:.1f} -> actuelle {cote_a:.1f}{mvt_str}")
            lignes.append(f"   Score matin : {score:.1f}% | {nb_p}/{nb_src} sources")

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
#  PROGRAMME PRINCIPAL v5 - PONCTUEL (sans attente)
# ──────────────────────────────────────────────
def main():
    today         = datetime.now()
    date_str      = today.strftime("%d%m%Y")
    date_iso      = today.strftime("%Y-%m-%d")
    date_str_fich = today.strftime("%Y%m%d")
    date_aff      = today.strftime("%d/%m/%Y")

    log.info("=" * 60)
    log.info(f"  PMU NOTIFIER v5 (ECONOME) - {date_aff}")
    log.info(f"  Fenetre : courses partant dans {MARGE_MIN_MIN}-{FENETRE_MIN} min")
    log.info(f"  Scraping : {'OK' if SCRAPING_DISPO else 'NON'}")
    log.info("=" * 60)

    # 1. Charger le CSV du matin
    pronos_matin = charger_pronos_matin(date_str_fich)
    if not pronos_matin:
        log.warning("Pas de CSV matin - le notifier ne peut rien faire (silencieux)")
        # v5 : pas de message Telegram d'erreur (evite le spam a chaque reveil)
        return

    # 2. Charger le programme du jour
    courses = get_courses_du_jour(date_str)
    if not courses:
        log.info("Aucune course au programme")
        return

    # 3. Selectionner SEULEMENT les courses dans la fenetre
    maintenant_ts = datetime.now(tz=TZ_PARIS).timestamp() * 1000
    borne_basse   = maintenant_ts + (MARGE_MIN_MIN * 60 * 1000)
    borne_haute   = maintenant_ts + (FENETRE_MIN * 60 * 1000)

    courses_fenetre = [
        c for c in courses
        if borne_basse <= c["heure_ts"] <= borne_haute
    ]

    if not courses_fenetre:
        log.info("Aucune course dans la fenetre - arret immediat (economie)")
        return

    # 4. Anti-doublon : retirer celles deja notifiees aujourd'hui
    deja = charger_etat(date_str_fich)
    courses_a_notifier = [
        c for c in courses_fenetre
        if f"R{c['nr']}C{c['nc']}" not in deja
    ]

    if not courses_a_notifier:
        log.info("Toutes les courses de la fenetre deja notifiees - arret")
        return

    log.info(f"{len(courses_a_notifier)} course(s) a notifier maintenant")

    # 5. Notifier chaque course (SANS attente - elles sont deja proches)
    for course in courses_a_notifier:
        nr = course["nr"]
        nc = course["nc"]
        cle = f"R{nr}C{nc}"

        log.info(f"  Notif R{nr}C{nc} - {course['libelle']}")
        partants_actuels = get_partants(date_str, nr, nc)

        if not partants_actuels:
            log.warning(f"  Partants indisponibles R{nr}C{nc}")
            deja.add(cle)  # on marque quand meme pour eviter de reessayer en boucle
            continue

        course_matin = pronos_matin.get((f"R{nr}", f"C{nc}"), [])
        if not course_matin:
            log.warning(f"  Pas de prono matin pour R{nr}C{nc} - ignore (pas de message)")
            deja.add(cle)
            continue

        maj = actualiser_course(
            course_matin_top5=course_matin,
            date_iso=date_iso,
            nr=int(nr), nc=int(nc),
            libelle=course["libelle"],
            partants_actuels=partants_actuels,
        )

        message = formater_message_h15(course, partants_actuels, maj)
        telegram_send(message)
        log.info(f"  Envoye R{nr}C{nc} : {maj.get('verdict', '?')}")

        deja.add(cle)
        time.sleep(1)

    # 6. Sauvegarder l'etat (anti-doublon pour les prochains reveils)
    sauver_etat(date_str_fich, deja)

    log.info("=" * 60)
    log.info(f"  NOTIFIER v5 TERMINE - {len(courses_a_notifier)} notif(s) envoyee(s)")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
