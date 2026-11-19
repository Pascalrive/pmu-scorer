"""Pure selection, ticket accounting and official settlement; integer cents."""
from collections import Counter
from datetime import datetime, timezone
from itertools import permutations
from math import isfinite
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
VERSION = 'tierce-cr-v2-toutes-courses-2026-11-19'
ARMS = {
    'tierce_favori_6_associes_30eur': ('TIERCÉ — FAVORI + 6 ASSOCIÉS — 30 €', 6),
    'tierce_favori_8_associes_56eur': ('TIERCÉ — FAVORI + 8 ASSOCIÉS — 56 €', 8),
}


def instant(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Horodatage sans fuseau')
    return dt


def tickets(base, associates):
    if base in associates or len(associates) != len(set(associates)):
        raise ValueError('Chevaux non distincts')
    return [[base, a, b] for a, b in permutations(associates, 2)]


def prepare(snapshot, now):
    race = snapshot['race']
    departure = instant(race['departure'])
    age = (now - instant(snapshot['captured_at'])).total_seconds()
    if race['date'] != now.astimezone(TZ).date().isoformat():
        raise ValueError('Date différente : aucune reconstitution')
    if not 120 < (departure - now).total_seconds() <= 3600 or not 0 <= age <= 900:
        raise ValueError('Hors fenêtre H-60 à H-2 ou sources périmées')
    if not race.get('internet_tierce_available'):
        raise ValueError('Tiercé Internet à 1 € indisponible')
    if not 0 <= (now - instant(race['odds_captured_at'])).total_seconds() <= 120:
        raise ValueError('Cotes non actualisées')
    horses = {int(n): h for n, h in race['horses'].items() if h.get('statut') == 'PARTANT'}
    quotes = {}
    for n, h in horses.items():
        q = h.get('pmu_odds') or {}
        value = q.get('value')
        stamp = q.get('official_time')
        if (q.get('kind') != 'direct' or not isinstance(value, (int, float))
                or not isfinite(value) or value <= 0 or not isinstance(stamp, (int, float))
                or not 0 <= now.timestamp() - stamp / 1000 <= 900):
            raise ValueError('Favori invérifiable : cote directe récente manquante')
        quotes[n] = value
    if len(quotes) < 7:
        raise ValueError('Nombre de partants insuffisant')
    base = min(quotes, key=lambda n: (quotes[n], n))
    votes, points, outsiders = Counter(), Counter(), Counter()
    publishers = set()
    evidence = []
    for row in snapshot['rows']:
        publisher = row.get('publisher')
        top = list(dict.fromkeys(row.get('top5', [])))
        if not publisher or publisher in publishers or len(top) != 5:
            continue
        if not row.get('url') or not row.get('sha256'):
            continue
        if not 0 <= (now - instant(row['retrieved_at'])).total_seconds() <= 900:
            continue
        if any(n not in horses for n in top):
            continue
        publishers.add(publisher)
        for i, n in enumerate(top):
            votes[n] += 1
            points[n] += 5 - i
        outsiders.update({x['number'] for x in row.get('outsiders', []) if x['number'] in horses})
        evidence.append(publisher)
    if len(publishers) < 5:
        raise ValueError('Moins de cinq pronostiqueurs complets et vérifiés')
    ranked = sorted((n for n in votes if n != base), key=lambda n: (-votes[n], -points[n], n))
    result = []
    for arm, (label, size) in ARMS.items():
        core = ranked[:size - 2]
        extra = sorted((n for n, v in outsiders.items() if v >= 2 and n != base and n not in core),
                       key=lambda n: (-outsiders[n], -votes[n], -points[n], n))[:2]
        reason = ''
        if len(core) != size - 2 or len(extra) != 2:
            reason = 'Associés incomplets : classement ou deux outsiders distincts cités par au moins deux sources absents'
        associates = core + extra
        combos = tickets(base, associates) if not reason else []
        result.append(dict(id=arm, label=label, version=VERSION, base=base, associates=associates,
                           core=core, outsiders=extra, tickets=combos, stake_cents=100 * len(combos),
                           reason=reason, publishers=evidence, votes=dict(votes), outsider_votes=dict(outsiders)))
    return result


def confirmed(record):
    try:
        receipt = record['receipt']
        departure = instant(record['race']['departure'])
        return (record['delivery'] == 'SENT' and int(receipt['message_id']) > 0
                and instant(record['frozen_at']) < departure
                and instant(record['send_started_at']) < departure
                and datetime.fromtimestamp(receipt['date'], timezone.utc) < departure
                and instant(record['sent_at']) < departure)
    except (KeyError, ValueError, TypeError):
        return False


def settle(record, official):
    """Conservative: unsupported NP/dead heat or missing dividend stays pending."""
    if not confirmed(record):
        return {'status': 'NON_COMPTABILISE', 'reason': 'Reçu pré-départ non confirmé'}
    markets = [x for x in official.get('reports', []) if x.get('typePari') == 'E_TIERCE']
    pending = lambda reason: {'status': 'EN_ATTENTE', 'reason': reason}
    if len(markets) != 1:
        return pending('Rapports définitifs PMU Internet Tiercé absents')
    market = markets[0]
    if market.get('miseBase') != 100:
        return pending('Unité officielle inattendue')
    stake = record['selection']['stake_cents']
    if market.get('rembourse') is True:
        return dict(status='REMBOURSE', returns_cents=stake, net_cents=0,
                    winning_tickets=0, losing_tickets=0, refunded_tickets=len(record['selection']['tickets']))
    if official.get('course', {}).get('arriveeDefinitive') is not True:
        return pending('Arrivée officielle non définitive')
    participants = official.get('participants', {}).get('participants', [])
    selected = {n for ticket in record['selection']['tickets'] for n in ticket}
    by_num = {p['numPmu']: p for p in participants}
    if any(n not in by_num or by_num[n].get('statut') != 'PARTANT' for n in selected):
        return pending('Non-partant ou identité manquante : règlement spécial à vérifier')
    arrival = official['course'].get('ordreArrivee', [])
    if len(arrival) < 3 or any(not isinstance(x, list) or len(x) != 1 for x in arrival[:3]):
        return pending('Arrivée ambiguë ou ex aequo : contrôle manuel')
    podium = [x[0] for x in arrival[:3]]
    dividends = {}
    for rank in (1, 2):
        reports = [r for r in market.get('rapports', []) if r.get('rangCombinaisonPayable') == rank]
        if len(reports) != 1 or reports[0].get('combinaison') != podium:
            return pending('Rapports Ordre/Désordre incomplets ou incohérents')
        value = reports[0].get('dividendePourUnEuro')
        if not isinstance(value, int) or value < 0:
            return pending('Rapport pour 1 € absent')
        dividends[rank] = value
    details = []
    for combo in record['selection']['tickets']:
        rank = 1 if combo == podium else 2 if set(combo) == set(podium) else None
        returns = dividends.get(rank, 0)
        details.append(dict(numbers=combo, stake_cents=100, returns_cents=returns,
                            net_cents=returns-100, outcome='ORDRE' if rank == 1 else 'DESORDRE' if rank == 2 else 'PERDU'))
    total = sum(d['returns_cents'] for d in details)
    winners = sum(d['outcome'] != 'PERDU' for d in details)
    return dict(status='REGLE', returns_cents=total, net_cents=total-stake,
                winning_tickets=winners, losing_tickets=len(details)-winners,
                refunded_tickets=0, tickets=details, arrival=podium, dividends_cents=dividends)


def totals(records, arm):
    admitted = [r for r in records if r['selection']['id'] == arm and confirmed(r)]
    settled = [r for r in admitted if r.get('result', {}).get('status') in ('REGLE', 'REMBOURSE')]
    stake = sum(r['selection']['stake_cents'] for r in settled)
    returns = sum(r['result']['returns_cents'] for r in settled)
    return dict(engaged_cents=sum(r['selection']['stake_cents'] for r in admitted),
                stake_cents=stake, returns_cents=returns, net_cents=returns-stake,
                roi_percent=round((returns-stake)*100/stake, 2) if stake else None,
                positive=sum(r['result']['net_cents'] > 0 for r in settled),
                negative=sum(r['result']['net_cents'] < 0 for r in settled),
                neutral=sum(r['result']['net_cents'] == 0 for r in settled),
                winning_tickets=sum(r['result']['winning_tickets'] for r in settled),
                losing_tickets=sum(r['result']['losing_tickets'] for r in settled),
                refunded_tickets=sum(r['result']['refunded_tickets'] for r in settled),
                pending=len(admitted)-len(settled),
                unconfirmed=sum(r['selection']['id'] == arm and not confirmed(r) for r in records))
