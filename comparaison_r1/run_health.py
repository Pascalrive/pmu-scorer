"""Audit observations without promoting previews into executable votes."""
from copy import deepcopy
from datetime import datetime, timedelta


def remember_preview(original, preview, groups, now):
    observation = {'at': now.isoformat(), 'groups': deepcopy(groups),
                   'tips': deepcopy(preview.get('tips', {}))}
    original.setdefault('preview_observations', []).append(observation)


def missing_control_reason(race):
    if race.get('final_check_started_at') and not race.get('final_check_completed_at') and not race.get('groups'):
        return 'Contrôle final commencé mais non terminé ; avis partiels incomplets, aucune mise confirmée'
    # Old captures prove a final control even before the new timestamps existed.
    if race.get('tips') or race.get('groups') or race.get('final_check_completed_at'):
        return None
    if race.get('final_check_started_at'):
        return 'Contrôle final commencé mais non terminé ; aucune mise confirmée'
    observations = race.get('preview_observations', [])
    agreement = observations[-1].get('groups') if observations else None
    prefix = 'Accord observé dans un aperçu ; ' if agreement else ''
    return prefix + 'contrôle final avant départ non enregistré ; course manquée ou contrôle indisponible'



def urgent_course(state, now, seconds=120):
    future=[r for r in state.get('races',[]) if 0<(datetime.fromisoformat(r['departure'])-now).total_seconds()<=seconds]
    return min(future,key=lambda r:r['departure']) if future else None


def live_window(state, now):
    if state.get('date')!=now.date().isoformat():return False
    starts=[datetime.fromisoformat(r['departure']) for r in state.get('races',[])]
    return bool(starts) and min(starts)-timedelta(minutes=70)<=now<=max(starts)+timedelta(minutes=35)
