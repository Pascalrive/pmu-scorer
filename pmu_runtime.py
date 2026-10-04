"""Controles d'exploitation : rattrapage initial et date du bilan, sans changer les scores."""
import csv
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Paris')


def csv_du_jour(day, root=Path('resultats')):
    """Un fichier vide ou illisible ne vaut pas collecte reussie."""
    for path in sorted(root.glob(f'pmu_{day}_*.csv'), reverse=True):
        try:
            with path.open(encoding='utf-8-sig', newline='') as source:
                rows = list(csv.DictReader(source))
            if rows and all(row.get('reunion') and row.get('course') and
                            row.get('num_partant') for row in rows):
                return path
        except (OSError, UnicodeError, csv.Error):
            continue
    return None


def assurer_initial(day, root=Path('resultats'), run=subprocess.run):
    if not csv_du_jour(day, root):
        print(f'::warning::Collecte initiale absente pour {day} : lancement de rattrapage', flush=True)
        run([sys.executable, 'pmu_scorer.py'], check=True)
    if not csv_du_jour(day, root):
        raise RuntimeError(f'COLLECTE EN ECHEC : aucun CSV exploitable pour {day}')


def date_bilan(now, explicit='', scheduled=False):
    if explicit:
        parsed = datetime.strptime(explicit, '%Y%m%d')
        if parsed.strftime('%Y%m%d') != explicit:
            raise ValueError('Date attendue : AAAAMMJJ')
        return explicit
    local = now.astimezone(TZ)
    # Le cron du bilan est le matin : toujours la journee civile precedente,
    # meme lorsque GitHub retarde le demarrage de plusieurs heures.
    return (local - timedelta(days=1) if scheduled else local).strftime('%Y%m%d')


def diagnostic(day, root=Path('resultats')):
    records = [json.loads(p.read_text()) for p in (root / 'journal').glob(f'{day}-*.json')]
    from pmu_tracking import dernieres_selections
    selected = dernieres_selections(records, day)
    observations = list((root / 'observations' / day).glob('*.json'))
    return {'date': day, 'csv': str(csv_du_jour(day, root) or ''),
            'observations': len(observations), 'journaux': len(records),
            'courses_avant_depart': len(selected),
            'envois_confirmes': sum(r.get('delivery') == 'SENT' for r in selected.values())}


def main():
    mode = sys.argv[1]
    now = datetime.now(TZ)
    day = now.strftime('%Y%m%d')
    if mode == 'collect':
        assurer_initial(day)
        subprocess.run([sys.executable, 'pmu_notifier.py'], check=True)
    elif mode == 'check':
        if not csv_du_jour(day):
            raise RuntimeError(f'COLLECTE EN ECHEC : aucun CSV exploitable pour {day}')
    elif mode == 'bilan':
        env = dict(os.environ)
        env['PMU_BILAN_DATE'] = date_bilan(now, env.get('PMU_BILAN_DATE_INPUT', ''),
                                         env.get('PMU_SCHEDULED') == '1')
        subprocess.run([sys.executable, 'pmu_results.py'], env=env, check=True)
    elif mode == 'diagnostic':
        for value in sys.argv[2:] or [day]:
            print(json.dumps(diagnostic(value), ensure_ascii=False))
    else:
        raise ValueError('Mode inconnu')


if __name__ == '__main__':
    main()
