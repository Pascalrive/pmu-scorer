"""Persiste les recus Telegram, meme si un autre job vient de pousser ses CSV."""
from pathlib import Path
import subprocess


def run(*args, check=True):
    return subprocess.run(args, check=check)


def main():
    paths = [str(p) for p in (Path('resultats/journal'), Path('resultats/bilans'), Path('resultats/officiels'), Path('resultats/observations')) if p.exists()]
    paths.extend(str(p) for p in Path('resultats').glob('pmu_*.csv'))
    if not paths:
        return
    run('git', 'config', 'user.name', 'PMU Bot')
    run('git', 'config', 'user.email', 'pmu@github-actions')
    run('git', 'add', '--', *paths)
    if run('git', 'diff', '--cached', '--quiet', check=False).returncode == 0:
        return
    run('git', 'commit', '-m', 'Archiver les envois Telegram et bilans officiels')
    for _ in range(3):
        # autostash preserve les CSV du scorer, geres par l'etape suivante.
        run('git', 'pull', '--rebase', '--autostash')
        if run('git', 'push', check=False).returncode == 0:
            return
    raise RuntimeError('Journal non pousse : recuperer l artefact de secours de ce run')


if __name__ == '__main__':
    main()
