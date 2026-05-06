"""
=============================================================
  PMU NOTIFIER v2 - Pronostics H-15min avant chaque course
=============================================================
  Nouveautes v2 :
    - URLs directes pour chaque source (Claude cherche mieux)
    - Format : TOP 2 + classement de tous les partants
    - Barre de progression visuelle
    - R/K affiche pour le trot
=============================================================
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import requests

BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

PAYS_AUTORISES     = {"FRA", "FRANCE"}
MINUTES_AVANT      = 15
DELAI_VERIFICATION = 60

DISCIPLINES_GALOP = {"PLAT", "HAIES", "STEEPLE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

SOURCES_POIDS_GALOP = {
    "Turf BZH": 4.0, "Paris-Turf": 3.5, "Frequence Turf": 3.2,
    "Equidia": 3.0, "Canalturf": 2.8, "Turfomania": 2.5,
    "Zone-Turf": 2.5, "Turfoo": 2.5, "Geny": 2.0,
    "Turf-fr": 1.8, "PMU officiel": 2.5,
}
SOURCES_POIDS_TROT = {
    "Le Trot": 4.0, "Equidia": 3.5, "Paris-Turf": 3.2,
    "Canalturf": 3.0, "Turfomania": 2.8, "Zone-Turf": 2.5,
    "Turfoo": 2.5, "Frequence Turf": 2.5, "Geny": 2.0,
    "Turf-fr": 1.8, "PMU officiel": 2.5,
}
SOURCES_PREMIUM = {"Turf BZH", "Paris-Turf", "Equidia", "Frequence Turf", "Le Trot", "Canalturf"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("notifier")

HEADERS_PMU = {"User-Agent": "Mozilla/5.0 (compatible; PMU-Notifier/2.0)", "Accept": "application/json"}


def est_trot(discipline: str) -> bool:
    return discipline.upper() in DISCIPLINES_TROT


def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    morceaux = [texte[i:i+4096] for i in range(0, len(texte), 4096)]
    for morceau in morceaux:
        try:
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": morceau}, timeout=15)
            if r.status_code != 200:
                log.warning(f"Telegram {r.status_code}")
                return False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Telegram: {e}")
            return False
    return True


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
            except (ValueError, TypeError):
                pass
    return 0.0


def collecter_pronostics(partants, libelle, hippodrome, discipline, date_aff, heure_str) -> dict:
    """Collecte les pronostics avec URLs directes pour chaque source."""
    if not ANTHROPIC_KEY:
        return {}

    trot     = est_trot(discipline)
    sources  = SOURCES_POIDS_TROT if trot else SOURCES_POIDS_GALOP
    type_str = "trot" if trot else "galop"

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    partants_str = "\n".join([
        f"  N{p.get('numPmu','?')}. {p.get('nom','?')} (cote {extraire_cote(p):.1f})"
        for p in sorted(partants_actifs, key=lambda x: x.get("numPmu") or 0)
    ])

    # URLs directes selon le type de course
    if trot:
        urls_str = f"""
1. https://www.equidia.fr/pronostics — cherche "{libelle}" ou "{hippodrome}"
2. https://www.canalturf.com/ — cherche "{libelle}"
3. https://www.turfomania.fr/ — cherche "{hippodrome}" {date_aff}
4. https://www.turfoo.fr/programmes-courses/ — date {date_aff}
5. https://www.zone-turf.fr/ — cherche "{libelle}"
6. https://www.turf-fr.com/ — cherche "{libelle}" {date_aff}
7. https://www.geny.com/ — cherche "{hippodrome}" {date_aff}"""
    else:
        urls_str = f"""
1. https://www.turf.bzh/ — cherche "{hippodrome}" {date_aff}
2. https://www.canalturf.com/ — cherche "{libelle}"
3. https://www.equidia.fr/pronostics — cherche "{libelle}" ou "{hippodrome}"
4. https://www.turfomania.fr/ — cherche "{hippodrome}" {date_aff}
5. https://www.turfoo.fr/programmes-courses/ — date {date_aff}
6. https://www.zone-turf.fr/ — cherche "{libelle}"
7. https://www.turf-fr.com/ — cherche "{libelle}" {date_aff}
8. https://www.geny.com/ — cherche "{libelle}" {date_aff}"""

    prompt = f"""Expert PMU {type_str}. Trouve les pronostics pour cette course SPECIFIQUE :

Course : "{libelle}"
Hippodrome : {hippodrome}
Date/Heure : {date_aff} a {heure_str}
Type : {type_str.upper()}

Partants :
{partants_str}

Visite CHACUNE de ces URLs et note les chevaux cites dans le TOP 3 :
{urls_str}

CRUCIAL : cherche EXACTEMENT la course "{libelle}" a {hippodrome}.
Ne confonds pas avec une autre course du meme jour.

JSON uniquement :
{{
  "nb_sources_trouvees": 8,
  "citations_top3": {{"NOM_CHEVAL": 6, "AUTRE_CHEVAL": 4}},
  "sources_par_cheval": {{
    "NOM_CHEVAL": ["Turf BZH", "Paris-Turf", "Equidia", "Canalturf"],
    "AUTRE_CHEVAL": ["Equidia", "Zone-Turf"]
  }},
  "sources_consultees": ["Turf BZH", "Paris-Turf", "Equidia"],
  "resume_tendance": "Description courte des tendances",
  "cheval_surprise": "NOM_OUTSIDER_REVENANT",
  "consensus": true
}}

consensus = true si 3+ sources premium citent le meme cheval.
Si aucune source : {{"nb_sources_trouvees": 0, "citations_top3": {{}}, "sources_par_cheval": {{}}, "sources_consultees": [], "resume_tendance": "Aucun pronostic disponible", "consensus": false}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 1000,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        if r.status_code != 200:
            log.warning(f"Claude {r.status_code}")
            return {}

        data  = r.json()
        texte = " ".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text").strip()
        parsed = json.loads(texte.replace("```json","").replace("```","").strip())

        citations_pond = {}
        for nom, srcs in parsed.get("sources_par_cheval", {}).items():
            nom_up = nom.upper().strip()
            citations_pond[nom_up] = round(sum(sources.get(s, 1.0) for s in srcs), 2)

        return {
            "nb_sources":    int(parsed.get("nb_sources_trouvees", 0)),
            "citations":     {k.upper(): int(v) for k, v in parsed.get("citations_top3", {}).items()},
            "citations_pond": citations_pond,
            "sources_par_ch": {k.upper(): v for k, v in parsed.get("sources_par_cheval", {}).items()},
            "sources_vues":  parsed.get("sources_consultees", []),
            "resume":        parsed.get("resume_tendance", ""),
            "surprise":      parsed.get("cheval_surprise", "").upper(),
            "consensus":     bool(parsed.get("consensus", False)),
        }
    except Exception as e:
        log.warning(f"Erreur collecte pronostics: {e}")
        return {}


def formater_message_h15(course_info, partants, pronostics, date_aff) -> str:
    """
    Format :
    - TOP 2 avec scores et pronostics
    - Classement de TOUS les partants avec cotes
    """
    disc       = course_info.get("discipline", "").replace("_", " ")
    libelle    = course_info.get("libelle", "")
    reunion    = course_info.get("reunion", "")
    nc         = course_info.get("course", "")
    hippo      = course_info.get("hippodrome", "")
    heure_str  = course_info.get("heure_str", "")
    trot       = est_trot(course_info.get("discipline", ""))

    nb_sources = pronostics.get("nb_sources", 0)
    citations  = pronostics.get("citations", {})
    cit_pond   = pronostics.get("citations_pond", {})
    sources_ch = pronostics.get("sources_par_ch", {})
    resume     = pronostics.get("resume", "")
    surprise   = pronostics.get("surprise", "")
    consensus  = pronostics.get("consensus", False)

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]

    # Enrichir les partants avec les pronostics
    for p in partants_actifs:
        nom_up = p.get("nom", "").upper().strip()
        p["_nb_cit"]  = citations.get(nom_up, 0)
        p["_pond"]    = cit_pond.get(nom_up, 0)
        p["_pct"]     = round((citations.get(nom_up, 0) / nb_sources * 100) if nb_sources > 0 else 0)
        p["_src_p"]   = [s for s in sources_ch.get(nom_up, []) if s in SOURCES_PREMIUM]
        p["_cote"]    = extraire_cote(p)

    # Trier par citations ponderees (si disponibles) sinon par cote
    if nb_sources > 0:
        partants_tries = sorted(partants_actifs, key=lambda x: x["_pond"], reverse=True)
    else:
        partants_tries = sorted(partants_actifs, key=lambda x: x["_cote"] if x["_cote"] > 0 else 999)

    lignes = []
    alert  = " *** CONSENSUS FORT ***" if consensus else ""

    lignes.append(f"DANS 15 MIN  {reunion} {nc} | {heure_str} | {disc}")
    lignes.append(f"{libelle[:50]}")
    lignes.append(f"{hippo}{alert}")
    lignes.append("=" * 35)

    if nb_sources == 0:
        lignes.append("Pronostics non encore disponibles")
        lignes.append("Classement par cote PMU :")
    else:
        lignes.append(f"SYNTHESE {nb_sources} SOURCES :")
        if resume and "Aucun" not in resume:
            lignes.append(f">> {resume[:120]}")

    lignes.append("")

    # TOP 2 detaille
    lignes.append("--- NOS 2 CHOIX ---")
    for rang, p in enumerate(partants_tries[:2], 1):
        num   = p.get("numPmu") or p.get("numero") or "?"
        nom   = p.get("nom", "?")
        cote  = p["_cote"]
        nb_c  = p["_nb_cit"]
        pct   = p["_pct"]
        src_p = p["_src_p"]
        corde = p.get("placeCorde", 0)
        poids = p.get("handicapPoids", 0)

        prefixe = ">>" if rang == 1 else "  "
        lignes.append(f"{prefixe} N{num}. {nom} (cote {cote:.1f})")

        if nb_sources > 0:
            # Barre de progression
            barres    = round(pct / 10)
            barre_str = "#" * barres + "-" * (10 - barres)
            lignes.append(f"   [{barre_str}] {pct}% — {nb_c}/{nb_sources} sources")
            if src_p:
                lignes.append(f"   Premium: {', '.join(src_p)}")

        if trot and corde:
            av = " AVANTAGE DECISIF" if corde <= 3 else ""
            lignes.append(f"   Corde {corde}/{len(partants_actifs)}{av}")
        elif poids and not trot:
            lignes.append(f"   Poids: {poids/10:.1f}kg")

    # Surprise
    if surprise and surprise not in [p.get("nom","").upper() for p in partants_tries[:2]]:
        for p in partants_actifs:
            if p.get("nom", "").upper() == surprise:
                lignes.append(f"\n!! Surprise possible: N{p.get('numPmu','?')}. {p.get('nom','?')} (cote {p['_cote']:.1f})")
                break

    # Classement de TOUS les partants
    lignes.append("")
    type_str = "TROT" if trot else "GALOP"
    lignes.append(f"--- CLASSEMENT {type_str} ({len(partants_actifs)} partants) ---")

    for p in partants_tries:
        num   = p.get("numPmu") or p.get("numero") or "?"
        nom   = p.get("nom", "?")
        cote  = p["_cote"]
        pct   = p["_pct"]
        corde = p.get("placeCorde", 0)

        cote_str  = f"{cote:.1f}" if cote > 0 else " n/a"
        pct_str   = f"{pct:3d}%" if nb_sources > 0 else "    "
        corde_str = f" C{corde}" if corde and trot else ""

        # Marquer notre top 2
        flag = ">>" if p in partants_tries[:2] else "  "
        lignes.append(f"{flag} N{str(num):<3} {nom:<22} {cote_str:>6}{corde_str}  {pct_str}")

    lignes.append("=" * 35)
    lignes.append("Outil statistique - Jouer responsable.")
    return "\n".join(lignes)


def get_courses_du_jour(date_str) -> list:
    try:
        data = requests.get(
            f"{BASE_URL}/programme/{date_str}",
            headers=HEADERS_PMU, timeout=20
        ).json()
    except Exception as e:
        log.error(f"Programme: {e}")
        return []

    if not data:
        return []

    courses = []
    for reunion in data.get("programme", {}).get("reunions", []):
        pays = reunion.get("pays", {})
        code = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code not in PAYS_AUTORISES:
            continue

        nr    = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippo = reunion.get("hippodrome", {}).get("libelleLong", "?")

        for course in reunion.get("courses", []):
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue

            nc    = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            heure = course.get("heureDepart", 0)
            if not heure:
                continue

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
                "hippodrome": hippo,
                "libelle":    course.get("libelle", f"R{nr}C{nc}"),
                "discipline": discipline,
                "heure_ts":   heure,
                "heure_dt":   heure_dt,
                "heure_str":  heure_str,
                "notifie":    False,
            })

    courses.sort(key=lambda x: x["heure_ts"])
    log.info(f"  {len(courses)} courses françaises.")
    return courses


def main():
    today    = datetime.now()
    date_str = today.strftime("%d%m%Y")
    date_aff = today.strftime("%d/%m/%Y")

    log.info("=" * 60)
    log.info(f"  PMU NOTIFIER v2 - {date_aff}")
    log.info(f"  URLs directes | Top2 + Classement complet")
    log.info(f"  H-{MINUTES_AVANT}min avant chaque course")
    log.info("=" * 60)

    if not ANTHROPIC_KEY:
        log.error("ANTHROPIC_API_KEY manquante")
        telegram_send(f"PMU Notifier {date_aff} - ERREUR : cle Anthropic manquante")
        return

    courses = get_courses_du_jour(date_str)
    if not courses:
        telegram_send(f"PMU Notifier {date_aff} - Aucune course française")
        return

    telegram_send(
        f"PMU Notifier v2 demarre - {date_aff}\n"
        f"{len(courses)} courses a couvrir\n"
        f"Pronostics H-{MINUTES_AVANT}min | URLs directes activees"
    )

    courses_restantes = [c for c in courses if not c["notifie"]]

    while courses_restantes:
        maintenant = datetime.now()

        for course in courses_restantes:
            heure_course = course["heure_dt"]
            heure_notif  = heure_course - timedelta(minutes=MINUTES_AVANT)
            heure_limite = heure_course + timedelta(minutes=5)

            if maintenant > heure_limite:
                course["notifie"] = True
                continue

            if maintenant < heure_notif:
                continue

            log.info(f"\n>>> {course['reunion']} {course['course']} — {course['heure_str']}")

            try:
                # Recuperer les partants
                data = requests.get(
                    f"{BASE_URL}/programme/{date_str}/R{course['nr']}/C{course['nc']}/participants",
                    headers=HEADERS_PMU, timeout=20
                ).json()
                partants = data.get("participants", []) if data and isinstance(data, dict) else []

                if not partants:
                    log.warning("  Pas de partants")
                    course["notifie"] = True
                    continue

                log.info(f"  Collecte pronostics ({course['discipline']})...")
                pronostics = collecter_pronostics(
                    partants, course["libelle"], course["hippodrome"],
                    course["discipline"], date_aff, course["heure_str"],
                )

                message = formater_message_h15(course, partants, pronostics, date_aff)

                if telegram_send(message):
                    log.info(f"  Envoye !")
                else:
                    log.warning(f"  Echec envoi")

            except Exception as e:
                log.error(f"  Erreur: {e}")

            course["notifie"] = True

        courses_restantes = [c for c in courses if not c["notifie"]]

        if courses_restantes:
            prochaine        = min(courses_restantes, key=lambda x: x["heure_ts"])
            heure_notif_proch = prochaine["heure_dt"] - timedelta(minutes=MINUTES_AVANT)
            attente          = max(0, (heure_notif_proch - datetime.now()).seconds)
            if attente > 120:
                log.info(f"  Prochaine: {prochaine['reunion']} {prochaine['course']} a {prochaine['heure_str']} — {attente//60} min")
                time.sleep(min(attente - 60, 300))
            else:
                time.sleep(DELAI_VERIFICATION)

    telegram_send(f"PMU Notifier {date_aff} - Toutes les courses couvertes !")
    log.info("Termine.")


if __name__ == "__main__":
    main()
