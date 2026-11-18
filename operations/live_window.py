"""Dependency-free preflight. Poll only useful windows; never creates a bet."""
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')
API = 'https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'
TONY = ('comparaison_r1', 'tony_artillan_2', 'tony_artillan_3_5')


def experiment_open(package, day, root=Path('.')):
    if package not in TONY:
        return True
    tree = ast.parse((root / package / 'model.py').read_text())
    dates = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in ('START', 'END'):
                    dates[name.id] = node.value.value
    return dates['START'] <= day <= dates['END']


def useful(package, programme, now, pending=False):
    if pending and package in TONY:
        return True, 'Reglement de mises confirmees en attente'
    for meeting in programme['programme']['reunions']:
        if meeting.get('pays', {}).get('code') not in ('FRA', 'FRANCE'):
            continue
        if package in TONY and meeting.get('numOfficiel') != 1:
            continue
        for race in meeting.get('courses', []):
            if package in TONY[1:] and now.date().isoformat() >= '2026-11-02' and race.get('discipline') != 'PLAT':
                continue
            # Scorer only retains couple ordre since 02/11. Keep H60 observations.
            if package == 'scorer' and now.date().isoformat() >= '2026-11-02':
                if not any(p.get('typePari') == 'E_COUPLE_ORDRE' and p.get('enVente') is not False for p in race.get('paris', [])):
                    continue
            minutes = (race['heureDepart'] / 1000 - now.timestamp()) / 60
            if (-35 if package in TONY else 0) <= minutes <= 70:
                return True, 'Course dans la fenetre de controle ou de reglement'
    return False, 'Aucune course utile dans la fenetre ; calcul et collecte evites'


def pending_bets(package, day, root=Path('.')):
    if package not in TONY:
        return False
    path = root / package / 'data' / day / 'state.json'
    if not path.exists():
        return False
    state = json.loads(path.read_text())
    return any(b.get('status') == 'EN_ATTENTE' and b.get('telegram_receipts')
               for sol in state.get('solutions', {}).values() for b in sol.get('bets', []))


def main():
    package = sys.argv[1]
    now = datetime.now(TZ)
    enabled, reason = True, 'Passage initial, manuel ou bilan'
    if os.environ.get('LIVE_POLL') == 'true':
        if not experiment_open(package, now.date().isoformat()):
            enabled, reason = False, 'Experience hors periode'
        else:
            try:
                pending = pending_bets(package, now.date().isoformat())
                with urlopen(API + now.strftime('%d%m%Y'), timeout=20) as response:
                    programme = json.load(response)
                enabled, reason = useful(package, programme, now, pending)
            except Exception as exc:
                # Do not suppress a real control because an optimisation API failed.
                enabled, reason = True, 'Precontrole indisponible : controle complet requis (' + type(exc).__name__ + ')'
    print(reason)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('enabled=' + str(enabled).lower() + '\n')


if __name__ == '__main__':
    main()
