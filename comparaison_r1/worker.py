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

from .recovery import recover_previous

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
        return subprocess.run(['git', *args], check=check, timeout=30)
    git('config', 'user.name', 'Tony Artillan archives')
    git('config', 'user.email', 'tony-artillan@users.noreply.github.com')
    git('add', package+'/data')
    if git('diff', '--cached', '--quiet', check=False).returncode != 0:
        git('commit', '-m', 'Archive '+package+' continuous follow-up')
    # Even with a clean index, a previous attempt may have committed locally
    # but failed to push. Always synchronize; never discard that commit.
    for attempt in range(3):
        try:
            git('pull', '--rebase', 'origin', 'main')
            if git('push', 'origin', 'HEAD:main', check=False).returncode == 0:
                return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # A rebase conflict is not safe to auto-resolve. The next pull fails
            # too; the artifact and failed run preserve evidence for inspection.
            if attempt == 2:raise
    raise RuntimeError('Archive push failed; worker stopped before next pass')


def dispatch(package, probe=False, recovery_attempt=None):
    token = os.environ['GH_TOKEN']
    repo = os.environ['GITHUB_REPOSITORY']
    url = f'https://api.github.com/repos/{repo}/actions/workflows/{package}.yml/dispatches'
    inputs={'dry_run':probe, 'relay_probe':probe}
    if recovery_attempt is not None:inputs['recovery_attempt']=str(recovery_attempt)
    req = Request(url, data=json.dumps({'ref':'main','inputs':inputs}).encode(),
                  headers={'Authorization':'Bearer '+token, 'Accept':'application/vnd.github+json',
                           'Content-Type':'application/json'}, method='POST')
    with urlopen(req, timeout=30) as response:
        if response.status != 204:
            raise RuntimeError('Continuation not accepted by GitHub')


def run(package, persist=False, continue_run=False, duration=10, interval=60):
    model = importlib.import_module(package+'.model')
    data = Path(package)/'data'
    data.mkdir(parents=True, exist_ok=True)
    # Reconcile a failed predecessor before any possible Telegram side effect.
    if persist and recover_previous(package):checkpoint(package)
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
            try:
                checkpoint(package)
            except Exception:
                # The artifact upload runs in the workflow's always() step. The
                # same concurrency group holds the child until that upload ends.
                state=json.loads(state_path.read_text()) if state_path.exists() else {}
                attempt=int(os.environ.get('RECOVERY_ATTEMPT','0') or 0)
                if continue_run and attempt<1 and active(state,datetime.now(TZ)):
                    dispatch(package,recovery_attempt=attempt+1)
                raise
        failures = 0 if ok else failures+1
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        now = datetime.now(TZ)
        if not model.START <= now.date().isoformat() <= model.END or not active(state, now):
            if not ok:raise RuntimeError('Collection failed outside the active session')
            return
        if failures >= 3:
            raise RuntimeError('Three failed passes; inspect Actions logs before retrying')
        # Ten-minute sessions; a last pass is bounded to ten more minutes.
        # Archival is bounded to three minutes; job timeout is 25 minutes.
        if time.monotonic()-started >= duration*60-interval:
            if continue_run:
                dispatch(package)
                heartbeat.update(status='RELAY_ACCEPTED', relay_at=datetime.now(TZ).isoformat())
                (data/'worker.json').write_text(json.dumps(heartbeat, indent=2))
                if persist:checkpoint(package)
            return
        time.sleep(interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', choices=PACKAGES)
    parser.add_argument('--checkpoint-only', action='store_true')
    parser.add_argument('--probe-relay', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--continue-run', action='store_true')
    args = parser.parse_args()
    if args.checkpoint_only:checkpoint(args.package)
    elif args.probe_relay:
        dispatch(args.package, probe=True)
        print('RELAY_PROBE_ACCEPTED '+args.package)
    else:run(args.package, persist=args.persist, continue_run=args.continue_run)


