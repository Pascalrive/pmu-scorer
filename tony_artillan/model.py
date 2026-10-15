"""Regles et comptabilite en centimes ; aucun acces reseau ni autre algorithme."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import re
import unicodedata

VERSION = 'tony-artillan-v1-2026-10-15'
BASE = 10000
TERMINAL = {'GAGNE', 'PERDU', 'REMBOURSE', 'NON_JOUE'}


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Horodatage sans fuseau horaire')
    return result


def norm(value):
    return re.sub('[^A-Z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().upper())


def choose_meeting(programme):
    candidates = [r for r in programme['programme']['reunions']
                  if r.get('pays', {}).get('code') == 'FRA'
                  and len(r.get('courses', [])) == 8
                  and {c['numOrdre'] for c in r['courses']} == set(range(1, 9))]
    principal = [r for r in candidates if r.get('numOfficiel') == 1]
    if principal:
        return principal[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError('Pas de R1 francaise a huit courses ; autre reunion unique non identifiable')


def new_day(day, meeting, now):
    races = sorted(meeting['courses'], key=lambda c: c['numOrdre'])
    departures = [datetime.fromtimestamp(c['heureDepart']/1000, now.tzinfo) for c in races]
    if departures != sorted(departures) or any(d.date() != now.date() for d in departures):
        raise ValueError('Ordre ou date des departs incoherent')
    return {'schema': 1, 'version': VERSION, 'date': day, 'virtual_only': True,
            'created_at': now.isoformat(), 'r': meeting['numOfficiel'],
            'venue': meeting['hippodrome']['libelleLong'], 'source_status': 'EN_ATTENTE_PARIS_TURF',
            'races': [{'c': c['numOrdre'], 'id': f"R{meeting['numOfficiel']}C{c['numOrdre']}",
                       'title': c['libelle'], 'departure': d.isoformat(),
                       'market': c.get('hasEParis') is not False and any(p.get('typePari') == 'E_SIMPLE_GAGNANT' and p.get('enVente') is not False
                                     for p in c.get('paris', [])), 'status': 'A_VENIR'}
                      for c, d in zip(races, departures)], 'notifications': []}


def validate_tips(document, state, participants, now):
    """Import de huit premiers choix explicitement attribues a Paris Turf.

    Le document est fourni/controle humainement, jamais remplace par un favori PMU.
    Le contenu source est conserve avec l'import, sans reconstruction apres course.
    """
    if norm(document.get('publisher', '')) != 'PARISTURF' or document.get('date') != state['date']:
        raise ValueError('Editeur ou date Paris Turf non concordant')
    if document.get('r') != state['r'] or not document.get('source_url', '').startswith('https://'):
        raise ValueError('Reunion ou reference source absente')
    captured = stamp(document['captured_at'])
    if captured > now:
        raise ValueError('Capture source dans le futur')
    rows = document.get('races', [])
    if len(rows) != 8 or {r['c'] for r in rows} != set(range(1, 9)):
        raise ValueError('Les huit pronostics Paris Turf sont requis')
    result = {}
    for tip in rows:
        race = state['races'][tip['c']-1]
        if norm(tip['title']) != norm(race['title']):
            raise ValueError('Titre de course non concordant')
        if captured >= stamp(race['departure']) or now >= stamp(state['races'][0]['departure']):
            raise ValueError('Import trop tardif : aucun rattrapage retrospectif')
        horse = next((p for p in participants[tip['c']] if p['numPmu'] == tip['number']), None)
        if not horse or norm(horse['nom']) != norm(tip['name']):
            raise ValueError('Numero/nom du cheval non concordant')
        result[tip['c']] = {'number': tip['number'], 'name': horse['nom'],
                           'source_url': document['source_url'], 'captured_at': captured.isoformat(),
                           'imported_at': now.isoformat(), 'publisher': 'Paris Turf'}
    return result


def next_stake(races, index):
    stake = BASE
    for race in races[:index]:
        status = race['status']
        if status not in TERMINAL:
            return None
        if status == 'GAGNE':
            stake = BASE
        elif status == 'PERDU':
            stake += BASE
        # NP, remboursement et absence de pari : pas de gain/perte, mise inchangee.
    return stake


def reserve(races, index, now, horse):
    race = races[index]
    if race['status'] != 'A_VENIR' or 'selection' not in race:
        return False
    if now >= stamp(race['departure']):
        return False
    stake = next_stake(races, index)
    if stake is None or not race['market']:
        return False
    if not horse or horse.get('statut') != 'PARTANT' or norm(horse['nom']) != norm(race['selection']['name']):
        return False
    race.update(status='ENGAGE_VIRTUEL', stake_cents=stake, reserved_at=now.isoformat(),
                odds=horse.get('dernierRapportDirect') or horse.get('dernierRapportReference'))
    return True


def settle(race, payload, participants, now, url):
    if race['status'] != 'ENGAGE_VIRTUEL' or now < stamp(race['departure']):
        return False
    n = race['selection']['number']
    horse = next((p for p in participants if p.get('numPmu') == n), None)
    if not horse or norm(horse.get('nom', '')) != norm(race['selection']['name']):
        return False
    tables = [p for p in payload if p.get('typePari') == 'E_SIMPLE_GAGNANT'] if isinstance(payload, list) else []
    if len(tables) != 1:
        return False
    table = tables[0]
    stake = race['stake_cents']
    if table.get('rembourse') is True or horse.get('statut') == 'NON_PARTANT':
        status, returned = 'REMBOURSE', stake
    else:
        reports = table.get('rapports', [])
        if not reports or any('dividendePourUnEuro' not in x for x in reports):
            return False
        try:
            rates = [Decimal(str(x['dividendePourUnEuro'])) for x in reports]
        except (InvalidOperation, ValueError, TypeError):
            return False
        if any(not r.is_finite() or r <= 0 for r in rates):
            return False
        matching = [x for x in reports if str(x.get('combinaison', '')).strip() == str(n)]
        if len(matching) > 1:
            return False
        if matching:
            rate = Decimal(str(matching[0]['dividendePourUnEuro']))
            if not rate.is_finite() or rate <= 0:
                return False
            status = 'GAGNE'
            returned = int((Decimal(stake)*rate/100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            race['official_dividend_cents_per_euro'] = str(rate)
        else:
            # Liste definitive du simple gagnant connue : cheval non gagnant.
            if any(not re.fullmatch(r'\d+', str(x.get('combinaison', '')).strip()) for x in reports):
                return False
            status, returned = 'PERDU', 0
    race.update(status=status, return_cents=returned, profit_cents=returned-stake,
                settled_at=now.isoformat(), result_url=url, rank=horse.get('ordreArrivee'))
    return True


def score(state):
    settled = [r for r in state['races'] if r['status'] in {'GAGNE','PERDU','REMBOURSE'}]
    stakes = sum(r['stake_cents'] for r in settled)
    returns = sum(r['return_cents'] for r in settled)
    pending = [r for r in state['races'] if r['status'] == 'ENGAGE_VIRTUEL']
    balance = 0
    minimum = 0
    for race in state['races']:
        if 'stake_cents' in race:
            balance -= race['stake_cents']
            minimum = min(minimum, balance)
            balance += race.get('return_cents', 0)
    return {'settled_bets': len(settled), 'wins': sum(r['status']=='GAGNE' for r in settled),
            'losses': sum(r['status']=='PERDU' for r in settled),
            'refunds': sum(r['status']=='REMBOURSE' for r in settled),
            'stake_cents': stakes, 'return_cents': returns, 'profit_cents': returns-stakes,
            'roi_percent': str((Decimal(returns-stakes)*100/stakes).quantize(Decimal('.01'))) if stakes else None,
            'pending_stake_cents': sum(r['stake_cents'] for r in pending),
            'cash_required_cents': -minimum, 'max_stake_cents': max([r.get('stake_cents',0) for r in state['races']]),
            'complete': all(r['status'] in TERMINAL for r in state['races'])}
