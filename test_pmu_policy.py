import unittest
from datetime import datetime
from unittest.mock import Mock
from pmu_tracking import paris_affiches, formater_selection, envoyer_trace, analyser_message

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
