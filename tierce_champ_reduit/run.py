"""One short scheduled pass. No real wagers, no retroactive commitments."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import urlopen, Request

from tierce_champ_reduit.model import ARMS, TZ, VERSION, confirmed, instant, prepare, settle, totals

REPO = Path(__file__).resolve().parents[1]
API = 'https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'


def clock():
    return datetime.now(timezone.utc)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def read(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def get_json(url):
    request = Request(url, headers={'User-Agent': 'pmu-scorer-virtual-tierce/1.0'})
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def checkpoint(root, persist):
    if not persist:
        return
    relative = root.relative_to(REPO).as_posix()
    def git(*args, check=True):
        return subprocess.run(['git', *args], cwd=REPO, check=check, capture_output=True, text=True)
    git('add', '--', relative)
    if git('diff', '--cached', '--quiet', check=False).returncode == 0:
        return
    git('commit', '-m', 'Archive independent Tierce virtual accounts')
    for _ in range(3):
        # The dedicated workflow is serialized. Other programs change other paths.
        git('pull', '--rebase', 'origin', 'main')
        if git('push', 'origin', 'HEAD:main', check=False).returncode == 0:
            return
    raise RuntimeError('Archive GitHub impossible ; envoi interrompu')


def send_message(text):
    import requests
    token, chat = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise RuntimeError('Configuration Telegram absente')
    response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                             json={'chat_id': chat, 'text': text, 'disable_web_page_preview': True}, timeout=20)
    # Never log response bodies or exceptions containing the bot URL/token.
    if response.status_code != 200:
        raise RuntimeError('Réponse Telegram non confirmée')
    payload = response.json()
    if payload.get('ok') is not True:
        raise RuntimeError('Reçu Telegram absent')
    result = payload['result']
    return {'message_id': result['message_id'], 'date': result['date']}


def prediction(record):
    s, race = record['selection'], record['race']
    horses = {int(n): h for n, h in race['horses'].items()}
    def horse(n):
        return f"N°{n} {horses[n]['nom']} · cote SG {horses[n]['pmu_odds']['value']:g}"
    return '\n'.join([
        s['label'], f"{race['date']} · {race['id']} · {race['title']}",
        'Départ : ' + instant(race['departure']).astimezone(TZ).strftime('%Hh%M'),
        'BASE FIXÉE PREMIÈRE : ' + horse(s['base']),
        'ASSOCIÉS :', *[horse(n) for n in s['associates']],
        'Dont outsiders confirmés : ' + ', '.join('N°'+str(n) for n in s['outsiders']),
        f"Champ réduit : {s['base']} – X – X ; X parmi les associés distincts.",
        f"{len(s['tickets'])} combinaisons ordonnées × 1 € = {s['stake_cents']/100:.0f} € à 100 %.",
        'Mise fixe par course, sans Flexi ni progression. Toutes courses françaises avec Tiercé Internet admissibles.',
        'Cotes indicatives. Règlement aux rapports définitifs PMU INTERNET Ordre/Désordre.',
        'SIMULATION UNIQUEMENT — aucun pari réel.',
    ])


def deliver(record, save, sender=send_message, now=clock):
    """Persist PENDING remotely BEFORE delivery; ambiguous attempts are never resent."""
    if record.get('delivery'):
        return
    record['delivery'] = 'PENDING'
    record['text'] = prediction(record)
    record['fingerprint'] = hashlib.sha256(record['text'].encode()).hexdigest()
    save()
    if (instant(record['race']['departure']) - now()).total_seconds() <= 120:
        record['delivery'] = 'BLOCKED_AFTER_CUTOFF'
        save()
        return
    record['send_started_at'] = now().isoformat()
    try:
        record['receipt'] = sender(record['text'])
        record['sent_at'] = now().isoformat()
        record['delivery'] = 'SENT'
        if not confirmed(record):
            record['delivery'] = 'LATE_OR_INVALID_RECEIPT'
    except Exception as error:
        record['delivery'] = 'UNCERTAIN'
        record['error_type'] = type(error).__name__
    save()


def tierce_courses(programme):
    """All French meetings, including non-Quinte races; retain closed markets for coverage."""
    return sorted([(r['numOfficiel'], c) for r in programme['programme']['reunions']
            if r.get('pays', {}).get('code') == 'FRA' for c in r['courses']
            if any(p.get('typePari') == 'E_TIERCE' and p.get('miseBase') == 100 for p in c.get('paris', []))],
            key=lambda pair: (pair[1]['heureDepart'], pair[0], pair[1]['numOrdre']))


def course_states(ledger):
    """Upgrade the original single-course ledger without losing receipts or frozen flags."""
    states = ledger.setdefault('courses', {})
    for record in ledger.get('records', []):
        race = record['race']
        states.setdefault(race['id'], {'departure': race['departure'], 'reasons': {},
                          'selection_frozen_at': record['frozen_at'], 'status': 'CHOIX_DEJA_FIGES'})
    ident = ledger.get('course')
    if ident:
        state = states.setdefault(ident, {'reasons': {}})
        state.setdefault('reasons', {}).update(ledger.get('reasons', {}))
        for key in ('departure', 'status', 'selection_frozen_at'):
            if key in ledger:
                state.setdefault(key, ledger[key])
        for key in ('course', 'departure', 'selection_frozen_at', 'reasons'):
            ledger.pop(key, None)
    return states


def collect_sources(day, r, course):
    """Collect the requested race directly. Never substitute the daily Quinte's tips."""
    sys.path.insert(0, str(REPO / 'consensus_pronostics'))
    from collector import SOURCES, Fetcher, source_url, parse, pmu_odds
    ident = f"R{r}C{course['numOrdre']}"
    prefix = API + day.strftime('%d%m%Y') + f"/R{r}/C{course['numOrdre']}"
    participants = get_json(prefix + '/participants')['participants']
    race = dict(id=ident, date=day.isoformat(), r=r, c=course['numOrdre'], title=course['libelle'],
                departure=datetime.fromtimestamp(course['heureDepart']/1000, timezone.utc).isoformat(),
                odds_captured_at=clock().isoformat(),
                horses={p['numPmu']: {**{k: p.get(k) for k in ('numPmu', 'nom', 'statut')},
                                      'pmu_odds': pmu_odds(p)} for p in participants})
    def one(key):
        fetcher = Fetcher()
        try:
            url = source_url(key, race, fetcher)
            body = fetcher.get(url)
            row = parse(key, body, race)  # Requires exact date, race identity and horse names.
            row.update(url=url, retrieved_at=clock().isoformat(), sha256=hashlib.sha256(body.encode()).hexdigest())
            return row, {'source': key, 'status': 'OK', 'url': url}, fetcher.audit
        except Exception as error:
            reason = str(error)[:180] if isinstance(error, ValueError) else type(error).__name__
            return None, {'source': key, 'status': 'INDISPONIBLE', 'reason': reason}, fetcher.audit
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, SOURCES))
    return {'version': VERSION, 'captured_at': clock().isoformat(), 'race': race,
            'rows': [row for row, _, _ in results if row],
            'statuses': [status for _, status, _ in results],
            'http_audit': [entry for _, _, audit in results for entry in audit]}


def collect_plans(day, r, course, archive=None):
    # Reuse public editorial parsers, but never write or send existing Consensus accounts.
    sys.path.insert(0, str(REPO / 'consensus_pronostics'))
    from collector import pmu_odds, norm
    snapshot = collect_sources(day, r, course)
    if archive:
        write(archive, snapshot)
    prefix = API + day.strftime('%d%m%Y') + f"/R{r}/C{course['numOrdre']}"
    latest = get_json(prefix)
    if latest.get('statut') != 'PROGRAMMEE' or latest.get('arriveeDefinitive'):
        raise ValueError('Course déjà partie, annulée ou statut pré-départ non confirmé')
    participants = get_json(prefix + '/participants')['participants']
    horses = {p['numPmu']: dict(numPmu=p['numPmu'], nom=p['nom'], statut=p['statut'],
                               pmu_odds=pmu_odds(p)) for p in participants}
    previous = {int(n): h for n, h in snapshot['race']['horses'].items()}
    if set(horses) != set(previous) or any(norm(h['nom']) != norm(previous[n]['nom']) for n, h in horses.items()):
        raise ValueError('Identité des chevaux modifiée entre collecte et contrôle')
    if norm(latest['libelle']) != norm(snapshot['race']['title']):
        raise ValueError('Identité de course incohérente')
    # Earlier time wins: a later schedule revision cannot justify an after-start send.
    departure = min(instant(snapshot['race']['departure']),
                    datetime.fromtimestamp(course['heureDepart']/1000, timezone.utc),
                    datetime.fromtimestamp(latest['heureDepart']/1000, timezone.utc))
    snapshot['race'].update(horses=horses, departure=departure.isoformat(), odds_captured_at=clock().isoformat(),
        internet_tierce_available=any(p.get('typePari') == 'E_TIERCE' and p.get('miseBase') == 100
                                      and p.get('enVente') is True for p in latest.get('paris', [])))
    snapshot['final_pmu_check'] = {'course': latest, 'participants': participants, 'url': prefix}
    if archive:
        write(archive, snapshot)
    return snapshot, prepare(snapshot, clock())


def money(cents):
    return f'{cents/100:.2f} €'


def summary_line(t):
    roi = 'indisponible' if t['roi_percent'] is None else f"{t['roi_percent']:+.2f} %"
    return (f"Engagé {money(t['engaged_cents'])} · réglé {money(t['stake_cents'])} · retours {money(t['returns_cents'])}"
            f" · net {money(t['net_cents'])} · ROI {roi}\n"
            f"Courses +/−/= : {t['positive']}/{t['negative']}/{t['neutral']} · tickets gagnants/perdants/remboursés : "
            f"{t['winning_tickets']}/{t['losing_tickets']}/{t['refunded_tickets']} · en attente {t['pending']}"
            f" · envois non confirmés {t['unconfirmed']}")


def reports(root, today):
    ledgers = [read(p, {}) for p in sorted(root.glob('????-??-??/journal.json'))]
    for ledger in ledgers:
        course_states(ledger)
    all_records = [r for ledger in ledgers for r in ledger['records']]
    daily = next((x for x in ledgers if x['date'] == today), {'records': [], 'status': 'Aucune donnée'})
    lines = [f'TIERCÉ CHAMP RÉDUIT — BILAN {today}', 'SIMULATIONS — comptes indépendants, pas de ROI additionné.',
             'COUVERTURE : ' + daily.get('status', 'Programme indisponible')]
    for arm, (label, _) in ARMS.items():
        day_stats, cumulative = totals(daily['records'], arm), totals(all_records, arm)
        lines += ['', label, 'JOUR : ' + summary_line(day_stats),
                  'CUMUL DEPUIS LE 19/11/2026 : ' + summary_line(cumulative)]
        if not daily.get('courses'):
            lines += ['COUVERTURE : ' + daily.get('status', 'Programme indisponible')]
        for ident, state in daily.get('courses', {}).items():
            if not any(r['selection']['id'] == arm and r['race']['id'] == ident for r in daily['records']):
                lines += [ident + ' · NON JOUÉ / DONNÉES : ' + (state.get('reasons', {}).get(arm) or state.get('status', ''))]
        for record in daily['records']:
            if record['selection']['id'] == arm:
                result = record.get('result', {})
                lines += [record['race']['id'] + ' · ' + result.get('status', record.get('delivery', 'NON_ENVOYE'))
                          + ' · ' + result.get('reason', '')]
                if result.get('arrival'):
                    lines += ['Arrivée : ' + ' – '.join(map(str, result['arrival']))]
                if confirmed(record):
                    lines += ['Mise ' + money(record['selection']['stake_cents']) + (' · retour ' + money(result['returns_cents'])
                              + ' · net ' + money(result['net_cents']) if 'returns_cents' in result else ' · retour/net EN ATTENTE')]
        folder = root / arm
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / 'bilan_cumule.json', {'formula': arm, 'label': label, **cumulative})
        with (folder / 'bilans_quotidiens.csv').open('w', encoding='utf-8', newline='') as handle:
            fields = ['date', *day_stats.keys(), 'reason']
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for ledger in ledgers:
                writer.writerow({'date': ledger['date'], **totals(ledger['records'], arm),
                                 'reason': ledger.get('status', '')})
        with (folder / 'bilans_par_course.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['date', 'course', *day_stats.keys(), 'reason'])
            writer.writeheader()
            for ledger in ledgers:
                for ident, state in ledger.get('courses', {}).items():
                    records = [r for r in ledger['records'] if r['race']['id'] == ident]
                    writer.writerow({'date': ledger['date'], 'course': ident, **totals(records, arm),
                                     'reason': state.get('reasons', {}).get(arm) or state.get('status', '')})
        (folder / 'README.md').write_text('# ' + label + '\n\n' + summary_line(cumulative) + '\n\n'
            + '[Par jour (CSV)](bilans_quotidiens.csv) · [Par course (CSV)](bilans_par_course.csv) — montants en centimes.\n', encoding='utf-8')
    text = '\n'.join(lines)
    (root / today / 'bilan_du_jour.txt').write_text(text + '\n', encoding='utf-8')
    (root / 'README.md').write_text('# Tiercé champ réduit — résultats indépendants\n\n'
        + '\n'.join(f'- [{label}]({arm}/README.md)' for arm, (label, _) in ARMS.items())
        + f'\n\nDernier bilan : [{today}]({today}/bilan_du_jour.txt).\n', encoding='utf-8')
    return text


def process_course(ledger, day, r, course, folder, save, send, deadline):
    ident = f"R{r}C{course['numOrdre']}"
    state = course_states(ledger).setdefault(ident, {'reasons': {}})
    state.update(title=course['libelle'], departure=datetime.fromtimestamp(course['heureDepart']/1000, timezone.utc).isoformat())
    try:
        remaining = (instant(state['departure']) - clock()).total_seconds()
        existing = {x['selection']['id'] for x in ledger['records'] if x['race']['id'] == ident}
        if existing or state.get('selection_frozen_at'):
            state['status'] = 'CHOIX_DEJA_FIGES'
            return
        if remaining > 3600:
            state['status'] = 'EN_ATTENTE_FENETRE_H60'
        elif remaining <= 120:
            state['status'] = 'Fenêtre pré-départ fermée ; aucune mise reconstituée'
        elif not any(p.get('typePari') == 'E_TIERCE' and p.get('miseBase') == 100 and p.get('enVente') is True for p in course.get('paris', [])):
            state['status'] = 'Tiercé Internet fermé ou disponibilité non confirmée'
        elif time.monotonic() >= deadline:
            state['status'] = 'REPORT_CONTROLE_PROCHAIN_PASSAGE : durée de session limitée'
        else:
            snapshot, plans = collect_plans(day, r, course, folder / ident / 'derniere_collecte.json')
            new_records = []
            for selection in plans:
                state['reasons'][selection['id']] = selection['reason']
                if selection['reason']:
                    continue
                if not send:
                    state['reasons'][selection['id']] = 'Mode contrôle sans envoi, aucune mise'
                    continue
                record = dict(selection=selection, race=snapshot['race'], frozen_at=clock().isoformat(),
                              source_snapshot=snapshot)
                ledger['records'].append(record)
                new_records.append(record)
            if new_records:
                # Both variants use the very same favourite and source snapshot.
                # An incomplete sibling is not silently rebuilt on different later choices.
                state['selection_frozen_at'] = clock().isoformat()
            for record in new_records:
                deliver(record, save)
            state['status'] = 'CONTROLE_EFFECTUE'
    except Exception as error:
        state['status'] = ('Données indisponibles : ' + str(error)) if isinstance(error, ValueError) else ('Erreur de collecte : ' + type(error).__name__)


def message_parts(text, limit=3500):
    parts, current = [], ''
    for line in text.splitlines():
        for start in range(0, max(1, len(line)), limit):
            segment = line[start:start+limit]
            if current and len(current) + len(segment) + 1 > limit:
                parts.append(current)
                current = ''
            current += ('\n' if current else '') + segment
    if current:
        parts.append(current)
    return parts


def run(root, send=False, persist=False):
    now = clock()
    day = now.astimezone(TZ).date()
    path = root / day.isoformat() / 'journal.json'
    ledger = read(path, {'date': day.isoformat(), 'version': VERSION, 'records': [], 'courses': {}})
    course_states(ledger)
    ledger.update(version=VERSION, checked_at=now.isoformat())
    save = lambda: (write(path, ledger), checkpoint(root, persist))
    deadline = time.monotonic() + 480
    try:
        courses = tierce_courses(get_json(API + day.strftime('%d%m%Y')))
        ledger['status'] = f'{len(courses)} courses françaises avec Tiercé Internet à 1 € au programme'
        for r, course in courses:
            process_course(ledger, day, r, course, path.parent, save, send, deadline)
    except Exception as error:
        ledger['status'] = 'Programme indisponible : ' + type(error).__name__
    save()
    for journal in sorted(root.glob('????-??-??/journal.json')):
        data = read(journal, {})
        cache = {}
        for record in data['records']:
            if not confirmed(record) or record.get('result', {}).get('status') in ('REGLE', 'REMBOURSE'):
                continue
            if clock() <= instant(record['race']['departure']):
                continue
            if time.monotonic() >= deadline + 120:
                record.setdefault('result', {'status': 'EN_ATTENTE', 'reason': 'Règlement reporté au prochain passage : session limitée'})
                continue
            race = record['race']
            prefix = API + datetime.fromisoformat(race['date']).strftime('%d%m%Y') + f"/R{race['r']}/C{race['c']}"
            try:
                if prefix not in cache:
                    cache[prefix] = {'retrieved_at': clock().isoformat(), 'specialisation': 'INTERNET',
                        'reports_url': prefix + '/rapports-definitifs?combinaisonEnTableau=true&specialisation=INTERNET',
                        'course': get_json(prefix), 'participants': get_json(prefix + '/participants'),
                        'reports': get_json(prefix + '/rapports-definitifs?combinaisonEnTableau=true&specialisation=INTERNET')}
                    write(journal.parent / race['id'] / 'rapports_pmu_internet.json', cache[prefix])
                record['result'] = settle(record, cache[prefix])
            except Exception as error:
                record['result'] = {'status': 'EN_ATTENTE', 'reason': 'Rapports indisponibles : ' + type(error).__name__}
        write(journal, data)
    text = reports(root, day.isoformat())
    checkpoint(root, persist)
    # One receipt per distinct end-of-course balance, never resend an uncertain attempt.
    if send and any(s.get('departure') and clock() > instant(s['departure']) for s in ledger['courses'].values()):
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        notices_path = root / day.isoformat() / 'bilans_telegram.json'
        notices = read(notices_path, [])
        if not any(x['fingerprint'] == fingerprint for x in notices):
            notice = {'fingerprint': fingerprint, 'delivery': 'PENDING', 'text': text, 'receipts': []}
            notices.append(notice)
            write(notices_path, notices)
            checkpoint(root, persist)
            try:
                for part in message_parts(text):
                    notice['receipts'].append(send_message(part))
                    write(notices_path, notices)
                    checkpoint(root, persist)
                notice['delivery'] = 'SENT'
            except Exception as error:
                notice.update(delivery='UNCERTAIN', error_type=type(error).__name__)
            write(notices_path, notices)
            checkpoint(root, persist)
    print(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--output', type=Path, default=REPO / 'tierce_champ_reduit' / 'data')
    args = parser.parse_args()
    if args.send and not args.persist:
        parser.error('--send exige --persist : archivage durable avant Telegram')
    run(args.output.resolve(), args.send, args.persist)
