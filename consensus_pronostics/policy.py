"""New financial simulations from 2 November; old receipts remain authoritative."""
EFFECTIVE='2026-11-02'
def simplified(race):
    return race.get('date','') >= EFFECTIVE

def profile_enabled(race, profile):
    return not simplified(race) or profile == 'cotes'
