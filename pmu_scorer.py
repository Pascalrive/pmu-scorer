"""
=============================================================
  PMU RACING SCORER v3 - Galop & Trot
=============================================================
  - Score proprietaire + trio ecurie
  - Mouvement de cote J-1 -> J
  - Signal presse via Claude API + web search
  - Envoi automatique des pronostics sur Telegram
=============================================================
"""

import csv
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
OUTPUT_DIR     = "resultats"

# Tous les codes de discipline acceptes
DISCIPLINES = {
    "PLAT", "HAIES", "STEEPLE",
    "TROT_ATTELE", "TROT_MONTE",
    "ATTELE", "MONTE", "GALOP",
}

# Poids du score final (total = 100)
W_FORME      = 30
W_DISTANCE   = 22
W_COTE       = 15
W_MOUVEMENT  = 13
W_JOCKEY     = 12
W_ECURIE     = 8

# Grandes ecuries francaises - bonus notoriete
GRANDES_ECURIES = {
    "WERTHEIMER ET FRERE":   85,
    "AGA KHAN":              82,
    "ROTHSCHILD":            80,
    "NIARCHOS":              78,
    "AL SHAQAB RACING":      80,
    "GODOLPHIN":             83,
    "COOLMORE":              82,
    "JUDDMONTE":             81,
    "HARAS DE BOUQUETOT":    72,
    "ECURIE ANTONIO CARO":   70,
    "GESTUT AMMERLAND":      68,
    "HARAS D'ETREHAM":       70,
    "HARAS DE LA GOURDAINE": 68,
    "SAINT CLOUD RACING":    65,
    "FRANCOIS ROHAUT":       70,
}

# ──────────────────────────────────────────────
#  LOGGING
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pmu_scorer.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("pmu")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ──────────────────────────────────────────────
#  1. TELEGRAM (texte brut, sans HTML)
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram non configure - message ignore.")
        return False

    url    = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    limite = 4096
    morceaux = [texte[i:i+limite] for i in range(0, len(texte), limite)]

    succes = True
    for morceau in morceaux:
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT,
                    "text":    morceau,
                },
                timeout=15,
            )
            if r.status_code != 200:
                log.warning(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Erreur Telegram: {e}")
            succes = False
    return succes


def formater_message_telegram(tous_resultats: list, date_aff: str, run_label: str) -> str:
    """
    Formate le recap des pronostics en texte brut pour Telegram.
    Format : R2 C4 pour identifier les courses.
    """
    lignes = [
        f"PMU - Pronostics du {date_aff}",
        run_label,
        "=" * 30,
    ]

    vus = set()
    courses_traitees = []
    for r in sorted(tous_resultats, key=lambda x: x["score_total"], reverse=True):
        cle = (r["reunion"], r["course"])
        if cle not in vus:
            vus.add(cle)
            courses_traitees.append(r)

    courses_traitees.sort(key=lambda x: (x["reunion"], x["course"]))

    for r in courses_traitees:
        disc  = r.get("discipline", "").replace("_", " ")
        heure = r.get("heure", "")
        cote  = r.get("cote_jour", 0)
        score = r.get("score_total", 0)
        nom   = r.get("nom_cheval", "?")
        jock  = r.get("jockey", "?")
        prop  = r.get("proprietaire", "")

        # Mouvement de cote
        mvt = ""
        val = r.get("variation_cote_%", "")
        if val != "" and isinstance(val, (int, float)):
            if val <= -25:
                mvt = f" [CHUTE COTE {val:+.0f}%!!!]"
            elif val <= -10:
                mvt = f" [cote -{abs(val):.0f}%]"
            elif val >= 15:
                mvt = f" [cote +{val:.0f}%]"

        # Ligne course
        lignes.append("")
        lignes.append(f"{r['reunion']} {r['course']} - {disc} - {heure}")
        lignes.append(f"** {nom} **")
        lignes.append(f"   Cote: {cote:.1f}{mvt}")
        lignes.append(f"   Score: {score:.1f}/100")
        lignes.append(f"   Jockey: {jock}")
        if prop:
            lignes.append(f"   Proprio: {prop[:35]}")

        # Signal presse
        resume  = r.get("presse_resume", "")
        signaux = r.get("presse_signaux", "")
        sentiment = r.get("presse_sentiment", 50)
        if resume and "Aucune" not in resume and len(resume) > 5:
            if sentiment >= 65:
                indicateur = "[+]"
            elif sentiment <= 35:
                indicateur = "[-]"
            else:
                indicateur = "[=]"
            lignes.append(f"   Presse {indicateur}: {resume[:120]}")
        if signaux:
            lignes.append(f"   Signaux: {signaux[:80]}")

    lignes.append("")
    lignes.append("=" * 30)
    lignes.append("Outil d'aide statistique. Jouer responsable.")

    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. APPELS API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/3.0)",
    "Accept": "application/json",
}


def api_get(path: str):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url, headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Erreur reseau {path}: {e}")
        return None


def get_programme(date_str: str):
    return api_get(f"/programme/{date_str}")


def get_participants(date_str: str, nr, nc) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants")
    if data and isinstance(data, dict):
        participants = data.get("participants", [])
        if participants:
            return participants
    data2 = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants?combinePlacesEtCouplees=true")
    if data2 and isinstance(data2, dict):
        return data2.get("participants", [])
    return []


def get_performances(date_str: str, nr, nc, num_partant) -> list:
    data = api_get(
        f"/programme/{date_str}/R{nr}/C{nc}"
        f"/performances-detaillees/PARTANT/{num_partant}"
    )
    if not data:
        return []
    return data if isinstance(data, list) else data.get("performances", [])


def get_cote_veille(date_str_veille: str, nom_cheval: str, nr, nc):
    partants = get_participants(date_str_veille, nr, nc)
    for p in partants:
        if p.get("nom", "").upper() == nom_cheval.upper():
            if p.get("dernierRapportDirect"):
                val = p["dernierRapportDirect"].get("rapport")
                return float(val) if val else None
            elif p.get("cotesPmu"):
                val = p["cotesPmu"].get("rapport")
                return float(val) if val else None
    return None


# ──────────────────────────────────────────────
#  3. SCORES STATISTIQUES
# ──────────────────────────────────────────────
def score_forme(performances: list, n: int = 5) -> float:
    if not performances:
        return 0.0
    scores = []
    for p in performances[:n]:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 0.0


def score_distance(performances: list, distance_course: int) -> float:
    if not performances or not distance_course:
        return 50.0
    pertinentes = [
        p for p in performances
        if abs((p.get("distance") or 0) - distance_course) <= 200
    ]
    if not pertinentes:
        return 50.0
    victoires = sum(
        1 for p in pertinentes
        if str(p.get("place") or p.get("ordreArrivee") or 99) == "1"
    )
    return (victoires / len(pertinentes)) * 100


def score_cote_statique(cote: float, cotes_course: list) -> float:
    if not cotes_course or not cote:
        return 50.0
    mediane = sorted(cotes_course)[len(cotes_course) // 2]
    rapport = mediane / cote if cote > 0 else 0
    return min(100, max(0, rapport * 50))


def score_mouvement_cote(cote_veille, cote_jour: float) -> float:
    if not cote_veille or cote_veille <= 0 or cote_jour <= 0:
        return 50.0
    variation = (cote_veille - cote_jour) / cote_veille
    if variation >= 0.40:
        return 95.0
    elif variation >= 0.25:
        return 80.0
    elif variation >= 0.10:
        return 65.0
    elif variation >= -0.05:
        return 50.0
    elif variation >= -0.15:
        return 35.0
    else:
        return 20.0


def score_jockey(jockey_nom: str, tous_partants: list) -> float:
    if not jockey_nom:
        return 50.0
    v = c = 0
    for p in tous_partants:
        nom_j = p.get("driver") or p.get("nomJockey") or ""
        if nom_j.lower() == jockey_nom.lower():
            v += p.get("nombreVictoires") or 0
            c += p.get("nombreCourses") or 0
    return (v / c * 100) if c else 50.0


def score_ecurie(proprietaire: str, entraineur: str, jockey: str, tous_partants: list) -> float:
    v_prop = c_prop = 0
    for p in tous_partants:
        prop_p = str(p.get("proprietaire") or "").upper()
        if prop_p and prop_p == proprietaire.upper():
            v_prop += p.get("nombreVictoires") or 0
            c_prop += p.get("nombreCourses") or 0

    if c_prop >= 5:
        score_prop = (v_prop / c_prop) * 100
    else:
        score_prop = 55.0
        for key, bonus in GRANDES_ECURIES.items():
            if key in proprietaire.upper():
                score_prop = float(bonus)
                break

    tv = tc = 0
    for p in tous_partants:
        prop_p   = str(p.get("proprietaire") or "").upper()
        entr_p   = p.get("entraineur") or {}
        entr_nom = entr_p.get("nom", "") if isinstance(entr_p, dict) else str(entr_p)
        jock_p   = str(p.get("driver") or p.get("nomJockey") or "").lower()
        if (prop_p == proprietaire.upper()
                and entr_nom.lower() == entraineur.lower()
                and jock_p == jockey.lower()):
            tv += p.get("nombreVictoires") or 0
            tc += p.get("nombreCourses") or 0

    bonus_trio = (tv / tc * 20) if tc >= 3 else 0.0
    return min(100, score_prop + bonus_trio)


def calculer_score_total(s_forme, s_distance, s_cote, s_mouvement, s_jockey, s_ecurie) -> float:
    return (
        s_forme      * W_FORME      / 100
        + s_distance * W_DISTANCE   / 100
        + s_cote     * W_COTE       / 100
        + s_mouvement* W_MOUVEMENT  / 100
        + s_jockey   * W_JOCKEY     / 100
        + s_ecurie   * W_ECURIE     / 100
    )


# ──────────────────────────────────────────────
#  4. SIGNAL PRESSE - CLAUDE API + WEB SEARCH
# ──────────────────────────────────────────────
def get_signal_presse(nom_cheval: str, date_affichage: str) -> dict:
    if not ANTHROPIC_KEY:
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": []}

    prompt = f"""Tu es un expert en courses hippiques francaises.
Recherche sur le web les informations du {date_affichage} sur le cheval "{nom_cheval}"
pour les courses PMU de ce jour (Paris-Turf, Equidia, At Racing, Turf Magazine).

Reponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "resume": "2-3 phrases factuelles",
  "sentiment": 70,
  "sources": ["Paris-Turf"],
  "signaux": ["entraineur confiant"]
}}

sentiment : 0-30 mauvais, 50 neutre, 70-100 tres positif.
Si rien trouve : {{"resume": "Aucune information presse trouvee", "sentiment": 50, "sources": [], "signaux": []}}"""

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
                "max_tokens": 400,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        if r.status_code != 200:
            return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": []}

        data  = r.json()
        texte = " ".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = json.loads(texte.replace("```json", "").replace("```", "").strip())
        return {
            "resume":    parsed.get("resume", ""),
            "sentiment": float(parsed.get("sentiment", 50)),
            "sources":   parsed.get("sources", []),
            "signaux":   parsed.get("signaux", []),
        }
    except Exception as e:
        log.warning(f"Erreur Claude API '{nom_cheval}': {e}")
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": []}


# ──────────────────────────────────────────────
#  5. ANALYSE D'UNE COURSE
# ──────────────────────────────────────────────
def analyser_course(
    date_str: str,
    date_veille: str,
    date_aff: str,
    nr,
    nc,
    info_course: dict,
    activer_presse: bool = True,
) -> list:

    discipline = info_course.get("discipline", "")
    distance   = info_course.get("distance", 0)
    libelle    = info_course.get("libelle", f"R{nr}C{nc}")
    heure      = info_course.get("heureDepart", "")

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants pour R{nr} C{nc}")
        return []

    log.info(f"  -> {len(partants)} partants trouves")

    cotes_course = []
    for p in partants:
        rapport = None
        if p.get("dernierRapportDirect"):
            rapport = p["dernierRapportDirect"].get("rapport")
        elif p.get("cotesPmu"):
            rapport = p["cotesPmu"].get("rapport")
        if rapport:
            try:
                cotes_course.append(float(rapport))
            except (ValueError, TypeError):
                pass

    resultats = []
    for partant in partants:
        if partant.get("statut") == "NON_PARTANT":
            continue

        num   = partant.get("numPmu") or partant.get("numero")
        nom   = partant.get("nom", f"Partant {num}")
        jockey = partant.get("driver") or partant.get("nomJockey") or ""

        entraineur = partant.get("entraineur") or ""
        if isinstance(entraineur, dict):
            entraineur = entraineur.get("nom", "")

        proprietaire = partant.get("proprietaire") or ""
        if isinstance(proprietaire, dict):
            proprietaire = proprietaire.get("nom", "")

        cote_jour = 0.0
        if partant.get("dernierRapportDirect"):
            try:
                cote_jour = float(partant["dernierRapportDirect"].get("rapport", 0) or 0)
            except (ValueError, TypeError):
                pass
        elif partant.get("cotesPmu"):
            try:
                cote_jour = float(partant["cotesPmu"].get("rapport", 0) or 0)
            except (ValueError, TypeError):
                pass

        perfs       = get_performances(date_str, nr, nc, num)
        time.sleep(0.3)
        cote_veille = get_cote_veille(date_veille, nom, nr, nc)
        time.sleep(0.3)

        s_forme  = score_forme(perfs)
        s_dist   = score_distance(perfs, distance)
        s_cote   = score_cote_statique(cote_jour, cotes_course)
        s_mvt    = score_mouvement_cote(cote_veille, cote_jour)
        s_jockey = score_jockey(str(jockey), partants)
        s_ecurie = score_ecurie(str(proprietaire), str(entraineur), str(jockey), partants)
        s_total  = calculer_score_total(s_forme, s_dist, s_cote, s_mvt, s_jockey, s_ecurie)

        presse = {"resume": "", "sentiment": 50.0, "sources": [], "signaux": []}
        if activer_presse and ANTHROPIC_KEY:
            presse  = get_signal_presse(nom, date_aff)
            delta   = (presse["sentiment"] - 50) * 0.10
            s_total = min(100, max(0, s_total + delta))
            time.sleep(1)

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion":          f"R{nr}",
            "course":           f"C{nc}",
            "heure":            heure,
            "libelle":          libelle,
            "discipline":       discipline,
            "distance_m":       distance,
            "num_partant":      num,
            "nom_cheval":       nom,
            "jockey":           jockey,
            "entraineur":       entraineur,
            "proprietaire":     proprietaire,
            "cote_veille":      round(cote_veille, 2) if cote_veille else "",
            "cote_jour":        round(cote_jour, 2),
            "variation_cote_%": var_cote,
            "score_forme":      round(s_forme, 1),
            "score_distance":   round(s_dist, 1),
            "score_cote":       round(s_cote, 1),
            "score_mouvement":  round(s_mvt, 1),
            "score_jockey":     round(s_jockey, 1),
            "score_ecurie":     round(s_ecurie, 1),
            "score_total":      round(s_total, 1),
            "presse_resume":    presse.get("resume", ""),
            "presse_sentiment": round(presse.get("sentiment", 50), 1),
            "presse_sources":   ", ".join(presse.get("sources", [])),
            "presse_signaux":   ", ".join(presse.get("signaux", [])),
        })
        time.sleep(0.5)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)

    log.info(f"\n{'─'*70}")
    log.info(f"  {libelle} - {discipline} - {distance}m - {heure}")
    log.info(f"{'─'*70}")
    for i, r in enumerate(resultats[:5], 1):
        mvt  = f"{r['variation_cote_%']:+.0f}%" if r["variation_cote_%"] != "" else "n/a"
        flag = " *" if i == 1 else ""
        log.info(
            f"  {i}. {r['nom_cheval']:<22} {str(r['proprietaire'])[:18]:<18} "
            f"Cote:{r['cote_jour']:>5.1f} Mvt:{mvt:>5} Score:{r['score_total']:>5.1f}{flag}"
        )

    return resultats


# ──────────────────────────────────────────────
#  6. PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today       = datetime.now()
    yesterday   = today - timedelta(days=1)
    date_str    = today.strftime("%d%m%Y")
    date_veille = yesterday.strftime("%d%m%Y")
    date_aff    = today.strftime("%d/%m/%Y")
    heure_run   = today.strftime("%Hh%M")

    run_label = (
        "Analyse du matin (cotes d'ouverture)"
        if today.hour < 10
        else "Analyse de mi-journee (cotes fraiches + presse)"
    )

    activer_presse = bool(ANTHROPIC_KEY)

    log.info("=" * 70)
    log.info(f"  PMU SCORER v3 - {date_aff} - {heure_run}")
    log.info(f"  Presse  : {'OK active' if activer_presse else 'desactive (ANTHROPIC_API_KEY manquante)'}")
    log.info(f"  Telegram: {'OK configure' if TELEGRAM_TOKEN else 'desactive (TELEGRAM_TOKEN manquant)'}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer demarre - {date_aff} {heure_run}\n{run_label}...")

    programme = get_programme(date_str)
    if not programme:
        msg = f"ERREUR PMU Scorer - impossible de recuperer le programme du {date_aff}"
        log.error(msg)
        telegram_send(msg)
        return

    reunions = programme.get("programme", {}).get("reunions", [])
    if not reunions:
        msg = f"ERREUR PMU Scorer - aucune reunion trouvee pour le {date_aff}"
        log.error(msg)
        telegram_send(msg)
        return

    log.info(f"{len(reunions)} reunions trouvees.")
    tous_resultats = []

    for reunion in reunions:
        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        courses    = reunion.get("courses", [])
        log.info(f"\n> R{nr} - {hippodrome} ({len(courses)} courses)")

        for course in courses:
            nc         = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            discipline = course.get("discipline", "")

            if discipline not in DISCIPLINES:
                log.info(f"  Ignore R{nr} C{nc} - discipline: {discipline}")
                continue

            try:
                res = analyser_course(
                    date_str, date_veille, date_aff,
                    nr, nc, course,
                    activer_presse=activer_presse,
                )
                tous_resultats.extend(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    if tous_resultats:
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion", "course", "heure", "libelle", "discipline", "distance_m",
            "num_partant", "nom_cheval", "jockey", "entraineur", "proprietaire",
            "cote_veille", "cote_jour", "variation_cote_%",
            "score_forme", "score_distance", "score_cote", "score_mouvement",
            "score_jockey", "score_ecurie", "score_total",
            "presse_resume", "presse_sentiment", "presse_sources", "presse_signaux",
        ]
        with open(nom_fichier, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=colonnes)
            writer.writeheader()
            writer.writerows(tous_resultats)
        log.info(f"\nCSV exporte : {nom_fichier}")

        message = formater_message_telegram(tous_resultats, date_aff, run_label)
        if telegram_send(message):
            log.info("Message Telegram envoye.")
        else:
            log.warning("Envoi Telegram echoue.")
    else:
        log.warning("Aucun resultat.")
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat trouve.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v3 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
