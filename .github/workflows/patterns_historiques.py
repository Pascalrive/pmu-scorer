# -*- coding: utf-8 -*-
"""
patterns_historiques.py
========================
Analyse les CSV d'audit accumulés (audit_YYYYMMDD.csv dans /resultats)
pour identifier les profils de courses qui GAGNENT le plus historiquement.

Usage par pmu_scorer.py :
    from patterns_historiques import detecter_pattern_gagnant
    if detecter_pattern_gagnant(course_data):
        # ajouter emoji 🎯

Pattern gagnant = combinaison de critères qui historiquement
produit un taux de placés > 50%.

Si moins de 50 audits accumulés, le module retourne False
pour TOUS les appels (pas assez de données pour fiabilité).
"""
from __future__ import annotations

import csv
import glob
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

OUTPUT_DIR = "resultats"

# Seuils retenus apres analyse des 143 paris du 12-16/05/2026 :
# - Cote 3-8 : 67% places, ROI +36%
# - Partants <= 10 : 67% places, ROI +91%
# - Score >= 50 + ecart >= 5 : profil le plus fiable
# - Plus de 50 audits pour activer (sinon trop fragile)
NB_MIN_AUDITS = 50


@dataclass
class ProfilGagnant:
    """Decrit un profil historiquement gagnant."""
    cote_min: float
    cote_max: float
    score_min: float
    ecart_min: float
    partants_max: int
    taux_observe: float  # taux de places observe historiquement


# Profils gagnants identifies sur les premiers audits.
# Seront a recalibrer quand on aura >= 200 audits.
PROFILS_GAGNANTS = [
    # Profil 1 : Petit champ + cote raisonnable (le plus fiable)
    ProfilGagnant(cote_min=2.5, cote_max=8.0,
                  score_min=40.0, ecart_min=3.0,
                  partants_max=10, taux_observe=0.67),
    # Profil 2 : Tres gros ecart de score (signal fort)
    ProfilGagnant(cote_min=1.8, cote_max=12.0,
                  score_min=40.0, ecart_min=10.0,
                  partants_max=14, taux_observe=1.00),
    # Profil 3 : Favori avec consensus
    ProfilGagnant(cote_min=2.0, cote_max=5.0,
                  score_min=45.0, ecart_min=5.0,
                  partants_max=12, taux_observe=0.75),
]


def _to_float(v, default=0.0):
    try:
        return float(v) if v not in ("", None) else default
    except (ValueError, TypeError):
        return default


def _to_int(v, default=0):
    try:
        return int(float(v)) if v not in ("", None) else default
    except (ValueError, TypeError):
        return default


def compter_audits() -> int:
    """Compte le nombre d'audits disponibles dans /resultats."""
    pattern = os.path.join(OUTPUT_DIR, "audit_*.csv")
    fichiers = sorted(glob.glob(pattern))
    total = 0
    for f in fichiers:
        try:
            with open(f, "r", encoding="utf-8-sig") as fp:
                total += sum(1 for _ in csv.DictReader(fp))
        except Exception:
            pass
    return total


def match_profil(course_data: dict, profil: ProfilGagnant) -> bool:
    """Verifie si une course matche un profil gagnant donne."""
    cote = _to_float(course_data.get("cote_n1") or course_data.get("cote_jour"))
    score = _to_float(course_data.get("score_n1") or course_data.get("score_total"))
    ecart = _to_float(course_data.get("ecart_n1_n2"))
    partants = _to_int(course_data.get("nb_partants"))

    if not (profil.cote_min <= cote <= profil.cote_max):
        return False
    if score < profil.score_min:
        return False
    if ecart < profil.ecart_min:
        return False
    if partants > 0 and partants > profil.partants_max:
        return False
    return True


def detecter_pattern_gagnant(course_data: dict, nb_audits_minimum: int = NB_MIN_AUDITS) -> bool:
    """
    Point d'entree principal pour le scorer.

    Args:
        course_data : dict avec les cles :
            - 'cote_n1' (ou 'cote_jour')
            - 'score_n1' (ou 'score_total')
            - 'ecart_n1_n2'
            - 'nb_partants'
        nb_audits_minimum : seuil sous lequel on ne se prononce pas

    Returns:
        True si la course matche au moins UN profil gagnant historique
        ET qu'on a assez de donnees pour etre fiable.
    """
    # Garde-fou : pas assez de donnees historiques
    nb_audits = compter_audits()
    if nb_audits < nb_audits_minimum:
        return False

    # Verifier si au moins un profil matche
    for profil in PROFILS_GAGNANTS:
        if match_profil(course_data, profil):
            return True
    return False


def calculer_score_opportunite(course_data: dict) -> float:
    """
    Score d'opportunite secondaire (0-100) base sur les 4 facteurs cles
    identifies dans l'analyse historique :
        - score N1 brut
        - ecart N1-N2
        - cote (zone optimale 3-8)
        - nombre de partants (moins = mieux)

    Utilise pour le tri "Top10 du jour" dans le scorer.
    """
    score_n1 = _to_float(course_data.get("score_n1") or course_data.get("score_total"))
    ecart    = _to_float(course_data.get("ecart_n1_n2"))
    cote     = _to_float(course_data.get("cote_n1") or course_data.get("cote_jour"))
    partants = _to_int(course_data.get("nb_partants"))

    # Composante 1 : score brut (0-40 points)
    if score_n1 >= 50: c1 = 40
    elif score_n1 >= 45: c1 = 30
    elif score_n1 >= 40: c1 = 20
    elif score_n1 >= 35: c1 = 10
    else: c1 = 0

    # Composante 2 : ecart N1/N2 (0-25 points)
    if ecart >= 10: c2 = 25
    elif ecart >= 5: c2 = 18
    elif ecart >= 3: c2 = 12
    elif ecart >= 1: c2 = 5
    else: c2 = 0

    # Composante 3 : cote dans zone optimale (0-20 points)
    if 3.0 <= cote <= 8.0: c3 = 20
    elif 2.0 <= cote < 3.0: c3 = 15
    elif 8.0 < cote <= 12.0: c3 = 10
    elif 1.8 <= cote < 2.0: c3 = 8
    else: c3 = 0  # < 1.8 ou > 12

    # Composante 4 : nb partants (0-15 points)
    if partants == 0: c4 = 7  # inconnu, neutre
    elif partants <= 10: c4 = 15
    elif partants <= 13: c4 = 8
    elif partants <= 15: c4 = 3
    else: c4 = 0

    return float(c1 + c2 + c3 + c4)


def info_patterns() -> str:
    """Renvoie un texte descriptif des patterns actifs (pour log/debug)."""
    nb = compter_audits()
    actif = "OUI" if nb >= NB_MIN_AUDITS else "NON (pas assez de donnees)"
    txt = [f"Patterns historiques : {actif} ({nb} audits accumules)"]
    if nb >= NB_MIN_AUDITS:
        txt.append(f"  {len(PROFILS_GAGNANTS)} profils gagnants actifs :")
        for i, p in enumerate(PROFILS_GAGNANTS, 1):
            txt.append(
                f"    {i}. Cote {p.cote_min}-{p.cote_max} | "
                f"Score >= {p.score_min} | Ecart >= {p.ecart_min} | "
                f"Partants <= {p.partants_max} "
                f"(taux histo : {p.taux_observe:.0%})"
            )
    return "\n".join(txt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(info_patterns())
