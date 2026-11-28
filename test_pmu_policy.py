import unittest
from datetime import datetime
from unittest.mock import Mock
from pmu_tracking import paris_affiches, formater_selection, envoyer_trace, analyser_message
from pmu_notifier import conseil_change

class RetainedScorerTests(unittest.TestCase):
    def setUp(self):
        self.top=[{'num_partant':1,'nom_cheval':'A','cote_jour':2},{'num_partant':2,'nom_cheval':'B','cote_jour':4}]
    def test_keep_order_only_without_converting_place_to_order(self):
        markets=['SIMPLE_PLACE','COUPLE_ORDRE']
        self.assertEqual(len(paris_affiches(self.top,7,markets,day='2026-11-01')),2)
        self.assertEqual(paris_affiches(self.top,7,markets,day='2026-11-02'),['COUPLE ORDRE : N1 + N2 (dans cet ordre)'])
        self.assertTrue(paris_affiches(self.top,8,markets+['COUPLE_PLACE'],day='2026-11-02')[0].startswith('AUCUN'))
    def test_delivery_cannot_bypass_new_policy(self):
        text='COURSE R1C1 — DEPART 15h00\nDATE : 2026-11-02\n1er choix : N1. A\nPARI : Simple Place sur N1'
        post=Mock()
        with self.assertRaises(ValueError):envoyer_trace(text,'token','chat',post=post,now=datetime.fromisoformat('2026-11-02T14:00:00+01:00'))
        post.assert_not_called()
    def test_order_parses_at_original_five_euros(self):
        txt='COURSE R1C1 — DEPART 15h00\nDATE : 2026-11-02\n'+'\n'.join(formater_selection(self.top,7,marches=['SIMPLE_PLACE','COUPLE_ORDRE'],day='2026-11-02'))
        e=analyser_message(txt,datetime.fromisoformat('2026-11-02T14:00:00+01:00'))
        self.assertEqual(e['paris'],[{'type':'COUPLE_ORDRE','numeros':['1','2'],'mise':'5.00'}])

    def test_order_advice_ignores_odds_and_hidden_alert_changes(self):
        day='2026-11-02'
        markets=['SIMPLE_PLACE','COUPLE_ORDRE']
        txt='COURSE R1C1 — DEPART 15h00\nDATE : '+day+'\n'+'\n'.join(formater_selection(self.top,7,marches=markets,day=day))
        prev={'event':analyser_message(txt,datetime.fromisoformat(day+'T14:00:00+01:00'))}
        maj={'top2_final':[dict(p,cote_actuel=3) for p in self.top],
             'paris_disponibles':markets,
             'experience':{'alertes':[{'num_partant':3,'motif':'Baisse de cote'}]}}
        self.assertFalse(conseil_change(maj,7,prev,day=day))
        self.assertTrue(conseil_change({**maj,'top2_final':self.top[::-1]},7,prev,day=day))
        self.assertTrue(conseil_change({**maj,'paris_disponibles':['SIMPLE_PLACE']},7,prev,day=day))

    def test_policy_change_is_detected_for_same_horses(self):
        markets=['SIMPLE_PLACE','COUPLE_ORDRE']
        txt='COURSE R1C1 — DEPART 15h00\nDATE : 2026-11-01\n'+'\n'.join(formater_selection(self.top,7,marches=markets,day='2026-11-01'))
        prev={'event':analyser_message(txt,datetime.fromisoformat('2026-11-01T14:00:00+01:00'))}
        maj={'top2_final':self.top,'paris_disponibles':markets}
        self.assertFalse(conseil_change(maj,7,prev,day='2026-11-01'))
        self.assertTrue(conseil_change(maj,7,prev,day='2026-11-02'))


class OfficialDisciplineTests(unittest.TestCase):
    def test_pmu_obstacle_codes_reach_notifier_and_initial_scorer(self):
        from unittest.mock import patch
        import pmu_notifier as notifier
        import pmu_scorer as scorer
        courses = [{'numOrdre': i, 'discipline': code, 'heureDepart': 1,
                    'paris': [{'typePari': 'E_COUPLE_ORDRE'}]}
                   for i, code in enumerate(('HAIE', 'STEEPLECHASE', 'HAIES', 'STEEPLE'), 1)]
        programme = {'programme': {'reunions': [{'numOfficiel': 2,
                     'pays': {'code': 'FRA'}, 'courses': courses}]}}
        with patch.object(notifier, 'api_get', return_value=programme):
            self.assertEqual(len(notifier.get_courses_du_jour('27112026')), 4)
        for course in courses:
            self.assertIn(course['discipline'], scorer.DISCIPLINES)
