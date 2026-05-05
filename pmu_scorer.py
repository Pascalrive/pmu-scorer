"""
=============================================================
  PMU RACING SCORER v10 - France uniquement
=============================================================
  Nouveautes v10 :
    TROT : Record kilométrique = 3ème critère (15 pts)
    GALOP/TROT : Filtre cote max 20.0 pour N1 sans pronostics
    GALOP/TROT : Bonus marché (cote basse = consensus)
    Sources ponderees par taux de reussite top3
    Score entraineur
    Galop et Trot separes
=============================================================
  Poids GALOP (100 pts) :
    Pronostics    25 | Forme recente  18 | Forme fraiche   7
    Terrain       10 | Mouvement cote 10 | Jockey         10
    Distance       9 | Entraineur      5 | Hippodrome      4
    Corde          2

  Poids TROT (100 pts) :
    Pronostics    25 | Forme recente  15 | R/K            15
    Corde         12 | Mouvement cote 10 | Jockey          7
    Distance       6 | Entraineur      5 | Hippodrome      5
    Forme fraiche  5
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

PAYS_AUTORISES    = {"FRA", "FRANCE"}
DISCIPLINES_GALOP = {"PLAT", "HAIES", "STEEPLE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

# Cote max pour etre N1 sans pronostics externes
COTE_MAX_N1_SANS_PRONOSTICS = 20.0
COTE_MAX_N1_AVEC_PRONOSTICS = 35.0

# Sources ponderees par taux reussite top3
SOURCES_POIDS_GALOP = {
    "Turf BZH":        4.0,
    "Paris-Turf":      3.5,
    "Frequence Turf":  3.2,
    "Equidia":         3.0,
    "Canalturf":       2.8,
    "Turfomania":      2.5,
    "Zone-Turf":       2.5,
    "Turfoo":          2.5,
    "Geny":            2.0,
    "GRM Turf":        2.0,
    "Turf-fr":         1.8,
    "PMU officiel":    2.5,
}

SOURCES_POIDS_TROT = {
    "Le Trot":         4.0,
    "Equidia":         3.5,
    "Paris-Turf":      3.2,
    "Canalturf":       3.0,
    "Turfomania":      2.8,
    "Zone-Turf":       2.5,
    "Turfoo":          2.5,
    "Frequence Turf":  2.5,
    "Geny":            2.0,
    "Turf-fr":         1.8,
    "PMU officiel":    2.5,
}

SOURCES_PREMIUM = {"Turf BZH", "Paris-Turf", "Equidia", "Frequence Turf", "Le Trot", "Canalturf"}

# Poids GALOP
W_GALOP = {
    "pronostics": 25, "forme_r": 18, "forme_f": 7,
    "terrain":    10, "mouvement": 10, "jockey":  10,
    "distance":    9, "entraineur": 5, "hippodrome": 4,
    "corde":       2, "rk":         0,
}

# Poids TROT — R/K = 3ème critère
W_TROT = {
    "pronostics": 25, "forme_r": 15, "rk":       15,
    "corde":      12, "mouvement": 10, "jockey":   7,
    "distance":    6, "entraineur": 5, "hippodrome": 5,
    "forme_f":     5, "terrain":    0,
}

assert sum(W_GALOP.values()) == 100, f"W_GALOP={sum(W_GALOP.values())}"
assert sum(W_TROT.values())  == 100, f"W_TROT={sum(W_TROT.values())}"

GRANDES_ECURIES = {
    "WERTHEIMER ET FRERE": 85, "AGA KHAN": 82, "AGA KHAN STUDS": 82,
    "ROTHSCHILD": 80, "NIARCHOS": 78, "AL SHAQAB RACING": 80,
    "WATHNAN RACING": 80, "GODOLPHIN": 83, "COOLMORE": 82,
    "JUDDMONTE": 81, "FLAXMAN STABLES": 79, "HARAS DE BOUQUETOT": 72,
    "HARAS D'ETREHAM": 70, "HARAS DE LA GOURDAINE": 68,
    "SAINT CLOUD RACING": 65, "FRANCOIS ROHAUT": 70,
    "HARAS DE CLAIREFONTAINE": 72, "G.AUGUSTIN-NORMAND": 75,
}

TERRAIN_COMPAT = {
    "BON":        {"BON": 100, "BON_SOUPLE": 80, "SOUPLE": 50, "LOURD": 20, "TRES_LOURD": 0},
    "BON_SOUPLE": {"BON": 80, "BON_SOUPLE": 100, "SOUPLE": 80, "LOURD": 40, "TRES_LOURD": 20},
    "SOUPLE":     {"BON": 50, "BON_SOUPLE": 80, "SOUPLE": 100, "LOURD": 80, "TRES_LOURD": 60},
    "LOURD":      {"BON": 20, "BON_SOUPLE": 40, "SOUPLE": 80, "LOURD": 100, "TRES_LOURD": 80},
    "TRES_LOURD": {"BON": 0, "BON_SOUPLE": 20, "SOUPLE": 60, "LOURD": 80, "TRES_LOURD": 100},
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


def est_trot(discipline: str) -> bool:
    return discipline.upper() in DISCIPLINES_TROT


# ──────────────────────────────────────────────
#  1. TELEGRAM
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
                url, json={"chat_id": TELEGRAM_CHAT, "text": morceau}, timeout=15,
            )
            if r.status_code != 200:
                log.warning(f"Telegram {r.status_code}: {r.text[:100]}")
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Telegram erreur: {e}")
            succes = False
    return succes


def formater_message_telegram(courses_galop, courses_trot, date_aff, run_label) -> str:

    def formater_course(course: dict) -> list:
        lignes = []
        if not course.get("top2"):
            return lignes
        disc     = course.get("discipline", "").replace("_", " ")
        heure_ts = course.get("heure", 0)
        libelle  = course.get("libelle", "")
        reunion  = course.get("reunion", "")
        nc       = course.get("course", "")
        terrain  = course.get("terrain", "")
        nb_src   = course.get("nb_sources_total", 0)
        consensus = course.get("consensus_fort", False)

        heure_str = ""
        if heure_ts and isinstance(heure_ts, (int, float)) and heure_ts > 0:
            try:
                heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
            except Exception:
                pass

        terrain_str  = f" | {terrain}" if terrain else ""
        alert_str    = " *** CONSENSUS FORT ***" if consensus else ""

        lignes.append("")
        lignes.append(f"{reunion} {nc} | {heure_str} | {disc}{terrain_str}{alert_str}")
        if libelle:
            lignes.append(f"{libelle[:50]}")
        lignes.append("-" * 35)

        for rang, cheval in enumerate(course["top2"], 1):
            nom       = cheval.get("nom_cheval", "?")
            num_ch    = cheval.get("num_partant", "")
            cote      = cheval.get("cote_jour", 0)
            score     = cheval.get("score_total", 0)
            prob      = cheval.get("probabilite", 0)
            nb_prono  = cheval.get("nb_pronostics", 0)
            pct_prono = cheval.get("pct_pronostics", 0)
            corde     = cheval.get("place_corde", 0)
            nb_part   = cheval.get("nb_partants", 0)
            poids     = cheval.get("poids_porte", 0)
            jockey    = cheval.get("jockey", "?")
            entraineur = cheval.get("entraineur", "")
            deferre   = cheval.get("deferre", False)
            value     = cheval.get("value_bet", False)
            rk_best   = cheval.get("rk_meilleur", 0)
            src_p     = cheval.get("sources_premium_citees", [])
            trot      = est_trot(cheval.get("discipline", ""))

            mvt = ""
            val = cheval.get("variation_cote_%", "")
            if val != "" and isinstance(val, (int, float)):
                if val <= -25:
                    mvt = f" [CHUTE {val:+.0f}%!!!]"
                elif val <= -10:
                    mvt = f" [cote {val:+.0f}%]"
                elif val >= 15:
                    mvt = f" [+{val:.0f}%]"

            value_str = " *** VALUE BET ***" if value else ""
            nom_aff   = f"N{num_ch}. {nom}" if num_ch else nom
            prefixe   = ">> " if rang == 1 else "   "

            lignes.append(f"{prefixe}{rang}. {nom_aff} (cote {cote:.1f}){mvt}{value_str}")
            lignes.append(f"   Score: {score:.1f}% | Proba: {prob:.1f}%")

            if nb_src > 0:
                lignes.append(f"   {nb_prono} source(s)/{nb_src} donnent ce cheval gagnant ({pct_prono:.0f}%)")
            else:
                lignes.append(f"   Pronostics: collecte en cours")

            if src_p:
                lignes.append(f"   Sources premium: {', '.join(src_p)}")

            # Corde — mise en avant pour le trot
            if corde and nb_part:
                av = " AVANTAGE DECISIF" if (trot and corde <= 3) else (" AVANTAGE" if corde <= 3 else "")
                lignes.append(f"   Corde {corde}/{nb_part}{av}")

            # R/K pour le trot
            if trot and rk_best > 0:
                mn  = int(rk_best) // 60
                sec = rk_best % 60
                lignes.append(f"   Meilleur R/K: {mn}'{sec:05.2f}")

            if poids and not trot:
                lignes.append(f"   Poids: {poids/10:.1f}kg")

            lignes.append(f"   Jockey: {jockey}")
            if entraineur:
                lignes.append(f"   Entraineur: {entraineur[:30]}")

            if deferre:
                lignes.append(f"   *** DEFERRE aujourd'hui ***")

            resume    = cheval.get("presse_resume", "")
            signaux   = cheval.get("presse_signaux", "")
            sentiment = cheval.get("presse_sentiment", 50)
            if resume and "Aucune" not in resume and len(resume) > 5:
                ind = "[+]" if sentiment >= 65 else ("[-]" if sentiment <= 35 else "[=]")
                lignes.append(f"   Presse {ind}: {resume[:100]}")
            if signaux:
                lignes.append(f"   Signaux: {signaux[:80]}")

        return lignes

    lignes = [
        f"PMU France - Pronostics du {date_aff}",
        run_label,
        "=" * 38,
    ]

    if courses_galop:
        lignes.append("")
        lignes.append("=" * 38)
        lignes.append("  GALOP (Plat / Haies / Steeple)")
        lignes.append("=" * 38)
        for c in courses_galop:
            lignes.extend(formater_course(c))

    if courses_trot:
        lignes.append("")
        lignes.append("=" * 38)
        lignes.append("  TROT (Attele / Monte)")
        lignes.append("=" * 38)
        for c in courses_trot:
            lignes.extend(formater_course(c))

    lignes.append("")
    lignes.append("=" * 38)
    lignes.append("Outil statistique - Jouer responsable.")
    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/10.0)",
    "Accept": "application/json",
}


def api_get(path):
    try:
        r = requests.get(f"{BASE_URL}{path}", headers=HEADERS_PMU, timeout=20)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"API {path}: {e}")
        return None


def get_programme(date_str):
    return api_get(f"/programme/{date_str}")


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


def get_pronostics_pmu(date_str, nr, nc) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/pronostics")
    if not data:
        return []
    try:
        if isinstance(data, list):
            return [str(p.get("numPmu") or p.get("numero") or "") for p in data if p]
        elif isinstance(data, dict):
            pl = data.get("pronostics", []) or data.get("partants", [])
            return [str(p.get("numPmu") or p.get("numero") or "") for p in pl if p]
    except Exception:
        pass
    return []


def get_performances(date_str, nr, nc, num_partant) -> list:
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/performances-detaillees/PARTANT/{num_partant}")
    if not data:
        return []
    return data if isinstance(data, list) else data.get("performances", [])


def get_cote_veille(date_str_veille, nom_cheval, nr, nc):
    for p in get_participants(date_str_veille, nr, nc):
        if p.get("nom", "").upper() == nom_cheval.upper():
            for champ in ["dernierRapportDirect", "dernierRapportReference", "cotesPmu"]:
                if p.get(champ):
                    val = p[champ].get("rapport")
                    if val:
                        return float(val)
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


# ──────────────────────────────────────────────
#  3. PRONOSTICS EXTERNES VIA CLAUDE
# ──────────────────────────────────────────────
def get_pronostics_externes(noms_chevaux, libelle, date_aff, hippodrome, discipline) -> dict:
    if not ANTHROPIC_KEY or not noms_chevaux:
        return {"citations": {}, "citations_pond": {}, "nb_sources": 0, "sources_par_ch": {}}

    trot      = est_trot(discipline)
    sources   = SOURCES_POIDS_TROT if trot else SOURCES_POIDS_GALOP
    type_str  = "trot" if trot else "galop"
    noms_str  = ", ".join(noms_chevaux[:16])

    # URLs directes selon le type de course
    if trot:
        urls = f"""
- https://www.equidia.fr/pronostics (cherche "{hippodrome}")
- https://www.canalturf.com/ (cherche "{libelle}")
- https://www.turfomania.fr/ (cherche "{hippodrome}")
- https://www.turfoo.fr/programmes-courses/ (date {date_aff})
- https://www.zone-turf.fr/ (cherche "{libelle}")
- https://www.turf-fr.com/ (cherche "{libelle}")
- https://www.geny.com/ (cherche "{hippodrome}")"""
    else:
        urls = f"""
- https://www.turf.bzh/ (cherche "{hippodrome}" {date_aff})
- https://www.canalturf.com/ (cherche "{libelle}")
- https://www.turfomania.fr/ (cherche "{hippodrome}")
- https://www.turfoo.fr/programmes-courses/ (date {date_aff})
- https://www.zone-turf.fr/ (cherche "{libelle}")
- https://www.turf-fr.com/ (cherche "{libelle}")
- https://www.equidia.fr/pronostics (cherche "{hippodrome}")
- https://www.geny.com/ (cherche "{libelle}")"""

    prompt = f"""Expert PMU {type_str}. Cherche les pronostics pour cette course PRECISE :

Course : "{libelle}" — {hippodrome} — {date_aff}
Partants : {noms_str}

Visite ces URLs et note les chevaux cites dans le TOP 3 de CETTE course :
{urls}

IMPORTANT : cherche bien "{libelle}" a {hippodrome}, pas une autre course.

JSON uniquement :
{{
  "nb_sources_trouvees": 8,
  "citations_top3": {{"NOM1": 6, "NOM2": 4}},
  "sources_par_cheval": {{"NOM1": ["Paris-Turf", "Equidia"], "NOM2": ["Equidia"]}},
  "sources_consultees": ["Paris-Turf", "Equidia"],
  "resume_tendance": "description courte"
}}

Si rien : {{"nb_sources_trouvees": 0, "citations_top3": {{}}, "sources_par_cheval": {{}}, "sources_consultees": [], "resume_tendance": "Aucun pronostic"}}"""

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
                "max_tokens": 800,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if r.status_code != 200:
            return {"citations": {}, "citations_pond": {}, "nb_sources": 0, "sources_par_ch": {}}

        data  = r.json()
        texte = " ".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = json.loads(texte.replace("```json", "").replace("```", "").strip())

        citations = {k.upper(): int(v) for k, v in parsed.get("citations_top3", {}).items()}

        citations_pond = {}
        sources_par_ch = {}
        for nom, srcs in parsed.get("sources_par_cheval", {}).items():
            nom_up = nom.upper().strip()
            sources_par_ch[nom_up] = srcs
            citations_pond[nom_up] = round(sum(sources.get(s, 1.0) for s in srcs), 2)

        nb_sources = int(parsed.get("nb_sources_trouvees", 0))
        log.info(f"  Pronostics [{type_str}]: {nb_sources} sources | {len(citations)} chevaux")

        return {
            "citations":     citations,
            "citations_pond": citations_pond,
            "nb_sources":    nb_sources,
            "sources_par_ch": sources_par_ch,
            "resume":        parsed.get("resume_tendance", ""),
        }
    except Exception as e:
        log.warning(f"Erreur pronostics: {e}")
        return {"citations": {}, "citations_pond": {}, "nb_sources": 0, "sources_par_ch": {}}


def get_signal_presse(nom_cheval, date_aff, discipline) -> dict:
    if not ANTHROPIC_KEY:
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}
    trot = est_trot(discipline)
    prompt = f"""Expert PMU {'trot' if trot else 'galop'}. Infos du {date_aff} sur "{nom_cheval}".
Cherche aussi si deferre/pieds nus aujourd'hui.
JSON : {{"resume": "2-3 phrases", "sentiment": 70, "sources": [], "signaux": [], "deferre": false}}
Si rien : {{"resume": "Aucune info", "sentiment": 50, "sources": [], "signaux": [], "deferre": false}}"""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 400,
                  "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=45,
        )
        if r.status_code != 200:
            return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}
        data  = r.json()
        texte = " ".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        parsed = json.loads(texte.replace("```json", "").replace("```", "").strip())
        return {
            "resume":    parsed.get("resume", ""),
            "sentiment": float(parsed.get("sentiment", 50)),
            "sources":   parsed.get("sources", []),
            "signaux":   parsed.get("signaux", []),
            "deferre":   bool(parsed.get("deferre", False)),
        }
    except Exception as e:
        log.warning(f"Claude '{nom_cheval}': {e}")
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}


# ──────────────────────────────────────────────
#  4. SCORES STATISTIQUES
# ──────────────────────────────────────────────
def score_forme_recente(performances, n=5) -> float:
    if not performances:
        return 0.0
    scores = []
    for p in performances[:n]:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 0.0


def score_forme_fraiche(performances) -> float:
    if not performances:
        return 50.0
    maintenant   = datetime.now().timestamp() * 1000
    trente_jours = 30 * 24 * 3600 * 1000
    recentes = [p for p in performances if (maintenant - (p.get("date") or 0)) <= trente_jours and (p.get("date") or 0) > 0]
    if not recentes:
        return 50.0
    scores = []
    for p in recentes:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 50.0


def score_record_kilometrique(performances, distance_course, partants_actifs) -> tuple:
    """
    Score base sur le record kilométrique (R/K) en trot.
    Compare le meilleur R/K du cheval avec les autres partants.
    Retourne (score, meilleur_rk_en_secondes).
    """
    if not performances:
        return 50.0, 0.0

    # Chercher le meilleur temps (reduction kilométrique ou temps obtenu)
    rk_values = []
    for p in performances:
        # Champ reductionKilometrique = temps/km en centièmes de seconde
        rk = p.get("reductionKilometrique") or p.get("tempsObtenu")
        if rk and isinstance(rk, (int, float)) and rk > 0:
            rk_values.append(float(rk))

    if not rk_values:
        return 50.0, 0.0

    meilleur_rk = min(rk_values)  # Plus petit = plus rapide

    # Collecter les R/K de tous les partants pour normaliser
    tous_rk = []
    for p_autre in partants_actifs:
        rk_autre = p_autre.get("_meilleur_rk", 0)
        if rk_autre > 0:
            tous_rk.append(rk_autre)

    if not tous_rk or len(tous_rk) < 2:
        return 50.0, meilleur_rk

    rk_min = min(tous_rk)  # Meilleur de la course
    rk_max = max(tous_rk)  # Moins bon de la course

    if rk_max == rk_min:
        return 50.0, meilleur_rk

    # Score : R/K le plus bas = 100 pts, le plus haut = 0 pts
    score = ((rk_max - meilleur_rk) / (rk_max - rk_min)) * 100
    return min(100, max(0, score)), meilleur_rk


def score_distance(performances, distance_course) -> float:
    if not performances or not distance_course:
        return 50.0
    pertinentes = [p for p in performances if abs((p.get("distance") or 0) - distance_course) <= 200]
    if not pertinentes:
        return 50.0
    victoires = sum(1 for p in pertinentes if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
    return (victoires / len(pertinentes)) * 100


def score_terrain(performances, terrain_actuel) -> float:
    if not terrain_actuel or not performances:
        return 50.0
    terrain_up = terrain_actuel.upper().replace(" ", "_")
    compat = TERRAIN_COMPAT.get(terrain_up, {})
    if not compat:
        return 50.0
    scores = []
    for p in performances:
        tp = (p.get("terrain") or p.get("etatSol") or "").upper().replace(" ", "_")
        place = p.get("place") or p.get("ordreArrivee")
        if tp and place and str(place).isdigit():
            scores.append(compat.get(tp, 50) * max(0, 110 - int(place) * 10) / 100)
    return min(100, sum(scores) / len(scores)) if scores else 50.0


def score_hippodrome(performances, hippodrome_actuel) -> float:
    if not hippodrome_actuel or not performances:
        return 50.0
    hippo_up = hippodrome_actuel.upper()
    courses_h = [p for p in performances if hippo_up in (p.get("hippodrome") or p.get("lieu") or "").upper()]
    if not courses_h:
        return 50.0
    v = sum(1 for p in courses_h if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
    pl = sum(1 for p in courses_h if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
    return min(100, (v / len(courses_h) * 60 + pl / len(courses_h) * 40) * 100)


def score_corde(place_corde, nb_partants, discipline, distance) -> float:
    if not place_corde or not nb_partants or nb_partants <= 1:
        return 50.0
    score_base = ((nb_partants - place_corde) / (nb_partants - 1)) * 100
    disc = discipline.upper()
    if disc in ("TROT_ATTELE", "ATTELE"):
        facteur = 1.0 if distance <= 2200 else (0.85 if distance <= 2750 else 0.7)
    elif disc in ("TROT_MONTE", "MONTE"):
        facteur = 0.85
    elif disc in ("PLAT", "GALOP"):
        facteur = 0.4
    elif disc in ("HAIES", "STEEPLE"):
        facteur = 0.2
    else:
        facteur = 0.5
    return min(100, max(0, 50 + (score_base - 50) * facteur))


def score_jockey(jockey_nom, tous_partants) -> float:
    if not jockey_nom:
        return 50.0
    v = c = 0
    for p in tous_partants:
        nom_j = p.get("driver") or p.get("nomJockey") or ""
        if nom_j.lower() == jockey_nom.lower():
            v += p.get("nombreVictoires") or 0
            c += p.get("nombreCourses") or 0
    return (v / c * 100) if c else 50.0


def score_entraineur(entraineur_nom, tous_partants) -> float:
    if not entraineur_nom:
        return 50.0
    v = c = 0
    for p in tous_partants:
        entr = p.get("entraineur") or {}
        nom_e = entr.get("nom", "") if isinstance(entr, dict) else str(entr)
        if nom_e.lower() == entraineur_nom.lower():
            v += p.get("nombreVictoiresEntraineur") or p.get("nombreVictoires") or 0
            c += p.get("nombreCoursesEntraineur") or p.get("nombreCourses") or 0
    if c >= 5:
        return min(100, (v / c) * 100)
    for key, bonus in GRANDES_ECURIES.items():
        if key in entraineur_nom.upper():
            return float(bonus)
    return 50.0


def score_mouvement_cote(cote_veille, cote_jour) -> float:
    if not cote_veille or cote_veille <= 0 or cote_jour <= 0:
        return 50.0
    variation = (cote_veille - cote_jour) / cote_veille
    if variation >= 0.40:   return 95.0
    elif variation >= 0.25: return 80.0
    elif variation >= 0.10: return 65.0
    elif variation >= -0.05: return 50.0
    elif variation >= -0.15: return 35.0
    else:                   return 20.0


def score_pronostics_pond(nom, citations_pond, poids_max) -> float:
    if not citations_pond or poids_max <= 0:
        return 0.0
    poids = citations_pond.get(nom.upper().strip(), 0)
    return min(100, (poids / poids_max) * 100) if poids > 0 else 0.0


def calculer_score_total(s, discipline) -> float:
    W = W_TROT if est_trot(discipline) else W_GALOP
    return sum(s.get(k, 0) * W.get(k, 0) / 100 for k in W)


def normaliser_scores(resultats) -> list:
    if not resultats:
        return resultats
    total = sum(r["score_total"] for r in resultats)
    if total <= 0:
        prob = 100.0 / len(resultats)
        for r in resultats:
            r["probabilite"] = round(prob, 1)
    else:
        for r in resultats:
            r["probabilite"] = round((r["score_total"] / total) * 100, 1)
    return resultats


def appliquer_filtre_cote(resultats, nb_sources) -> list:
    """
    Filtre les outsiders aberrants en N1.
    Si pas de pronostics : cote max 20.0 pour le N1.
    Si pronostics disponibles : cote max 35.0.
    Exception : si chute de cote > 30% (signal fort du marché).
    """
    if not resultats:
        return resultats

    cote_max = COTE_MAX_N1_AVEC_PRONOSTICS if nb_sources > 0 else COTE_MAX_N1_SANS_PRONOSTICS

    # Vérifier si le N1 dépasse la cote max
    n1 = resultats[0]
    cote_n1 = n1.get("cote_jour", 0)
    mvt_n1  = n1.get("variation_cote_%", "")

    # Exception : forte chute de cote = signal fort
    chute_forte = isinstance(mvt_n1, (int, float)) and mvt_n1 <= -30

    if cote_n1 > cote_max and not chute_forte:
        # Chercher le meilleur cheval avec une cote raisonnable
        for i, r in enumerate(resultats[1:], 1):
            if r.get("cote_jour", 0) <= cote_max:
                # Echanger le N1 et ce cheval
                resultats[0], resultats[i] = resultats[i], resultats[0]
                log.info(f"  Filtre cote: N1 {n1['nom_cheval']} ({cote_n1}) remplace par {resultats[0]['nom_cheval']}")
                break

    return resultats


# ──────────────────────────────────────────────
#  5. ANALYSE D'UNE COURSE
# ──────────────────────────────────────────────
def analyser_course(date_str, date_veille, date_aff, nr, nc, info_course,
                    hippodrome="", terrain="", activer_presse=True) -> dict:

    discipline = info_course.get("discipline", "")
    distance   = info_course.get("distance", 0)
    libelle    = info_course.get("libelle", f"R{nr} C{nc}")
    heure      = info_course.get("heureDepart", "")
    trot       = est_trot(discipline)
    type_str   = "TROT" if trot else "GALOP"

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants R{nr} C{nc}")
        return {}

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    nb_partants     = len(partants_actifs)
    log.info(f"  [{type_str}] {nb_partants} partants | terrain: {terrain}")

    # Pre-calculer les R/K pour la normalisation
    if trot:
        for partant in partants_actifs:
            num   = partant.get("numPmu") or partant.get("numero")
            perfs = get_performances(date_str, nr, nc, num)
            rk_vals = [
                float(p.get("reductionKilometrique") or p.get("tempsObtenu") or 0)
                for p in perfs
                if (p.get("reductionKilometrique") or p.get("tempsObtenu") or 0) > 0
            ]
            partant["_meilleur_rk"] = min(rk_vals) if rk_vals else 0
            time.sleep(0.2)

    # Pronostics PMU officiels
    pronostics_pmu = get_pronostics_pmu(date_str, nr, nc)
    time.sleep(0.5)

    # Pronostics externes via Claude
    noms_actifs    = [p.get("nom", "") for p in partants_actifs if p.get("nom")]
    pronostics_ext = {"citations": {}, "citations_pond": {}, "nb_sources": 0, "sources_par_ch": {}}
    if activer_presse and ANTHROPIC_KEY:
        pronostics_ext = get_pronostics_externes(noms_actifs, libelle, date_aff, hippodrome, discipline)
        time.sleep(2)

    citations      = dict(pronostics_ext.get("citations", {}))
    citations_pond = dict(pronostics_ext.get("citations_pond", {}))
    sources_par_ch = dict(pronostics_ext.get("sources_par_ch", {}))
    nb_sources     = pronostics_ext.get("nb_sources", 0)

    sources_dict = SOURCES_POIDS_TROT if trot else SOURCES_POIDS_GALOP
    if pronostics_pmu:
        nb_sources += 1
        poids_pmu = sources_dict.get("PMU officiel", 2.5)
        for num_str in pronostics_pmu:
            for p in partants_actifs:
                if str(p.get("numPmu") or "") == num_str:
                    nom_up = p.get("nom", "").upper()
                    citations[nom_up]      = citations.get(nom_up, 0) + 1
                    citations_pond[nom_up] = citations_pond.get(nom_up, 0) + poids_pmu
                    if nom_up not in sources_par_ch:
                        sources_par_ch[nom_up] = []
                    sources_par_ch[nom_up].append("PMU officiel")

    poids_max = max(citations_pond.values()) if citations_pond else 1.0

    resultats = []
    for partant in partants_actifs:
        num          = partant.get("numPmu") or partant.get("numero")
        nom          = partant.get("nom", f"Partant {num}")
        jockey       = partant.get("driver") or partant.get("nomJockey") or ""
        entraineur   = partant.get("entraineur") or ""
        if isinstance(entraineur, dict):
            entraineur = entraineur.get("nom", "")
        proprietaire = partant.get("proprietaire") or ""
        if isinstance(proprietaire, dict):
            proprietaire = proprietaire.get("nom", "")

        place_corde = int(partant.get("placeCorde") or 0)
        poids       = int(partant.get("handicapPoids") or 0)
        oeilleres   = partant.get("oeilleres") or ""
        cote_jour   = extraire_cote(partant)

        # Performances (déjà récupérées pour le R/K en trot)
        if trot and partant.get("_meilleur_rk", 0) > 0:
            perfs = get_performances(date_str, nr, nc, num)
        else:
            perfs = get_performances(date_str, nr, nc, num)
        time.sleep(0.3)
        cote_veille = get_cote_veille(date_veille, nom, nr, nc)
        time.sleep(0.3)

        nom_up  = nom.upper().strip()
        nb_cit  = citations.get(nom_up, 0)
        pond    = citations_pond.get(nom_up, 0)
        pct_cit = round((nb_cit / nb_sources * 100) if nb_sources > 0 else 0, 1)
        src_p   = [s for s in sources_par_ch.get(nom_up, []) if s in SOURCES_PREMIUM]

        # Score R/K pour le trot
        s_rk, rk_best = score_record_kilometrique(perfs, distance, partants_actifs) if trot else (0.0, 0.0)

        s = {
            "pronostics": score_pronostics_pond(nom, citations_pond, poids_max),
            "forme_r":    score_forme_recente(perfs),
            "forme_f":    score_forme_fraiche(perfs),
            "rk":         s_rk,
            "distance":   score_distance(perfs, distance),
            "terrain":    score_terrain(perfs, terrain),
            "mouvement":  score_mouvement_cote(cote_veille, cote_jour),
            "jockey":     score_jockey(str(jockey), partants_actifs),
            "entraineur": score_entraineur(str(entraineur), partants_actifs),
            "hippodrome": score_hippodrome(perfs, hippodrome),
            "corde":      score_corde(place_corde, nb_partants, discipline, distance),
        }
        s_total = calculer_score_total(s, discipline)

        # Bonus oeilleres
        if "AUSTRALIENNES" in oeilleres:
            s_total = max(0, s_total - 2)
        elif "CLASSIQUE" in oeilleres:
            s_total = max(0, s_total - 1)

        # Value bet
        value_bet = (pct_cit >= 40 and cote_jour >= (100 / max(pct_cit, 1)) * 1.4)

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
            "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
            "discipline": discipline, "type_course": type_str, "distance_m": distance,
            "nb_partants": nb_partants, "num_partant": num, "nom_cheval": nom,
            "place_corde": place_corde, "poids_porte": poids, "oeilleres": oeilleres,
            "deferre": False, "value_bet": value_bet, "consensus_fort": len(src_p) >= 3,
            "sources_premium_citees": src_p, "rk_meilleur": round(rk_best, 2),
            "jockey": jockey, "entraineur": str(entraineur), "proprietaire": str(proprietaire),
            "cote_veille": round(cote_veille, 2) if cote_veille else "",
            "cote_jour": round(cote_jour, 2), "variation_cote_%": var_cote,
            "nb_pronostics": nb_cit, "nb_pronostics_pondere": round(pond, 1),
            "pct_pronostics": pct_cit, "nb_sources_total": nb_sources,
            "score_pronostics": round(s["pronostics"], 1),
            "score_forme": round(s["forme_r"], 1), "score_forme_fraiche": round(s["forme_f"], 1),
            "score_rk": round(s_rk, 1), "score_distance": round(s["distance"], 1),
            "score_terrain": round(s["terrain"], 1), "score_mouvement": round(s["mouvement"], 1),
            "score_jockey": round(s["jockey"], 1), "score_entraineur": round(s["entraineur"], 1),
            "score_hippodrome": round(s["hippodrome"], 1), "score_corde": round(s["corde"], 1),
            "score_total": round(s_total, 1),
            "presse_resume": "", "presse_sentiment": 50.0, "presse_sources": "", "presse_signaux": "",
        })
        time.sleep(0.5)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)
    resultats = normaliser_scores(resultats)
    resultats = appliquer_filtre_cote(resultats, nb_sources)

    consensus_fort = any(r.get("consensus_fort") for r in resultats[:2])

    # Signal presse top 2 uniquement
    if activer_presse and ANTHROPIC_KEY:
        for r in resultats[:2]:
            presse = get_signal_presse(r["nom_cheval"], date_aff, discipline)
            r["presse_resume"]    = presse.get("resume", "")
            r["presse_sentiment"] = presse.get("sentiment", 50.0)
            r["presse_sources"]   = ", ".join(presse.get("sources", []))
            r["presse_signaux"]   = ", ".join(presse.get("signaux", []))
            r["deferre"]          = presse.get("deferre", False)
            if presse.get("deferre"):
                r["score_total"] = min(100, r["score_total"] + 3)
            time.sleep(1)

    # Log
    log.info(f"\n{'─'*70}")
    log.info(f"  [{type_str}] {libelle} | {distance}m | {terrain}")
    if trot:
        log.info(f"  {'#':<3} {'Cheval':<22} {'Cote':>6} {'R/K':>8} {'Corde':>6} {'Score':>7}")
        for i, r in enumerate(resultats[:4], 1):
            rk_str = f"{int(r['rk_meilleur'])//60}'{r['rk_meilleur']%60:05.2f}" if r["rk_meilleur"] > 0 else "  n/a"
            log.info(f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} {rk_str:>8} {str(r['place_corde']):>5} {r['score_total']:>7.1f}")
    else:
        log.info(f"  {'#':<3} {'Cheval':<22} {'Cote':>6} {'Prono':>8} {'Score':>7}")
        for i, r in enumerate(resultats[:4], 1):
            vb = " VALUE" if r["value_bet"] else ""
            log.info(f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} {r['nb_pronostics']:>4}/{r['nb_sources_total']:<3} {r['score_total']:>7.1f}{vb}")

    return {
        "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
        "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
        "discipline": discipline, "type_course": type_str,
        "nb_sources_total": nb_sources, "consensus_fort": consensus_fort,
        "top2": resultats[:2], "tous_resultats": resultats,
    }


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
        else "Analyse de mi-journee (cotes fraiches + pronostics)"
    )
    activer_presse = bool(ANTHROPIC_KEY)

    log.info("=" * 70)
    log.info(f"  PMU SCORER v10 - GALOP & TROT - {date_aff} - {heure_run}")
    log.info(f"  R/K trot actif | Filtre cote actif | Sources ponderees")
    log.info(f"  Pronostics: {'OK' if activer_presse else 'desactive'}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer v10 demarre - {date_aff} {heure_run}\n{run_label}...")

    programme = get_programme(date_str)
    if not programme:
        msg = f"ERREUR - programme indisponible {date_aff}"
        log.error(msg); telegram_send(msg); return

    reunions = programme.get("programme", {}).get("reunions", [])
    if not reunions:
        msg = f"ERREUR - aucune reunion {date_aff}"
        log.error(msg); telegram_send(msg); return

    log.info(f"{len(reunions)} reunions.")
    tous_csv = []; courses_galop = []; courses_trot = []

    for reunion in reunions:
        pays = reunion.get("pays", {})
        code = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code not in PAYS_AUTORISES:
            continue

        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        courses    = reunion.get("courses", [])
        terrain_r  = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain_r, dict):
            terrain_r = terrain_r.get("libelle", "") or terrain_r.get("code", "")

        log.info(f"\n> R{nr} - {hippodrome} | {terrain_r} ({len(courses)} courses)")

        for course in courses:
            nc         = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue

            terrain = course.get("terrain") or course.get("etatSol") or terrain_r
            if isinstance(terrain, dict):
                terrain = terrain.get("libelle", "") or terrain.get("code", "")

            try:
                res = analyser_course(
                    date_str, date_veille, date_aff, nr, nc, course,
                    hippodrome=hippodrome, terrain=str(terrain).upper() if terrain else "",
                    activer_presse=activer_presse,
                )
                if res and res.get("tous_resultats"):
                    tous_csv.extend(res["tous_resultats"])
                    (courses_trot if res["type_course"] == "TROT" else courses_galop).append(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    log.info(f"\nGALOP: {len(courses_galop)} courses | TROT: {len(courses_trot)} courses")

    if tous_csv:
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion","course","heure","hippodrome","terrain","libelle","discipline","type_course",
            "distance_m","nb_partants","num_partant","nom_cheval","place_corde","poids_porte",
            "oeilleres","deferre","value_bet","consensus_fort","rk_meilleur",
            "jockey","entraineur","proprietaire","cote_veille","cote_jour","variation_cote_%",
            "nb_pronostics","nb_pronostics_pondere","pct_pronostics","nb_sources_total",
            "score_pronostics","score_forme","score_forme_fraiche","score_rk","score_distance",
            "score_terrain","score_mouvement","score_jockey","score_entraineur",
            "score_hippodrome","score_corde","score_total",
            "presse_resume","presse_sentiment","presse_sources","presse_signaux",
        ]
        with open(nom_fichier, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tous_csv)
        log.info(f"CSV: {nom_fichier}")

        message = formater_message_telegram(courses_galop, courses_trot, date_aff, run_label)
        if telegram_send(message):
            log.info("Telegram envoye.")
        else:
            log.warning("Telegram echoue.")
    else:
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat France.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v10 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
