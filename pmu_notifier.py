"""
=============================================================
  PMU NOTIFIER - Pronostics H-15min avant chaque course
=============================================================
  Tourne en continu de 11h a 20h.
  15 minutes avant chaque course, collecte les pronostics
  de 30 sources et envoie une synthese sur Telegram.
=============================================================
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import requests

# ──────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────
BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

PAYS_AUTORISES    = {"FRA", "FRANCE"}
MINUTES_AVANT     = 15    # Envoyer X minutes avant la course
DELAI_VERIFICATION = 60   # Verifier toutes les 60 secondes

# ── 30 sources de pronostics avec poids top3 ──
SOURCES_GALOP = {
    "Turf BZH":          4.0,
    "Paris-Turf":        3.5,
    "Frequence Turf":    3.2,
    "Equidia":           3.0,
    "Canalturf":         2.8,
    "Europe 1 Turf":     2.5,
    "Turfomania":        2.5,
    "Zone-Turf":         2.5,
    "Turfoo":            2.5,
    "Sud Radio Turf":    2.3,
    "Geny":              2.0,
    "GRM Turf":          2.0,
    "Coin Turf":         1.8,
    "Tierce Magazine":   1.8,
    "Turf-fr":           1.5,
    "PMU officiel":      2.5,
}

SOURCES_TROT = {
    "Le Trot":           4.0,
    "Equidia":           3.5,
    "Paris-Turf":        3.2,
    "Canalturf":         3.0,
    "Turfomania":        2.8,
    "Zone-Turf":         2.5,
    "Turfoo":            2.5,
    "Frequence Turf":    2.5,
    "GRM Turf":          2.3,
    "Geny":              2.0,
    "Coin Turf":         1.8,
    "Tierce Magazine":   1.8,
    "PMU officiel":      2.5,
}

SOURCES_PREMIUM_GALOP = {"Turf BZH", "Paris-Turf", "Equidia", "Frequence Turf", "Canalturf"}
SOURCES_PREMIUM_TROT  = {"Le Trot", "Equidia", "Paris-Turf", "Canalturf", "Frequence Turf"}

DISCIPLINES_GALOP = {"PLAT", "HAIES", "STEEPLE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

# ──────────────────────────────────────────────
#  LOGGING
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("notifier")


def est_trot(discipline: str) -> bool:
    return discipline.upper() in DISCIPLINES_TROT


# ──────────────────────────────────────────────
#  TELEGRAM
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limite   = 4096
    morceaux = [texte[i:i+limite] for i in range(0, len(texte), limite)]
    for morceau in morceaux:
        try:
            r = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT, "text": morceau},
                timeout=15,
            )
            if r.status_code != 200:
                log.warning(f"Telegram {r.status_code}: {r.text[:100]}")
                return False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Telegram erreur: {e}")
            return False
    return True


# ──────────────────────────────────────────────
#  API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Notifier/1.0)",
    "Accept": "application/json",
}


def api_get(path: str):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"API erreur {path}: {e}")
        return None


def get_participants(date_str, nr, nc) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if data and isinstance(data, dict):
        p = data.get("participants", [])
        if p:
            return p
    data2 = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants?combinePlacesEtCouplees=true")
    if data2 and isinstance(data2, dict):
        return data2.get("participants", [])
    return []


def extraire_cote(partant: dict) -> float:
    for champ in ["dernierRapportDirect", "dernierRapportReference", "cotesPmu"]:
        if partant.get(champ):
            try:
                val = partant[champ].get("rapport", 0)
                if val and float(val) > 0:
                    return float(val)
            except (ValueError, TypeError):
                pass
    return 0.0


# ──────────────────────────────────────────────
#  COLLECTE PRONOSTICS 30 SOURCES VIA CLAUDE
# ──────────────────────────────────────────────
def collecter_pronostics_course(
    partants: list,
    libelle: str,
    hippodrome: str,
    discipline: str,
    date_aff: str,
    heure_str: str,
) -> dict:
    """
    Interroge Claude pour collecter les pronostics de 30 sources
    pour une course specifique.
    Retourne un dict complet avec citations ponderees.
    """
    if not ANTHROPIC_KEY:
        return {}

    trot = est_trot(discipline)
    sources = SOURCES_TROT if trot else SOURCES_GALOP
    sources_premium = SOURCES_PREMIUM_TROT if trot else SOURCES_PREMIUM_GALOP
    type_course = "trot (attele/monte)" if trot else "galop (plat/haies/steeple)"

    # Construire la liste des partants avec numeros
    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    partants_str = ", ".join([
        f"N{p.get('numPmu','?')}. {p.get('nom','?')} (cote {extraire_cote(p):.1f})"
        for p in partants_actifs[:16]
    ])
    sources_str = "\n".join([f"- {s} (poids {w})" for s, w in sources.items()])

    prompt = f"""Tu es un expert en courses hippiques francaises, specialiste {type_course}.

Course : "{libelle}" a {hippodrome}
Heure  : {heure_str} le {date_aff}
Type   : {type_course.upper()}

Partants (numero. nom cote) :
{partants_str}

Recherche MAINTENANT les pronostics de ces sources pour CETTE course specifique :
{sources_str}

IMPORTANT : cherche les pronostics du TOP 3 (pas seulement le gagnant).
Utilise le nom exact de la course et l'hippodrome pour trouver les bons pronostics.

Reponds UNIQUEMENT en JSON :
{{
  "nb_sources_trouvees": 12,
  "citations_top3": {{
    "NOM_CHEVAL_1": 10,
    "NOM_CHEVAL_2": 7,
    "NOM_CHEVAL_3": 5
  }},
  "sources_par_cheval": {{
    "NOM_CHEVAL_1": ["Paris-Turf", "Equidia", "Turf BZH", "Frequence Turf"],
    "NOM_CHEVAL_2": ["Equidia", "Zone-Turf", "Turfomania"]
  }},
  "sources_consultees": ["Paris-Turf", "Equidia", "Turf BZH"],
  "resume_tendance": "Description des tendances principales",
  "cheval_surprise": "Nom du cheval outsider qui revient souvent",
  "consensus": true
}}

consensus = true si au moins 3 sources premium citent le meme cheval.
Si aucune source trouvee : {{"nb_sources_trouvees": 0, "citations_top3": {{}}, "sources_par_cheval": {{}}, "sources_consultees": [], "resume_tendance": "Aucun pronostic trouve", "consensus": false}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        if r.status_code != 200:
            log.warning(f"Claude API {r.status_code}")
            return {}

        data  = r.json()
        texte = " ".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = json.loads(texte.replace("```json", "").replace("```", "").strip())

        # Calculer les citations ponderees
        citations_pond = {}
        for nom, sources_citantes in parsed.get("sources_par_cheval", {}).items():
            nom_up = nom.upper().strip()
            poids  = sum(sources.get(s, 1.0) for s in sources_citantes)
            citations_pond[nom_up] = round(poids, 2)

        return {
            "nb_sources":       int(parsed.get("nb_sources_trouvees", 0)),
            "citations":        {k.upper(): v for k, v in parsed.get("citations_top3", {}).items()},
            "citations_pond":   citations_pond,
            "sources_par_ch":   {k.upper(): v for k, v in parsed.get("sources_par_cheval", {}).items()},
            "sources_vues":     parsed.get("sources_consultees", []),
            "resume":           parsed.get("resume_tendance", ""),
            "cheval_surprise":  parsed.get("cheval_surprise", "").upper(),
            "consensus":        bool(parsed.get("consensus", False)),
            "sources_premium":  sources_premium,
        }

    except Exception as e:
        log.warning(f"Erreur collecte pronostics: {e}")
        return {}


# ──────────────────────────────────────────────
#  FORMATAGE DU MESSAGE H-15min
# ──────────────────────────────────────────────
def formater_message_h15(
    course_info: dict,
    partants: list,
    pronostics: dict,
    date_aff: str,
) -> str:

    disc     = course_info.get("discipline", "").replace("_", " ")
    libelle  = course_info.get("libelle", "")
    reunion  = course_info.get("reunion", "")
    nc       = course_info.get("course", "")
    hippo    = course_info.get("hippodrome", "")
    heure_str = course_info.get("heure_str", "")
    trot     = est_trot(course_info.get("discipline", ""))

    nb_sources = pronostics.get("nb_sources", 0)
    citations  = pronostics.get("citations", {})
    cit_pond   = pronostics.get("citations_pond", {})
    sources_ch = pronostics.get("sources_par_ch", {})
    resume     = pronostics.get("resume", "")
    surprise   = pronostics.get("cheval_surprise", "")
    consensus  = pronostics.get("consensus", False)
    src_premium = pronostics.get("sources_premium", set())

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]

    # Trier par citations ponderees
    classement = sorted(
        [(nom, pts) for nom, pts in cit_pond.items()],
        key=lambda x: x[1], reverse=True
    )

    poids_max = max(cit_pond.values()) if cit_pond else 1.0

    lignes = []
    alert  = "*** CONSENSUS FORT ***" if consensus else ""

    lignes.append(f"DANS 15 MIN  {reunion} {nc} | {heure_str} | {disc}")
    lignes.append(f"{libelle[:50]}")
    lignes.append(f"{hippo}")
    if alert:
        lignes.append(alert)
    lignes.append("=" * 35)

    if nb_sources == 0:
        lignes.append("Pronostics non encore disponibles")
        lignes.append("Analyse statistique uniquement")
    else:
        lignes.append(f"SYNTHESE {nb_sources} SOURCES :")
        lignes.append("")

        # Barre de progression pour chaque cheval cité
        for nom, pts in classement[:6]:
            nb_cit  = citations.get(nom, 0)
            pct     = round((nb_cit / nb_sources) * 100) if nb_sources > 0 else 0
            barres  = round(pct / 10)
            barre_str = "#" * barres + "-" * (10 - barres)

            # Trouver le numero du partant
            num_ch = ""
            cote   = 0.0
            for p in partants_actifs:
                if p.get("nom", "").upper() == nom:
                    num_ch = str(p.get("numPmu") or p.get("numero") or "")
                    cote   = extraire_cote(p)
                    break

            nom_aff = f"N{num_ch}. {nom}" if num_ch else nom

            # Sources premium qui citent ce cheval
            src_p = [s for s in sources_ch.get(nom, []) if s in src_premium]
            star  = " CONSENSUS" if len(src_p) >= 3 else ""

            cote_str = f"(cote {cote:.1f})" if cote > 0 else ""
            lignes.append(f"[{barre_str}] {pct:3d}% ({nb_cit}/{nb_sources}) {nom_aff} {cote_str}{star}")

            if src_p:
                lignes.append(f"   Sources premium : {', '.join(src_p)}")

        lignes.append("")

        # Resume tendance
        if resume and "Aucun" not in resume:
            lignes.append(f"Tendance : {resume[:150]}")

        # Cheval surprise
        if surprise:
            # Trouver sa cote
            cote_surp = 0.0
            num_surp  = ""
            for p in partants_actifs:
                if p.get("nom", "").upper() == surprise:
                    cote_surp = extraire_cote(p)
                    num_surp  = str(p.get("numPmu") or "")
                    break
            surp_str = f"N{num_surp}. {surprise}" if num_surp else surprise
            cote_str = f"(cote {cote_surp:.1f})" if cote_surp > 0 else ""
            lignes.append(f"Surprise possible : {surp_str} {cote_str}")

    lignes.append("")

    # Afficher tous les partants avec cotes pour reference
    lignes.append("--- Partants ---")
    type_str = "TROT" if trot else "GALOP"
    lignes.append(f"[{type_str}] {len(partants_actifs)} partants")
    for p in sorted(partants_actifs, key=lambda x: x.get("numPmu") or x.get("numero") or 0):
        num   = p.get("numPmu") or p.get("numero") or "?"
        nom   = p.get("nom", "?")
        cote  = extraire_cote(p)
        corde = p.get("placeCorde", "")
        corde_str = f" C{corde}" if corde and trot else ""
        cote_str  = f"{cote:.1f}" if cote > 0 else "n/a"
        lignes.append(f"  N{num}. {nom:<22} {cote_str:>6}{corde_str}")

    lignes.append("=" * 35)
    lignes.append("Outil statistique - Jouer responsable.")

    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  RECUPERATION DU PROGRAMME
# ──────────────────────────────────────────────
def get_courses_du_jour(date_str: str) -> list:
    """Retourne la liste des courses françaises du jour avec leurs heures."""
    data = requests.get(
        f"{BASE_URL}/programme/{date_str}",
        headers=HEADERS_PMU, timeout=20
    ).json() if True else None

    if not data:
        return []

    reunions = data.get("programme", {}).get("reunions", [])
    courses  = []

    for reunion in reunions:
        pays = reunion.get("pays", {})
        code_pays = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code_pays not in PAYS_AUTORISES:
            continue

        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        terrain    = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain, dict):
            terrain = terrain.get("libelle", "") or terrain.get("code", "")

        for course in reunion.get("courses", []):
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue

            nc    = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            heure = course.get("heureDepart", 0)
            if not heure:
                continue

            # Convertir timestamp en datetime
            try:
                heure_dt  = datetime.fromtimestamp(heure / 1000)
                heure_str = heure_dt.strftime("%Hh%M")
            except Exception:
                continue

            courses.append({
                "reunion":    f"R{nr}",
                "course":     f"C{nc}",
                "nr":         nr,
                "nc":         nc,
                "hippodrome": hippodrome,
                "terrain":    str(terrain).upper() if terrain else "",
                "libelle":    course.get("libelle", f"R{nr}C{nc}"),
                "discipline": discipline,
                "heure_ts":   heure,
                "heure_dt":   heure_dt,
                "heure_str":  heure_str,
                "notifie":    False,
            })

    # Trier par heure
    courses.sort(key=lambda x: x["heure_ts"])
    log.info(f"  {len(courses)} courses françaises trouvees.")
    return courses


# ──────────────────────────────────────────────
#  BOUCLE PRINCIPALE
# ──────────────────────────────────────────────
def main():
    today    = datetime.now()
    date_str = today.strftime("%d%m%Y")
    date_aff = today.strftime("%d/%m/%Y")

    log.info("=" * 60)
    log.info(f"  PMU NOTIFIER - {date_aff}")
    log.info(f"  Envoi pronostics H-{MINUTES_AVANT}min avant chaque course")
    log.info("=" * 60)

    if not ANTHROPIC_KEY:
        log.error("ANTHROPIC_API_KEY manquante - impossible de collecter les pronostics")
        telegram_send(f"PMU Notifier {date_aff} - ERREUR : cle Anthropic manquante")
        return

    # Charger le programme
    try:
        courses = get_courses_du_jour(date_str)
    except Exception as e:
        log.error(f"Erreur chargement programme: {e}")
        telegram_send(f"PMU Notifier - Erreur programme: {e}")
        return

    if not courses:
        telegram_send(f"PMU Notifier {date_aff} - Aucune course française trouvée")
        return

    telegram_send(
        f"PMU Notifier demarre - {date_aff}\n"
        f"{len(courses)} courses a couvrir\n"
        f"Pronostics envoyes H-{MINUTES_AVANT}min avant chaque course"
    )

    log.info(f"Surveillance de {len(courses)} courses...")
    courses_restantes = [c for c in courses if not c["notifie"]]

    while courses_restantes:
        maintenant = datetime.now()

        for course in courses_restantes:
            heure_course  = course["heure_dt"]
            heure_notif   = heure_course - timedelta(minutes=MINUTES_AVANT)
            heure_limite  = heure_course + timedelta(minutes=5)  # Ne plus envoyer apres le depart

            # Heure passée sans notification → passer
            if maintenant > heure_limite:
                course["notifie"] = True
                log.info(f"  {course['reunion']} {course['course']} — course passée, ignorée")
                continue

            # Pas encore l'heure d'envoyer
            if maintenant < heure_notif:
                mins_restantes = (heure_notif - maintenant).seconds // 60
                if mins_restantes % 10 == 0:  # Log toutes les 10 minutes
                    log.info(f"  {course['reunion']} {course['course']} ({course['heure_str']}) — dans {mins_restantes} min")
                continue

            # C'est l'heure d'envoyer !
            log.info(f"\n>>> NOTIFICATION {course['reunion']} {course['course']} — {course['heure_str']}")

            try:
                # Récuperer les partants
                partants = get_courses_du_jour  # On a deja les partants via API
                partants_course = []
                try:
                    data = requests.get(
                        f"{BASE_URL}/programme/{date_str}/R{course['nr']}/C{course['nc']}/participants",
                        headers=HEADERS_PMU, timeout=20
                    ).json()
                    if data and isinstance(data, dict):
                        partants_course = data.get("participants", [])
                except Exception:
                    pass

                if not partants_course:
                    log.warning(f"  Pas de partants disponibles")
                    course["notifie"] = True
                    continue

                # Collecter les pronostics
                log.info(f"  Collecte pronostics en cours...")
                pronostics = collecter_pronostics_course(
                    partants_course,
                    course["libelle"],
                    course["hippodrome"],
                    course["discipline"],
                    date_aff,
                    course["heure_str"],
                )

                # Formater et envoyer
                message = formater_message_h15(
                    course, partants_course, pronostics, date_aff
                )

                if telegram_send(message):
                    log.info(f"  Message envoye pour {course['reunion']} {course['course']}")
                else:
                    log.warning(f"  Echec envoi Telegram")

            except Exception as e:
                log.error(f"  Erreur notification {course['reunion']} {course['course']}: {e}")

            course["notifie"] = True

        # Mettre a jour la liste des courses restantes
        courses_restantes = [c for c in courses if not c["notifie"]]

        if courses_restantes:
            prochaine = min(courses_restantes, key=lambda x: x["heure_ts"])
            heure_notif_prochaine = prochaine["heure_dt"] - timedelta(minutes=MINUTES_AVANT)
            attente = max(0, (heure_notif_prochaine - datetime.now()).seconds)
            if attente > 120:
                log.info(f"  Prochaine notification : {prochaine['reunion']} {prochaine['course']} a {prochaine['heure_str']} — attente {attente//60} min")
                time.sleep(min(attente - 60, 300))  # Max 5 min de sleep
            else:
                time.sleep(DELAI_VERIFICATION)

    log.info("Toutes les courses du jour ont ete couvertes.")
    telegram_send(f"PMU Notifier {date_aff} - Toutes les courses couvertes. Bonne soiree !")


if __name__ == "__main__":
    main()
