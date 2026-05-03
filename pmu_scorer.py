"""
=============================================================
  PMU RACING SCORER v7 - France uniquement
=============================================================
  Nouveautes v7 :
    - Agregation pronostics PMU officiels + Claude web search
    - Score "value betting" (consensus vs cote reelle)
    - Affichage TOP 2 par course avec probabilites
    - Format : "X sources donnent ce cheval gagnant (X%)"
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

PAYS_AUTORISES = {"FRA", "FRANCE"}

DISCIPLINES = {
    "PLAT", "HAIES", "STEEPLE",
    "TROT_ATTELE", "TROT_MONTE",
    "ATTELE", "MONTE", "GALOP",
}

# Sources de pronostics interrogees via Claude
SOURCES_PRONOSTICS = [
    "Paris-Turf", "Equidia", "Geny Courses", "Turf Magazine",
    "At Racing", "Teleturf", "Le Trot", "Jeu Gagnant",
]

# Poids du score final (total = 100)
W_FORME      = 20
W_DISTANCE   = 15
W_COTE       = 10
W_MOUVEMENT  = 10
W_JOCKEY     = 8
W_ECURIE     = 5
W_CORDE      = 7
W_POIDS      = 5
W_HANDICAP   = 3
W_PRONOSTICS = 17   # Nouveau : consensus des pronostics externes

GRANDES_ECURIES = {
    "WERTHEIMER ET FRERE":     85,
    "AGA KHAN":                82,
    "AGA KHAN STUDS":          82,
    "ROTHSCHILD":              80,
    "NIARCHOS":                78,
    "AL SHAQAB RACING":        80,
    "WATHNAN RACING":          80,
    "GODOLPHIN":               83,
    "COOLMORE":                82,
    "JUDDMONTE":               81,
    "FLAXMAN STABLES":         79,
    "HARAS DE BOUQUETOT":      72,
    "ECURIE ANTONIO CARO":     70,
    "GESTUT AMMERLAND":        68,
    "HARAS D'ETREHAM":         70,
    "HARAS DE LA GOURDAINE":   68,
    "SAINT CLOUD RACING":      65,
    "FRANCOIS ROHAUT":         70,
    "HARAS DE CLAIREFONTAINE": 72,
    "ECURIE MESSICA":          68,
    "G.AUGUSTIN-NORMAND":      75,
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
#  1. TELEGRAM
# ──────────────────────────────────────────────
def telegram_send(texte: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram non configure.")
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
                log.warning(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
                succes = False
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Erreur Telegram: {e}")
            succes = False
    return succes


def formater_message_telegram(resultats_par_course: list, date_aff: str, run_label: str) -> str:
    """
    Format v7 :
    R1 C4 | 13h15 | Plat | PRIX DU PALAIS BOURBON
    ------------------------------------------------
    1. AURA (cote 5.0) - Score: 62.3%
       12 sources sur 15 donnent ce cheval gagnant (80%)
       Corde 7/15 | Poids 55kg | [cote -15%]
       Presse [+]: Forme excellente, entraineur confiant
       Signaux: deferre premiere fois

    2. TROPHANE (cote 9.9) - Score: 54.1%
       6 sources sur 15 donnent ce cheval gagnant (40%)
       Corde 10/15 | Poids 58.5kg
    """
    lignes = [
        f"PMU France - Pronostics du {date_aff}",
        run_label,
        "=" * 38,
    ]

    for course in resultats_par_course:
        if not course.get("top2"):
            continue

        disc     = course.get("discipline", "").replace("_", " ")
        heure_ts = course.get("heure", 0)
        libelle  = course.get("libelle", "")
        reunion  = course.get("reunion", "")
        nc       = course.get("course", "")
        nb_sources_total = course.get("nb_sources_total", 0)

        heure_str = ""
        if heure_ts and isinstance(heure_ts, (int, float)) and heure_ts > 0:
            try:
                heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
            except Exception:
                pass

        lignes.append("")
        lignes.append(f"{reunion} {nc} | {heure_str} | {disc}")
        if libelle:
            lignes.append(f"{libelle[:50]}")
        lignes.append("-" * 35)

        for rang, cheval in enumerate(course["top2"], 1):
            nom        = cheval.get("nom_cheval", "?")
            cote       = cheval.get("cote_jour", 0)
            score      = cheval.get("score_total", 0)
            nb_prono   = cheval.get("nb_pronostics", 0)
            pct_prono  = cheval.get("pct_pronostics", 0)
            corde      = cheval.get("place_corde", 0)
            nb_part    = cheval.get("nb_partants", 0)
            poids      = cheval.get("poids_porte", 0)
            jockey     = cheval.get("jockey", "?")
            deferre    = cheval.get("deferre", False)

            # Mouvement de cote
            mvt = ""
            val = cheval.get("variation_cote_%", "")
            if val != "" and isinstance(val, (int, float)):
                if val <= -25:
                    mvt = f" [CHUTE COTE {val:+.0f}%!!!]"
                elif val <= -10:
                    mvt = f" [cote {val:+.0f}%]"
                elif val >= 15:
                    mvt = f" [cote +{val:.0f}%]"

            # Infos corde et poids
            corde_info = f"Corde {corde}/{nb_part}" if corde and nb_part else ""
            avantage   = " (AVANTAGE)" if corde and corde <= 3 else ""
            poids_info = f"Poids {poids/10:.1f}kg" if poids else ""

            # Pronostics
            if nb_sources_total > 0 and nb_prono > 0:
                prono_line = f"{nb_prono} source(s) sur {nb_sources_total} donnent ce cheval gagnant ({pct_prono:.0f}%)"
            else:
                prono_line = ""

            # Presse
            resume    = cheval.get("presse_resume", "")
            signaux   = cheval.get("presse_signaux", "")
            sentiment = cheval.get("presse_sentiment", 50)

            # Affichage
            prefixe = ">> " if rang == 1 else "   "
            lignes.append(f"{prefixe}{rang}. {nom} (cote {cote:.1f}){mvt}")
            lignes.append(f"   Score global: {score:.1f}%")
            if prono_line:
                lignes.append(f"   {prono_line}")

            details = []
            if corde_info:
                details.append(f"{corde_info}{avantage}")
            if poids_info:
                details.append(poids_info)
            if details:
                lignes.append(f"   {' | '.join(details)}")

            lignes.append(f"   Jockey: {jockey}")

            if deferre:
                lignes.append(f"   *** DEFERRE aujourd'hui ***")
            if resume and "Aucune" not in resume and len(resume) > 5:
                ind = "[+]" if sentiment >= 65 else ("[-]" if sentiment <= 35 else "[=]")
                lignes.append(f"   Presse {ind}: {resume[:100]}")
            if signaux:
                lignes.append(f"   Signaux: {signaux[:80]}")

    lignes.append("")
    lignes.append("=" * 38)
    lignes.append("Outil statistique - Jouer responsable.")
    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. APPELS API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/7.0)",
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
        p = data.get("participants", [])
        if p:
            return p
    data2 = api_get(f"/programme/{date_str}/R{nr}/C{nc}/participants?combinePlacesEtCouplees=true")
    if data2 and isinstance(data2, dict):
        return data2.get("participants", [])
    return []


def get_pronostics_pmu(date_str: str, nr, nc) -> list:
    """
    Recupere les pronostics officiels PMU pour une course.
    Retourne une liste de numeros de partants.
    """
    data = api_get(f"/programme/{date_str}/R{nr}/C{nc}/pronostics")
    if not data:
        return []
    try:
        if isinstance(data, list):
            return [str(p.get("numPmu") or p.get("numero") or "") for p in data if p]
        elif isinstance(data, dict):
            pronostics = data.get("pronostics", []) or data.get("partants", [])
            return [str(p.get("numPmu") or p.get("numero") or "") for p in pronostics if p]
    except Exception:
        pass
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
def get_pronostics_externes(
    noms_chevaux: list,
    libelle_course: str,
    date_affichage: str,
    hippodrome: str,
) -> dict:
    """
    Interroge Claude pour collecter les pronostics de sources externes
    (Paris-Turf, Equidia, Geny, etc.) pour une course.

    Retourne un dict {nom_cheval: nb_citations} + nb_sources_total
    """
    if not ANTHROPIC_KEY or not noms_chevaux:
        return {"citations": {}, "nb_sources": 0}

    noms_str = ", ".join(noms_chevaux[:16])  # Max 16 chevaux
    sources_str = ", ".join(SOURCES_PRONOSTICS)

    prompt = f"""Tu es un expert en courses hippiques francaises.
Nous analysons la course "{libelle_course}" a {hippodrome} le {date_affichage}.

Les partants sont : {noms_str}

Recherche sur le web les PRONOSTICS de ces sources pour cette course :
{sources_str}

Pour chaque source que tu trouves, note quel(s) cheval/chevaux elle donne comme favoris ou selectionnes.

Reponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "nb_sources_trouvees": 8,
  "citations": {{
    "NOM_CHEVAL_1": 6,
    "NOM_CHEVAL_2": 4,
    "NOM_CHEVAL_3": 2
  }},
  "sources_consultees": ["Paris-Turf", "Equidia", "Geny Courses"],
  "resume": "Description courte des tendances des pronostics"
}}

- nb_sources_trouvees : nombre de sources qui ont publie des pronostics
- citations : nombre de fois que chaque cheval est cite comme favori/selectionne
- N'inclure que les chevaux effectivement cites
- Si aucune source trouvee : {{"nb_sources_trouvees": 0, "citations": {{}}, "sources_consultees": [], "resume": "Aucun pronostic trouve"}}"""

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
                "max_tokens": 600,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if r.status_code != 200:
            return {"citations": {}, "nb_sources": 0}

        data  = r.json()
        texte = " ".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        parsed = json.loads(texte.replace("```json", "").replace("```", "").strip())

        citations_raw = parsed.get("citations", {})
        # Normaliser les noms en majuscules
        citations = {}
        for nom, nb in citations_raw.items():
            citations[nom.upper().strip()] = int(nb)

        nb_sources = int(parsed.get("nb_sources_trouvees", 0))
        log.info(f"  Pronostics externes: {nb_sources} sources, {len(citations)} chevaux cites")
        log.info(f"  Sources: {parsed.get('sources_consultees', [])}")

        return {
            "citations":  citations,
            "nb_sources": nb_sources,
            "resume":     parsed.get("resume", ""),
            "sources":    parsed.get("sources_consultees", []),
        }

    except Exception as e:
        log.warning(f"Erreur pronostics externes: {e}")
        return {"citations": {}, "nb_sources": 0}


def get_signal_presse_et_fers(nom_cheval: str, date_affichage: str) -> dict:
    """Signal presse + detection fers/deferre via Claude."""
    if not ANTHROPIC_KEY:
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}

    prompt = f"""Tu es un expert en courses hippiques francaises.
Recherche sur le web les informations du {date_affichage} sur le cheval "{nom_cheval}"
(Paris-Turf, Equidia, At Racing, Turf Magazine, Google News turf).

Cherche aussi si ce cheval court DEFERRE (sans fers) aujourd'hui.

Reponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "resume": "2-3 phrases factuelles",
  "sentiment": 70,
  "sources": ["Paris-Turf"],
  "signaux": ["entraineur confiant"],
  "deferre": false
}}

sentiment : 0-30 mauvais, 50 neutre, 70-100 tres positif.
deferre : true si le cheval court deferre aujourd'hui.
Si rien trouve : {{"resume": "Aucune information trouvee", "sentiment": 50, "sources": [], "signaux": [], "deferre": false}}"""

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
            return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}

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
            "deferre":   bool(parsed.get("deferre", False)),
        }
    except Exception as e:
        log.warning(f"Erreur Claude API '{nom_cheval}': {e}")
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}


# ──────────────────────────────────────────────
#  4. SCORES STATISTIQUES
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
    cotes_valides = [c for c in cotes_course if c > 0]
    if not cotes_valides:
        return 50.0
    mediane = sorted(cotes_valides)[len(cotes_valides) // 2]
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


def score_corde(place_corde: int, nb_partants: int, discipline: str, distance: int) -> float:
    if not place_corde or not nb_partants or nb_partants <= 1:
        return 50.0
    score_base = ((nb_partants - place_corde) / (nb_partants - 1)) * 100
    disc = discipline.upper()
    if disc in ("TROT_ATTELE", "ATTELE"):
        facteur = 1.0 if distance <= 2200 else (0.8 if distance <= 2750 else 0.6)
    elif disc in ("TROT_MONTE", "MONTE"):
        facteur = 0.7
    elif disc in ("PLAT", "GALOP"):
        facteur = 0.5
    elif disc in ("HAIES", "STEEPLE"):
        facteur = 0.3
    else:
        facteur = 0.5
    return min(100, max(0, 50 + (score_base - 50) * facteur))


def score_poids(poids: int, poids_course: list) -> float:
    if not poids or not poids_course:
        return 50.0
    poids_valides = [p for p in poids_course if p > 0]
    if not poids_valides or len(poids_valides) < 2:
        return 50.0
    poids_min = min(poids_valides)
    poids_max = max(poids_valides)
    if poids_max == poids_min:
        return 50.0
    return ((poids_max - poids) / (poids_max - poids_min)) * 100


def score_handicap(handicap_val: float, handicaps_course: list) -> float:
    if not handicap_val or not handicaps_course:
        return 50.0
    h_valides = [h for h in handicaps_course if h > 0]
    if not h_valides or len(h_valides) < 2:
        return 50.0
    h_min = min(h_valides)
    h_max = max(h_valides)
    if h_max == h_min:
        return 50.0
    return ((h_max - handicap_val) / (h_max - h_min)) * 100


def score_pronostics(nom_cheval: str, citations: dict, nb_sources: int) -> float:
    """
    Score base sur le nombre de sources externes qui citent ce cheval.
    0 citations = 0 pts, cite par toutes les sources = 100 pts.
    """
    if not citations or nb_sources == 0:
        return 0.0
    nb_citations = citations.get(nom_cheval.upper().strip(), 0)
    if nb_citations == 0:
        return 0.0
    return min(100, (nb_citations / nb_sources) * 100)


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


def calculer_score_total(s) -> float:
    """s = dict des scores composants."""
    return (
        s["forme"]      * W_FORME      / 100
        + s["distance"] * W_DISTANCE   / 100
        + s["cote"]     * W_COTE       / 100
        + s["mvt"]      * W_MOUVEMENT  / 100
        + s["jockey"]   * W_JOCKEY     / 100
        + s["ecurie"]   * W_ECURIE     / 100
        + s["corde"]    * W_CORDE      / 100
        + s["poids"]    * W_POIDS      / 100
        + s["handicap"] * W_HANDICAP   / 100
        + s["pronostics"] * W_PRONOSTICS / 100
    )


def normaliser_scores(resultats: list) -> list:
    """
    Convertit les scores bruts en probabilites (%) qui s'additionnent a 100%.
    Utilise une normalisation softmax simplifiee.
    """
    if not resultats:
        return resultats

    scores = [r["score_total"] for r in resultats]
    total  = sum(scores)

    if total <= 0:
        prob_uniforme = 100.0 / len(resultats)
        for r in resultats:
            r["probabilite"] = round(prob_uniforme, 1)
    else:
        for r in resultats:
            r["probabilite"] = round((r["score_total"] / total) * 100, 1)

    return resultats


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
    hippodrome: str = "",
    activer_presse: bool = True,
) -> dict:
    """
    Retourne un dict avec :
    - top2 : les 2 meilleurs chevaux avec tous leurs scores
    - tous_resultats : tous les chevaux (pour CSV)
    - meta : infos de la course
    """
    discipline = info_course.get("discipline", "")
    distance   = info_course.get("distance", 0)
    libelle    = info_course.get("libelle", f"R{nr} C{nc}")
    heure      = info_course.get("heureDepart", "")

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants pour R{nr} C{nc}")
        return {}

    partants_actifs  = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    nb_partants      = len(partants_actifs)
    cotes_course     = [extraire_cote(p) for p in partants_actifs if extraire_cote(p) > 0]
    poids_course     = [p.get("handicapPoids", 0) for p in partants_actifs if p.get("handicapPoids")]
    handicaps_course = [p.get("handicapValeur", 0) for p in partants_actifs if p.get("handicapValeur")]

    log.info(f"  -> {nb_partants} partants actifs")

    # Pronostics PMU officiels
    pronostics_pmu = get_pronostics_pmu(date_str, nr, nc)
    time.sleep(0.5)

    # Pronostics externes via Claude (1 appel par course)
    noms_actifs = [p.get("nom", "") for p in partants_actifs if p.get("nom")]
    pronostics_ext = {"citations": {}, "nb_sources": 0}
    if activer_presse and ANTHROPIC_KEY:
        pronostics_ext = get_pronostics_externes(noms_actifs, libelle, date_aff, hippodrome)
        time.sleep(2)

    # Fusion pronostics PMU + externes
    citations_fusionnees = dict(pronostics_ext.get("citations", {}))
    nb_sources_total = pronostics_ext.get("nb_sources", 0)

    # Ajouter les pronostics PMU officiels (comptes comme 1 source supplementaire)
    if pronostics_pmu:
        nb_sources_total += 1
        for num_str in pronostics_pmu:
            for partant in partants_actifs:
                if str(partant.get("numPmu") or "") == num_str:
                    nom_upper = partant.get("nom", "").upper()
                    citations_fusionnees[nom_upper] = citations_fusionnees.get(nom_upper, 0) + 1

    log.info(f"  Sources totales: {nb_sources_total} | Citations: {citations_fusionnees}")

    # Calcul des scores pour chaque partant
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

        place_corde  = int(partant.get("placeCorde") or 0)
        poids        = int(partant.get("handicapPoids") or 0)
        handicap_val = float(partant.get("handicapValeur") or 0)
        oeilleres    = partant.get("oeilleres") or "SANS_OEILLERES"
        cote_jour    = extraire_cote(partant)

        perfs       = get_performances(date_str, nr, nc, num)
        time.sleep(0.3)
        cote_veille = get_cote_veille(date_veille, nom, nr, nc)
        time.sleep(0.3)

        # Nombre et % de citations dans les pronostics
        nb_cit  = citations_fusionnees.get(nom.upper().strip(), 0)
        pct_cit = round((nb_cit / nb_sources_total * 100) if nb_sources_total > 0 else 0, 1)

        s = {
            "forme":       score_forme(perfs),
            "distance":    score_distance(perfs, distance),
            "cote":        score_cote_statique(cote_jour, cotes_course),
            "mvt":         score_mouvement_cote(cote_veille, cote_jour),
            "jockey":      score_jockey(str(jockey), partants_actifs),
            "ecurie":      score_ecurie(str(proprietaire), str(entraineur), str(jockey), partants_actifs),
            "corde":       score_corde(place_corde, nb_partants, discipline, distance),
            "poids":       score_poids(poids, poids_course),
            "handicap":    score_handicap(handicap_val, handicaps_course),
            "pronostics":  score_pronostics(nom, citations_fusionnees, nb_sources_total),
        }
        s_total = calculer_score_total(s)

        # Bonus oeilleres
        if oeilleres == "OEILLERES_CLASSIQUE":
            s_total = max(0, s_total - 1.5)
        elif oeilleres == "OEILLERES_AUSTRALIENNES":
            s_total = max(0, s_total - 2.5)

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion":           f"R{nr}",
            "course":            f"C{nc}",
            "heure":             heure,
            "hippodrome":        hippodrome,
            "libelle":           libelle,
            "discipline":        discipline,
            "distance_m":        distance,
            "nb_partants":       nb_partants,
            "num_partant":       num,
            "nom_cheval":        nom,
            "place_corde":       place_corde,
            "poids_porte":       poids,
            "handicap_valeur":   handicap_val,
            "oeilleres":         oeilleres,
            "deferre":           False,
            "jockey":            jockey,
            "entraineur":        entraineur,
            "proprietaire":      proprietaire,
            "cote_veille":       round(cote_veille, 2) if cote_veille else "",
            "cote_jour":         round(cote_jour, 2),
            "variation_cote_%":  var_cote,
            "nb_pronostics":     nb_cit,
            "pct_pronostics":    pct_cit,
            "nb_sources_total":  nb_sources_total,
            "score_forme":       round(s["forme"], 1),
            "score_distance":    round(s["distance"], 1),
            "score_cote":        round(s["cote"], 1),
            "score_mouvement":   round(s["mvt"], 1),
            "score_jockey":      round(s["jockey"], 1),
            "score_ecurie":      round(s["ecurie"], 1),
            "score_corde":       round(s["corde"], 1),
            "score_poids":       round(s["poids"], 1),
            "score_handicap":    round(s["handicap"], 1),
            "score_pronostics":  round(s["pronostics"], 1),
            "score_total":       round(s_total, 1),
            "presse_resume":     "",
            "presse_sentiment":  50.0,
            "presse_sources":    "",
            "presse_signaux":    "",
        })
        time.sleep(0.5)

    # Trier par score
    resultats.sort(key=lambda x: x["score_total"], reverse=True)

    # Normalisation en probabilites
    resultats = normaliser_scores(resultats)

    # Signal presse uniquement pour les 2 premiers (economie de tokens)
    if activer_presse and ANTHROPIC_KEY:
        for r in resultats[:2]:
            presse = get_signal_presse_et_fers(r["nom_cheval"], date_aff)
            r["presse_resume"]    = presse.get("resume", "")
            r["presse_sentiment"] = presse.get("sentiment", 50.0)
            r["presse_sources"]   = ", ".join(presse.get("sources", []))
            r["presse_signaux"]   = ", ".join(presse.get("signaux", []))
            r["deferre"]          = presse.get("deferre", False)
            if presse.get("deferre"):
                r["score_total"] = min(100, r["score_total"] + 3)
            time.sleep(1)

    # Log console
    log.info(f"\n{'─'*70}")
    log.info(f"  {libelle} - {discipline} - {distance}m")
    log.info(f"  {'#':<3} {'Cheval':<22} {'Cote':>6} {'Pronostics':>12} {'Prob':>6} {'Score':>7}")
    for i, r in enumerate(resultats[:4], 1):
        flag = " *" if i == 1 else ""
        log.info(
            f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} "
            f"{r['nb_pronostics']:>5}/{r['nb_sources_total']:<5} "
            f"{r['probabilite']:>5.1f}% {r['score_total']:>7.1f}{flag}"
        )

    return {
        "reunion":         f"R{nr}",
        "course":          f"C{nc}",
        "heure":           heure,
        "hippodrome":      hippodrome,
        "libelle":         libelle,
        "discipline":      discipline,
        "nb_sources_total": nb_sources_total,
        "top2":            resultats[:2],
        "tous_resultats":  resultats,
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
    log.info(f"  PMU SCORER v7 - France - {date_aff} - {heure_run}")
    log.info(f"  Pronostics/presse : {'OK active' if activer_presse else 'desactive'}")
    log.info(f"  Telegram          : {'OK configure' if TELEGRAM_TOKEN else 'desactive'}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer v7 demarre - {date_aff} {heure_run}\n{run_label}...")

    programme = get_programme(date_str)
    if not programme:
        msg = f"ERREUR - impossible de recuperer le programme du {date_aff}"
        log.error(msg)
        telegram_send(msg)
        return

    reunions = programme.get("programme", {}).get("reunions", [])
    if not reunions:
        msg = f"ERREUR - aucune reunion trouvee pour le {date_aff}"
        log.error(msg)
        telegram_send(msg)
        return

    log.info(f"{len(reunions)} reunions au total.")

    tous_resultats_csv = []
    resultats_par_course = []
    reunions_france = 0

    for reunion in reunions:
        pays = reunion.get("pays", {})
        code_pays = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code_pays not in PAYS_AUTORISES:
            continue

        reunions_france += 1
        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        courses    = reunion.get("courses", [])
        log.info(f"\n> R{nr} - {hippodrome} ({len(courses)} courses)")

        for course in courses:
            nc         = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            discipline = course.get("discipline", "")

            if discipline not in DISCIPLINES:
                continue

            try:
                res = analyser_course(
                    date_str, date_veille, date_aff,
                    nr, nc, course,
                    hippodrome=hippodrome,
                    activer_presse=activer_presse,
                )
                if res and res.get("tous_resultats"):
                    tous_resultats_csv.extend(res["tous_resultats"])
                    resultats_par_course.append(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    log.info(f"\n{reunions_france} reunions francaises analysees.")

    if tous_resultats_csv:
        # Export CSV complet
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion", "course", "heure", "hippodrome", "libelle", "discipline", "distance_m",
            "nb_partants", "num_partant", "nom_cheval", "place_corde", "poids_porte",
            "handicap_valeur", "oeilleres", "deferre", "jockey", "entraineur", "proprietaire",
            "cote_veille", "cote_jour", "variation_cote_%",
            "nb_pronostics", "pct_pronostics", "nb_sources_total",
            "score_forme", "score_distance", "score_cote", "score_mouvement",
            "score_jockey", "score_ecurie", "score_corde", "score_poids",
            "score_handicap", "score_pronostics", "score_total",
            "presse_resume", "presse_sentiment", "presse_sources", "presse_signaux",
        ]
        with open(nom_fichier, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tous_resultats_csv)
        log.info(f"CSV exporte : {nom_fichier}")

        # Envoi Telegram
        message = formater_message_telegram(resultats_par_course, date_aff, run_label)
        if telegram_send(message):
            log.info("Message Telegram envoye.")
        else:
            log.warning("Envoi Telegram echoue.")
    else:
        log.warning("Aucun resultat France trouve.")
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat France trouve.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v7 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
