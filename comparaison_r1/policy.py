"""Prospective discipline filter; historical accounting is never rewritten."""
EFFECTIVE = '2026-11-02'

def flat_only_reason(race):
    if race.get('date', '') < EFFECTIVE:
        return None
    discipline = str(race.get('discipline') or '').strip().upper()
    if discipline == 'PLAT':
        return None
    return ('Test plat uniquement depuis le 02/11 : ' +
            (discipline + ' exclu' if discipline else 'discipline officielle indisponible'))
