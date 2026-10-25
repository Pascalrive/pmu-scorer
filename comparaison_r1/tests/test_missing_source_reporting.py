import unittest
from copy import deepcopy
from comparaison_r1 import main as majority
from tony_artillan_2 import main as pair
from comparaison_r1.geny_fallback import GenyFallbackError


class MissingSourceReporting(unittest.TestCase):
    def test_missing_sources_never_crash_either_report(self):
        race = {'date': '2026-10-25', 'id': 'R1C5', 'c': 5,
                'title': "PRIX DE L'ELEVAGE", 'departure': '2026-10-25T15:15:00+01:00',
                'tips': {}, 'groups': {}, 'errors': {}}
        for runner in (majority, pair):
            with self.subTest(program=runner.__name__):
                self.assertIn('GENY : sélection non disponible', runner.race_message(race))
                r = deepcopy(race)
                e = GenyFallbackError('Geny indisponible', ValueError('Rubrique éditoriale absente'))
                r['errors']['geny'] = {'source_status': e.source_status}
                self.assertIn('secours Genybet tenté, aucun choix validé', runner.race_message(r))
                preview = {'captured_at': '2026-10-25T08:00:00+01:00', 'races': [r]}
                self.assertIn('secours Genybet tenté, aucun choix validé', runner.preview_report({'date': r['date'], 'venue': 'SAINT-CLOUD'}, preview))
                self.assertEqual(r['tips'], {})

    def test_successful_backup_keeps_its_label(self):
        for runner in (majority, pair):
            r = {'date': '2026-10-25', 'id': 'R1C1', 'c': 1, 'title': 'TEST',
                 'departure': '2026-10-25T13:00:00+01:00', 'groups': {},
                 'tips': {'geny': {'number': 1, 'name': 'HORSE', 'playable': True, 'fallback': True}}}
            self.assertIn('GENY (secours Genybet) : N°1', runner.race_message(r))
