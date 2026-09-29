"""Journal des messages Telegram et bilan des seules selections envoyees.
Rapports definitifs PMU INTERNET, en centimes par euro, par combinaison.
Aucune estimation de rapport. La mise de 5 EUR est une simulation, pas un pari execute.
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
JOURNAL = Path('resultats/journal')
BASE = 'https://online.turfinfo.api.pmu.fr/rest/client/61'
LABELS = {'SIMPLE_PLACE': 'Simple place', 'COUPLE_PLACE': 'Couple place',
          'COUPLE_GAGNANT': 'Couple gagnant'}
LOG = logging.getLogger(__name__)


def paris_affiches(top, nb_partants):
    """Une seule source pour les lignes de paris, sans modifier le classement."""
    if not top:
        return ['AUCUN PARI CONSEILLE : selection indisponible.']
    a = top[0]
    n1 = str(a.get('num_partant') or '').strip()
    if not n1.isdigit():
        return ['AUCUN PARI CONSEILLE : numero manquant.']
    lines = [f"PARI : Simple Place sur N{n1} {a.get('nom_cheval', '')}"]
    if len(top) > 1:
        b = top[1]
        n2 = str(b.get('num_partant') or '').strip()
        odds = b.get('cote_actuel', b.get('cote_jour', 0)) or 0
        if n2.isdigit() and n1 != n2 and 0 < odds < 12 and nb_partants >= 4:
            kind = 'GAGNANT' if nb_partants <= 7 else 'PLACE'
            lines.append(f"COUPLE {kind} (les 2 choix ci-dessus) : N{n1} {a.get('nom_cheval', '')} + N{n2} {b.get('nom_cheval', '')}")
    return lines


def analyser_message(text, now):
    """Parse uniquement le format explicite emis par nos deux programmes."""
    match = re.search(r'COURSE\s*:?\s*R(\d+)\s*C(\d+)', text)
    if not match:
        return None
    clock = re.search(r'(?:DEPART|HEURE\s*:)\s*(\d{2})h(\d{2})', text)
    if not clock:
        raise ValueError('Course sans heure de depart : journal incomplet')
    depart = now.replace(hour=int(clock[1]), minute=int(clock[2]), second=0, microsecond=0)
    choices = []
    for role, num, name in re.findall(r'(PRONOSTIC PRINCIPAL|DEUXIEME CHOIX)\s*:\s*🔴\s*N(\d+)\.\s*([^\n]+)', text):
        if len(choices) == 2:
            break
        choices.append({'num': str(int(num)), 'nom': name.split(' (cote')[0].strip()})
    bets = []
    simple = re.search(r'PARI\s*:\s*Simple Place sur N(\d+)', text)
    if simple:
        bets.append({'type': 'SIMPLE_PLACE', 'numeros': [str(int(simple[1]))], 'mise': '5.00'})
    couple = re.search(r'COUPLE (PLACE|GAGNANT)[^\n]*?:\s*N(\d+)[^\n]*?\+\s*N(\d+)', text)
    if couple:
        bets.append({'type': 'COUPLE_' + couple[1], 'numeros': [str(int(couple[2])), str(int(couple[3]))], 'mise': '5.00'})
    if choices and not bets:
        raise ValueError('Choix sans pari explicite : ne pas inventer la mise')
    selected = [c['num'] for c in choices]
    for bet in bets:
        if not selected or bet['numeros'] != selected[:len(bet['numeros'])]:
            raise ValueError('Incoherence entre chevaux affiches et paris')
    return {'date': now.strftime('%Y%m%d'), 'course': f'R{match[1]}C{match[2]}',
            'depart': depart.isoformat(), 'source': 'H15' if 'ACTUALISATION' in text else 'MATIN',
            'choix': choices, 'paris': bets}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def envoyer_trace(text, token, chat_id, *, post=None, journal=None, now=None):
    """Un recu par course ; les envois incomplets restent explicitement incertains."""
    if not token or not chat_id:
        return False
    if post is None:
        import requests
        post = requests.post
    now = now or datetime.now(TZ)
    journal = Path(journal) if journal is not None else JOURNAL
    # Separer les courses pour pouvoir attester chaque selection independamment.
    blocks = re.split(r'(?=^[^\w\n]*COURSE\s*:?\s*R\d+\s*C\d+)', text, flags=re.M)
    source_h15 = 'ACTUALISATION DE L\'ALGORITHME' in text
    success = True
    for block in blocks:
        if not block.strip():
            continue
        event = analyser_message(('ACTUALISATION\n' if source_h15 else '') + block, now)
        record = {'schema': 1, 'id': uuid4().hex, 'sent_at': now.isoformat(),
                  'revision': os.environ.get('GITHUB_SHA', 'local'), 'event': event,
                  'text': block, 'sha256': hashlib.sha256(block.encode()).hexdigest(),
                  'delivery': 'PENDING', 'receipts': []}
        path = journal / f"{now:%Y%m%d}-{record['id']}.json"
        if event:
            _write(path, record)  # Echec disque => ne pas envoyer sans trace.
        try:
            for pos in range(0, len(block), 3500):
                response = post(f'https://api.telegram.org/bot{token}/sendMessage',
                                json={'chat_id': chat_id, 'text': block[pos:pos+3500]}, timeout=20)
                body = response.json()
                if response.status_code != 200 or body.get('ok') is not True:
                    raise ValueError('Telegram refuse le message')
                result = body['result']
                record['receipts'].append({'message_id': result['message_id'], 'date': result['date']})
                if event:
                    _write(path, record)
            record['delivery'] = 'SENT'
            # Date du dernier morceau confirmee par Telegram, pas l'horloge du runner.
            record['sent_at'] = datetime.fromtimestamp(record['receipts'][-1]['date'], TZ).isoformat()
        except Exception as exc:
            record['delivery'] = 'UNCERTAIN'
            LOG.warning('Envoi Telegram non confirme (%s)', type(exc).__name__)
            success = False
        if event:
            _write(path, record)
    return success


def dernieres_selections(records, day):
    chosen = {}
    for row in records:
        e = row.get('event')
        if not e or e['date'] != day:
            continue
        sent = datetime.fromisoformat(row['sent_at'])
        if sent >= datetime.fromisoformat(e['depart']):
            continue  # Pas de pronostic retrospectif.
        previous = chosen.get(e['course'])
        if previous is None or sent > datetime.fromisoformat(previous['sent_at']):
            chosen[e['course']] = row
        elif sent == datetime.fromisoformat(previous['sent_at']) and row['sha256'] != previous['sha256']:
            # Deux versions differentes dans la meme seconde : ne pas choisir arbitrairement.
            chosen[e['course']] = {**row, 'delivery': 'UNCERTAIN'}
    return chosen


def tables_rapports(payload):
    """Ne reconnait que le contrat observe de rapports-definitifs INTERNET."""
    tables = {}
    if not isinstance(payload, list):
        return tables
    for item in payload:
        kind = item.get('typePari', '')
        if not kind.startswith('E_'):
            continue
        kind = kind[2:]
        if kind not in LABELS:
            continue
        table = {'rembourse': item.get('rembourse') is True, 'valeurs': {}}
        for r in item.get('rapports', []):
            combination = str(r.get('combinaison', ''))
            if not re.fullmatch(r'(?:\d+|NP)(?:-(?:\d+|NP))*', combination):
                continue
            try:
                amount = Decimal(str(r['dividendePourUnEuro'])) / Decimal(100)
            except (KeyError, InvalidOperation):
                continue
            if not amount.is_finite() or amount <= 0:
                continue
            key = tuple(sorted(combination.split('-')))
            if key in table['valeurs'] and table['valeurs'][key] != amount:
                raise ValueError('Rapports contradictoires pour une combinaison')
            table['valeurs'][key] = amount
        if table['rembourse'] or table['valeurs']:
            if kind in tables and tables[kind] != table:
                raise ValueError('Plusieurs tables de rapports incompatibles')
            tables[kind] = table
    return tables


def regler_pari(bet, participants, tables):
    kind, nums = bet['type'], bet['numeros']
    stake = Decimal(bet['mise'])
    def result(status, returned=None, reason=''):
        return {**bet, 'statut': status, 'retour': None if returned is None else str(returned.quantize(Decimal('.01'))), 'raison': reason}
    table = tables.get(kind)
    if not table:
        return result('EN_ATTENTE', reason='Rapports definitifs absents')
    if table['rembourse']:
        return result('REMBOURSE', stake, 'Pari rembourse par PMU')
    runners = {str(p.get('numPmu')): p for p in participants}
    if any(n not in runners for n in nums):
        return result('EN_ATTENTE', reason='Participant non identifie')
    np = {n for n in nums if runners[n].get('statut') == 'NON_PARTANT' or runners[n].get('incident') == 'NON_PARTANT'}
    if np and kind == 'SIMPLE_PLACE':
        return result('REMBOURSE', stake, 'Non-partant officiel')
    key = tuple(sorted('NP' if n in np else n for n in nums))
    dividend = table['valeurs'].get(key)
    if dividend is not None:
        return result('REGLE_NP' if np else 'GAGNE', stake * dividend, f'Rapport officiel {dividend} EUR pour 1 EUR')
    if np:
        return result('EN_ATTENTE', reason='Couple avec non-partant : rapport specifique requis')
    # Ne pas convertir un resultat de participant inconnu en perte.
    if not all(p.get('ordreArrivee', 0) or p.get('incident') in {'DISQUALIFIE', 'ARRETE', 'TOMBE', 'DISTANCE'} for p in (runners[n] for n in nums)):
        return result('EN_ATTENTE', reason='Classement ou incident non confirme')
    return result('PERDU', Decimal(0), 'Combinaison absente des rapports definitifs')


def bilan(records, day, fetch):
    selections = dernieres_selections(records, day)
    lines = [f'BILAN DES PRONOSTICS ENVOYES — {day[6:8]}/{day[4:6]}/{day[:4]}',
             'Derniere version envoyee avant depart, une seule selection par course.',
             'Simulation : 5 EUR par pari explicitement conseille ; aucun pari execute.',
             'Rapports officiels PMU INTERNET uniquement.']
    audit = []
    won = placed = evaluated = pending_choices = 0
    for key, record in sorted(selections.items()):
        event = record['event']
        lines.append(f"\n{key} — {event['source']} — envoi {datetime.fromisoformat(record['sent_at']).strftime('%Hh%M')}")
        if record['delivery'] != 'SENT':
            lines.append('ENVOI INCERTAIN : exclu du bilan, pas de remplacement par le choix du matin.')
            audit.append({'course': key, 'statut': 'ENVOI_INCERTAIN', 'journal_id': record['id']})
            pending_choices += 1
            continue
        if not event['choix']:
            lines.append('Aucune selection finale conseillee.')
            continue
        nr, nc = re.fullmatch(r'R(\d+)C(\d+)', key).groups()
        api_date = day[6:8] + day[4:6] + day[:4]
        prefix = f'/programme/{api_date}/R{nr}/C{nc}'
        participants_payload = fetch(prefix + '/participants')
        payload = fetch(prefix + '/rapports-definitifs?specialisation=INTERNET')
        participants = (participants_payload or {}).get('participants', []) if isinstance(participants_payload, dict) else []
        tables = tables_rapports(payload)
        runners = {str(p.get('numPmu')): p for p in participants}
        for i, c in enumerate(event['choix']):
            runner = runners.get(c['num'], {})
            rank = runner.get('ordreArrivee')
            status = 'NON-PARTANT' if runner.get('statut') == 'NON_PARTANT' else (f'{rank}e' if rank else 'EN ATTENTE / NON CLASSE')
            lines.append(f"Choix {i+1} : N{c['num']} {c['nom']} — {status}")
        primary = event['choix'][0]['num']
        settlements = [regler_pari(b, participants, tables) for b in event['paris']]
        for settled in settlements:
            audit.append({**settled, 'course': key, 'journal_id': record['id'], 'source': event['source'], 'sent_at': record['sent_at'],
                          'rapport_url': BASE + prefix + '/rapports-definitifs?specialisation=INTERNET'})
            amount = f" ; retour {settled['retour']} EUR" if settled['retour'] is not None else ''
            lines.append(f"{LABELS[settled['type']]} {'+'.join(settled['numeros'])} : {settled['statut']}{amount}")
            if settled['type'] == 'SIMPLE_PLACE':
                if settled['statut'] in {'GAGNE', 'PERDU'}:
                    evaluated += 1
                    placed += settled['statut'] == 'GAGNE'
                    won += runners.get(primary, {}).get('ordreArrivee') == 1
                elif settled['statut'] == 'EN_ATTENTE':
                    pending_choices += 1
    lines += ['', f'Premier choix gagnant : {won}/{evaluated} classes et regles.',
              f'Premier choix place (gagnants inclus) : {placed}/{evaluated} classes et regles.',
              f'Courses en attente ou envoi incertain : {pending_choices}. Non-partants exclus des taux.']
    settled = [r for r in audit if r.get('retour') is not None]
    unresolved = [r for r in audit if r.get('statut') in {'EN_ATTENTE', 'ENVOI_INCERTAIN'}]
    refunded = sum(r['statut'] == 'REMBOURSE' for r in settled)
    invested = sum((Decimal(r['mise']) for r in settled), Decimal(0))
    returns = sum((Decimal(r['retour']) for r in settled), Decimal(0))
    lines += [f'Paris regles : {len(settled)}, dont {refunded} rembourses. Paris/envois en attente : {len(unresolved)}.',
              f'Sous-total regle : mises {invested:.2f} EUR ; retours {returns:.2f} EUR ; solde {returns-invested:+.2f} EUR.']
    if unresolved or not selections:
        lines.append('BILAN INCOMPLET : aucun ROI global publie.')
    elif invested:
        lines.append(f'ROI simule sur les paris regles : {(returns/invested-1)*100:+.1f} %.')
    if not selections:
        lines.append('Aucun historique d\'envoi avant depart disponible. Aucun remplacement par les CSV du scoreur.')
    lines.append('Les anciennes simulations estimees ne sont pas comparables a ce bilan.')
    return '\n'.join(lines), audit


def main():
    import requests
    day = os.environ.get('PMU_BILAN_DATE', datetime.now(TZ).strftime('%Y%m%d'))
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('PMU_BILAN_DATE doit etre au format AAAAMMJJ')
    datetime.strptime(day, '%Y%m%d')
    records = [json.loads(p.read_text(encoding='utf-8')) for p in JOURNAL.glob(f'{day}-*.json')]
    snapshot_dir = Path('resultats/officiels') / day
    def fetch(path):
        try:
            r = requests.get(BASE + path, timeout=25)
            r.raise_for_status()
            data = r.json()
            _write(snapshot_dir / (hashlib.sha256(path.encode()).hexdigest() + '.json'),
                   {'url': BASE + path, 'retrieved_at': datetime.now(TZ).isoformat(), 'payload': data})
            return data
        except requests.RequestException:
            LOG.warning('Donnees PMU indisponibles pour %s', path)
            return None
    message, audit = bilan(records, day, fetch)
    destination = Path('resultats/bilans')
    _write(destination / f'bilan_{day}.json', {'date': day, 'generated_at': datetime.now(TZ).isoformat(), 'audit': audit, 'message': message})
    print(message)
    if os.environ.get('PMU_DRY_RUN') != '1':
        if not envoyer_trace(message, os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')):
            raise RuntimeError('Bilan non envoye a Telegram')


if __name__ == '__main__':
    main()
