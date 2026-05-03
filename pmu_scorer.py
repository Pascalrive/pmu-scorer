"""
=============================================================
  PMU RACING SCORER v6 - Galop & Trot - France uniquement
=============================================================
  Criteres de scoring :
    - Forme recente (25 pts)
    - Adequation distance (18 pts)
    - Valeur de cote (12 pts)
    - Mouvement de cote J-1->J (11 pts)
    - Stats jockey (10 pts)
    - Trio ecurie (6 pts)
    - Place a la corde (8 pts)
    - Poids porte (6 pts)
    - Handicap valeur (4 pts)
    - Oeilleres / Fers via Claude web search (bonus/malus)
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

# Poids du score final (total = 100)
W_FORME      = 25
W_DISTANCE   = 18
W_COTE       = 12
W_MOUVEMENT  = 11
W_JOCKEY     = 10
W_ECURIE     = 6
W_CORDE      = 8
W_POIDS      = 6
W_HANDICAP   = 4

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


def formater_message_pronostics(tous_resultats: list, date_aff: str, run_label: str) -> str:
    lignes = [
        f"PMU France - Pronostics du {date_aff}",
        run_label,
        "=" * 35,
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
        disc     = r.get("discipline", "").replace("_", " ")
        heure_ts = r.get("heure", 0)
        cote     = r.get("cote_jour", 0)
        score    = r.get("score_total", 0)
        nom      = r.get("nom_cheval", "?")
        jock     = r.get("jockey", "?")
        prop     = r.get("proprietaire", "")
        libelle  = r.get("libelle", "")
        corde    = r.get("place_corde", 0)
        nb_part  = r.get("nb_partants", 0)
        poids    = r.get("poids_porte", 0)
        oeill    = r.get("oeilleres", "")

        heure_str = ""
        if heure_ts and isinstance(heure_ts, (int, float)) and heure_ts > 0:
            try:
                heure_str = datetime.fromtimestamp(heure_ts / 1000).strftime("%Hh%M")
            except Exception:
                pass

        # Mouvement de cote
        mvt = ""
        val = r.get("variation_cote_%", "")
        if val != "" and isinstance(val, (int, float)):
            if val <= -25:
                mvt = f"  [CHUTE COTE {val:+.0f}%!!!]"
            elif val <= -10:
                mvt = f"  [cote {val:+.0f}%]"
            elif val >= 15:
                mvt = f"  [cote +{val:.0f}%]"

        # Place a la corde
        corde_info = ""
        if corde and nb_part and isinstance(corde, int):
            if corde <= 3:
                corde_info = f" [corde {corde}/{nb_part} AVANTAGE]"
            else:
                corde_info = f" [corde {corde}/{nb_part}]"

        # Poids
        poids_info = ""
        if poids and poids > 0:
            poids_kg = poids / 10
            poids_info = f"  Poids: {poids_kg:.1f}kg"

        # Oeilleres
        oeill_info = ""
        if oeill and oeill != "SANS_OEILLERES":
            oeill_info = f"  Oeilleres: {oeill.replace('_', ' ').lower()}"

        lignes.append("")
        lignes.append(f"--- {r['reunion']} {r['course']} | {heure_str} | {disc} ---")
        if libelle:
            lignes.append(f"    {libelle[:45]}")
        lignes.append(f"    >> {nom} <<{corde_info}")
        lignes.append(f"    Cote: {cote:.1f}{mvt}")
        lignes.append(f"    Score: {score:.1f}/100")
        lignes.append(f"    Jockey: {jock}{poids_info}")
        if oeill_info:
            lignes.append(f"    {oeill_info.strip()}")
        if prop:
            lignes.append(f"    Proprio: {prop[:35]}")

        resume    = r.get("presse_resume", "")
        signaux   = r.get("presse_signaux", "")
        sentiment = r.get("presse_sentiment", 50)
        if resume and "Aucune" not in resume and len(resume) > 5:
            ind = "[+]" if sentiment >= 65 else ("[-]" if sentiment <= 35 else "[=]")
            lignes.append(f"    Presse {ind}: {resume[:120]}")
        if signaux:
            lignes.append(f"    Signaux: {signaux[:80]}")

    lignes.append("")
    lignes.append("=" * 35)
    lignes.append("Outil statistique - Jouer responsable.")
    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. APPELS API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/6.0)",
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
    """
    Score base sur le poids porte.
    Moins le cheval porte, meilleur le score.
    poids en grammes * 10 dans l'API (600 = 60.0 kg).
    """
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
    """
    Score base sur la valeur de handicap.
    Un cheval avec handicap bas dans sa course est potentiellement sous-evalue.
    """
    if not handicap_val or not handicaps_course:
        return 50.0
    h_valides = [h for h in handicaps_course if h > 0]
    if not h_valides or len(h_valides) < 2:
        return 50.0
    h_min = min(h_valides)
    h_max = max(h_valides)
    if h_max == h_min:
        return 50.0
    # Handicap bas = sous-evalue = bon signe
    return ((h_max - handicap_val) / (h_max - h_min)) * 100


def score_oeilleres(oeilleres: str) -> float:
    """
    Score base sur les oeilleres.
    Neutre par defaut. Penalite si oeilleres = signe de difficulte comportementale.
    Note : les fers (deferre) sont detectes via la presse Claude.
    """
    if not oeilleres or oeilleres == "SANS_OEILLERES":
        return 50.0
    elif oeilleres in ("OEILLERES_CLASSIQUE",):
        return 42.0   # Leger malus - cheval qui se distrait
    elif oeilleres in ("OEILLERES_AUSTRALIENNES",):
        return 38.0   # Malus - cheval avec concentration difficile
    else:
        return 46.0   # Autre type, leger malus


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


def calculer_score_total(
    s_forme, s_distance, s_cote, s_mouvement,
    s_jockey, s_ecurie, s_corde, s_poids, s_handicap
) -> float:
    return (
        s_forme      * W_FORME      / 100
        + s_distance * W_DISTANCE   / 100
        + s_cote     * W_COTE       / 100
        + s_mouvement* W_MOUVEMENT  / 100
        + s_jockey   * W_JOCKEY     / 100
        + s_ecurie   * W_ECURIE     / 100
        + s_corde    * W_CORDE      / 100
        + s_poids    * W_POIDS      / 100
        + s_handicap * W_HANDICAP   / 100
    )


# ──────────────────────────────────────────────
#  4. SIGNAL PRESSE + FERS - CLAUDE API
# ──────────────────────────────────────────────
def get_signal_presse(nom_cheval: str, date_affichage: str) -> dict:
    if not ANTHROPIC_KEY:
        return {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}

    prompt = f"""Tu es un expert en courses hippiques francaises.
Recherche sur le web les informations du {date_affichage} sur le cheval "{nom_cheval}"
pour les courses PMU de ce jour (Paris-Turf, Equidia, At Racing, Turf Magazine).

Cherche aussi si ce cheval court DEFERRE (sans fers) aujourd'hui.
Un cheval deferre pour la premiere fois est souvent en progression - signal positif important.

Reponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "resume": "2-3 phrases factuelles",
  "sentiment": 70,
  "sources": ["Paris-Turf"],
  "signaux": ["entraineur confiant", "deferre premiere fois"],
  "deferre": false
}}

sentiment : 0-30 mauvais, 50 neutre, 70-100 tres positif.
deferre : true si le cheval court deferre aujourd'hui, false sinon.
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
) -> list:

    discipline = info_course.get("discipline", "")
    distance   = info_course.get("distance", 0)
    libelle    = info_course.get("libelle", f"R{nr} C{nc}")
    heure      = info_course.get("heureDepart", "")

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants pour R{nr} C{nc}")
        return []

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    nb_partants = len(partants_actifs)
    log.info(f"  -> {nb_partants} partants actifs")

    cotes_course    = [extraire_cote(p) for p in partants_actifs if extraire_cote(p) > 0]
    poids_course    = [p.get("handicapPoids", 0) for p in partants_actifs if p.get("handicapPoids")]
    handicaps_course = [p.get("handicapValeur", 0) for p in partants_actifs if p.get("handicapValeur")]

    resultats = []
    for partant in partants_actifs:
        num   = partant.get("numPmu") or partant.get("numero")
        nom   = partant.get("nom", f"Partant {num}")
        jockey = partant.get("driver") or partant.get("nomJockey") or ""

        entraineur = partant.get("entraineur") or ""
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

        s_forme    = score_forme(perfs)
        s_dist     = score_distance(perfs, distance)
        s_cote     = score_cote_statique(cote_jour, cotes_course)
        s_mvt      = score_mouvement_cote(cote_veille, cote_jour)
        s_jockey   = score_jockey(str(jockey), partants_actifs)
        s_ecurie   = score_ecurie(str(proprietaire), str(entraineur), str(jockey), partants_actifs)
        s_corde    = score_corde(place_corde, nb_partants, discipline, distance)
        s_poids    = score_poids(poids, poids_course)
        s_handicap = score_handicap(handicap_val, handicaps_course)
        s_oeill    = score_oeilleres(oeilleres)
        s_total    = calculer_score_total(
            s_forme, s_dist, s_cote, s_mvt,
            s_jockey, s_ecurie, s_corde, s_poids, s_handicap
        )

        # Bonus oeilleres applique en dehors du calcul principal
        bonus_oeill = (s_oeill - 50) * 0.05   # max +-2.5 pts
        s_total = min(100, max(0, s_total + bonus_oeill))

        # Signal presse + fers
        presse = {"resume": "", "sentiment": 50.0, "sources": [], "signaux": [], "deferre": False}
        if activer_presse and ANTHROPIC_KEY:
            presse  = get_signal_presse(nom, date_aff)
            delta   = (presse["sentiment"] - 50) * 0.10
            # Bonus si deferre
            if presse.get("deferre"):
                delta += 3.0
                log.info(f"  [DEFERRE] {nom} -> bonus +3 pts")
            s_total = min(100, max(0, s_total + delta))
            time.sleep(1)

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)

        resultats.append({
            "reunion":          f"R{nr}",
            "course":           f"C{nc}",
            "heure":            heure,
            "hippodrome":       hippodrome,
            "libelle":          libelle,
            "discipline":       discipline,
            "distance_m":       distance,
            "nb_partants":      nb_partants,
            "num_partant":      num,
            "nom_cheval":       nom,
            "place_corde":      place_corde,
            "poids_porte":      poids,
            "handicap_valeur":  handicap_val,
            "oeilleres":        oeilleres,
            "deferre":          presse.get("deferre", False),
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
            "score_corde":      round(s_corde, 1),
            "score_poids":      round(s_poids, 1),
            "score_handicap":   round(s_handicap, 1),
            "score_total":      round(s_total, 1),
            "presse_resume":    presse.get("resume", ""),
            "presse_sentiment": round(presse.get("sentiment", 50), 1),
            "presse_sources":   ", ".join(presse.get("sources", [])),
            "presse_signaux":   ", ".join(presse.get("signaux", [])),
        })
        time.sleep(0.5)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)

    log.info(f"\n{'─'*70}")
    log.info(f"  {libelle} - {discipline} - {distance}m")
    log.info(f"  {'#':<3} {'Cheval':<22} {'Corde':>5} {'Poids':>6} {'Cote':>6} {'Score':>7}")
    for i, r in enumerate(resultats[:5], 1):
        flag = " *" if i == 1 else ""
        poids_kg = r["poids_porte"] / 10 if r["poids_porte"] else 0
        log.info(
            f"  {i:<3} {r['nom_cheval']:<22} {str(r['place_corde']):>5} "
            f"{poids_kg:>5.1f}k {r['cote_jour']:>6.1f} {r['score_total']:>7.1f}{flag}"
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
    log.info(f"  PMU SCORER v6 - France - {date_aff} - {heure_run}")
    log.info(f"  Presse/fers : {'OK active' if activer_presse else 'desactive'}")
    log.info(f"  Telegram    : {'OK configure' if TELEGRAM_TOKEN else 'desactive'}")
    log.info("=" * 70)

    if TELEGRAM_TOKEN:
        telegram_send(f"PMU Scorer v6 demarre - {date_aff} {heure_run}\n{run_label}...")

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
    tous_resultats = []
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
                tous_resultats.extend(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(1)

    log.info(f"\n{reunions_france} reunions francaises analysees.")

    if tous_resultats:
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion", "course", "heure", "hippodrome", "libelle", "discipline", "distance_m",
            "nb_partants", "num_partant", "nom_cheval", "place_corde", "poids_porte",
            "handicap_valeur", "oeilleres", "deferre",
            "jockey", "entraineur", "proprietaire",
            "cote_veille", "cote_jour", "variation_cote_%",
            "score_forme", "score_distance", "score_cote", "score_mouvement",
            "score_jockey", "score_ecurie", "score_corde", "score_poids",
            "score_handicap", "score_total",
            "presse_resume", "presse_sentiment", "presse_sources", "presse_signaux",
        ]
        with open(nom_fichier, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=colonnes)
            writer.writeheader()
            writer.writerows(tous_resultats)
        log.info(f"CSV exporte : {nom_fichier}")

        message = formater_message_pronostics(tous_resultats, date_aff, run_label)
        if telegram_send(message):
            log.info("Message Telegram envoye.")
        else:
            log.warning("Envoi Telegram echoue.")
    else:
        log.warning("Aucun resultat France trouve.")
        telegram_send(f"PMU Scorer {date_aff} - aucun resultat France trouve.")

    log.info("\n" + "=" * 70)
    log.info("  SCORER v6 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
