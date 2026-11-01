"""Audit observations without promoting previews into executable votes."""
from copy import deepcopy


def remember_preview(original, preview, groups, now):
    observation = {'at': now.isoformat(), 'groups': deepcopy(groups),
                   'tips': deepcopy(preview.get('tips', {}))}
    original.setdefault('preview_observations', []).append(observation)


def missing_control_reason(race):
    # Old captures prove a final control even before the new timestamps existed.
    if race.get('tips') or race.get('groups') or race.get('final_check_completed_at'):
        return None
    if race.get('final_check_started_at'):
        return 'Contrôle final commencé mais non terminé ; aucune mise confirmée'
    observations = race.get('preview_observations', [])
    agreement = observations[-1].get('groups') if observations else None
    prefix = 'Accord observé dans un aperçu ; ' if agreement else ''
    return prefix + 'contrôle final avant départ non enregistré ; course manquée ou contrôle indisponible'
