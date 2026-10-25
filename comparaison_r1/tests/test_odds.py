import unittest
from comparaison_r1.odds import odds_label


class OddsDisplay(unittest.TestCase):
    def test_quote_time_is_pmu_time_in_paris(self):
        tip = {'captured_at': '2026-10-25T08:29:53+01:00', 'odds': {
            'rapport': 7.7, 'typeRapport': 'DIRECT', 'dateRapport': 1792912523000}}
        self.assertEqual(odds_label(tip), 'cote PMU SG 7.7 · direct 25/10 08h15')

    def test_reference_and_missing_time_are_explicit(self):
        self.assertEqual(odds_label({}), 'cote PMU SG indisponible')
        self.assertIn('référence', odds_label({'odds': {'rapport': 5, 'typeRapport': 'REFERENCE'}}))
        self.assertIn('heure non fournie', odds_label({'odds': {'rapport': 5}}))
