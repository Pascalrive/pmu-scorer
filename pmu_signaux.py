"""Qualite des donnees et experience outsider, sans ajuster les ponderations."""
import math
import re

VERSION = '2026-10-12-v1'


def nombre(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def deferrage_officiel(partant):
    code = str(partant.get('deferre') or '').upper().replace('DEFERRRE', 'DEFERRE')
    if code in {'D4', 'DP4', 'DEFERRE_ANTERIEURS_POSTERIEURS'} or 'QUATRE' in code:
        return {'code': code, 'deferre': True, 'score': 80.0}
    if code in {'DA', 'DEFERRE_ANTERIEURS', 'DEFERRE_ANTERIEURS_PROTEGE_POSTERIEURS'}:
        return {'code': code, 'deferre': True, 'score': 58.0}
    if code in {'DP', 'DEFERRE_POSTERIEURS', 'PROTEGE_ANTERIEURS_DEFERRE_POSTERIEURS'}:
        return {'code': code, 'deferre': True, 'score': 65.0}
    if code.startswith(('PROTEGE_', 'FERRE')) or code in {'F', 'NON_DEFERRE'}:
        return {'code': code, 'deferre': False, 'score': 50.0}
    return {'code': code, 'deferre': None, 'score': 50.0}


def marches_internet(course):
    """Pas de deduction depuis le seul nombre de partants."""
    if course.get('hasEParis') is False:
        return []
    return sorted({p['typePari'][2:] for p in course.get('paris', [])
                   if str(p.get('typePari', '')).startswith('E_')
                   and p.get('enVente') is not False})


def alerter_outsiders(partants):
    """Regle figee : forme + baisse >=20%, cote (6,20], score dans les trois premiers.

    Ce signal est exploratoire. Il ne remplace jamais le choix envoye.
    """
    if not partants:
        return []
    scores = sorted((nombre(p.get('score_total')) for p in partants), reverse=True)
    seuil = scores[min(2, len(scores) - 1)]
    alerts = []
    for p in partants:
        perf = re.findall(r'([0-9DTRA])[a-zA-Z]', str(p.get('musique') or ''), re.I)
        forme = bool(perf) and (perf[0] == '1' or sum(x == '1' for x in perf[:3]) >= 2)
        initiale = nombre(p.get('cote_jour'))
        cote = nombre(p.get('cote_actuel'))
        if not forme or initiale <= 0 or not 6 < cote <= 20:
            continue
        variation = (cote / initiale - 1) * 100
        if variation > -20 or nombre(p.get('score_total')) < seuil:
            continue
        alerts.append({**p, 'variation_cote_pc': round(variation, 1),
                       'motif': 'Derniere sortie gagnee' if perf[0] == '1' else 'Deux victoires sur trois sorties'})
    return sorted(alerts, key=lambda p: (-nombre(p.get('score_total')), nombre(p.get('cote_actuel')), str(p['num_partant'])))


def preparer_experience(partants, selection, nb_partants, marches=None):
    from pmu_tracking import paris_affiches, analyser_message, TZ
    from datetime import datetime
    alerts = alerter_outsiders(partants)
    def event(top):
        lines = paris_affiches(top, nb_partants, marches)
        if not any(x.startswith('PARI :') for x in lines):
            return {'choix': [], 'paris': []}
        text = 'COURSE R1C1 — DEPART 23h59\n' + '\n'.join(
            [f"{i+1}er choix : N{p['num_partant']}. {p['nom_cheval']}" if i == 0
             else f"2e choix : N{p['num_partant']}. {p['nom_cheval']}" for i, p in enumerate(top)] + lines)
        parsed = analyser_message(text, datetime.now(TZ))
        return {'choix': parsed['choix'], 'paris': parsed['paris']}
    reference = event(selection[:2])
    alternative = []
    if alerts and selection and reference['paris']:
        candidate = alerts[0]
        if str(candidate['num_partant']) not in {str(p['num_partant']) for p in selection[:2]}:
            alternative = [candidate, selection[0]][:len(selection[:2])]
    shadow = event(alternative) if alternative else None
    if shadow:
        shadow['paris'] = shadow['paris'][:len(reference['paris'])]
        if len(shadow['paris']) != len(reference['paris']):
            shadow = None  # Ne jamais comparer deux budgets differents.
    return {'version': VERSION, 'alertes': alerts, 'reference': reference,
            'variante_outsider': shadow, 'mise_par_pari': '5.00'}


def formater_alertes(alerts):
    if not alerts:
        return []
    lines = ['', 'ALERTE OUTSIDER — SUIVI EXPERIMENTAL']
    for p in alerts[:2]:
        lines += [f"N{p['num_partant']}. {p['nom_cheval']} — {p['motif']}",
                  f"Cote {p['cote_jour']:.1f} → {p['cote_actuel']:.1f} ({p['variation_cote_pc']:+.1f} %)"]
    lines.append('Observation uniquement. Aucun pari supplementaire conseille.')
    return lines
