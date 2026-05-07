"""
=============================================================
  PMU RACING SCORER v13 - France uniquement
=============================================================
  Nouveautes v13 :
    - Score propriétaire (via boturfers.fr / france-galop)
    - Trio proprietaire + jockey + entraineur sur hippodrome
    - Pronostics passes a 15% (consensus) + 5% (outsider surprise)
    - Suppression malus oeilleres australiennes
    - Malus trot : fautes/galop sur 5 dernieres courses (-8 pts)
    - Jockey/driver sur cet hippodrome + hippodromes similaires
    - Format : top2 + 3 suivants dans Telegram
    - Inversion N1/N2 si pronostics justifient
    - VALUE BET : minimum 3 sources
    - Délai 60s entre appels Claude
=============================================================
  Poids GALOP (100 pts) :
    Pronostics consensus   15 | Outsider surprise      5
    Forme recente          14 | Mouvement cote         10
    Terrain                 8 | Trio proprio+joc+entr  18
    Distance                7 | Jockey sur hippodrome   5
    Progression             5 | Forme fraiche           4
    Hippodrome cheval       3 | Corde                   2
    R/K                     0 | Terrain                 8
    Total = 96 + arrondi   = 100

  Poids TROT (100 pts) :
    Pronostics consensus   15 | Outsider surprise      5
    Forme recente          12 | R/K kilometrique       13
    Corde                  12 | Mouvement cote          8
    Trio proprio+joc+entr  15 | Jockey sur hippodrome   5
    Distance                5 | Progression             3
    Hippodrome cheval       3 | Forme fraiche           4
    Total = 100
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

TYPE_HANDICAP   = "HANDICAP"
TYPE_CONDITIONS = "CONDITIONS"
TYPE_GROUPE     = "GROUPE"
TYPE_RECLAMER   = "RECLAMER"
TYPE_INCONNU    = "AUTRE"

# Sources ponderees
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

# Poids GALOP
W_GALOP_NORMAL = {
    "pronostics": 15, "outsider": 5, "forme_r": 16, "mouvement": 12,
    "terrain": 8, "trio_pje": 18, "distance": 7, "jockey_hippo": 5,
    "progression": 5, "forme_f": 4, "hippodrome": 3, "corde": 2,
    "rk": 0, "fautes": 0,
}
W_GALOP_HANDICAP = {
    "pronostics": 15, "outsider": 5, "forme_r": 12, "mouvement": 12,
    "terrain": 6, "trio_pje": 18, "distance": 5, "jockey_hippo": 5,
    "progression": 8, "forme_f": 4, "hippodrome": 3, "corde": 2,
    "rk": 0, "fautes": 5,
}

# Poids TROT
W_TROT_NORMAL = {
    "pronostics": 15, "outsider": 5, "forme_r": 12, "rk": 13,
    "corde": 12, "mouvement": 8, "trio_pje": 15, "jockey_hippo": 5,
    "distance": 5, "progression": 3, "hippodrome": 3, "forme_f": 4,
    "terrain": 0, "fautes": 0,
}
W_TROT_HANDICAP = {
    "pronostics": 15, "outsider": 5, "forme_r": 10, "rk": 13,
    "corde": 12, "mouvement": 10, "trio_pje": 15, "jockey_hippo": 5,
    "distance": 3, "progression": 6, "hippodrome": 3, "forme_f": 3,
    "terrain": 0, "fautes": 0,
}

for w in [W_GALOP_NORMAL, W_GALOP_HANDICAP, W_TROT_NORMAL, W_TROT_HANDICAP]:
    total = sum(w.values())
    assert total == 100, f"Poids invalide: {total} — {w}"

GRANDES_ECURIES = {
    "WERTHEIMER ET FRERE": 88, "AGA KHAN": 85, "AGA KHAN STUDS": 85,
    "ROTHSCHILD": 82, "NIARCHOS": 80, "AL SHAQAB RACING": 82,
    "WATHNAN RACING": 82, "GODOLPHIN": 85, "COOLMORE": 84,
    "JUDDMONTE": 83, "FLAXMAN STABLES": 80, "HARAS DE BOUQUETOT": 74,
    "HARAS D'ETREHAM": 72, "HARAS DE LA GOURDAINE": 70,
    "SAINT CLOUD RACING": 68, "FRANCOIS ROHAUT": 72,
    "HARAS DE CLAIREFONTAINE": 74, "G.AUGUSTIN-NORMAND": 77,
    "GUERRIN": 78, "ECURIE GUERRIN": 78,
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


def detecter_type_course(info_course: dict) -> str:
    libelle   = (info_course.get("libelle") or "").upper()
    cond      = (info_course.get("conditions") or "").upper()
    categorie = (info_course.get("categorieParticularite") or "").upper()
    if any(k in libelle for k in ["GROUPE I","GROUPE II","GROUPE III","GR.I","GR.II","GR.III","LISTED"]):
        return TYPE_GROUPE
    if any(k in libelle + cond for k in ["RECLAMER","A RECLAMER","CLAIMING"]):
        return TYPE_RECLAMER
    if any(k in libelle + cond + categorie for k in ["HANDICAP","HCAP","H.CAP"]):
        return TYPE_HANDICAP
    return TYPE_CONDITIONS


# ──────────────────────────────────────────────
#  1. TELEGRAM
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return False
    url      = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    morceaux = [texte[i:i+4096] for i in range(0, len(texte), 4096)]
    succes = True
    for morceau in morceaux:
        try:
            r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": morceau}, timeout=15)
            if r.status_code != 200:
                log.warning(f"Telegram {r.status_code}: {r.text[:100]}")
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Telegram: {e}")
            succes = False
    return succes


def formater_message_telegram(courses_galop, courses_trot, date_aff, run_label) -> str:

    def formater_course(course: dict) -> list:
        lignes = []
        if not course.get("top5"):
            return lignes

        disc      = course.get("discipline", "").replace("_", " ")
        heure_ts  = course.get("heure", 0)
        libelle   = course.get("libelle", "")
        reunion   = course.get("reunion", "")
        nc        = course.get("course", "")
        terrain   = course.get("terrain", "")
        nb_src    = course.get("nb_sources_total", 0)
        consensus = course.get("consensus_fort", False)
        type_c    = course.get("type_course_details", TYPE_CONDITIONS)
        trot      = est_trot(course.get("discipline", ""))

        heure_str = ""
        if heure_ts and isinstance(heure_ts, (int, float)) and heure_ts > 0:
            try:
                heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
            except Exception:
                pass

        terrain_str = f" | {terrain}" if terrain else ""
        alert_str   = " *** CONSENSUS FORT ***" if consensus else ""
        type_str    = f" [{type_c}]" if type_c not in (TYPE_CONDITIONS, TYPE_INCONNU) else ""

        lignes.append("")
        lignes.append(f"{reunion} {nc} | {heure_str} | {disc}{terrain_str}{type_str}{alert_str}")
        if libelle:
            lignes.append(f"{libelle[:50]}")
        lignes.append("-" * 35)

        top2  = course["top5"][:2]
        top35 = course["top5"][2:5]

        for rang, cheval in enumerate(top2, 1):
            nom        = cheval.get("nom_cheval", "?")
            num_ch     = cheval.get("num_partant", "")
            cote       = cheval.get("cote_jour", 0)
            score      = cheval.get("score_total", 0)
            prob       = cheval.get("probabilite", 0)
            nb_prono   = cheval.get("nb_pronostics", 0)
            pct_prono  = cheval.get("pct_pronostics", 0)
            nb_src_ch  = cheval.get("nb_sources_total", 0)
            corde      = cheval.get("place_corde", 0)
            nb_part    = cheval.get("nb_partants", 0)
            poids      = cheval.get("poids_porte", 0)
            jockey     = cheval.get("jockey", "?")
            entraineur = cheval.get("entraineur", "")
            proprietaire = cheval.get("proprietaire", "")
            value      = cheval.get("value_bet", False)
            outsider   = cheval.get("est_outsider_surprise", False)
            src_p      = cheval.get("sources_premium_citees", [])
            rk_best    = cheval.get("rk_meilleur", 0)
            score_trio = cheval.get("score_trio_pje", 0)

            mvt = ""
            val = cheval.get("variation_cote_%", "")
            if val != "" and isinstance(val, (int, float)):
                if val <= -25:
                    mvt = f" [CHUTE {val:+.0f}%!!!]"
                elif val <= -10:
                    mvt = f" [cote {val:+.0f}%]"
                elif val >= 15:
                    mvt = f" [+{val:.0f}%]"

            value_str   = " *** VALUE BET ***" if value else ""
            outsider_str = " [SURPRISE]" if outsider else ""
            nom_aff     = f"N{num_ch}. {nom}" if num_ch else nom
            prefixe     = ">> " if rang == 1 else "   "

            lignes.append(f"{prefixe}{rang}. {nom_aff} (cote {cote:.1f}){mvt}{value_str}{outsider_str}")
            lignes.append(f"   Score: {score:.1f}% | Proba: {prob:.1f}%")

            if nb_src_ch > 0:
                lignes.append(f"   {nb_prono} source(s)/{nb_src_ch} ({pct_prono:.0f}%)")
            else:
                lignes.append(f"   Pronostics: collecte en cours")

            if src_p:
                lignes.append(f"   Sources premium: {', '.join(src_p)}")

            if corde and nb_part:
                av = " AVANTAGE DECISIF" if (trot and corde <= 3) else (" AVANTAGE" if corde <= 3 else "")
                lignes.append(f"   Corde {corde}/{nb_part}{av}")

            if trot and rk_best > 0:
                mn  = int(rk_best) // 60
                sec = rk_best % 60
                lignes.append(f"   Meilleur R/K: {mn}'{sec:05.2f}")

            if poids and not trot:
                lignes.append(f"   Poids: {poids/10:.1f}kg")

            lignes.append(f"   Jockey: {jockey}")
            if entraineur:
                lignes.append(f"   Entraineur: {str(entraineur)[:30]}")
            if proprietaire:
                lignes.append(f"   Prop: {str(proprietaire)[:30]}")

        # Top 3-5 : format compact pour les combinaisons
        if top35:
            lignes.append("   --- Autres possibilites ---")
            for rang, cheval in enumerate(top35, 3):
                nom    = cheval.get("nom_cheval", "?")
                num_ch = cheval.get("num_partant", "")
                cote   = cheval.get("cote_jour", 0)
                prob   = cheval.get("probabilite", 0)
                nb_p   = cheval.get("nb_pronostics", 0)
                nb_s   = cheval.get("nb_sources_total", 0)
                out    = " [SURPRISE]" if cheval.get("est_outsider_surprise") else ""
                nom_aff = f"N{num_ch}. {nom}" if num_ch else nom
                prono_str = f" {nb_p}/{nb_s}" if nb_s > 0 else ""
                lignes.append(f"   {rang}. {nom_aff} (cote {cote:.1f}) {prob:.1f}%{prono_str}{out}")

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
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/13.0)",
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
        return {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                "sources_par_ch": {}, "outsiders": []}

    trot     = est_trot(discipline)
    sources  = SOURCES_POIDS_TROT if trot else SOURCES_POIDS_GALOP
    type_str = "trot" if trot else "galop"
    noms_str = ", ".join(noms_chevaux[:16])

    prompt = f"""Cherche pronostics PMU pour : "{libelle}" {hippodrome} {date_aff}
Partants : {noms_str}

Reponds UNIQUEMENT avec ce JSON (rien d autre, pas de texte, pas de ```):
{{"nb_sources_trouvees":5,"citations_top3":{{"NOM1":4,"NOM2":2}},"sources_par_cheval":{{"NOM1":["Paris-Turf","Equidia"]}},"outsiders_surprises":["NOM_OUTSIDER"],"deferres":["NOM_DEFERRE"],"sources_consultees":["Paris-Turf"],"resume_tendance":"tendance"}}

outsiders_surprises = chevaux a grosse cote cites comme trouble-fete.
deferres = chevaux annonces sans fers (deferres) aujourd hui - cherche dans presse du jour.
Si aucun pronostic : {{"nb_sources_trouvees":0,"citations_top3":{{}},"sources_par_cheval":{{}},"outsiders_surprises":[],"deferres":[],"sources_consultees":[],"resume_tendance":"Aucun pronostic"}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-5", "max_tokens": 1500,
                  "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90,
        )
        if r.status_code != 200:
            log.error(f"Claude API ERREUR {r.status_code}: {r.text[:200]}")
            return {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                    "sources_par_ch": {}, "outsiders": []}

        log.info(f"  Claude API OK")
        data  = r.json()
        texte = " ".join(b.get("text","") for b in data.get("content",[])
                         if b.get("type")=="text").strip()

        # Extraire uniquement le JSON
        debut = texte.find("{")
        fin   = texte.rfind("}") + 1
        if debut < 0 or fin <= debut:
            log.warning(f"  Pas de JSON dans la reponse")
            return {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                    "sources_par_ch": {}, "outsiders": []}

        parsed = json.loads(texte[debut:fin])

        citations = {k.upper(): int(v) for k, v in parsed.get("citations_top3", {}).items()}
        citations_pond = {}
        sources_par_ch = {}
        for nom, srcs in parsed.get("sources_par_cheval", {}).items():
            nom_up = nom.upper().strip()
            sources_par_ch[nom_up] = srcs
            citations_pond[nom_up] = round(sum(sources.get(s, 1.0) for s in srcs), 2)

        outsiders = [o.upper().strip() for o in parsed.get("outsiders_surprises", [])]
        nb_sources = int(parsed.get("nb_sources_trouvees", 0))
        log.info(f"  Pronostics [{type_str}]: {nb_sources} sources | "
                 f"{len(citations)} chevaux | {len(outsiders)} outsiders")

        deferres = [d.upper().strip() for d in parsed.get("deferres", [])]
        log.info(f"  Deferres detectes: {deferres}")

        return {
            "citations": citations,
            "citations_pond": citations_pond,
            "nb_sources": nb_sources,
            "sources_par_ch": sources_par_ch,
            "outsiders": outsiders,
            "deferres": deferres,
            "resume": parsed.get("resume_tendance", ""),
        }
    except Exception as e:
        log.warning(f"Pronostics: {e}")
        return {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                "sources_par_ch": {}, "outsiders": [], "deferres": []}


def get_stats_proprietaire(proprietaire: str, hippodrome: str) -> float:
    """
    Cherche le taux de victoire du proprietaire via Claude.
    Sources : boturfers.fr, france-galop.com
    """
    if not ANTHROPIC_KEY or not proprietaire or len(proprietaire) < 3:
        return 50.0

    # Verifier d abord les grandes ecuries connues
    prop_up = proprietaire.upper()
    for key, score in GRANDES_ECURIES.items():
        if key in prop_up:
            return float(score)

    prompt = f"""Stats du proprietaire de courses "{proprietaire}" sur boturfers.fr ou france-galop.com.
JSON uniquement: {{"taux_victoire_pct": 12.5, "nb_courses": 150, "source": "boturfers.fr"}}
Si inconnu: {{"taux_victoire_pct": 5.0, "nb_courses": 0, "source": "inconnu"}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-5", "max_tokens": 200,
                  "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        if r.status_code != 200:
            return 50.0

        data  = r.json()
        texte = " ".join(b.get("text","") for b in data.get("content",[])
                         if b.get("type")=="text").strip()
        debut = texte.find("{")
        fin   = texte.rfind("}") + 1
        if debut < 0:
            return 50.0
        parsed = json.loads(texte[debut:fin])
        taux = float(parsed.get("taux_victoire_pct", 5.0))
        return min(100, taux * 5)  # Normalise : 20% taux = 100 pts
    except Exception:
        return 50.0


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
    recentes = [p for p in performances
                if (maintenant - (p.get("date") or 0)) <= trente_jours
                and (p.get("date") or 0) > 0]
    if not recentes:
        return 50.0
    scores = []
    for p in recentes:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 50.0


def score_fautes_trot(performances, n=5, musique="") -> float:
    """
    Malus pour les chevaux qui se mettent souvent au galop ou commettent
    des erreurs en trot sur les 5 dernieres courses.

    Lit :
    1. Le champ incident/typeIncident dans les performances
    2. Le champ ordreArrivee (D=Disqualifie/Galop, A=Arrete, T=Tombe)
    3. La musique PMU : D, G, A dans les 5 derniers caracteres

    Retourne un malus negatif (0 = pas de faute).
    """
    nb_fautes = 0
    nb_analysees = 0

    # Analyser les performances detaillees
    for p in performances[:n]:
        nb_analysees += 1
        incident = str(p.get("incident") or p.get("typeIncident") or "").upper()
        arrivee  = str(p.get("ordreArrivee") or p.get("place") or "").upper()

        if incident in ("GALOP", "DECROCHEMENT", "DISQUALIFIE", "TOMBE",
                        "CHUTE", "ABANDON", "G", "D", "A", "T"):
            nb_fautes += 1
        elif arrivee in ("D", "G", "T", "A"):
            nb_fautes += 1

    # Analyser la musique PMU si peu de performances detaillees
    if nb_analysees < 3 and musique:
        # Extraire les 10 derniers caracteres de la musique
        musique_recente = musique.upper().replace(" ", "")[-20:]
        # Compter les codes de fautes
        for code in ["D", "G", "A", "T"]:
            nb_fautes += musique_recente.count(code)
        nb_analysees = max(nb_analysees, min(5, len(musique_recente) // 2))

    if nb_analysees == 0:
        return 0.0

    taux = nb_fautes / nb_analysees

    # Malus progressif
    if taux == 0:
        return 0.0
    elif taux <= 0.2:   # 1 faute sur 5
        return -4.0
    elif taux <= 0.4:   # 2 fautes sur 5
        return -8.0
    elif taux <= 0.6:   # 3 fautes sur 5
        return -12.0
    else:               # 4+ fautes sur 5
        return -18.0


def score_progression(performances, n=4) -> float:
    if not performances or len(performances) < 2:
        return 50.0
    places = []
    for p in performances[:n]:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            places.append(int(place))
    if len(places) < 2:
        return 50.0
    ameliorations = sum(1 for i in range(len(places)-1) if places[i] < places[i+1])
    total_paires  = len(places) - 1
    taux = ameliorations / total_paires
    meilleure_recente = places[0] <= min(places)
    if taux >= 0.75 and meilleure_recente:
        return 95.0
    elif taux >= 0.67:
        return 80.0
    elif taux >= 0.50:
        return 65.0
    elif taux >= 0.33:
        return 50.0
    else:
        return 30.0


def score_distance(performances, distance_course, type_course) -> float:
    if not performances or not distance_course:
        return 50.0
    pertinentes = [p for p in performances
                   if abs((p.get("distance") or 0) - distance_course) <= 200]
    if not pertinentes:
        return 50.0 if type_course == TYPE_HANDICAP else 40.0
    victoires = sum(1 for p in pertinentes
                    if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
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


def score_hippodrome_cheval(performances, hippodrome_actuel) -> float:
    if not hippodrome_actuel or not performances:
        return 50.0
    hippo_up = hippodrome_actuel.upper()
    courses_h = [p for p in performances
                 if hippo_up in (p.get("hippodrome") or p.get("lieu") or "").upper()]
    if not courses_h:
        return 50.0
    v  = sum(1 for p in courses_h if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
    pl = sum(1 for p in courses_h
             if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
    return min(100, (v / len(courses_h) * 60 + pl / len(courses_h) * 40) * 100)


def score_jockey_sur_hippodrome(performances, jockey_nom, hippodrome_actuel) -> float:
    """
    Score du jockey/driver specifiquement sur CET hippodrome.
    Si peu de donnees sur cet hippodrome, elargit aux hippodromes similaires.
    """
    if not jockey_nom or not hippodrome_actuel or not performances:
        return 50.0

    hippo_up = hippodrome_actuel.upper()

    # Filtrer les performances du jockey sur cet hippodrome
    perfs_hippo = [
        p for p in performances
        if (jockey_nom.lower() in (p.get("driver") or p.get("nomJockey") or "").lower())
        and hippo_up in (p.get("hippodrome") or p.get("lieu") or "").upper()
    ]

    if len(perfs_hippo) >= 3:
        # Suffisamment de donnees sur cet hippodrome
        v  = sum(1 for p in perfs_hippo
                 if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
        pl = sum(1 for p in perfs_hippo
                 if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
        taux_v  = v / len(perfs_hippo)
        taux_pl = pl / len(perfs_hippo)
        return min(100, (taux_v * 60 + taux_pl * 40) * 100)
    else:
        # Peu de donnees : utiliser toutes les performances du jockey
        perfs_jockey = [
            p for p in performances
            if jockey_nom.lower() in (p.get("driver") or p.get("nomJockey") or "").lower()
        ]
        if not perfs_jockey:
            return 50.0
        v  = sum(1 for p in perfs_jockey
                 if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
        pl = sum(1 for p in perfs_jockey
                 if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
        taux_v  = v / len(perfs_jockey)
        taux_pl = pl / len(perfs_jockey)
        # Coefficient reduit car pas specifique a l hippodrome
        return min(100, (taux_v * 50 + taux_pl * 30) * 100)


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


def score_record_kilometrique(performances, distance_course, partants_actifs) -> tuple:
    if not performances:
        return 50.0, 0.0
    rk_values = []
    for p in performances:
        rk = p.get("reductionKilometrique") or p.get("tempsObtenu")
        if rk and isinstance(rk, (int, float)) and rk > 0:
            rk_values.append(float(rk))
    if not rk_values:
        return 50.0, 0.0
    meilleur_rk = min(rk_values)
    tous_rk = [p.get("_meilleur_rk", 0) for p in partants_actifs if p.get("_meilleur_rk", 0) > 0]
    if not tous_rk or len(tous_rk) < 2:
        return 50.0, meilleur_rk
    rk_min = min(tous_rk)
    rk_max = max(tous_rk)
    if rk_max == rk_min:
        return 50.0, meilleur_rk
    score = ((rk_max - meilleur_rk) / (rk_max - rk_min)) * 100
    return min(100, max(0, score)), meilleur_rk


def score_trio_proprietaire_jockey_entraineur(
    score_proprio: float,
    score_jockey_global: float,
    score_entraineur: float,
) -> float:
    """
    Score combine du trio proprietaire + jockey + entraineur.
    Poids : proprio 30%, jockey 40%, entraineur 30%
    """
    return (score_proprio * 0.30 + score_jockey_global * 0.40 + score_entraineur * 0.30)


def score_jockey_global(jockey_nom, tous_partants) -> float:
    if not jockey_nom:
        return 50.0
    v = c = 0
    for p in tous_partants:
        nom_j = p.get("driver") or p.get("nomJockey") or ""
        if nom_j.lower() == jockey_nom.lower():
            v += p.get("nombreVictoires") or 0
            c += p.get("nombreCourses") or 0
    return (v / c * 100) if c else 50.0


def score_entraineur_global(entraineur_nom, tous_partants) -> float:
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


def score_pronostics_pond(nom, citations_pond, poids_max) -> float:
    if not citations_pond or poids_max <= 0:
        return 0.0
    poids = citations_pond.get(nom.upper().strip(), 0)
    return min(100, (poids / poids_max) * 100) if poids > 0 else 0.0


def score_outsider(nom, outsiders, cote) -> float:
    """
    Score pour les chevaux identifies comme outsiders/surprise par les pronostiqueurs.
    """
    nom_up = nom.upper().strip()
    if nom_up in outsiders and cote >= 15.0:
        return 80.0  # Signal fort : outsider cite + grosse cote
    elif nom_up in outsiders:
        return 60.0  # Cite comme surprise mais cote pas si haute
    return 0.0


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


def bonus_age_saison(partant: dict) -> float:
    age  = partant.get("age", 0)
    mois = datetime.now().month
    if age == 3 and 3 <= mois <= 6:
        return 3.0
    elif age == 4 and 3 <= mois <= 5:
        return 1.5
    return 0.0


def calculer_score_total(s: dict, discipline: str, type_course: str) -> float:
    trot = est_trot(discipline)
    if trot:
        W = W_TROT_HANDICAP if type_course == TYPE_HANDICAP else W_TROT_NORMAL
    else:
        W = W_GALOP_HANDICAP if type_course == TYPE_HANDICAP else W_GALOP_NORMAL
    return sum(s.get(k, 0) * W.get(k, 0) / 100 for k in W)


def normaliser_scores(resultats) -> list:
    if not resultats:
        return resultats
    total = sum(r["score_total"] for r in resultats)
    if total <= 0:
        for r in resultats:
            r["probabilite"] = round(100.0 / len(resultats), 1)
    else:
        for r in resultats:
            r["probabilite"] = round((r["score_total"] / total) * 100, 1)
    return resultats


def est_outsider_suspect(r, nb_sources, type_course) -> bool:
    """
    Suspect si grosse cote ET aucun signal externe.
    Seuil : 15.0 sans pronostics / 30.0 avec pronostics.
    """
    cote   = r.get("cote_jour", 0)
    nb_cit = r.get("nb_pronostics", 0)
    mvt    = r.get("variation_cote_%", "")
    chute  = isinstance(mvt, (int, float)) and mvt <= -25

    # Seuil selon disponibilite des pronostics
    seuil = 30.0 if nb_sources > 0 else 15.0

    if cote <= seuil or cote == 0:
        return False
    if nb_cit > 0:
        return False
    if chute:
        return False
    if type_course == TYPE_HANDICAP:
        return False
    return True


def appliquer_filtre_et_inversion(resultats, nb_sources, type_course) -> list:
    """
    1. Filtre les outsiders suspects en N1
    2. Inverse N1/N2 si pronostics le justifient
    3. Si scores egaux et pas de pronostics : favori de cote en N1
    """
    if not resultats:
        return resultats

    # Filtre N1 suspect
    n1 = resultats[0]
    if est_outsider_suspect(n1, nb_sources, type_course):
        for i, r in enumerate(resultats[1:], 1):
            if not est_outsider_suspect(r, nb_sources, type_course):
                resultats[0], resultats[i] = resultats[i], resultats[0]
                log.info(f"  Filtre intelligent: {n1['nom_cheval']} ({n1['cote_jour']}) -> {resultats[0]['nom_cheval']}")
                break

    # Inversion N1/N2 si pronostics justifient
    if len(resultats) >= 2:
        n1 = resultats[0]
        n2 = resultats[1]
        pond_n1 = n1.get("nb_pronostics_pondere", 0) or 0
        pond_n2 = n2.get("nb_pronostics_pondere", 0) or 0
        ecart   = n1.get("score_total", 0) - n2.get("score_total", 0)
        if pond_n2 > pond_n1 * 1.5 and ecart < 5:
            resultats[0], resultats[1] = resultats[1], resultats[0]
            log.info(f"  Inversion N1/N2: {n2['nom_cheval']} -> N1")

    # Si scores tres proches (< 1 pt) et pas de pronostics
    # -> le favori de cote (plus basse cote = plus confiance du marche) en N1
    if len(resultats) >= 2 and nb_sources == 0:
        n1 = resultats[0]
        n2 = resultats[1]
        ecart_score = abs(n1.get("score_total", 0) - n2.get("score_total", 0))
        cote_n1 = n1.get("cote_jour", 999)
        cote_n2 = n2.get("cote_jour", 999)
        if ecart_score < 1.0 and cote_n2 > 0 and cote_n1 > cote_n2 * 1.5:
            resultats[0], resultats[1] = resultats[1], resultats[0]
            log.info(
                f"  Favori marche: {n2['nom_cheval']} (cote {cote_n2}) "
                f"-> N1 (scores egaux, marche prefere)"
            )

    return resultats


# ──────────────────────────────────────────────
#  5. ANALYSE D UNE COURSE
# ──────────────────────────────────────────────
def analyser_course(date_str, date_veille, date_aff, nr, nc, info_course,
                    hippodrome="", terrain="", activer_presse=True) -> dict:

    discipline  = info_course.get("discipline", "")
    distance    = info_course.get("distance", 0)
    libelle     = info_course.get("libelle", f"R{nr} C{nc}")
    heure       = info_course.get("heureDepart", "")
    trot        = est_trot(discipline)
    type_str    = "TROT" if trot else "GALOP"
    type_course = detecter_type_course(info_course)

    log.info(f"  [{type_str}] [{type_course}] {libelle}")

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants R{nr} C{nc}")
        return {}

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    nb_partants     = len(partants_actifs)

    # Pre-calculer R/K pour trot
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

    pronostics_pmu = get_pronostics_pmu(date_str, nr, nc)
    time.sleep(0.5)

    noms_actifs    = [p.get("nom", "") for p in partants_actifs if p.get("nom")]
    pronostics_ext = {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                      "sources_par_ch": {}, "outsiders": []}
    if activer_presse and ANTHROPIC_KEY:
        pronostics_ext = get_pronostics_externes(
            noms_actifs, libelle, date_aff, hippodrome, discipline)
        time.sleep(60)  # Eviter rate limit 30k tokens/min

    citations      = dict(pronostics_ext.get("citations", {}))
    citations_pond = dict(pronostics_ext.get("citations_pond", {}))
    sources_par_ch = dict(pronostics_ext.get("sources_par_ch", {}))
    outsiders      = pronostics_ext.get("outsiders", [])
    deferres       = pronostics_ext.get("deferres", [])
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
        cote_jour   = extraire_cote(partant)
        age         = partant.get("age", 0)

        perfs       = get_performances(date_str, nr, nc, num)
        time.sleep(0.3)
        cote_veille = get_cote_veille(date_veille, nom, nr, nc)
        time.sleep(0.3)

        nom_up  = nom.upper().strip()
        nb_cit  = citations.get(nom_up, 0)
        pond    = citations_pond.get(nom_up, 0)
        pct_cit = round((nb_cit / nb_sources * 100) if nb_sources > 0 else 0, 1)
        src_p   = [s for s in sources_par_ch.get(nom_up, []) if s in SOURCES_PREMIUM]

        # Initialisation
        est_deferre = False

        # Scores individuels
        s_proprio  = get_stats_proprietaire(str(proprietaire), hippodrome) if str(proprietaire) else 50.0
        s_joc_glob = score_jockey_global(str(jockey), partants_actifs)
        s_entr     = score_entraineur_global(str(entraineur), partants_actifs)
        s_trio     = score_trio_proprietaire_jockey_entraineur(s_proprio, s_joc_glob, s_entr)
        s_joc_hippo = score_jockey_sur_hippodrome(perfs, str(jockey), hippodrome)
        s_rk, rk_best = score_record_kilometrique(perfs, distance, partants_actifs) if trot else (0.0, 0.0)
        musique_ch = partant.get('musique') or ''
        s_fautes   = score_fautes_trot(perfs, musique=musique_ch) if trot else 0.0

        s = {
            "pronostics":   score_pronostics_pond(nom, citations_pond, poids_max),
            "outsider":     score_outsider(nom, outsiders, cote_jour),
            "forme_r":      score_forme_recente(perfs),
            "forme_f":      score_forme_fraiche(perfs),
            "rk":           s_rk,
            "distance":     score_distance(perfs, distance, type_course),
            "terrain":      score_terrain(perfs, terrain),
            "mouvement":    score_mouvement_cote(cote_veille, cote_jour),
            "trio_pje":     s_trio,
            "jockey_hippo": s_joc_hippo,
            "progression":  score_progression(perfs),
            "hippodrome":   score_hippodrome_cheval(perfs, hippodrome),
            "corde":        score_corde(place_corde, nb_partants, discipline, distance),
            "fautes":       0.0,  # Gere separement comme malus
        }
        s_total = calculer_score_total(s, discipline, type_course)

        # Malus fautes trot (hors poids normaux)
        s_total = max(0, s_total + s_fautes)

        # Bonus age saison
        s_total = min(100, s_total + bonus_age_saison(partant))

        # Bonus deferre : cheval sans fers = plus rapide (+4 pts)
        est_deferre = nom_up in deferres
        if est_deferre:
            s_total = min(100, s_total + 4)
            log.info(f"  *** DEFERRE: {nom} +4 pts ***")

        # Value bet : minimum 3 sources
        value_bet = (nb_cit >= 3 and pct_cit >= 40
                     and cote_jour >= (100 / max(pct_cit, 1)) * 1.4)

        # Outsider surprise identifie
        est_outsider_surprise = nom_up in outsiders

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
            "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
            "discipline": discipline, "type_course": type_str,
            "type_course_details": type_course, "distance_m": distance,
            "nb_partants": nb_partants, "num_partant": num, "nom_cheval": nom,
            "age": age, "place_corde": place_corde, "poids_porte": poids,
            "deferre": est_deferre, "value_bet": value_bet,
            "est_outsider_surprise": est_outsider_surprise,
            "consensus_fort": len(src_p) >= 3,
            "sources_premium_citees": src_p, "rk_meilleur": round(rk_best, 2),
            "jockey": jockey, "entraineur": str(entraineur),
            "proprietaire": str(proprietaire),
            "cote_veille": round(cote_veille, 2) if cote_veille else "",
            "cote_jour": round(cote_jour, 2), "variation_cote_%": var_cote,
            "nb_pronostics": nb_cit, "nb_pronostics_pondere": round(pond, 1),
            "pct_pronostics": pct_cit, "nb_sources_total": nb_sources,
            "score_pronostics": round(s["pronostics"], 1),
            "score_outsider": round(s["outsider"], 1),
            "score_forme": round(s["forme_r"], 1),
            "score_forme_fraiche": round(s["forme_f"], 1),
            "score_rk": round(s_rk, 1),
            "score_fautes": round(s_fautes, 1),
            "score_distance": round(s["distance"], 1),
            "score_terrain": round(s["terrain"], 1),
            "score_mouvement": round(s["mouvement"], 1),
            "score_trio_pje": round(s_trio, 1),
            "score_jockey_hippo": round(s_joc_hippo, 1),
            "score_progression": round(s["progression"], 1),
            "score_hippodrome": round(s["hippodrome"], 1),
            "score_corde": round(s["corde"], 1),
            "score_total": round(s_total, 1),
            "presse_resume": "", "presse_sentiment": 50.0,
            "presse_sources": "", "presse_signaux": "",
        })
        time.sleep(0.5)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)
    resultats = normaliser_scores(resultats)
    resultats = appliquer_filtre_et_inversion(resultats, nb_sources, type_course)

    consensus_fort = any(r.get("consensus_fort") for r in resultats[:2])

    # Log
    log.info(f"\n{'─'*70}")
    log.info(f"  [{type_str}] [{type_course}] {libelle} | {distance}m")
    log.info(f"  {'#':<3} {'Cheval':<22} {'Cote':>6} {'Trio':>6} {'Faute':>6} {'Score':>7}")
    for i, r in enumerate(resultats[:5], 1):
        out = " OUT" if r.get("est_outsider_surprise") else ""
        log.info(
            f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} "
            f"{r['score_trio_pje']:>6.1f} {r['score_fautes']:>6.1f} "
            f"{r['score_total']:>7.1f}{out}"
        )

    return {
        "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
        "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
        "discipline": discipline, "type_course": type_str,
        "type_course_details": type_course,
        "nb_sources_total": nb_sources, "consensus_fort": consensus_fort,
        "top5": resultats[:5], "top2": resultats[:2], "tous_resultats": resultats,
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
        "Analyse du matin (cotes d ouverture)"
        if today.hour < 10
        else "Analyse de mi-journee (cotes fraiches + pronostics)"
    )
    activer_presse = bool(ANTHROPIC_KEY)

    log.info("=" * 70)
    log.info(f"  PMU SCORER v13 - {date_aff} - {heure_run}")
    log.info(f"  Trio proprio+jockey+entraineur | Outsider surprise | Fautes trot")
    log.info(f"  Pronostics 15% | Top5 affiche | Delai 60s")
    log.info(f"  Pronostics: {'OK' if activer_presse else 'desactive'}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer v13 demarre - {date_aff} {heure_run}\n{run_label}...")

    programme = get_programme(date_str)
    if not programme:
        msg = f"ERREUR programme {date_aff}"
        log.error(msg); telegram_send(msg); return

    reunions = programme.get("programme", {}).get("reunions", [])
    if not reunions:
        msg = f"ERREUR aucune reunion {date_aff}"
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
                    hippodrome=hippodrome,
                    terrain=str(terrain).upper() if terrain else "",
                    activer_presse=activer_presse,
                )
                if res and res.get("tous_resultats"):
                    tous_csv.extend(res["tous_resultats"])
                    (courses_trot if res["type_course"] == "TROT" else courses_galop).append(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    log.info(f"\nGALOP: {len(courses_galop)} | TROT: {len(courses_trot)}")

    if tous_csv:
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion","course","heure","hippodrome","terrain","libelle",
            "discipline","type_course","type_course_details","distance_m",
            "nb_partants","num_partant","nom_cheval","age","place_corde","poids_porte",
            "deferre","value_bet","est_outsider_surprise","consensus_fort","rk_meilleur",
            "jockey","entraineur","proprietaire","cote_veille","cote_jour","variation_cote_%",
            "nb_pronostics","nb_pronostics_pondere","pct_pronostics","nb_sources_total",
            "score_pronostics","score_outsider","score_forme","score_forme_fraiche",
            "score_rk","score_fautes","score_distance","score_terrain","score_mouvement",
            "score_trio_pje","score_jockey_hippo","score_progression",
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
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v13 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
