"""
=============================================================
  PMU RACING SCORER v8 - France uniquement
=============================================================
  Nouveautes v8 :
    - Etat du terrain (nouveau critere)
    - Historique sur l'hippodrome
    - Forme fraiche (30 derniers jours)
    - Value betting : cherche les chevaux sous-cotes
    - Poids revus : pronostics externes = 25pts
    - Sauvegarde CSV dans le depot Git
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

SOURCES_PRONOSTICS = [
    "Paris-Turf", "Equidia", "Geny Courses", "Turf Magazine",
    "At Racing", "Teleturf", "Le Trot", "Jeu Gagnant",
    "Les Turfistes", "Pronostics-courses.fr", "Cheval-FR",
    "Turf-fr.com", "Mes-pronostics.com", "Zone-Turf",
]

# ── Poids du score final (total = 100) ──────────
W_FORME_RECENTE  = 15   # Forme globale
W_FORME_FRAICHE  = 7    # NOUVEAU : courses des 30 derniers jours
W_DISTANCE       = 10   # Adequation distance
W_TERRAIN        = 8    # NOUVEAU : etat du terrain
W_HIPPODROME     = 5    # NOUVEAU : historique sur cet hippodrome
W_PRONOSTICS     = 25   # Consensus sources externes (augmente)
W_MOUVEMENT      = 12   # Mouvement de cote J-1->J
W_COTE           = 5    # Valeur de cote (reduit - evite de suivre les favoris)
W_JOCKEY         = 8    # Stats jockey
W_CORDE          = 5    # Place a la corde

# Total = 100
assert W_FORME_RECENTE + W_FORME_FRAICHE + W_DISTANCE + W_TERRAIN + W_HIPPODROME + \
       W_PRONOSTICS + W_MOUVEMENT + W_COTE + W_JOCKEY + W_CORDE == 100, "Total != 100"

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
    "HARAS D'ETREHAM":         70,
    "HARAS DE LA GOURDAINE":   68,
    "SAINT CLOUD RACING":      65,
    "FRANCOIS ROHAUT":         70,
    "HARAS DE CLAIREFONTAINE": 72,
    "G.AUGUSTIN-NORMAND":      75,
}

# Compatibilite terrain : bon pour chaque type
TERRAIN_COMPAT = {
    "BON":         {"BON": 100, "BON_SOUPLE": 80, "SOUPLE": 50, "LOURD": 20, "TRES_LOURD": 0},
    "BON_SOUPLE":  {"BON": 80, "BON_SOUPLE": 100, "SOUPLE": 80, "LOURD": 40, "TRES_LOURD": 20},
    "SOUPLE":      {"BON": 50, "BON_SOUPLE": 80, "SOUPLE": 100, "LOURD": 80, "TRES_LOURD": 60},
    "LOURD":       {"BON": 20, "BON_SOUPLE": 40, "SOUPLE": 80, "LOURD": 100, "TRES_LOURD": 80},
    "TRES_LOURD":  {"BON": 0,  "BON_SOUPLE": 20, "SOUPLE": 60, "LOURD": 80,  "TRES_LOURD": 100},
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
        terrain  = course.get("terrain", "")
        nb_src   = course.get("nb_sources_total", 0)

        heure_str = ""
        if heure_ts and isinstance(heure_ts, (int, float)) and heure_ts > 0:
            try:
                heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
            except Exception:
                pass

        terrain_str = f" | Terrain: {terrain}" if terrain else ""

        lignes.append("")
        lignes.append(f"{reunion} {nc} | {heure_str} | {disc}{terrain_str}")
        if libelle:
            lignes.append(f"{libelle[:50]}")
        lignes.append("-" * 35)

        for rang, cheval in enumerate(course["top2"], 1):
            nom       = cheval.get("nom_cheval", "?")
            cote      = cheval.get("cote_jour", 0)
            score     = cheval.get("score_total", 0)
            prob      = cheval.get("probabilite", 0)
            nb_prono  = cheval.get("nb_pronostics", 0)
            pct_prono = cheval.get("pct_pronostics", 0)
            corde     = cheval.get("place_corde", 0)
            nb_part   = cheval.get("nb_partants", 0)
            poids     = cheval.get("poids_porte", 0)
            jockey    = cheval.get("jockey", "?")
            deferre   = cheval.get("deferre", False)
            value     = cheval.get("value_bet", False)

            # Mouvement de cote
            mvt = ""
            val = cheval.get("variation_cote_%", "")
            if val != "" and isinstance(val, (int, float)):
                if val <= -25:
                    mvt = f" [CHUTE {val:+.0f}%!!!]"
                elif val <= -10:
                    mvt = f" [cote {val:+.0f}%]"
                elif val >= 15:
                    mvt = f" [cote +{val:.0f}%]"

            # Value bet
            value_str = " *** VALUE BET ***" if value else ""

            prefixe = ">> " if rang == 1 else "   "
            lignes.append(f"{prefixe}{rang}. {nom} (cote {cote:.1f}){mvt}{value_str}")
            lignes.append(f"   Score: {score:.1f}% | Proba: {prob:.1f}%")

            # Pronostics
            if nb_src > 0:
                lignes.append(f"   {nb_prono} source(s) sur {nb_src} donnent ce cheval gagnant ({pct_prono:.0f}%)")
            else:
                lignes.append(f"   Pronostics externes: collecte en cours")

            # Corde et poids
            details = []
            if corde and nb_part:
                av = " AVANTAGE" if corde <= 3 else ""
                details.append(f"Corde {corde}/{nb_part}{av}")
            if poids:
                details.append(f"Poids {poids/10:.1f}kg")
            if details:
                lignes.append(f"   {' | '.join(details)}")

            lignes.append(f"   Jockey: {jockey}")

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

    lignes.append("")
    lignes.append("=" * 38)
    lignes.append("Outil statistique - Jouer responsable.")
    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. APPELS API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/8.0)",
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
def get_pronostics_externes(noms_chevaux, libelle_course, date_affichage, hippodrome) -> dict:
    if not ANTHROPIC_KEY or not noms_chevaux:
        return {"citations": {}, "nb_sources": 0}

    noms_str    = ", ".join(noms_chevaux[:16])
    sources_str = ", ".join(SOURCES_PRONOSTICS)

    prompt = f"""Tu es un expert en courses hippiques francaises.
Nous analysons la course "{libelle_course}" a {hippodrome} le {date_affichage}.
Les partants sont : {noms_str}

Recherche sur le web les pronostics de ces sources pour cette course :
{sources_str}

Pour chaque source trouvee, note quel(s) cheval/chevaux elle donne comme favoris ou selectionnes.

Reponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "nb_sources_trouvees": 8,
  "citations": {{
    "NOM_CHEVAL_1": 6,
    "NOM_CHEVAL_2": 4
  }},
  "sources_consultees": ["Paris-Turf", "Equidia"],
  "resume": "Tendance generale des pronostics"
}}

Si aucune source trouvee : {{"nb_sources_trouvees": 0, "citations": {{}}, "sources_consultees": [], "resume": "Aucun pronostic trouve"}}"""

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

        citations = {}
        for nom, nb in parsed.get("citations", {}).items():
            citations[nom.upper().strip()] = int(nb)

        nb_sources = int(parsed.get("nb_sources_trouvees", 0))
        log.info(f"  Pronostics: {nb_sources} sources | {len(citations)} chevaux cites")

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
    if not ANTHROPIC_KEY:
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}

    prompt = f"""Expert courses hippiques. Recherche infos du {date_affichage} sur "{nom_cheval}"
(Paris-Turf, Equidia, At Racing, Turf Magazine). Cherche aussi si deferre aujourd'hui.

JSON uniquement :
{{"resume": "2-3 phrases", "sentiment": 70, "sources": ["Paris-Turf"], "signaux": ["confiant"], "deferre": false}}

sentiment 0-100. deferre true si sans fers. Si rien : {{"resume": "Aucune info", "sentiment": 50, "sources": [], "signaux": [], "deferre": false}}"""

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
        log.warning(f"Erreur Claude '{nom_cheval}': {e}")
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}


# ──────────────────────────────────────────────
#  4. SCORES STATISTIQUES
# ──────────────────────────────────────────────
def score_forme_recente(performances: list, n: int = 5) -> float:
    if not performances:
        return 0.0
    scores = []
    for p in performances[:n]:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 0.0


def score_forme_fraiche(performances: list) -> float:
    """Forme des 30 derniers jours uniquement."""
    if not performances:
        return 50.0
    maintenant = datetime.now().timestamp() * 1000
    trente_jours = 30 * 24 * 3600 * 1000
    recentes = [
        p for p in performances
        if (maintenant - (p.get("date") or 0)) <= trente_jours
        and (p.get("date") or 0) > 0
    ]
    if not recentes:
        return 50.0  # Neutre si pas de course recente
    scores = []
    for p in recentes:
        place = p.get("place") or p.get("ordreArrivee")
        if place and str(place).isdigit():
            scores.append(max(0, 110 - int(place) * 10))
    return sum(scores) / len(scores) if scores else 50.0


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


def score_terrain(performances: list, terrain_actuel: str) -> float:
    """
    Score base sur la compatibilite entre le terrain actuel et
    les terrains sur lesquels le cheval a deja bien performe.
    """
    if not terrain_actuel or not performances:
        return 50.0

    terrain_actuel = terrain_actuel.upper().replace(" ", "_")
    compat = TERRAIN_COMPAT.get(terrain_actuel, {})
    if not compat:
        return 50.0

    scores_terrain = []
    for p in performances:
        terrain_perf = (p.get("terrain") or p.get("etatSol") or "").upper().replace(" ", "_")
        place = p.get("place") or p.get("ordreArrivee")
        if terrain_perf and place and str(place).isdigit():
            score_compat = compat.get(terrain_perf, 50)
            score_place  = max(0, 110 - int(place) * 10)
            scores_terrain.append(score_compat * score_place / 100)

    if not scores_terrain:
        return 50.0
    return min(100, sum(scores_terrain) / len(scores_terrain))


def score_hippodrome(performances: list, hippodrome_actuel: str) -> float:
    """
    Score base sur l'historique du cheval sur cet hippodrome specifique.
    """
    if not hippodrome_actuel or not performances:
        return 50.0

    hippo_upper = hippodrome_actuel.upper()
    courses_hippo = [
        p for p in performances
        if hippo_upper in (p.get("hippodrome") or p.get("lieu") or "").upper()
    ]

    if not courses_hippo:
        return 50.0  # Neutre - jamais couru ici

    victoires = sum(
        1 for p in courses_hippo
        if str(p.get("place") or p.get("ordreArrivee") or 99) == "1"
    )
    places = sum(
        1 for p in courses_hippo
        if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1", "2", "3")
    )

    taux_victoire = victoires / len(courses_hippo)
    taux_place    = places / len(courses_hippo)

    # Score combine victoires + places sur cet hippodrome
    return min(100, (taux_victoire * 60 + taux_place * 40) * 100)


def score_cote_value(cote: float, pct_pronostics: float) -> float:
    """
    VALUE BETTING : cherche les chevaux sous-cotes par rapport
    au consensus des pronostics.
    
    Si beaucoup de sources citent ce cheval mais sa cote est haute
    -> le marche le sous-estime -> valeur !
    """
    if not cote or cote <= 0 or pct_pronostics <= 0:
        return 50.0

    # Cote "attendue" selon les pronostics (si 60% le citent, cote attendue ~2/1)
    cote_attendue = 100 / max(pct_pronostics, 1)

    if cote_attendue <= 0:
        return 50.0

    ratio = cote / cote_attendue
    if ratio >= 2.0:
        return 95.0   # Grosse valeur - cote 2x plus haute que prevu
    elif ratio >= 1.5:
        return 80.0   # Bonne valeur
    elif ratio >= 1.1:
        return 65.0   # Legere valeur
    elif ratio >= 0.9:
        return 50.0   # Neutre - cote coherente
    elif ratio >= 0.7:
        return 35.0   # Favori "pricé" - peu de valeur
    else:
        return 20.0   # Sur-favori - mauvaise valeur


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


def score_pronostics(nom_cheval: str, citations: dict, nb_sources: int) -> float:
    if not citations or nb_sources == 0:
        return 0.0
    nb = citations.get(nom_cheval.upper().strip(), 0)
    return min(100, (nb / nb_sources) * 100) if nb > 0 else 0.0


def calculer_score_total(s: dict) -> float:
    return (
        s["forme_recente"]  * W_FORME_RECENTE  / 100
        + s["forme_fraiche"]* W_FORME_FRAICHE  / 100
        + s["distance"]     * W_DISTANCE       / 100
        + s["terrain"]      * W_TERRAIN        / 100
        + s["hippodrome"]   * W_HIPPODROME     / 100
        + s["pronostics"]   * W_PRONOSTICS     / 100
        + s["mouvement"]    * W_MOUVEMENT      / 100
        + s["cote_value"]   * W_COTE           / 100
        + s["jockey"]       * W_JOCKEY         / 100
        + s["corde"]        * W_CORDE          / 100
    )


def normaliser_scores(resultats: list) -> list:
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


# ──────────────────────────────────────────────
#  5. ANALYSE D'UNE COURSE
# ──────────────────────────────────────────────
def analyser_course(
    date_str, date_veille, date_aff,
    nr, nc, info_course,
    hippodrome="", terrain="",
    activer_presse=True,
) -> dict:

    discipline = info_course.get("discipline", "")
    distance   = info_course.get("distance", 0)
    libelle    = info_course.get("libelle", f"R{nr} C{nc}")
    heure      = info_course.get("heureDepart", "")

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants pour R{nr} C{nc}")
        return {}

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    nb_partants     = len(partants_actifs)
    log.info(f"  -> {nb_partants} partants | terrain: {terrain}")

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
    citations = dict(pronostics_ext.get("citations", {}))
    nb_sources = pronostics_ext.get("nb_sources", 0)

    if pronostics_pmu:
        nb_sources += 1
        for num_str in pronostics_pmu:
            for p in partants_actifs:
                if str(p.get("numPmu") or "") == num_str:
                    nom_up = p.get("nom", "").upper()
                    citations[nom_up] = citations.get(nom_up, 0) + 1

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

        perfs       = get_performances(date_str, nr, nc, num)
        time.sleep(0.3)
        cote_veille = get_cote_veille(date_veille, nom, nr, nc)
        time.sleep(0.3)

        nb_cit  = citations.get(nom.upper().strip(), 0)
        pct_cit = round((nb_cit / nb_sources * 100) if nb_sources > 0 else 0, 1)

        s = {
            "forme_recente":  score_forme_recente(perfs),
            "forme_fraiche":  score_forme_fraiche(perfs),
            "distance":       score_distance(perfs, distance),
            "terrain":        score_terrain(perfs, terrain),
            "hippodrome":     score_hippodrome(perfs, hippodrome),
            "pronostics":     score_pronostics(nom, citations, nb_sources),
            "mouvement":      score_mouvement_cote(cote_veille, cote_jour),
            "cote_value":     score_cote_value(cote_jour, pct_cit),
            "jockey":         score_jockey(str(jockey), partants_actifs),
            "corde":          score_corde(place_corde, nb_partants, discipline, distance),
        }
        s_total = calculer_score_total(s)

        # Bonus/malus oeilleres
        oeilleres = partant.get("oeilleres") or ""
        if "AUSTRALIENNES" in oeilleres:
            s_total = max(0, s_total - 2)
        elif "CLASSIQUE" in oeilleres:
            s_total = max(0, s_total - 1)

        # Value bet flag
        value_bet = (pct_cit >= 40 and cote_jour >= (100 / max(pct_cit, 1)) * 1.4)

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion":           f"R{nr}",
            "course":            f"C{nc}",
            "heure":             heure,
            "hippodrome":        hippodrome,
            "terrain":           terrain,
            "libelle":           libelle,
            "discipline":        discipline,
            "distance_m":        distance,
            "nb_partants":       nb_partants,
            "num_partant":       num,
            "nom_cheval":        nom,
            "place_corde":       place_corde,
            "poids_porte":       poids,
            "oeilleres":         oeilleres,
            "deferre":           False,
            "value_bet":         value_bet,
            "jockey":            jockey,
            "entraineur":        entraineur,
            "proprietaire":      proprietaire,
            "cote_veille":       round(cote_veille, 2) if cote_veille else "",
            "cote_jour":         round(cote_jour, 2),
            "variation_cote_%":  var_cote,
            "nb_pronostics":     nb_cit,
            "pct_pronostics":    pct_cit,
            "nb_sources_total":  nb_sources,
            "score_forme":       round(s["forme_recente"], 1),
            "score_forme_fraiche": round(s["forme_fraiche"], 1),
            "score_distance":    round(s["distance"], 1),
            "score_terrain":     round(s["terrain"], 1),
            "score_hippodrome":  round(s["hippodrome"], 1),
            "score_pronostics":  round(s["pronostics"], 1),
            "score_mouvement":   round(s["mouvement"], 1),
            "score_cote_value":  round(s["cote_value"], 1),
            "score_jockey":      round(s["jockey"], 1),
            "score_corde":       round(s["corde"], 1),
            "score_total":       round(s_total, 1),
            "presse_resume":     "",
            "presse_sentiment":  50.0,
            "presse_sources":    "",
            "presse_signaux":    "",
        })
        time.sleep(0.5)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)
    resultats = normaliser_scores(resultats)

    # Signal presse uniquement pour le top 2
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
    log.info(f"  {libelle} | {discipline} | {distance}m | terrain: {terrain}")
    log.info(f"  {'#':<3} {'Cheval':<22} {'Cote':>6} {'Prono':>8} {'Value':>6} {'Score':>7}")
    for i, r in enumerate(resultats[:4], 1):
        vb = " VALUE" if r["value_bet"] else ""
        log.info(
            f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} "
            f"{r['nb_pronostics']:>4}/{r['nb_sources_total']:<3} "
            f"{r['probabilite']:>5.1f}% {r['score_total']:>7.1f}{vb}"
        )

    return {
        "reunion":          f"R{nr}",
        "course":           f"C{nc}",
        "heure":            heure,
        "hippodrome":       hippodrome,
        "terrain":          terrain,
        "libelle":          libelle,
        "discipline":       discipline,
        "nb_sources_total": nb_sources,
        "top2":             resultats[:2],
        "tous_resultats":   resultats,
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
    log.info(f"  PMU SCORER v8 - France - {date_aff} - {heure_run}")
    log.info(f"  Pronostics/presse : {'OK' if activer_presse else 'desactive'}")
    log.info(f"  Terrain/hippodrome: actif")
    log.info(f"  Value betting     : actif")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer v8 demarre - {date_aff} {heure_run}\n{run_label}...")

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
    tous_resultats_csv   = []
    resultats_par_course = []

    for reunion in reunions:
        pays = reunion.get("pays", {})
        code_pays = pays.get("code", "") if isinstance(pays, dict) else str(pays)
        if code_pays not in PAYS_AUTORISES:
            continue

        nr         = reunion.get("numExterne") or reunion.get("numOfficiel") or reunion.get("numero")
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        courses    = reunion.get("courses", [])

        # Etat du terrain au niveau de la reunion
        terrain_reunion = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain_reunion, dict):
            terrain_reunion = terrain_reunion.get("libelle", "") or terrain_reunion.get("code", "")

        log.info(f"\n> R{nr} - {hippodrome} | terrain: {terrain_reunion} ({len(courses)} courses)")

        for course in courses:
            nc         = course.get("numExterne") or course.get("numOfficiel") or course.get("numero")
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue

            # Terrain peut aussi etre au niveau de la course
            terrain = course.get("terrain") or course.get("etatSol") or terrain_reunion
            if isinstance(terrain, dict):
                terrain = terrain.get("libelle", "") or terrain.get("code", "")

            try:
                res = analyser_course(
                    date_str, date_veille, date_aff,
                    nr, nc, course,
                    hippodrome=hippodrome,
                    terrain=str(terrain).upper() if terrain else "",
                    activer_presse=activer_presse,
                )
                if res and res.get("tous_resultats"):
                    tous_resultats_csv.extend(res["tous_resultats"])
                    resultats_par_course.append(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    if tous_resultats_csv:
        # Sauvegarde CSV dans le depot (accessible pour pmu_results.py)
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion", "course", "heure", "hippodrome", "terrain", "libelle",
            "discipline", "distance_m", "nb_partants", "num_partant", "nom_cheval",
            "place_corde", "poids_porte", "oeilleres", "deferre", "value_bet",
            "jockey", "entraineur", "proprietaire",
            "cote_veille", "cote_jour", "variation_cote_%",
            "nb_pronostics", "pct_pronostics", "nb_sources_total",
            "score_forme", "score_forme_fraiche", "score_distance", "score_terrain",
            "score_hippodrome", "score_pronostics", "score_mouvement", "score_cote_value",
            "score_jockey", "score_corde", "score_total",
            "presse_resume", "presse_sentiment", "presse_sources", "presse_signaux",
        ]
        with open(nom_fichier, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=colonnes, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(tous_resultats_csv)
        log.info(f"CSV exporte : {nom_fichier}")

        message = formater_message_telegram(resultats_par_course, date_aff, run_label)
        if telegram_send(message):
            log.info("Message Telegram envoye.")
        else:
            log.warning("Envoi Telegram echoue.")
    else:
        log.warning("Aucun resultat France trouve.")
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat France trouve.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v8 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
