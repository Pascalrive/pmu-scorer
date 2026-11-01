import copy
from datetime import datetime, timedelta
import importlib
import unittest
from unittest.mock import patch

from comparaison_r1.run_health import remember_preview
from comparaison_r1.worker import active, checkpoint, dispatch, PACKAGES


class RunHealthTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-11-01T15:00:00+01:00')
        self.race = {'id':'R1C4','c':4,'date':'2026-11-01','title':'TEST',
                     'departure':'2026-11-01T15:15:00+01:00',
                     'tips':{},'groups':{},'errors':{}}

    def test_missing_capture_is_not_disagreement_in_all_programs(self):
        for pkg in PACKAGES:
            mod = importlib.import_module(pkg+'.main')
            race = copy.deepcopy(self.race)
            race['no_bet_reason'] = 'Moins de trois premiers choix identiques validés'
            self.assertIn('contrôle final avant départ non enregistré', mod.no_bet_reason({'date':race['date']},race))

    def test_preview_is_audit_only_and_cannot_become_votes(self):
        race = copy.deepcopy(self.race)
        preview = {'tips':{'geny':{'number':4}}}
        remember_preview(race,preview,{'majorite':{'number':4}},self.now)
        preview['tips']['geny']['number']=12
        self.assertEqual(race['tips'],{})
        self.assertEqual(race['groups'],{})
        self.assertEqual(race['preview_observations'][0]['tips']['geny']['number'],4)
        mod=importlib.import_module('tony_artillan_3_5.main')
        self.assertIn('Accord observé dans un aperçu',mod.no_bet_reason({},race))

    def test_real_checked_disagreement_is_retained(self):
        for pkg in PACKAGES:
            mod=importlib.import_module(pkg+'.main');race=copy.deepcopy(self.race)
            race['final_check_completed_at']=self.now.isoformat()
            self.assertNotIn('course manquée',mod.no_bet_reason({},race))

    def test_official_error_is_not_hidden_by_empty_votes(self):
        for pkg in PACKAGES:
            mod=importlib.import_module(pkg+'.main');race=copy.deepcopy(self.race)
            race['errors']['official']={'reason':'Identité officielle modifiée'}
            self.assertEqual(mod.no_bet_reason({},race),'Identité officielle modifiée')

    def test_delivery_failure_keeps_its_explicit_reason(self):
        mod=importlib.import_module('tony_artillan_3_5.main');race=copy.deepcopy(self.race)
        race.update(delivery_attempt={'status':'FAILED'},no_bet_reason='Envoi non confirmé')
        self.assertEqual(mod.no_bet_reason({},race),'Envoi non confirmé')

    def test_incomplete_control_is_visible(self):
        mod=importlib.import_module('tony_artillan_3_5.main');race=copy.deepcopy(self.race)
        race['final_check_started_at']=self.now.isoformat()
        self.assertIn('commencé mais non terminé',mod.no_bet_reason({},race))

    def test_active_window_is_bounded_to_current_meeting(self):
        state={'date':'2026-11-01','races':[self.race]}
        self.assertTrue(active(state,self.now))
        self.assertFalse(active(state,self.now-timedelta(hours=2)))
        self.assertFalse(active(state,self.now+timedelta(hours=2)))
        self.assertFalse(active(state,self.now+timedelta(days=1)))

    def test_persistence_failure_stops_worker(self):
        with patch('comparaison_r1.worker.subprocess.run',side_effect=RuntimeError('push failed')):
            with self.assertRaises(RuntimeError):checkpoint('tony_artillan_3_5')

    def test_continuation_calls_only_same_workflow(self):
        with patch.dict('os.environ',{'GH_TOKEN':'test','GITHUB_REPOSITORY':'owner/repo'}), patch('comparaison_r1.worker.urlopen') as call:
            call.return_value.__enter__.return_value.status=204
            dispatch('tony_artillan_3_5')
            request=call.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/tony_artillan_3_5.yml/dispatches'))
            self.assertEqual(request.get_method(),'POST')

    def test_all_programs_require_complete_predeparture_receipts(self):
        for pkg in PACKAGES:
            mod=importlib.import_module(pkg+'.main')
            departure=self.race['departure']
            epoch=int(datetime.fromisoformat(departure).timestamp())
            good={'status':'SENT','receipts':[{'message_id':4,'date':epoch-1}]}
            self.assertTrue(mod.confirmed_before(good,departure))
            for bad in (None,{'status':'SENT','receipts':[]},
                        {'status':'UNCERTAIN','receipts':good['receipts']},
                        {'status':'SENT','receipts':[{'message_id':4,'date':epoch}]},
                        {'status':'SENT','receipts':good['receipts']+[{'message_id':5,'date':epoch+1}]}):
                self.assertFalse(mod.confirmed_before(bad,departure))


if __name__=='__main__':unittest.main()
