"""Suivi planifie, preuves de source et rapports officiels isoles des autres programmes."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from .model import (VERSION, choose_meeting, new_day, validate_tips, reserve, settle,
                    stamp, score, TERMINAL, norm)
from .telegram import report, send

TZ = ZoneInfo('Europe/Paris')
ROOT = Path(__file__).parent
API = 'https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)


class Fetcher:
    def __init__(self, folder, now):
        self.folder, self.now, self.cache = folder, now, {}

    def get(self, url):
        if url not in self.cache:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            body = r.json()
            key = hashlib.sha256(url.encode()).hexdigest()
            write(self.folder/'officiels'/f'{self.now.strftime("%Y%m%dT%H%M%S")}-{key}.json',
                  {'url':url,'retrieved_at':self.now.isoformat(),'payload':body})
            self.cache[url] = body
        return self.cache[url]


def run(now=None, root=ROOT, notify=True, fetcher_factory=Fetcher):
    now = now or datetime.now(TZ)
    now = now.astimezone(TZ)
    day = now.date().isoformat()
    # Reprendre les journees incompletes deja creees, meme apres minuit.
    dates = sorted({day} | {p.parent.name for p in (root/'data').glob('????-??-??/state.json')
                           if not json.loads(p.read_text()).get('score', {}).get('complete')})
    for date in dates:
        folder = root/'data'/date; path = folder/'state.json'
        fetcher = fetcher_factory(folder, now)
        prefix = API+datetime.fromisoformat(date).strftime('%d%m%Y')
        if path.exists():
            state = json.loads(path.read_text())
        elif date == day:
            try:
                programme = fetcher.get(prefix)
                state = new_day(date, choose_meeting(programme), now)
            except (ValueError, KeyError, requests.RequestException) as e:
                error_path = folder/'error.json'
                error = json.loads(error_path.read_text()) if error_path.exists() else {'notifications':[]}
                error.update(at=now.isoformat(), reason=str(e)[:350])
                save_error = lambda: write(error_path, error)
                save_error()
                if notify:
                    token, chat = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
                    if not token or not chat:
                        raise RuntimeError('Configuration Telegram absente')
                    send(error, '🏇 PARIS TURF — ANCIEN PROGRAMME — '+date+'\nSimulation suspendue : aucune réunion française de huit courses identifiable ou programme PMU indisponible.\nAucun pari engagé ; aucun gain calculé.',
                         token, chat, save_error, now)
                print('TONY_MEETING_UNAVAILABLE',type(e).__name__)
                continue
        else:
            continue
        before = json.dumps(state, sort_keys=True)
        save = lambda: write(path, state)
        input_path = root/'inputs'/(date+'.json')
        if state['source_status'] != 'VERIFIEE' and input_path.exists():
            try:
                document = json.loads(input_path.read_text())
                runners = {race['c']:fetcher.get(prefix+f"/R{state['r']}/C{race['c']}/participants")['participants']
                           for race in state['races']}
                tips = validate_tips(document, state, runners, now)
                for race in state['races']:
                    race['selection'] = tips[race['c']]
                state['source_status'] = 'VERIFIEE'
                write(folder/'source_import.json', {'imported_at':now.isoformat(),
                      'sha256':hashlib.sha256(input_path.read_bytes()).hexdigest(),'document':document})
                state.pop('source_error',None)
            except (ValueError, KeyError, requests.RequestException) as e:
                state['source_error'] = str(e)[:350]
        for index, race in enumerate(state['races']):
            base = prefix+f"/R{state['r']}/C{race['c']}"
            try:
                if race['status'] == 'ENGAGE_VIRTUEL' and now >= stamp(race['departure']):
                    ps = fetcher.get(base+'/participants')['participants']
                    url = base+'/rapports-definitifs?specialisation=INTERNET'
                    payload = fetcher.get(url)
                    settle(race, payload, ps, now, url)
                if race['status'] == 'A_VENIR' and now >= stamp(race['departure']):
                    race.update(status='NON_JOUE',reason='Aucune mise valide figee avant depart')
                # Engager seulement la prochaine course, pres du depart ; toutes
                # les huit selections peuvent en revanche etre affichees le matin.
                if (race['status'] == 'A_VENIR' and 'selection' in race
                        and timedelta(0) < stamp(race['departure'])-now <= timedelta(minutes=30)):
                    meta = fetcher.get(base)
                    if (meta.get('numReunion') != state['r'] or meta.get('numOrdre') != race['c']
                            or norm(meta.get('libelle','')) != norm(race['title'])
                            or meta.get('heureDepart') != int(stamp(race['departure']).timestamp()*1000)):
                        raise ValueError('Identite/horaire officiel modifie : mise suspendue')
                    race['market'] = meta.get('hasEParis') is not False and any(p.get('typePari')=='E_SIMPLE_GAGNANT' and p.get('enVente') is not False
                                         for p in meta.get('paris',[]))
                    ps = fetcher.get(base+'/participants')['participants']
                    horse = next((p for p in ps if p.get('numPmu')==race['selection']['number']),None)
                    reserve(state['races'],index,now,horse)
                race.pop('fetch_error',None)
            except (requests.RequestException, ValueError, KeyError) as e:
                race['fetch_error'] = type(e).__name__
        state['score'] = score(state)
        if json.dumps(state, sort_keys=True) != before:
            state['updated_at'] = now.isoformat()
        save()
        message = report(state)
        (folder/'rapport.txt').write_text(message)
        if notify:
            token, chat = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
            if not token or not chat:
                raise RuntimeError('Configuration Telegram absente')
            send(state, message, token, chat, save, now)
        print('TONY_STATUS',date,state['source_status'],state['score'])
    states = [json.loads(p.read_text()) for p in (root/'data').glob('????-??-??/state.json')]
    write(root/'data'/'BILAN.json', {'program':'Tony Artillan', 'version':VERSION,
          'virtual_only':True, 'days':[{'date':s['date'], 'source_status':s['source_status'], **score(s)} for s in states],
          'stake_cents':sum(score(s)['stake_cents'] for s in states),
          'return_cents':sum(score(s)['return_cents'] for s in states),
          'profit_cents':sum(score(s)['profit_cents'] for s in states)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args = parser.parse_args()
    run(notify=not args.dry_run)
