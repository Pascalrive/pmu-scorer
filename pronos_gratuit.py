# -*- coding: utf-8 -*-
"""
pronos_gratuit.py - Remplacement gratuit de get_pronostics_claude()
====================================================================
Scrape directement les sites de pronostics gratuits au lieu de passer
par l'API Claude (qui coute 50EUR / 4 jours en mode v14).

Sources scrapees :
  1. Geny "chevaux reperes"    -> page unique = top1 par course/reunion
  2. Geny "partants" par course -> base + pronostics presse
  3. Zone-Turf "pronos toile"   -> consensus toile
  4. Canalturf                  -> pronos journalistes
  5. Equidia                    -> URL predictive R{n}/C{n}

Usage (remplacement direct dans pmu_scorer.py) :
    from pronos_gratuit import get_pronostics_gratuit
    pronos = get_pronostics_gratuit(date_str, reunion_num, course_num,
                                    nom_course, partants)

Retour : meme format que get_pronostics_claude() v14, soit :
    {
      "nb_sources": int,
      "scores": {nom_cheval_normalise: float entre 0 et 100},
      "details": str (synthese pour log),
      "raw_text": str (concat brut des sources, pour debug)
    }
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
TIMEOUT = 8  # secondes
DELAI_ENTRE_REQUETES = 0.6  # politesse entre fetchs (anti-rate-limit)

# Ponderation par source (ajustable). Geny pese le plus car couvre tout.
POIDS_SOURCES = {
    "geny_reperes": 25,    # cheval N1 du jour selon Geny
    "geny_course": 20,     # presse Paris-Turf via Geny
    "zone_turf": 20,       # consensus toile
    "canalturf": 20,       # journalistes
    "equidia": 15,         # analyse Equidia
}

# Cache global pour eviter de re-scraper la meme page entre courses
_CACHE: dict[str, str] = {}


# ----------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------
def normalize(s: str) -> str:
    """Normalise un nom de cheval pour comparaison robuste."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).strip().upper()
    return s


def http_get(url: str, *, use_cache: bool = True) -> Optional[str]:
    """Fetch HTTP avec cache, gestion d'erreurs et politesse."""
    if use_cache and url in _CACHE:
        return _CACHE[url]
    try:
        time.sleep(DELAI_ENTRE_REQUETES)
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            html = r.text
            if use_cache:
                _CACHE[url] = html
            return html
        log.debug("HTTP %s sur %s", r.status_code, url)
    except requests.RequestException as e:
        log.debug("Erreur fetch %s : %s", url, e)
    return None


def trouver_cheval(texte: str, partants: list[dict]) -> set[str]:
    """Cherche les noms de partants mentionnes dans un texte."""
    txt_norm = normalize(texte)
    trouves: set[str] = set()
    for p in partants:
        nom_norm = normalize(p["nom"])
        if not nom_norm:
            continue
        # Match plein-mot pour eviter "BARZA" qui matche "BARZAMBITION"
        # Tolere les noms en plusieurs mots.
        pat = r"\b" + re.escape(nom_norm) + r"\b"
        if re.search(pat, txt_norm):
            trouves.add(p["nom"])
    return trouves


# ----------------------------------------------------------------------
# Scrapers
# ----------------------------------------------------------------------
@dataclass
class ResultatSource:
    """Resultat d'un scraper : chevaux mentionnes + rang si dispo."""
    source: str
    poids: int
    rangs: dict[str, int] = field(default_factory=dict)  # nom -> rang (1=meilleur)

    @property
    def chevaux(self) -> set[str]:
        return set(self.rangs.keys())


def scrape_geny_reperes(date_str: str, reunion: int, course: int,
                        partants: list[dict]) -> ResultatSource:
    """
    Geny publie une page unique avec UN cheval repere par course :
        https://www.geny.com/reperes-pmu

    Format observe :
        '4 - Prix des Ducs de Normandie · 12 - Inexess Bleu · 3 - Igrec de Celland'
    Le cheval repere a un ID base sur son numero (12 = N12).
    """
    res = ResultatSource("geny_reperes", POIDS_SOURCES["geny_reperes"])
    html = http_get("https://www.geny.com/reperes-pmu")
    if not html:
        return res

    # Recherche par nom de cheval directement (plus robuste que parser la structure)
    soup = BeautifulSoup(html, "html.parser")
    texte = soup.get_text(" ", strip=True)
    chevaux_trouves = trouver_cheval(texte, partants)
    # Tous les chevaux reperes ici ont rang 1
    for c in chevaux_trouves:
        res.rangs[c] = 1
    return res


def scrape_geny_course(date_str: str, reunion: int, course: int,
                       partants: list[dict]) -> ResultatSource:
    """
    Page partants/pronos Geny par course. URL pattern :
        https://www.geny.com/partants-pmu/{date}-{ville}-pmu-{slug}_c{id}

    Comme on ne connait ni le slug ni l'id, on passe par la page racine
    qui liste les courses du jour avec liens.
    """
    res = ResultatSource("geny_course", POIDS_SOURCES["geny_course"])
    # On reutilise le HTML de la page reunion (mise en cache)
    racine = f"https://www.geny.com/reunions-courses-pmu/_d{date_str}"
    html = http_get(racine)
    if not html:
        return res

    soup = BeautifulSoup(html, "html.parser")
    # Cherche les liens vers les courses
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "partants-pmu" not in href:
            continue
        # Filtre par numero de reunion/course si possible
        # (heuristique : le slug contient la ville, on prend tout pour l'instant)
        url = href if href.startswith("http") else "https://www.geny.com" + href
        sub = http_get(url, use_cache=True)
        if not sub:
            continue
        chevaux_trouves = trouver_cheval(sub, partants)
        # On donne rang 1 aux 3 premiers cites (heuristique grossiere)
        for i, c in enumerate(sorted(chevaux_trouves)[:5]):
            res.rangs[c] = i + 1
        if res.rangs:
            break  # une page a suffi
    return res


def scrape_zone_turf(date_str: str, reunion: int, course: int,
                     partants: list[dict]) -> ResultatSource:
    """
    Zone-Turf publie les pronostics par course sur :
        https://www.zone-turf.fr/pronostics/
    On scrape la page pronos du jour et on cherche les noms.
    """
    res = ResultatSource("zone_turf", POIDS_SOURCES["zone_turf"])
    html = http_get("https://www.zone-turf.fr/pronostics/")
    if not html:
        return res
    chevaux_trouves = trouver_cheval(html, partants)
    for c in chevaux_trouves:
        res.rangs[c] = 1
    return res


def scrape_canalturf(date_str: str, reunion: int, course: int,
                     partants: list[dict]) -> ResultatSource:
    """Canalturf - pronostics gratuits du jour."""
    res = ResultatSource("canalturf", POIDS_SOURCES["canalturf"])
    html = http_get("https://www.canalturf.com/courses_liste_pronostics.php")
    if not html:
        return res
    chevaux_trouves = trouver_cheval(html, partants)
    for c in chevaux_trouves:
        res.rangs[c] = 1
    return res


def scrape_equidia(date_str: str, reunion: int, course: int,
                   partants: list[dict]) -> ResultatSource:
    """
    Equidia a une URL predictive geniale :
        https://www.equidia.fr/courses/2026-05-09/R1/C4
    On peut taper directement la page de la course.
    """
    res = ResultatSource("equidia", POIDS_SOURCES["equidia"])
    url = f"https://www.equidia.fr/courses/{date_str}/R{reunion}/C{course}"
    html = http_get(url)
    if not html:
        return res
    chevaux_trouves = trouver_cheval(html, partants)
    for c in chevaux_trouves:
        res.rangs[c] = 1
    return res


# ----------------------------------------------------------------------
# Agregation
# ----------------------------------------------------------------------
def get_pronostics_gratuit(date_str: str,
                           reunion_num: int,
                           course_num: int,
                           nom_course: str,
                           partants: list[dict]) -> dict:
    """
    Point d'entree principal. Remplace get_pronostics_claude() de la v14.

    Args:
        date_str    : 'YYYY-MM-DD' (ex: '2026-05-09')
        reunion_num : 1, 2, ... (ex: 1 pour R1)
        course_num  : 1, 2, ...
        nom_course  : libelle pour log
        partants    : liste de dicts avec au moins {'nom': str}

    Returns:
        {
          "nb_sources": int,         # nb de sources ayant trouve >=1 cheval
          "scores":   dict,          # nom_cheval -> score 0..100
          "details":  str,           # synthese pour log
          "raw_text": str,           # bonus debug
        }
    """
    scrapers = [
        scrape_geny_reperes,
        scrape_geny_course,
        scrape_zone_turf,
        scrape_canalturf,
        scrape_equidia,
    ]

    resultats: list[ResultatSource] = []
    for fn in scrapers:
        try:
            res = fn(date_str, reunion_num, course_num, partants)
            if res.rangs:
                resultats.append(res)
        except Exception as e:
            log.debug("Scraper %s en erreur : %s", fn.__name__, e)

    # Agregation : chaque source attribue son poids aux chevaux qu'elle cite.
    # Si rang dispo, ponderation degressive : rang1=100%, rang2=70%, rang3=50%, rang4=35%, rang5=25%
    coef_rang = {1: 1.00, 2: 0.70, 3: 0.50, 4: 0.35, 5: 0.25}

    scores_brut: dict[str, float] = {}
    for r in resultats:
        for nom, rang in r.rangs.items():
            coef = coef_rang.get(rang, 0.20)
            scores_brut[nom] = scores_brut.get(nom, 0.0) + r.poids * coef

    # Normalise sur 100 (le max devient 100)
    if scores_brut:
        m = max(scores_brut.values())
        scores = {n: round(v * 100 / m, 1) for n, v in scores_brut.items()}
    else:
        scores = {}

    nb_sources = len(resultats)
    sources_noms = ", ".join(r.source for r in resultats) if resultats else "aucune"
    top3 = sorted(scores.items(), key=lambda x: -x[1])[:3]
    details = (
        f"[{nb_sources} src: {sources_noms}] "
        + " | ".join(f"{n}={s}" for n, s in top3)
        if top3 else f"[{nb_sources} src] aucun cheval reconnu"
    )

    return {
        "nb_sources": nb_sources,
        "scores": scores,
        "details": details,
        "raw_text": "",  # pas remonte par defaut (peut etre ajoute pour debug)
    }


# ----------------------------------------------------------------------
# Test rapide (executable en standalone)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    partants_test = [
        {"nom": "INEXESS BLEU", "num": 12},
        {"nom": "INO DU LUPIN", "num": 7},
        {"nom": "IDAO DE TILLARD", "num": 15},
        {"nom": "JEAN BALTHAZAR", "num": 8},
        {"nom": "KOBAYASHI", "num": 2},
    ]
    res = get_pronostics_gratuit("2026-05-09", 1, 4,
                                 "PRIX DES DUCS DE NORMANDIE",
                                 partants_test)
    print("=" * 60)
    print(f"Resultat : {res['details']}")
    print(f"Scores : {res['scores']}")
