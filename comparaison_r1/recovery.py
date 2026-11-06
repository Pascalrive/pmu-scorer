"""Restore interrupted runs before permitting a new virtual engagement.

Only the latest completed run of this workflow is considered. Its artifact is
authoritative only when it preserves every financial entry already published.
No artifact, ambiguous receipt, or ledger conflict means no new collection.
"""
import io
import json
import os
from pathlib import Path, PurePosixPath
import zipfile
import requests

PREFIXES = {'comparaison_r1':'comparaison-r1-', 'tony_artillan_2':'tony-artillan-2-',
            'tony_artillan_3_5':'tony-artillan-3-5-'}


def api(path, binary=False):
    # requests removes Authorization on cross-host artifact redirects.
    response=requests.get('https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+'/'+path,
                          headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                                   'Accept':'application/vnd.github+json'}, timeout=45)
    response.raise_for_status()
    return response.content if binary else response.json()


def bet_identity(bet):
    return (bet.get('race_id'),bet.get('number'),bet.get('stake_cents'),
            bet.get('telegram_fingerprint'))


def preserve_financial_state(current, restored):
    """Never discard an existing receipt, stake or definitive settlement."""
    if current.get('date')!=restored.get('date'):
        raise RuntimeError('Recovery date mismatch')
    for key, solution in current.get('solutions',{}).items():
        proposed=restored.get('solutions',{}).get(key,{}).get('bets',[])
        indexed={bet_identity(b):b for b in proposed}
        for bet in solution.get('bets',[]):
            target=indexed.get(bet_identity(bet))
            if target is None or target.get('telegram_receipts')!=bet.get('telegram_receipts'):
                raise RuntimeError('Recovery ledger conflict; manual reconciliation required')
            if bet.get('status') in ('GAGNE','PERDU','REMBOURSE'):
                if target.get('status') in ('GAGNE','PERDU','REMBOURSE') and any(
                        target.get(k)!=bet.get(k) for k in ('status','return_cents','profit_cents')):
                    raise RuntimeError('Recovery settlement conflict')
                target.update(bet)


def restore_archive(data, payload):
    """Validate the whole archive before writing; reject paths outside data."""
    staged={}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            if member.is_dir():continue
            p=PurePosixPath(member.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in member.filename:
                raise RuntimeError('Unsafe recovery path')
            if member.file_size>20_000_000:
                raise RuntimeError('Oversized recovery file')
            # Restore state, evidence and the Telegram outbox, not generated reports.
            if p.name not in ('state.json','notifications.json') and 'preuves' not in p.parts:
                continue
            raw=archive.read(member)
            dest=data/str(p)
            if p.name=='state.json':
                restored=json.loads(raw)
                if dest.exists():preserve_financial_state(json.loads(dest.read_text()),restored)
                raw=json.dumps(restored,ensure_ascii=False,indent=2).encode()
            elif p.name=='notifications.json':
                restored=json.loads(raw)
                if dest.exists():
                    current=json.loads(dest.read_text())
                    by={n['fingerprint']:n for n in restored.get('notifications',[])}
                    for n in current.get('notifications',[]):
                        old=by.get(n['fingerprint'])
                        if old is None or n.get('status')=='SENT':by[n['fingerprint']]=n
                    restored['notifications']=list(by.values())
                raw=json.dumps(restored,ensure_ascii=False,indent=2).encode()
            staged[dest]=raw
    if not any(p.name=='state.json' for p in staged) or not any(p.name=='notifications.json' for p in staged):
        raise RuntimeError('Recovery artifact lacks state or Telegram receipts')
    for dest, raw in staged.items():
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_suffix(dest.suffix+'.recovery-tmp');tmp.write_bytes(raw);tmp.replace(dest)


def recover_previous(package):
    """Called under workflow concurrency, before any Telegram send."""
    if not os.environ.get('GITHUB_RUN_ID'):return False  # local tests/manual audit
    current=int(os.environ['GITHUB_RUN_ID'])
    runs=api(f'actions/workflows/{package}.yml/runs?per_page=100')['workflow_runs']
    prior=None
    artifacts=[]
    for candidate in runs:
        if candidate['id']>=current or candidate.get('status')!='completed':continue
        items=api(f"actions/runs/{candidate['id']}/artifacts")['artifacts']
        items=[a for a in items if a['name'].startswith(PREFIXES[package])]
        if not items:
            # Probe-only runs and cancellations before collection have no ledger.
            jobs=api(f"actions/runs/{candidate['id']}/jobs")['jobs']
            collected=any(s.get('name')=='Collecte et bilan independants' and
                          s.get('conclusion')!='skipped' for j in jobs for s in j.get('steps',[]))
            if collected:raise RuntimeError('Previous collection has no recovery artifact; no new stakes')
            continue
        prior=candidate;artifacts=items;break
    if prior is None:return False
    data=Path(package)/'data'
    if prior.get('conclusion')=='success':return False
    marker=data/'recovery.json'
    if marker.exists() and json.loads(marker.read_text()).get('recovered_run_id')==prior['id']:
        return False
    candidates=[a for a in artifacts if not a.get('expired') and a['name'].startswith(PREFIXES[package])]
    if len(candidates)!=1:
        raise RuntimeError('Interrupted run has no unambiguous recovery artifact; no new stakes')
    restore_archive(data,api(f"actions/artifacts/{candidates[0]['id']}/zip",binary=True))
    marker.write_text(json.dumps({'recovered_run_id':prior['id'],'artifact_id':candidates[0]['id']}))
    print('RECOVERED_RUN',prior['id'])
    return True
