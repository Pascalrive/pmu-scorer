"""Collectes avant course et conseils actualises. Aucune modification des ponderations."""

import csv
import glob
import json
import logging
import os
from pathlib import Path
import hashlib
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    TZ_PARIS = ZoneInfo('Europe/Paris')
except ImportError:
    from datetime import timezone, timedelta
    TZ_PARIS = timezone(timedelta(hours=2))

import requests
from pmu_tracking import erreur_identite, erreur_chevaux, envoyer_trace, paris_affiches, formater_selection, archiver_observation, dernieres_selections
from pmu_signaux import marches_internet, preparer_experience, formater_alertes

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
DISCIPLINES_GALOP = {"PLAT", "HAIE", "HAIES", "STEEPLE", "STEEPLECHASE", "STEEPLE_CHASE", "GALOP"}
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
ETAT_FICHIER    = os.path.join(OUTPUT_DIR, "observations", "etat_{date}.json")
SOURCE_CSV = None

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
def telegram_send(texte: str, experience=None) -> bool:
    return envoyer_trace(texte, TELEGRAM_TOKEN, TELEGRAM_CHAT, experience=experience)


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
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
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
    global SOURCE_CSV
    SOURCE_CSV = {'fichier': fichier, 'sha256': hashlib.sha256(Path(fichier).read_bytes()).hexdigest()}
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
                    "musique":        r.get('musique', ''),
                    "qualite_version": r.get('qualite_version', 'avant-correctifs'),
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
                      partants_actuels: list, marches=None) -> dict:
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
            "musique": p_actuel.get('musique') or ch.get('musique', ''),
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

    tous_partants_observes = [dict(c) for c in chevaux_actualises]
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
    experience = preparer_experience(tous_partants_observes, chevaux_actualises[:2], len(partants_actuels), marches)

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
        "tous_partants_observes": tous_partants_observes,
        "top2_final":  chevaux_actualises[:5],  # MODIF 28/05 : 5 choix (était 2)
        "tous_top5":   chevaux_actualises,
        "non_partants": non_partants_matin,
        "nb_sources_frais": pronos_frais.get("nb_sources", 0),
        "paris_disponibles": marches,
        "experience": experience,
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

        nr         = reunion.get("numOfficiel")
        if not nr:
            log.warning("Reunion sans numero officiel : ignoree")
            continue
        hippodrome = reunion.get("hippodrome", {}).get("libelleLong", "?")
        terrain_r  = reunion.get("terrain") or reunion.get("etatSol") or ""
        if isinstance(terrain_r, dict):
            terrain_r = terrain_r.get("libelle", "") or terrain_r.get("code", "")

        for course in reunion.get("courses", []):
            nc         = course.get("numOrdre")
            if not nc:
                log.warning("Course sans numero officiel : ignoree")
                continue
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
                "paris_disponibles": marches_internet(course),
            })

    courses.sort(key=lambda x: x["heure_ts"])
    log.info(f"{len(courses)} courses au programme du jour")
    return courses


# ──────────────────────────────────────────────
#  FORMAT MESSAGE H-15MIN (v4 - inchange sauf emoji mvt)
# ──────────────────────────────────────────────
def formater_message_h15(course: dict, partants: list,
                          maj: dict) -> str:
    depart = datetime.fromtimestamp(course['heure_ts'] / 1000, tz=TZ_PARIS)
    phase = course.get('phase', 'H15')
    lignes = [f"COURSE R{course['nr']}C{course['nc']} — DEPART {depart:%Hh%M}",
               f"DATE : {depart:%Y-%m-%d}",
               course['hippodrome'].replace('HIPPODROME DE ', ''), course['libelle'],
               '', '🔄 ACTUALISATION' if phase == 'H15' else '🔄 CONTROLE FINAL',
               f"Donnees verifiees a {datetime.now(TZ_PARIS):%Hh%M}"]
    # Le marqueur ACTUALISATION reste present pour le journal des controles finaux.
    if phase != 'H15':
        lignes.append('ACTUALISATION des conseils')
    etats = {'CHANGEMENT': 'Selection modifiee', 'ATTENTION': 'Points a verifier',
              'CONFIRME': 'Selection confirmee', 'RENFORCE': 'Selection maintenue',
              'INDISPONIBLE': 'Donnees insuffisantes'}
    lignes.append(etats.get(maj.get('verdict'), 'Selection actualisee'))
    if maj.get('non_partants'):
        lignes.append('Non-partants : ' + ', '.join(maj['non_partants']))
    lignes.append('')
    lignes.extend(formater_selection(maj.get('top2_final', [])[:2], len(partants), True, maj.get('paris_disponibles'), day=depart.date().isoformat()))
    if depart.date().isoformat() < '2026-11-02':
        lignes.extend(formater_alertes(maj.get('experience', {}).get('alertes', [])))
    lignes.extend(['', 'Remplace le conseil precedent pour cette course.'])
    return '\n'.join(lignes)


# ──────────────────────────────────────────────
#  PROGRAMME PRINCIPAL v5 - PONCTUEL (sans attente)
# ──────────────────────────────────────────────
def phase_collecte(minutes):
    # Fenetres tolerantes aux retards GitHub ; aucun passage exact garanti.
    if 0 < minutes <= 8:
        return 'H5'
    if 8 < minutes <= 25:
        return 'H15'
    if 40 <= minutes <= 75:
        return 'H60'
    return None


def conseil_change(maj, nb_partants, precedent, *, day=None):
    if not precedent:
        return True
    day = day or datetime.now(TZ_PARIS).date().isoformat()
    top = maj.get('top2_final', [])[:2]
    # Comparer les numeros ET le type de pari, sans compter les variations de cote.
    txt = f'COURSE R1C1 — DEPART 23h59\nDATE : {day}\n' + '\n'.join(formater_selection(top, nb_partants, True, maj.get('paris_disponibles'), day=day))
    from pmu_tracking import analyser_message
    event = analyser_message(txt, datetime.now(TZ_PARIS))
    old = precedent['event']
    alerts = lambda e: [(str(p['num_partant']), p['motif']) for p in (e or {}).get('alertes', [])]
    return ((event['choix'], event['paris']) != (old['choix'], old['paris'])
            or (day < '2026-11-02' and
                alerts(maj.get('experience')) != alerts(precedent.get('experience'))))


def main():
    today = datetime.now(TZ_PARIS)
    date_str, date_iso, day = today.strftime('%d%m%Y'), today.strftime('%Y-%m-%d'), today.strftime('%Y%m%d')
    pronos = charger_pronos_matin(day)
    if not pronos:
        log.warning('Pas de CSV du jour : aucun conseil actualise')
    courses = get_courses_du_jour(date_str)
    deja = charger_etat(day)
    records = [json.loads(p.read_text()) for p in Path('resultats/journal').glob(f'{day}-*.json')]
    derniers = dernieres_selections(records, day)
    for course in courses:
        nr, nc = course['nr'], course['nc']
        cle = f'R{nr}C{nc}'
        now = datetime.now(TZ_PARIS)
        phase = phase_collecte((course['heure_ts'] / 1000 - now.timestamp()) / 60)
        if not phase or f'{cle}:{phase}' in deja:
            continue
        debut = now.isoformat()
        payload = api_get(f'/programme/{date_str}/R{nr}/C{nc}/participants')
        raw = payload.get('participants', []) if isinstance(payload, dict) else []
        if not raw:
            archiver_observation(course, phase, raw, debut=debut, calcul={'erreur': 'Partants indisponibles'})
            continue  # Reessayer au prochain passage, sans valider l'etape.
        actifs = [p for p in raw if p.get('statut') != 'NON_PARTANT']
        if any(extraire_cote(p) <= 0 for p in actifs):
            archiver_observation(course, phase + '_AVANT_REESSAI', raw, debut=debut, source_csv=SOURCE_CSV)
            second = api_get(f'/programme/{date_str}/R{nr}/C{nc}/participants')
            if isinstance(second, dict) and second.get('participants'):
                raw = second['participants']
                actifs = [p for p in raw if p.get('statut') != 'NON_PARTANT']
        matin = pronos.get((f'R{nr}', f'C{nc}'), [])
        if phase == 'H60':
            archiver_observation(course, phase, raw, debut=debut, source_csv=SOURCE_CSV)
            deja.add(f'{cle}:{phase}')
            sauver_etat(day, deja)
            continue
        if not matin:
            archiver_observation(course, phase, raw, debut=debut, calcul={'erreur': 'CSV initial absent'})
            continue
        # Une absence dans une reponse partielle ne prouve pas un forfait.
        numeros = {str(p.get('numPmu') or p.get('numero')) for p in raw}
        if {str(c['num_partant']) for c in matin} - numeros:
            archiver_observation(course, phase, raw, debut=debut,
                                  calcul={'erreur': 'Liste des partants incomplete'}, source_csv=SOURCE_CSV)
            continue
        officiel = api_get(f'/programme/{date_str}/R{nr}/C{nc}')
        raison = erreur_identite(course, officiel, nr, nc)
        for ch in matin:
            raison = raison or erreur_identite(ch, officiel, nr, nc)
        raison = raison or erreur_chevaux([{'num': c['num_partant'], 'nom': c['nom_cheval']} for c in matin], raw)
        if raison:
            log.error('%s : %s ; aucun conseil', cle, raison)
            archiver_observation(course, phase, raw, debut=debut, calcul={'erreur': raison}, source_csv=SOURCE_CSV)
            continue
        marches = marches_internet(officiel)
        if 'SIMPLE_PLACE' not in marches:
            archiver_observation(course, phase, raw, debut=debut,
                                  calcul={'erreur': 'Simple place PMU Internet non propose'}, source_csv=SOURCE_CSV)
            continue
        maj = actualiser_course(matin, date_iso, int(nr), int(nc), course['libelle'], actifs, marches)
        archiver_observation(course, phase, raw, calcul=maj, debut=debut, source_csv=SOURCE_CSV)
        if not actifs or any(extraire_cote(p) <= 0 for p in actifs):
            log.warning('%s : cotes incompletes, aucun nouveau conseil', cle)
            continue
        precedent = derniers.get(cle)
        if date_iso >= '2026-11-02' and not precedent and not any(x.startswith('COUPLE ORDRE :') for x in paris_affiches(maj.get('top2_final',[])[:2], len(actifs), marches, day=date_iso)):
            continue
        if precedent and precedent.get('delivery') != 'SENT':
            log.warning('%s : envoi precedent incertain, verification manuelle necessaire', cle)
            continue
        if precedent and precedent['event'].get('source') != 'MATIN' and not conseil_change(maj, len(actifs), precedent, day=date_iso):
            deja.add(f'{cle}:{phase}')  # Donnees archivees, aucun message identique.
        elif telegram_send(formater_message_h15({**course, 'phase': phase}, actifs, maj), maj.get('experience')):
            deja.add(f'{cle}:{phase}')
        sauver_etat(day, deja)


if __name__ == "__main__":
    main()
