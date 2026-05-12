"""
=============================================================
  ANALYSE AUDIT - Consolidation des CSV audit_YYYYMMDD.csv
=============================================================
  Lance localement (ou en GitHub Action manuel) apres avoir
  accumule >= 100 paris dans /resultats.

  Usage :
      python analyse_audit.py

  Produit un rapport texte qui repond aux questions :
    - Le score predit-il vraiment la reussite ?
    - L'ecart N1/N2 ameliore-t-il la decision ?
    - Quels filtres sont efficaces ?
    - Quelle decision V2 a le meilleur ROI reel ?
=============================================================
"""

import csv
import glob
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime

OUTPUT_DIR = "resultats"


def lire_tous_audits() -> list:
    """Charge tous les audit_*.csv du dossier /resultats."""
    pattern = os.path.join(OUTPUT_DIR, "audit_*.csv")
    fichiers = sorted(glob.glob(pattern))
    lignes = []
    for f in fichiers:
        with open(f, "r", encoding="utf-8-sig") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                lignes.append(row)
    return lignes


def to_float(v, default=0.0):
    try:
        return float(v) if v not in ("", None) else default
    except (ValueError, TypeError):
        return default


def to_int(v, default=0):
    try:
        return int(float(v)) if v not in ("", None) else default
    except (ValueError, TypeError):
        return default


def analyse_par_tranche(rows, cle_tranche, tranches_def):
    """
    Decoupe les paris en tranches selon une cle (ex: score, cote)
    et calcule pour chaque tranche : nb, % places, ROI reel.
    """
    buckets = defaultdict(lambda: {"nb": 0, "places": 0, "investi": 0.0, "retour": 0.0})
    for row in rows:
        val = to_float(row.get(cle_tranche))
        a_place = to_int(row.get("n1_a_place"))
        mise = to_float(row.get("p1_mise"))
        gain = to_float(row.get("p1_gain"))

        # Trouve la tranche
        nom_tranche = None
        for label, (mini, maxi) in tranches_def:
            if mini <= val < maxi:
                nom_tranche = label
                break
        if not nom_tranche:
            continue

        b = buckets[nom_tranche]
        b["nb"] += 1
        b["places"] += a_place
        b["investi"] += mise
        b["retour"] += gain

    return buckets


def afficher_tranches(titre, buckets, ordre_tranches):
    print(f"\n{titre}")
    print("-" * 78)
    print(f"{'Tranche':<20} {'N':>5} {'Places':>8} {'Taux':>7} {'Investi':>10} {'Retour':>10} {'ROI':>7}")
    print("-" * 78)
    for tranche in ordre_tranches:
        b = buckets.get(tranche)
        if not b or b["nb"] == 0:
            print(f"{tranche:<20} {'-':>5}")
            continue
        taux = b["places"] / b["nb"] * 100
        roi = (b["retour"] - b["investi"]) / b["investi"] * 100 if b["investi"] > 0 else 0
        print(f"{tranche:<20} {b['nb']:>5} {b['places']:>8} {taux:>6.0f}% "
              f"{b['investi']:>9.2f}e {b['retour']:>9.2f}e {roi:>+6.0f}%")


def analyse_decision_v2(rows):
    """ROI reel par decision V2 simulee."""
    buckets = defaultdict(lambda: {"nb": 0, "places": 0, "investi": 0.0, "retour": 0.0})
    for row in rows:
        d = row.get("v2_decision", "")
        a_place = to_int(row.get("n1_a_place"))
        mise = to_float(row.get("p1_mise"))
        gain = to_float(row.get("p1_gain"))
        b = buckets[d]
        b["nb"] += 1
        b["places"] += a_place
        if d in ("PARI FORT", "PARI PRUDENT"):
            b["investi"] += mise
            b["retour"] += gain
    return buckets


def analyse_combinaison_filtres(rows):
    """
    Pour chaque combinaison de criteres (score, ecart, cote, partants),
    mesure le ROI reel. Aide a trouver les meilleurs filtres.
    """
    combinaisons = {
        "Tout (baseline)":
            lambda r: True,
        "Score >= 40":
            lambda r: to_float(r.get("n1_score")) >= 40,
        "Score >= 50":
            lambda r: to_float(r.get("n1_score")) >= 50,
        "Ecart N1/N2 >= 3":
            lambda r: to_float(r.get("ecart_n1_n2")) >= 3,
        "Ecart N1/N2 >= 5":
            lambda r: to_float(r.get("ecart_n1_n2")) >= 5,
        "Cote 2-12":
            lambda r: 2 <= to_float(r.get("n1_cote")) <= 12,
        "Cote 3-8":
            lambda r: 3 <= to_float(r.get("n1_cote")) <= 8,
        "Partants <= 12":
            lambda r: to_int(r.get("nb_partants")) <= 12,
        "Sources >= 1":
            lambda r: to_int(r.get("nb_sources")) >= 1,
        "Sources >= 2":
            lambda r: to_int(r.get("nb_sources")) >= 2,
        "Consensus fort":
            lambda r: to_int(r.get("consensus_fort")) == 1,
        "Value bet":
            lambda r: to_int(r.get("value_bet")) == 1,
        # Combinaisons :
        "Score>=40 & Ecart>=3":
            lambda r: to_float(r.get("n1_score")) >= 40 and to_float(r.get("ecart_n1_n2")) >= 3,
        "Score>=50 & Cote 3-8":
            lambda r: to_float(r.get("n1_score")) >= 50 and 3 <= to_float(r.get("n1_cote")) <= 8,
        "FORT v2 strict":
            lambda r: (to_float(r.get("n1_score")) >= 50
                       and to_float(r.get("ecart_n1_n2")) >= 5
                       and 2 <= to_float(r.get("n1_cote")) <= 12
                       and to_int(r.get("nb_sources")) >= 2),
    }

    resultats = []
    for nom, fn_filtre in combinaisons.items():
        sous = [r for r in rows if fn_filtre(r)]
        if not sous:
            resultats.append((nom, 0, 0, 0, 0, 0))
            continue
        places = sum(to_int(r.get("n1_a_place")) for r in sous)
        investi = sum(to_float(r.get("p1_mise")) for r in sous)
        retour = sum(to_float(r.get("p1_gain")) for r in sous)
        profit = retour - investi
        roi = (profit / investi * 100) if investi > 0 else 0
        resultats.append((nom, len(sous), places, investi, retour, roi))
    return resultats


def main():
    rows = lire_tous_audits()
    if not rows:
        print("Aucun fichier audit_*.csv trouve dans /resultats")
        print("Lance d'abord pmu_results.py pendant quelques jours.")
        return

    # En-tete
    nb_total = len(rows)
    dates = sorted(set(r.get("date", "") for r in rows if r.get("date")))
    nb_dates = len(dates)
    print("=" * 78)
    print(f"ANALYSE AUDIT - {nb_total} paris sur {nb_dates} jour(s)")
    if dates:
        print(f"Periode : {dates[0]} -> {dates[-1]}")
    print("=" * 78)

    # Avertissement echantillon
    if nb_total < 100:
        print(f"\n[AVERTISSEMENT] Seulement {nb_total} paris analyses.")
        print("Les conclusions ci-dessous ne sont PAS fiables.")
        print("Continuer a accumuler des donnees jusqu'a >= 200-300 paris.")

    # 1. Baseline
    places_total = sum(to_int(r.get("n1_a_place")) for r in rows)
    gagnants_total = sum(to_int(r.get("n1_a_gagne")) for r in rows)
    investi = sum(to_float(r.get("p1_mise")) for r in rows)
    retour = sum(to_float(r.get("p1_gain")) for r in rows)
    profit = retour - investi
    roi = (profit / investi * 100) if investi > 0 else 0
    print(f"\nBASELINE (jouer N1 systematiquement) :")
    print(f"  Paris        : {nb_total}")
    print(f"  Gagnants     : {gagnants_total} ({gagnants_total/nb_total*100:.0f}%)")
    print(f"  Places       : {places_total} ({places_total/nb_total*100:.0f}%)")
    print(f"  Investi      : {investi:.2f}e")
    print(f"  Retour reel  : {retour:.2f}e")
    print(f"  Profit reel  : {profit:+.2f}e  (ROI {roi:+.0f}%)")

    # 2. Decoupage par score
    afficher_tranches(
        "REUSSITE PAR TRANCHE DE SCORE N1",
        analyse_par_tranche(rows, "n1_score", [
            ("0-30", (0, 30)),
            ("30-35", (30, 35)),
            ("35-40", (35, 40)),
            ("40-45", (40, 45)),
            ("45-50", (45, 50)),
            ("50-55", (50, 55)),
            ("55+", (55, 999)),
        ]),
        ["0-30", "30-35", "35-40", "40-45", "45-50", "50-55", "55+"],
    )

    # 3. Decoupage par ecart N1/N2
    afficher_tranches(
        "REUSSITE PAR ECART DE SCORE N1-N2",
        analyse_par_tranche(rows, "ecart_n1_n2", [
            ("< 1", (-100, 1)),
            ("1-3", (1, 3)),
            ("3-5", (3, 5)),
            ("5-10", (5, 10)),
            ("10+", (10, 999)),
        ]),
        ["< 1", "1-3", "3-5", "5-10", "10+"],
    )

    # 4. Decoupage par cote N1
    afficher_tranches(
        "REUSSITE PAR COTE N1",
        analyse_par_tranche(rows, "n1_cote", [
            ("< 2", (0, 2)),
            ("2-3", (2, 3)),
            ("3-5", (3, 5)),
            ("5-8", (5, 8)),
            ("8-15", (8, 15)),
            ("15+", (15, 9999)),
        ]),
        ["< 2", "2-3", "3-5", "5-8", "8-15", "15+"],
    )

    # 5. Decoupage par nb partants
    afficher_tranches(
        "REUSSITE PAR NOMBRE DE PARTANTS",
        analyse_par_tranche(rows, "nb_partants", [
            ("<= 7", (0, 8)),
            ("8-10", (8, 11)),
            ("11-13", (11, 14)),
            ("14-16", (14, 17)),
            ("17+", (17, 999)),
        ]),
        ["<= 7", "8-10", "11-13", "14-16", "17+"],
    )

    # 6. Decision V2 simulee
    print("\nDECISION V2 (regle de filtrage simulee)")
    print("-" * 78)
    dv2 = analyse_decision_v2(rows)
    for nom in ("PARI FORT", "PARI PRUDENT", "NO BET", "DONNEES INSUFFISANTES"):
        b = dv2.get(nom, {"nb": 0, "places": 0, "investi": 0, "retour": 0})
        if b["nb"] == 0:
            print(f"  {nom:<25} 0 pari")
            continue
        taux = b["places"] / b["nb"] * 100
        if b["investi"] > 0:
            profit_v2 = b["retour"] - b["investi"]
            roi_v2 = profit_v2 / b["investi"] * 100
            print(f"  {nom:<25} {b['nb']:>4} paris | "
                  f"{b['places']:>3} places ({taux:>3.0f}%) | "
                  f"Profit {profit_v2:+.2f}e | ROI {roi_v2:+.0f}%")
        else:
            print(f"  {nom:<25} {b['nb']:>4} paris | "
                  f"{b['places']:>3} auraient place ({taux:>3.0f}%) | non joue")

    # 7. Comparaison de tous les filtres possibles
    print("\nCOMPARAISON DE FILTRES (trie par ROI)")
    print("-" * 78)
    resultats_filtres = analyse_combinaison_filtres(rows)
    # Tri par ROI decroissant (en ignorant les filtres sans pari)
    resultats_filtres.sort(key=lambda x: -x[5] if x[1] > 0 else 1)
    print(f"{'Filtre':<25} {'N':>5} {'Places':>7} {'Investi':>9} {'Retour':>9} {'ROI':>7}")
    print("-" * 78)
    for nom, nb, places, investi, retour, roi in resultats_filtres:
        if nb == 0:
            print(f"{nom:<25} {'0':>5}")
        else:
            print(f"{nom:<25} {nb:>5} {places:>7} "
                  f"{investi:>8.2f}e {retour:>8.2f}e {roi:>+6.0f}%")

    # 8. Conclusion automatique
    print("\n" + "=" * 78)
    print("RECOMMANDATIONS")
    print("=" * 78)

    if nb_total < 100:
        print(f"  Echantillon trop petit ({nb_total} paris). Continuer a accumuler.")
        print(f"  Cible : >= 200 paris avant de fixer une regle.")
    else:
        # Trouve le meilleur filtre (>= 30 paris, ROI max)
        candidats = [r for r in resultats_filtres
                     if r[1] >= 30 and r[0] != "Tout (baseline)"]
        if candidats:
            meilleur = max(candidats, key=lambda x: x[5])
            print(f"  Meilleur filtre observe : {meilleur[0]}")
            print(f"    -> {meilleur[1]} paris, ROI {meilleur[5]:+.0f}%")
            print(f"    -> A confirmer sur plus de donnees avant activation.")
        else:
            print("  Pas encore de filtre avec >= 30 paris.")
            print("  Continuer a accumuler des donnees.")

    print(f"\nGenere : {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
