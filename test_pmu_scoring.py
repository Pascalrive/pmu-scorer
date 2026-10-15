"""Regression des erreurs de donnees et d'arithmetique, sans cible de rendement."""
from datetime import datetime, timedelta
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pmu_scorer as s


class ScoringTests(TestCase):
    def test_replay_archived_pre_race_participants_without_network_or_outcome(self):
        data = json.loads((Path(__file__).parent / 'tests/fixtures/scoring-20261014-r4c2.json').read_text())
        with ExitStack() as stack:
            for name, value in [('api_get', data['course']),
                                ('get_participants', deepcopy(data['participants'])),
                                ('get_performances', []), ('get_pronostics_pmu', []),
                                ('get_cote_veille', 0), ('archiver_observation', None)]:
                stack.enter_context(patch.object(s, name, return_value=value))
            stack.enter_context(patch.object(s.time, 'sleep'))
            result = s.analyser_course('14102026', '2026-10-14', '13102026',
                                      '14/10/2026', 4, 2, data['course'],
                                      hippodrome='HIPPODROME DE CABOURG', activer_presse=False)
        runners = result['tous_resultats']
        self.assertEqual(len(runners), 15)  # Une des seize engagees est non-partante.
        self.assertTrue(all(p['score_trio_pje'] == 50 for p in runners))
        self.assertTrue(all(p['source_performances'] == 'MUSIQUE_SEULE' for p in runners))
        self.assertTrue(all(p['nb_performances_detaillees'] == 0 for p in runners))
        queen = next(p for p in runners if p['nom_cheval'] == 'MISSISSIPPI QUEEN')
        self.assertEqual(queen['score_fautes'], -8)

    def test_horse_career_is_not_a_persons_statistics(self):
        runners = [dict(driver='M. MOTTIER', entraineur='V. COLIGNY',
                        nombreVictoires=2, nombreCourses=13)]
        for wins in (0, 2, 13):
            runners[0]['nombreVictoires'] = wins
            self.assertEqual(s.score_jockey_global('M. MOTTIER', runners), 50)
            self.assertEqual(s.score_entraineur_global('V. COLIGNY', runners), 50)
        self.assertEqual(s.get_stats_proprietaire('ECURIE BAZIRE', 'CABOURG'), 50)

    def test_driver_trainer_identity_requires_more_than_shared_initial(self):
        # L'ancien test acceptait D. THOMAIN / D. TRAVERT (archive du 14/10).
        self.assertFalse(s.meme_personne('D. THOMAIN', 'D. TRAVERT'))
        self.assertFalse(s.meme_personne('K. DAVID', 'L.M. DAVID'))
        self.assertFalse(s.meme_personne('', ''))
        self.assertTrue(s.meme_personne('L.M. DAVID', 'l. m. david'))
        self.assertTrue(s.meme_personne('É. RAFFIN', 'E. RAFFIN'))
        self.assertFalse(s.meme_personne('G. HORRACH VIDAL', 'Guillermo HORRACH VIDAL'))

    def test_faults_count_recent_left_hand_runs_not_old_runs(self):
        self.assertEqual(s.score_fautes_trot([], musique='DaDaDa1a1a1a1a1a1a1a'), -12)
        self.assertEqual(s.score_fautes_trot([], musique='1a1a1a1a1aDaDaDaDaDa'), 0)
        self.assertEqual(s.score_fautes_trot([], musique='Da(25)1a'), -12)

    def test_partial_history_does_not_double_count_music(self):
        self.assertEqual(s.score_fautes_trot([{'ordreArrivee': 'D'}], musique='Da'), -18)
        self.assertEqual(s.score_fautes_trot([{'place': 1}], musique='DaDaDa'), 0)
        self.assertEqual(s.score_fautes_trot([], musique=''), 0)

    def test_venue_percentages_do_not_saturate_on_one_placing(self):
        perfs = [dict(place=p, hippodrome='CABOURG', driver='D. THOMAIN')
                 for p in (1, 2, 5, 6)]
        # 25% de victoires, 50% places => 25%*60 + 50%*40 = 35.
        self.assertEqual(s.score_hippodrome_cheval(perfs, 'CABOURG'), 35)
        self.assertEqual(s.score_jockey_sur_hippodrome(perfs, 'D. THOMAIN', 'CABOURG'), 35)
        self.assertEqual(s.score_jockey_sur_hippodrome(perfs, 'D. THOMAIN', 'REIMS'), 27.5)
        self.assertEqual(s.score_jockey_sur_hippodrome(perfs, 'D. THO', 'CABOURG'), 50)

    def test_music_does_not_provide_undocumented_aptitudes(self):
        perfs = s.musique_vers_perfs('1a2a3a')
        self.assertEqual(s.score_forme_recente(perfs), 90)
        self.assertEqual(s.score_forme_fraiche(perfs), 50)
        self.assertEqual(s.score_distance(perfs, 2750, 'CONDITIONS'), 50)
        self.assertEqual(s.score_hippodrome_cheval(perfs, 'CABOURG'), 50)

    def test_future_performance_is_not_recent_form(self):
        future = (datetime.now() + timedelta(days=2)).timestamp() * 1000
        self.assertEqual(s.score_forme_fraiche([{'place': 1, 'date': future}]), 50)
