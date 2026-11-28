"""
=============================================================
  PMU RACING SCORER v15.2 - France uniquement
  (v15.2 = v15.1 + selection 3 niveaux PEPITE/SOLIDE/CORRECT)
=============================================================
  Changements v15.1 -> v15.2 :
    - Selection a 3 niveaux dans le message du matin :
        PEPITE  : cote 2-8 + partants <=8  + ecart>=3 + score>=45
        SOLIDE  : cote 2-8 + partants <=10 + ecart>=3
        CORRECT : cote 2-8 + partants <=10
    - Compteur de courses selectionnees en tete de message
    - Affiche le couple des deux choix du scoring presentes dans le message
    - N'affiche QUE les courses selectionnees (le CSV garde tout)
    - Base sur l'analyse de 401 paris (12-24/05/2026)

  Changements v15 -> v15.1 :
    - emoji devant les numeros de chevaux Top1/Top2
    - encadre pour les courses Top10 du jour (score V2)
    - pattern historique gagnant
=============================================================
"""

import csv
import logging
import os
import time
import unicodedata
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo('Europe/Paris')
except ImportError:
    from datetime import timezone
    import datetime as dt
    TZ_PARIS = timezone(timedelta(hours=2))  # UTC+2 ete

import requests
from pmu_tracking import erreur_identite, erreur_chevaux, envoyer_trace, paris_affiches, formater_selection, archiver_observation
from pmu_signaux import VERSION, deferrage_officiel, marches_internet

# v15 : module de scraping gratuit qui remplace les appels Claude
from pronos_gratuit import get_pronostics_gratuit

# v15.1 : module patterns historiques
try:
    from patterns_historiques import (
        detecter_pattern_gagnant,
        calculer_score_opportunite,
        compter_audits,
        info_patterns,
    )
    PATTERNS_DISPO = True
except ImportError:
    PATTERNS_DISPO = False
    def detecter_pattern_gagnant(*args, **kwargs): return False
    def calculer_score_opportunite(*args, **kwargs): return 0.0
    def compter_audits(): return 0
    def info_patterns(): return "patterns_historiques.py absent"

# v15.2 : module de selection a 3 niveaux (PEPITE / SOLIDE / CORRECT)
try:
    from selection_niveaux import classer_niveau_course
    SELECTION_DISPO = True
except ImportError:
    SELECTION_DISPO = False
    def classer_niveau_course(course): return {"niveau": None, "emoji": "", "raison": ""}

# ──────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────
BASE_URL       = "https://online.turfinfo.api.pmu.fr/rest/client/61"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
OUTPUT_DIR     = "resultats"

PAYS_AUTORISES    = {"FRA", "FRANCE"}
DISCIPLINES_GALOP = {"PLAT", "HAIE", "HAIES", "STEEPLE", "STEEPLECHASE", "STEEPLE_CHASE", "GALOP"}
DISCIPLINES_TROT  = {"TROT_ATTELE", "TROT_MONTE", "ATTELE", "MONTE"}
DISCIPLINES       = DISCIPLINES_GALOP | DISCIPLINES_TROT

TYPE_HANDICAP   = "HANDICAP"
TYPE_CONDITIONS = "CONDITIONS"
TYPE_GROUPE     = "GROUPE"
TYPE_RECLAMER   = "RECLAMER"
TYPE_INCONNU    = "AUTRE"

SOURCES_PREMIUM = {"Turf BZH", "Paris-Turf", "Equidia", "Frequence Turf",
                   "Le Trot", "Canalturf", "Geny", "Zone-Turf"}

W_GALOP_NORMAL = {
    "pronostics": 15, "outsider": 5, "forme_r": 12, "mouvement": 12,
    "terrain": 6, "trio_pje": 18, "distance": 7, "jockey_hippo": 8,
    "progression": 5, "forme_f": 4, "hippodrome": 3, "corde": 2,
    "rk": 0, "fautes": 3, "deferre_pmu": 0,
}
W_GALOP_HANDICAP = {
    "pronostics": 15, "outsider": 5, "forme_r": 9, "mouvement": 12,
    "terrain": 5, "trio_pje": 18, "distance": 5, "jockey_hippo": 8,
    "progression": 8, "forme_f": 4, "hippodrome": 3, "corde": 2,
    "rk": 0, "fautes": 6, "deferre_pmu": 0,
}
W_TROT_NORMAL = {
    "pronostics": 15, "outsider": 5, "forme_r": 12, "rk": 11,
    "corde": 11, "mouvement": 8, "trio_pje": 15, "jockey_hippo": 2,
    "distance": 5, "progression": 3, "hippodrome": 3, "forme_f": 2,
    "terrain": 0, "fautes": 0, "deferre_pmu": 8,
}
W_TROT_HANDICAP = {
    "pronostics": 15, "outsider": 5, "forme_r": 10, "rk": 11,
    "corde": 11, "mouvement": 10, "trio_pje": 15, "jockey_hippo": 2,
    "distance": 3, "progression": 6, "hippodrome": 2, "forme_f": 2,
    "terrain": 0, "fautes": 0, "deferre_pmu": 8,
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
    return envoyer_trace(texte, TELEGRAM_TOKEN, TELEGRAM_CHAT)


def evaluer_fiabilite_course(course: dict) -> str:
    if not course.get("top5"):
        return ""
    n1 = course["top5"][0]
    score    = n1.get("score_total", 0) or 0
    cote     = n1.get("cote_jour", 99) or 99
    nb_src   = n1.get("nb_sources_total", 0) or 0
    nb_cit   = n1.get("nb_pronostics", 0) or 0
    consens  = n1.get("consensus_fort", False)
    value    = n1.get("value_bet", False)

    f = 0
    if score >= 50:           f += 35
    elif score >= 45:         f += 25
    elif score >= 40:         f += 15
    if nb_cit >= 3:           f += 25
    elif nb_cit >= 2:         f += 15
    elif nb_cit >= 1:         f += 8
    if cote < 3:              f += 25
    elif cote < 5:            f += 18
    elif cote < 8:            f += 10
    if consens:               f += 15
    if value:                 f += 10
    if nb_src == 0:           f -= 15

    if f >= 60:
        return "⭐⭐⭐ "
    elif f >= 40:
        return "⭐⭐ "
    elif f >= 25:
        return "⭐ "
    return ""


def formater_message_telegram(courses_galop, courses_trot, date_aff, run_label) -> str:
    """
    v15.2 : n'affiche QUE les courses selectionnees (PEPITE/SOLIDE/CORRECT),
    triees par niveau. Le simple reprend le premier choix affiche ;
    le couple reprend exclusivement les deux choix affiches.
    """

    toutes_courses = list(courses_galop) + list(courses_trot)

    # 1. Calcul score opportunite + pattern (comme v15.1)
    for c in toutes_courses:
        if not c.get("top5"):
            continue
        n1 = c["top5"][0]
        n2 = c["top5"][1] if len(c["top5"]) > 1 else {}
        data_pattern = {
            "score_n1":     n1.get("score_total", 0),
            "cote_n1":      n1.get("cote_jour", 0),
            "ecart_n1_n2":  n1.get("score_total", 0) - n2.get("score_total", 0),
            "nb_partants":  n1.get("nb_partants", 0),
        }
        c["_score_opp"]     = calculer_score_opportunite(data_pattern)
        c["_pattern_match"] = detecter_pattern_gagnant(data_pattern)
        # v15.2 : niveau de selection
        cls = classer_niveau_course(c)
        c["_niveau"] = cls["niveau"]
        c["_niveau_emoji"] = cls["emoji"]
        c["_niveau_raison"] = cls["raison"]

    # 2. Ne garder que les courses classees
    selection = [c for c in toutes_courses if c.get("_niveau")]

    # 3. Trier par niveau (PEPITE > SOLIDE > CORRECT) puis par score_opp
    ordre_niveau = {"PEPITE": 0, "SOLIDE": 1, "CORRECT": 2}
    selection.sort(key=lambda c: (ordre_niveau.get(c["_niveau"], 9),
                                  -c.get("_score_opp", 0)))

    # 4. Comptage par niveau
    nb_pepite  = sum(1 for c in selection if c["_niveau"] == "PEPITE")
    nb_solide  = sum(1 for c in selection if c["_niveau"] == "SOLIDE")
    nb_correct = sum(1 for c in selection if c["_niveau"] == "CORRECT")
    nb_total_analyse = sum(1 for c in toutes_courses if c.get("top5"))

    def formater_course(course: dict) -> list:
        if not course.get("top5"):
            return []
        stamp = course.get("heure", 0)
        depart = datetime.fromtimestamp(stamp / 1000, tz=TZ_PARIS) if stamp else None
        top = course["top5"][:2]
        day = depart.date().isoformat() if depart else datetime.now(TZ_PARIS).date().isoformat()
        if day >= '2026-11-02' and not any(line.startswith('COUPLE ORDRE :') for line in paris_affiches(top, top[0].get('nb_partants',0), course.get('paris_disponibles'), day=day)):
            return []
        lignes = [f"COURSE {course.get('reunion', '')}{course.get('course', '')} — DEPART {depart:%Hh%M}" if depart else f"COURSE {course.get('reunion', '')}{course.get('course', '')}"]
        if depart:
            lignes.append(f"DATE : {depart:%Y-%m-%d}")
        lignes.extend([str(course.get('hippodrome', '')).replace('HIPPODROME DE ', ''),
                       course.get('libelle', ''),
                       str(course.get('discipline', '')).replace('_', ' '), '', 'SELECTION INITIALE', ''])
        lignes.extend(formater_selection(top, top[0].get('nb_partants', 0), marches=course.get('paris_disponibles'), day=depart.date().isoformat() if depart else datetime.now(TZ_PARIS).date().isoformat()))
        lignes.append('')
        return lignes

    cards = [formater_course(c) for c in selection]
    cards = [c for c in cards if c]
    lignes = [f"🐎 PMU — {date_aff}", f"{len(cards)} course(s) retenue(s).", '']
    if not cards:
        lignes.append("Aucune course retenue aujourd'hui.")
    for card in cards:
        lignes.extend(card)
    return "\n".join(lignes)


# ──────────────────────────────────────────────
#  2. API PMU
# ──────────────────────────────────────────────
HEADERS_PMU = {
    "User-Agent": "Mozilla/5.0 (compatible; PMU-Scorer/15.0)",
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
    import glob, csv as csv_mod
    pattern = os.path.join(OUTPUT_DIR, f"pmu_{datetime.now().strftime('%Y%m%d')}_*.csv")
    fichiers = sorted(glob.glob(pattern))
    if fichiers:
        try:
            with open(fichiers[0], "r", encoding="utf-8-sig") as f:
                for row in csv_mod.DictReader(f):
                    if (row.get("nom_cheval", "").upper() == nom_cheval.upper()
                            and row.get("reunion", "") == f"R{nr}"
                            and row.get("course", "") == f"C{nc}"):
                        cote = float(row.get("cote_jour", 0) or 0)
                        if cote > 0:
                            return cote
        except Exception:
            pass
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
#  3. PRONOSTICS EXTERNES VIA SCRAPING GRATUIT (v15)
# ──────────────────────────────────────────────
def get_pronostics_externes(date_str_iso, nr, nc, libelle, partants_actifs,
                             discipline) -> dict:
    if not partants_actifs:
        return {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                "sources_par_ch": {}, "outsiders": [], "deferres": []}

    partants_pour_scraper = [
        {"nom": p.get("nom", ""), "num": p.get("numPmu") or p.get("numero")}
        for p in partants_actifs if p.get("nom")
    ]

    res = get_pronostics_gratuit(
        date_str=date_str_iso,
        reunion_num=nr,
        course_num=nc,
        nom_course=libelle,
        partants=partants_pour_scraper,
    )

    nb_sources = res.get("nb_sources", 0)
    scores     = res.get("scores", {})

    citations: dict = {}
    citations_pond: dict = {}
    sources_par_ch: dict = {}

    for nom, score in scores.items():
        nom_up = nom.upper().strip()
        src = list(dict.fromkeys(res.get('sources_par_ch', {}).get(nom, [])))
        nb_cit = len(src)
        if not nb_cit:
            continue  # Aucun nombre de citations reconstruit depuis une note.
        citations[nom_up]      = nb_cit
        citations_pond[nom_up] = round(score / 20, 2)
        sources_par_ch[nom_up] = src

    outsiders: list = []
    for p in partants_actifs:
        nom_up = (p.get("nom") or "").upper().strip()
        cote = extraire_cote(p)
        if nom_up in citations and cote >= 15.0:
            outsiders.append(nom_up)

    log.info(f"  Pronos [{discipline}]: {nb_sources} src | "
             f"{len(citations)} chevaux cites | {len(outsiders)} outsiders")
    log.info(f"  {res.get('details', '')}")

    return {
        "citations": citations,
        "citations_pond": citations_pond,
        "nb_sources": nb_sources,
        "sources_par_ch": sources_par_ch,
        "outsiders": outsiders,
        "deferres": [],
        "resume": res.get("details", ""),
    }


def get_stats_proprietaire(proprietaire: str, hippodrome: str) -> float:
    # Aucun historique proprietaire verifie : ne pas noter la reputation du nom.
    return 50.0


# ──────────────────────────────────────────────
#  DÉCODEUR DE MUSIQUE (ajout 27/05/2026)
#  La musique (ex "8a3m1m0a1m(25)1m2a9a0a") est dans l'endpoint participants
#  DÉJÀ appelé (comme le R/K). Elle remplace l'endpoint mort performances-detaillees
#  comme source primaire de forme/fautes/progression.
# ──────────────────────────────────────────────
import re as _re
_MUSIQUE_PATTERN = _re.compile(r"\((\d{2})\)|([0-9DTRA])([a-zA-Z])")

def decoder_musique(musique: str) -> list:
    """Décode une musique PMU en liste de perfs : {place, faute, discipline}.
    place 1-9 = rang ; 0 = hors top 10 (=11) ; D/T/A/R = faute (place=None).
    La perf la plus récente est à GAUCHE."""
    if not musique:
        return []
    perfs = []
    for m in _MUSIQUE_PATTERN.finditer(musique.strip().replace(" ", "")):
        if m.group(1):  # marqueur d'année (25), on ignore
            continue
        place_raw = m.group(2).upper()
        faute = place_raw in ("D", "T", "A", "R")
        if place_raw.isdigit():
            place = int(place_raw)
            place = 11 if place == 0 else place
        else:
            place = None
        perfs.append({"place": place, "faute": faute})
    return perfs


def musique_vers_perfs(musique: str) -> list:
    """Convertit la musique en pseudo-performances compatibles avec les fonctions
    de score existantes (clé 'place').
    Une faute (D/T/A/R) est encodée comme une mauvaise place (10) : elle pénalise
    la forme et la progression, ce qui est le comportement voulu (un cheval qui
    faute souvent n'est pas "en forme")."""
    out = []
    for p in decoder_musique(musique):
        if p["faute"]:
            out.append({"place": 10, "ordreArrivee": "D", "_faute": True})
        else:
            out.append({"place": p["place"]})
    return out


def score_deferre_pmu(partant: dict) -> float:
    """Score de déferrage basé sur la donnée OFFICIELLE PMU (champ 'deferre').
    Grille experte : déferré des 4 pieds = signal d'intention le plus fort au trot
    (recherche de vitesse max ce jour-là). Hiérarchie :
      4 pieds > postérieurs > antérieurs > ferré normal.
    NON ENCORE VALIDÉ statistiquement (journée expérimentale 28/05)."""
    return deferrage_officiel(partant)['score']


# ──────────────────────────────────────────────
#  4. SCORES STATISTIQUES — réparés via la musique (27/05/2026)
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
                if 0 <= (maintenant - (p.get("date") or 0)) <= trente_jours
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
    nb_fautes = 0
    nb_analysees = 0
    for p in performances[:n]:
        nb_analysees += 1
        incident = str(p.get("incident") or p.get("typeIncident") or "").upper()
        arrivee  = str(p.get("ordreArrivee") or p.get("place") or "").upper()
        if incident in ("GALOP", "DECROCHEMENT", "DISQUALIFIE", "TOMBE",
                        "CHUTE", "ABANDON", "G", "D", "A", "T"):
            nb_fautes += 1
        elif arrivee in ("D", "G", "T", "A"):
            nb_fautes += 1
    if nb_analysees == 0 and musique:
        # La plus recente est a GAUCHE. Ne pas compter les marqueurs d'annee,
        # ni additionner musique et historique (ce seraient les memes sorties).
        recentes = decoder_musique(musique)[:n]
        nb_analysees = len(recentes)
        nb_fautes = sum(p['faute'] for p in recentes)
    if nb_analysees == 0:
        return 0.0
    taux = nb_fautes / nb_analysees
    if taux == 0:
        return 0.0
    elif taux <= 0.2:
        return -4.0
    elif taux <= 0.4:
        return -8.0
    elif taux <= 0.6:
        return -12.0
    else:
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
        return 50.0
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
    return min(100, v / len(courses_h) * 60 + pl / len(courses_h) * 40)


def score_jockey_sur_hippodrome(performances, jockey_nom, hippodrome_actuel) -> float:
    if not jockey_nom or not hippodrome_actuel or not performances:
        return 50.0
    hippo_up = hippodrome_actuel.upper()
    perfs_hippo = [
        p for p in performances
        if meme_personne(jockey_nom, p.get("driver") or p.get("nomJockey") or "")
        and hippo_up in (p.get("hippodrome") or p.get("lieu") or "").upper()
    ]
    if len(perfs_hippo) >= 3:
        v  = sum(1 for p in perfs_hippo
                 if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
        pl = sum(1 for p in perfs_hippo
                 if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
        taux_v  = v / len(perfs_hippo)
        taux_pl = pl / len(perfs_hippo)
        return min(100, taux_v * 60 + taux_pl * 40)
    else:
        perfs_jockey = [
            p for p in performances
            if meme_personne(jockey_nom, p.get("driver") or p.get("nomJockey") or "")
        ]
        if not perfs_jockey:
            return 50.0
        v  = sum(1 for p in perfs_jockey
                 if str(p.get("place") or p.get("ordreArrivee") or 99) == "1")
        pl = sum(1 for p in perfs_jockey
                 if str(p.get("place") or p.get("ordreArrivee") or 99) in ("1","2","3"))
        taux_v  = v / len(perfs_jockey)
        taux_pl = pl / len(perfs_jockey)
        return min(100, taux_v * 50 + taux_pl * 30)


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
    elif disc in ("HAIE", "HAIES", "STEEPLE", "STEEPLECHASE", "STEEPLE_CHASE"):
        facteur = 0.2
    else:
        facteur = 0.5
    score = min(100, max(0, 50 + (score_base - 50) * facteur))
    if disc in ("TROT_ATTELE", "ATTELE") and place_corde <= 2 and distance <= 2400:
        score = min(100, score + 8)
    return score


def score_record_kilometrique(meilleur_rk_partant, distance_course, partants_actifs) -> tuple:
    """Note la reduction kilometrique du partant courant par rapport au peloton.
    meilleur_rk_partant : la R/K du cheval (plus petit = plus rapide), 0 si inconnue.
    Renvoie (score 0-100, rk_du_partant). Score eleve = cheval rapide vs ses rivaux."""
    meilleur_rk = float(meilleur_rk_partant or 0)
    if meilleur_rk <= 0:
        return 50.0, 0.0
    tous_rk = [p.get("_meilleur_rk", 0) for p in partants_actifs if p.get("_meilleur_rk", 0) > 0]
    if not tous_rk or len(tous_rk) < 2:
        return 50.0, meilleur_rk
    rk_min = min(tous_rk)
    rk_max = max(tous_rk)
    if rk_max == rk_min:
        return 50.0, meilleur_rk
    # Plus la R/K est petite (rapide), plus le score est haut
    score = ((rk_max - meilleur_rk) / (rk_max - rk_min)) * 100
    return min(100, max(0, score)), meilleur_rk


def score_trio_proprietaire_jockey_entraineur(score_proprio, score_jockey_global, score_entraineur) -> float:
    return (score_proprio * 0.30 + score_jockey_global * 0.40 + score_entraineur * 0.30)


def score_jockey_global(jockey_nom, tous_partants) -> float:
    # nombreVictoires/nombreCourses de /participants decrivent le CHEVAL.
    # En attendant un historique de personnes verifie, valeur neutre, pas d'ELO fictif.
    return 50.0


def score_entraineur_global(entraineur_nom, tous_partants) -> float:
    # Les compteurs des chevaux ne permettent pas d'estimer ceux de l'entraineur.
    return 50.0


def meme_personne(a, b):
    """Identite textuelle stricte ; une initiale commune ne prouve rien.

    Les alias prenom complet/initiale exigent une source d'identite externe.
    """
    def cle(value):
        text = unicodedata.normalize('NFKD', str(value or '')).upper()
        return tuple(_re.findall(r'[A-Z0-9]+', ''.join(
            c for c in text if not unicodedata.combining(c))))
    x, y = cle(a), cle(b)
    return bool(x and len(''.join(x)) > 3 and x == y)


def score_pronostics_pond(nom, citations_pond, poids_max) -> float:
    if not citations_pond or poids_max <= 0:
        return 0.0
    poids = citations_pond.get(nom.upper().strip(), 0)
    return min(100, (poids / poids_max) * 100) if poids > 0 else 0.0


def score_outsider(nom, outsiders, cote) -> float:
    nom_up = nom.upper().strip()
    if nom_up in outsiders and cote >= 15.0:
        return 80.0
    elif nom_up in outsiders:
        return 60.0
    return 0.0


def score_mouvement_cote(cote_veille, cote_jour) -> float:
    if not cote_veille or cote_veille <= 0 or cote_jour <= 0:
        return 50.0
    variation = (cote_veille - cote_jour) / cote_veille
    variation = max(-1.0, min(2.0, variation))
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
    cote   = r.get("cote_jour", 0)
    nb_cit = r.get("nb_pronostics", 0)
    mvt    = r.get("variation_cote_%", "")
    chute  = isinstance(mvt, (int, float)) and mvt <= -25
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
    if not resultats:
        return resultats

    top5 = resultats[:5]
    reste = resultats[5:]

    credibles = [r for r in top5 if not est_outsider_suspect(r, nb_sources, type_course)]
    suspects  = [r for r in top5 if est_outsider_suspect(r, nb_sources, type_course)]

    if len(suspects) > 2:
        log.info(f"  Filtre annule: {len(suspects)} suspects (trop) -> top5 brut")
    elif suspects:
        for s in suspects:
            log.info(f"  Filtre top5: {s['nom_cheval']} (cote {s['cote_jour']}) suspect -> recule")
        resultats = credibles + suspects + reste

    if len(resultats) >= 2:
        if resultats[0].get("score_total", 0) < resultats[1].get("score_total", 0):
            ecart = resultats[1]["score_total"] - resultats[0]["score_total"]
            if ecart > 3:
                log.info(f"  Garde-fou ordre: swap")
                resultats[0], resultats[1] = resultats[1], resultats[0]

    n1 = resultats[0]
    if est_outsider_suspect(n1, nb_sources, type_course):
        for i, r in enumerate(resultats[1:], 1):
            if not est_outsider_suspect(r, nb_sources, type_course):
                resultats[0], resultats[i] = resultats[i], resultats[0]
                log.info(f"  Filtre N1: {n1['nom_cheval']} ({n1['cote_jour']}) -> {resultats[0]['nom_cheval']}")
                break

    grand_favori = None
    for i, r in enumerate(resultats):
        if 0 < r.get("cote_jour", 99) < 2.0:
            grand_favori = (i, r)
            break
    if grand_favori:
        idx, fav = grand_favori
        if idx > 1:
            score_n1 = resultats[0].get("score_total", 0)
            score_fav = fav.get("score_total", 0)
            if score_n1 - score_fav < 10:
                resultats.pop(idx)
                resultats.insert(0, fav)
                log.info(f"  Grand favori: {fav['nom_cheval']} (cote {fav['cote_jour']}) remonte en N1")
            else:
                resultats.pop(idx)
                resultats.insert(1, fav)
                log.info(f"  Grand favori: {fav['nom_cheval']} (cote {fav['cote_jour']}) remonte en N2")

    if len(resultats) >= 2:
        n1 = resultats[0]
        n2 = resultats[1]
        pond_n1 = n1.get("nb_pronostics_pondere", 0) or 0
        pond_n2 = n2.get("nb_pronostics_pondere", 0) or 0
        ecart   = n1.get("score_total", 0) - n2.get("score_total", 0)
        if pond_n2 > pond_n1 * 1.5 and ecart < 5:
            resultats[0], resultats[1] = resultats[1], resultats[0]
            log.info(f"  Inversion N1/N2: {n2['nom_cheval']} -> N1")

    if len(resultats) >= 2 and nb_sources == 0:
        n1 = resultats[0]
        n2 = resultats[1]
        ecart_score = abs(n1.get("score_total", 0) - n2.get("score_total", 0))
        cote_n1 = n1.get("cote_jour", 999)
        cote_n2 = n2.get("cote_jour", 999)
        if ecart_score < 1.5 and cote_n2 > 0 and cote_n1 > cote_n2 * 1.3:
            resultats[0], resultats[1] = resultats[1], resultats[0]
            log.info(f"  Favori marche: {n2['nom_cheval']} (cote {cote_n2}) -> N1")

    return resultats


# ──────────────────────────────────────────────
#  5. ANALYSE D UNE COURSE
# ──────────────────────────────────────────────
def analyser_course(date_str, date_str_iso, date_veille, date_aff, nr, nc,
                    info_course, hippodrome="", terrain="",
                    activer_presse=True) -> dict:

    discipline  = info_course.get("discipline", "")
    distance    = info_course.get("distance", 0)
    libelle     = info_course.get("libelle", f"R{nr} C{nc}")
    heure       = info_course.get("heureDepart", "")
    trot        = est_trot(discipline)
    type_str    = "TROT" if trot else "GALOP"
    type_course = detecter_type_course(info_course)

    log.info(f"  [{type_str}] [{type_course}] {libelle}")

    officiel = api_get(f'/programme/{date_str}/R{nr}/C{nc}')
    raison = erreur_identite({'hippodrome': hippodrome, 'libelle': libelle}, officiel, nr, nc)
    if raison:
        log.error('R%sC%s : %s ; aucun conseil', nr, nc, raison)
        archiver_observation(info_course, 'IDENTITE_NON_VALIDEE', [], calcul={'erreur': raison})
        return {}

    partants = get_participants(date_str, nr, nc)
    if not partants:
        log.warning(f"  Pas de partants R{nr} C{nc}")
        return {}

    partants_actifs = [p for p in partants if p.get("statut") != "NON_PARTANT"]
    archiver_observation({'reunion': nr, 'course': nc, **info_course}, 'INITIAL_BRUT', partants)
    if any(extraire_cote(p) <= 0 for p in partants_actifs):
        nouveau = get_participants(date_str, nr, nc)
        if nouveau:
            partants = nouveau
            partants_actifs = [p for p in partants if p.get('statut') != 'NON_PARTANT']
            archiver_observation({'reunion': nr, 'course': nc, **info_course}, 'INITIAL_REESSAI', partants)
    nb_partants     = len(partants_actifs)

    partants_avec_cote = [p for p in partants_actifs if extraire_cote(p) > 0]
    if len(partants_avec_cote) < 3:
        log.info(f"  Cours ignoree : moins de 3 partants avec cote ({len(partants_avec_cote)})")
        return {}

    if trot:
        for partant in partants_actifs:
            # La reduction kilometrique est disponible DIRECTEMENT dans le JSON
            # participants (champ reductionKilometrique, sinon tempsObtenu).
            # Plus petit = plus rapide. On ne depend plus de l'endpoint mort
            # performances-detaillees.
            rk_direct = (partant.get("reductionKilometrique")
                         or partant.get("tempsObtenu") or 0)
            try:
                rk_direct = float(rk_direct)
            except (TypeError, ValueError):
                rk_direct = 0
            if rk_direct > 0:
                partant["_meilleur_rk"] = rk_direct
            else:
                # Fallback : ancien endpoint detaille (au cas ou, sans bloquer si vide)
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

    pronostics_ext = {"citations": {}, "citations_pond": {}, "nb_sources": 0,
                      "sources_par_ch": {}, "outsiders": [], "deferres": []}
    if activer_presse:
        pronostics_ext = get_pronostics_externes(
            date_str_iso, nr, nc, libelle, partants_actifs, discipline)

    citations      = dict(pronostics_ext.get("citations", {}))
    citations_pond = dict(pronostics_ext.get("citations_pond", {}))
    sources_par_ch = dict(pronostics_ext.get("sources_par_ch", {}))
    outsiders      = pronostics_ext.get("outsiders", [])
    deferres       = pronostics_ext.get("deferres", [])
    nb_sources     = pronostics_ext.get("nb_sources", 0)

    if pronostics_pmu:
        nb_sources += 1
        poids_pmu = 2.5
        for num_str in set(pronostics_pmu):
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

        est_deferre = False

        s_proprio  = get_stats_proprietaire(str(proprietaire), hippodrome) if str(proprietaire) else 50.0
        s_joc_glob = score_jockey_global(str(jockey), partants_actifs)
        s_entr     = score_entraineur_global(str(entraineur), partants_actifs)
        s_trio     = score_trio_proprietaire_jockey_entraineur(s_proprio, s_joc_glob, s_entr)
        s_joc_hippo = score_jockey_sur_hippodrome(perfs, str(jockey), hippodrome)
        s_rk, rk_best = score_record_kilometrique(partant.get("_meilleur_rk", 0), distance, partants_actifs) if trot else (0.0, 0.0)
        musique_ch = partant.get('musique') or ''

        # La musique renseigne la forme et la progression, sans date ni parcours.
        # Les autres aptitudes ne doivent exploiter que l'historique detaille.
        perfs_pour_score = perfs if perfs else musique_vers_perfs(musique_ch)

        s_fautes   = score_fautes_trot(perfs, musique=musique_ch) if trot else 0.0

        s = {
            "pronostics":   score_pronostics_pond(nom, citations_pond, poids_max),
            "outsider":     score_outsider(nom, outsiders, cote_jour),
            "forme_r":      score_forme_recente(perfs_pour_score),
            "forme_f":      score_forme_fraiche(perfs),
            "rk":           s_rk,
            "distance":     score_distance(perfs, distance, type_course),
            "terrain":      score_terrain(perfs, terrain),
            "mouvement":    score_mouvement_cote(cote_veille, cote_jour),
            "trio_pje":     s_trio,
            "jockey_hippo": s_joc_hippo,
            "progression":  score_progression(perfs_pour_score),
            "hippodrome":   score_hippodrome_cheval(perfs, hippodrome),
            "corde":        score_corde(place_corde, nb_partants, discipline, distance),
            "deferre_pmu":  score_deferre_pmu(partant) if trot else 50.0,
            "fautes":       0.0,
        }
        s_total = calculer_score_total(s, discipline, type_course)
        s_total = max(0, s_total + s_fautes)
        s_total = min(100, s_total + bonus_age_saison(partant))

        # NOTE 28/05 : l'ancien bonus +4 "deferre" (base sur scraping externe) est
        # remplace par le vrai score_deferre_pmu (base donnee officielle PMU, pondere).
        deferrage = deferrage_officiel(partant)
        est_deferre = deferrage['deferre']

        if meme_personne(jockey, entraineur):
            s_total = min(100, s_total + 4)
            log.info(f"  *** DRIVER=ENTRAINEUR: {nom} ({jockey}) +4 pts ***")

        value_bet = (nb_cit >= 3 and pct_cit >= 40
                     and cote_jour >= (100 / max(pct_cit, 1)) * 1.4)
        est_outsider_surprise = nom_up in outsiders

        var_cote = ""
        if cote_veille and cote_jour:
            var_cote = round((cote_veille - cote_jour) / cote_veille * 100, 1)
            var_cote = max(-100.0, min(200.0, var_cote))

        resultats.append({
            "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
            "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
            "discipline": discipline, "type_course": type_str,
            "type_course_details": type_course, "distance_m": distance,
            "nb_partants": nb_partants, "num_partant": num, "nom_cheval": nom,
            "age": age, "place_corde": place_corde, "poids_porte": poids,
            "deferre": est_deferre, "deferrage_code": deferrage['code'], "value_bet": value_bet,
            "qualite_version": VERSION,
            "paris_disponibles": ';'.join(marches_internet(info_course)),
            "est_outsider_surprise": est_outsider_surprise,
            "consensus_fort": len(src_p) >= 3,
            "sources_premium_citees": src_p, "rk_meilleur": round(rk_best, 2),
            "musique": musique_ch,
            "source_performances": "PMU_DETAILLE" if perfs else "MUSIQUE_SEULE",
            "nb_performances_detaillees": len(perfs),
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
        time.sleep(0.3)

    resultats.sort(key=lambda x: x["score_total"], reverse=True)
    resultats = normaliser_scores(resultats)
    resultats = appliquer_filtre_et_inversion(resultats, nb_sources, type_course)

    consensus_fort = any(r.get("consensus_fort") for r in resultats[:2])

    # v15.2 : calcul du niveau de selection (pour tracabilite CSV)
    # On classe la course une seule fois ici, puis on inscrit le niveau
    # dans CHAQUE ligne (toutes les lignes d'une meme course ont le meme
    # niveau, qui depend du N1). Vide = course rejetee.
    course_pour_niveau = {"top5": resultats[:5]}
    classement = classer_niveau_course(course_pour_niveau)
    niveau_sel = classement.get("niveau") or ""
    for r in resultats:
        r["niveau_selection"] = niveau_sel

    log.info(f"\n{'-'*70}")
    log.info(f"  [{type_str}] [{type_course}] {libelle} | {distance}m")
    for i, r in enumerate(resultats[:5], 1):
        out = " OUT" if r.get("est_outsider_surprise") else ""
        log.info(
            f"  {i:<3} {r['nom_cheval']:<22} {r['cote_jour']:>6.1f} "
            f"{r['score_total']:>7.1f}{out}"
        )

    return {
        "reunion": f"R{nr}", "course": f"C{nc}", "heure": heure,
        "hippodrome": hippodrome, "terrain": terrain, "libelle": libelle,
        "discipline": discipline, "type_course": type_str,
        "type_course_details": type_course,
        "nb_sources_total": nb_sources, "consensus_fort": consensus_fort,
        "top5": resultats[:5], "top2": resultats[:2], "tous_resultats": resultats,
        "paris_disponibles": marches_internet(info_course),
    }


# ──────────────────────────────────────────────
#  6. PROGRAMME PRINCIPAL
# ──────────────────────────────────────────────
def main():
    today        = datetime.now(TZ_PARIS)
    yesterday    = today - timedelta(days=1)
    date_str     = today.strftime("%d%m%Y")
    date_str_iso = today.strftime("%Y-%m-%d")
    date_veille  = yesterday.strftime("%d%m%Y")
    date_aff     = today.strftime("%d/%m/%Y")
    heure_run    = today.strftime("%Hh%M")

    run_label = (
        "Analyse du matin (cotes d ouverture)"
        if today.hour < 10
        else "Analyse de mi-journee (cotes fraiches + pronostics)"
    )
    activer_presse = True

    log.info("=" * 70)
    log.info(f"  PMU SCORER v15.2 - {date_aff} - {heure_run}")
    log.info(f"  Mode GRATUIT : scraping Geny + Zone-Turf + Canalturf + Equidia")
    log.info(f"  Selection 3 niveaux : {'OK' if SELECTION_DISPO else 'NON'}")
    log.info(f"  {info_patterns()}")
    log.info("=" * 70)


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

        nr         = reunion.get("numOfficiel")
        if not nr:
            log.warning("Reunion sans numero officiel : ignoree")
            continue
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        courses    = reunion.get("courses", [])
        terrain_r  = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain_r, dict):
            terrain_r = terrain_r.get("libelle", "") or terrain_r.get("code", "")

        log.info(f"\n> R{nr} - {hippodrome} | {terrain_r} ({len(courses)} courses)")

        for course in courses:
            nc         = course.get("numOrdre")
            if not nc:
                log.warning("Course sans numero officiel : ignoree")
                continue
            discipline = course.get("discipline", "")
            if discipline not in DISCIPLINES:
                continue
            if 'SIMPLE_PLACE' not in marches_internet(course):
                log.info(f'R{nr}C{nc} sans simple place PMU Internet : ignoree')
                continue

            terrain = course.get("terrain") or course.get("etatSol") or terrain_r
            if isinstance(terrain, dict):
                terrain = terrain.get("libelle", "") or terrain.get("code", "")

            if course.get("heureDepart", 0) <= datetime.now(TZ_PARIS).timestamp() * 1000:
                log.info(f"R{nr}C{nc} deja partie : ignoree")
                continue
            debut_collecte = datetime.now(TZ_PARIS).isoformat()
            try:
                res = analyser_course(
                    date_str, date_str_iso, date_veille, date_aff, nr, nc, course,
                    hippodrome=hippodrome,
                    terrain=str(terrain).upper() if terrain else "",
                    activer_presse=activer_presse,
                )
                if res and res.get("tous_resultats"):
                    archiver_observation(course, 'INITIAL', res['tous_resultats'],
                                          calcul=res, debut=debut_collecte)
                    tous_csv.extend(res["tous_resultats"])
                    (courses_trot if res["type_course"] == "TROT" else courses_galop).append(res)
            except Exception as e:
                log.error(f"Erreur R{nr} C{nc}: {e}")
            time.sleep(0.5)

    log.info(f"\nGALOP: {len(courses_galop)} | TROT: {len(courses_trot)}")

    if tous_csv:
        nom_fichier = os.path.join(OUTPUT_DIR, f"pmu_{today.strftime('%Y%m%d_%H%M')}.csv")
        colonnes = [
            "reunion","course","heure","hippodrome","terrain","libelle",
            "discipline","type_course","type_course_details","distance_m",
            "nb_partants","num_partant","nom_cheval","age","place_corde","poids_porte",
            "deferre","deferrage_code","qualite_version","paris_disponibles","value_bet","est_outsider_surprise","consensus_fort","rk_meilleur",
            "musique","source_performances","nb_performances_detaillees",
            "jockey","entraineur","proprietaire","cote_veille","cote_jour","variation_cote_%",
            "nb_pronostics","nb_pronostics_pondere","pct_pronostics","nb_sources_total",
            "score_pronostics","score_outsider","score_forme","score_forme_fraiche",
            "score_rk","score_fautes","score_distance","score_terrain","score_mouvement",
            "score_trio_pje","score_jockey_hippo","score_progression",
            "score_hippodrome","score_corde","score_total",
            "niveau_selection",
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
    log.info("  SCORER v15.2 TERMINE")
    log.info("=" * 70)


if __name__ == "__main__":
    main()


