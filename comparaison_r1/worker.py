"""Bounded Actions worker: persist each pass, continue while R1 is active.

Scheduling is still hosted by GitHub: a platform outage or exhausted Actions
budget cannot be bypassed. Never synthesizes bets or skips delivery checks.
"""
import argparse
from datetime import datetime, timedelta
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
PACKAGES = ('comparaison_r1', 'tony_artillan_2', 'tony_artillan_3_5')


def active(state, now):
    if not state or state.get('date') != now.date().isoformat():
        return False
    departures = [datetime.fromisoformat(r['departure']) for r in state.get('races', [])]
    return bool(departures) and min(departures)-timedelta(minutes=70) <= now <= max(departures)+timedelta(minutes=35)


def checkpoint(package):
    """Fail closed on persistence failure: do not send another unarchived stake."""
    def git(*args, check=True):
        return subprocess.run(['git', *args], check=check, timeout=120)
    git('config', 'user.name', 'Tony Artillan archives')
    git('config', 'user.email', 'tony-artillan@users.noreply.github.com')
    git('add', package+'/data')
    if git('diff', '--cached', '--quiet', check=False).returncode == 0:
        return
    git('commit', '-m', 'Archive '+package+' continuous follow-up')
    for attempt in range(3):
        git('pull', '--rebase', 'origin', 'main')
        if git('push', 'origin', 'HEAD:main', check=False).returncode == 0:
            return
    raise RuntimeError('Archive push failed; worker stopped before next pass')


def dispatch(package):
    token = os.environ['GH_TOKEN']
    repo = os.environ['GITHUB_REPOSITORY']
    url = f'https://api.github.com/repos/{repo}/actions/workflows/{package}.yml/dispatches'
    req = Request(url, data=json.dumps({'ref':'main','inputs':{'dry_run':False}}).encode(),
                  headers={'Authorization':'Bearer '+token, 'Accept':'application/vnd.github+json',
                           'Content-Type':'application/json'}, method='POST')
    with urlopen(req, timeout=30) as response:
        if response.status != 204:
            raise RuntimeError('Continuation not accepted by GitHub')


def run(package, persist=False, continue_run=False, duration=70, interval=60):
    model = importlib.import_module(package+'.model')
    data = Path(package)/'data'
    data.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    failures = 0
    while True:
        now = datetime.now(TZ)
        day = now.date().isoformat()
        state_path = data/day/'state.json'
        heartbeat = {'started_at':now.isoformat(), 'status':'RUNNING',
                     'run_id':os.environ.get('GITHUB_RUN_ID')}
        (data/'worker.json').write_text(json.dumps(heartbeat, indent=2))
        try:
            result = subprocess.run([sys.executable, '-m', package+'.main'], timeout=600)
            ok = result.returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
        heartbeat.update(completed_at=datetime.now(TZ).isoformat(), status='OK' if ok else 'FAILED')
        (data/'worker.json').write_text(json.dumps(heartbeat, indent=2))
        if persist:
            checkpoint(package)
        failures = 0 if ok else failures+1
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        now = datetime.now(TZ)
        if not model.START <= now.date().isoformat() <= model.END or not active(state, now):
            if not ok:raise RuntimeError('Collection failed outside the active session')
            return
        if failures >= 3:
            raise RuntimeError('Three failed passes; inspect Actions logs before retrying')
        # Leave ten minutes for a pass and archival before the Actions job timeout.
        if time.monotonic()-started >= duration*60:
            if continue_run:
                dispatch(package)
            return
        time.sleep(interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', choices=PACKAGES)
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--continue-run', action='store_true')
    args = parser.parse_args()
    run(args.package, persist=args.persist, continue_run=args.continue_run)
