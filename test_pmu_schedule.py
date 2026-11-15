import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from operations.live_window import useful, pending_bets
from comparaison_r1 import worker


class LiveScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-11-15T14:00:00+01:00')

    def programme(self, minutes=15, discipline='PLAT', market='E_COUPLE_ORDRE'):
        return {'programme': {'reunions': [{'numOfficiel': 1, 'pays': {'code': 'FRA'},
            'courses': [{'heureDepart': (self.now + timedelta(minutes=minutes)).timestamp()*1000,
                         'discipline': discipline, 'paris': [{'typePari': market}]}]}]}}

    def test_classic_keeps_obstacles_but_secondary_flat_only(self):
        p = self.programme(discipline='HAIE')
        self.assertTrue(useful('comparaison_r1', p, self.now)[0])
        for pkg in ('tony_artillan_2', 'tony_artillan_3_5'):
            self.assertFalse(useful(pkg, p, self.now)[0])
            self.assertTrue(useful(pkg, self.programme(), self.now)[0])

    def test_no_idle_processing_between_or_after_races(self):
        for minutes in (90, -60):
            self.assertFalse(useful('comparaison_r1', self.programme(minutes), self.now)[0])
        self.assertTrue(useful('comparaison_r1', self.programme(-10), self.now)[0])
        self.assertTrue(useful('comparaison_r1', self.programme(-60), self.now, pending=True)[0])

    def test_scorer_couple_ordre_only_and_no_postdeparture_send(self):
        self.assertTrue(useful('scorer', self.programme(), self.now)[0])
        self.assertFalse(useful('scorer', self.programme(market='E_SIMPLE_GAGNANT'), self.now)[0])
        self.assertFalse(useful('scorer', self.programme(-1), self.now)[0])

    def test_pending_requires_a_confirmed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/'comparaison_r1/data/2026-11-15/state.json';p.parent.mkdir(parents=True)
            bet={'status':'EN_ATTENTE'}
            def save():p.write_text(json.dumps({'solutions':{'majority':{'bets':[bet]}}}))
            save();self.assertFalse(pending_bets('comparaison_r1','2026-11-15',root))
            bet['telegram_receipts']=[{'message_id':1}];save()
            self.assertTrue(pending_bets('comparaison_r1','2026-11-15',root))

    def test_single_pass_persists_without_sleep_or_recursive_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd=os.getcwd();os.chdir(tmp)
            try:
                with patch.object(worker,'recover_previous',return_value=False), \
                     patch.object(worker,'checkpoint') as cp, \
                     patch.object(worker.subprocess,'run',return_value=Mock(returncode=0)), \
                     patch.object(worker.time,'sleep') as sleep, patch.object(worker,'dispatch') as send:
                    worker.run('comparaison_r1',persist=True,once=True)
                    cp.assert_called_once();sleep.assert_not_called();send.assert_not_called()
            finally:os.chdir(cwd)

    def test_single_pass_failure_stays_red_and_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd=os.getcwd();os.chdir(tmp)
            try:
                with patch.object(worker,'recover_previous',return_value=False), \
                     patch.object(worker,'checkpoint') as cp, \
                     patch.object(worker.subprocess,'run',return_value=Mock(returncode=1)):
                    with self.assertRaises(RuntimeError):worker.run('comparaison_r1',persist=True,once=True)
                    cp.assert_called_once()
            finally:os.chdir(cwd)

    def test_workflows_really_use_single_pass_and_regular_poll(self):
        for pkg in ('comparaison_r1','tony_artillan_2','tony_artillan_3_5'):
            text=Path('.github/workflows',pkg+'.yml').read_text()
            self.assertIn("cron: '7,17,27,37,47,57 8-22 * * *'",text)
            self.assertIn('worker '+pkg+' --persist --once',text)
            self.assertIn('python operations/live_window.py '+pkg,text)
        text=Path('.github/workflows/pmu_daily.yml').read_text()
        self.assertIn("github.event.schedule == '7,17,27,37,47,57 8-22 * * *'",text)
        self.assertIn('python operations/live_window.py scorer',text)


if __name__ == '__main__':
    unittest.main()
