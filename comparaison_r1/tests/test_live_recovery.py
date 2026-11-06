import copy
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import zipfile

from comparaison_r1 import recovery, worker
from comparaison_r1.run_health import missing_control_reason, urgent_course


PACKAGES=('comparaison_r1','tony_artillan_2','tony_artillan_3_5')


class LiveControlTests(unittest.TestCase):
    def collect(self, package, seconds=40, late_third=False):
        m=importlib.import_module(package+'.main')
        now=[datetime.fromisoformat('2026-11-06T14:29:00+01:00')]
        departure=now[0]+timedelta(seconds=seconds)
        race={'id':'R1C2','c':2,'date':'2026-11-06','title':'TEST','discipline':'PLAT',
              'departure':departure.isoformat(),'tips':{},'groups':{},'errors':{}}
        horse={'numPmu':12,'nom':'TEST HORSE','statut':'PARTANT'}
        meta={'numReunion':1,'numOrdre':2,'libelle':'TEST','discipline':'PLAT',
              'heureDepart':departure.timestamp()*1000,'paris':[{'typePari':'E_SIMPLE_GAGNANT'}]}
        fetch=Mock();fetch.json.side_effect=lambda url:{'participants':[horse]} if url.endswith('/participants') else meta
        read=[]
        def tip(site,*args):
            read.append(site)
            if late_third and len(read)==3:now[0]=departure+timedelta(seconds=1)
            else:now[0]+=timedelta(seconds=2)
            return 'url','body',{'site':site,'number':12,'name':'TEST HORSE'}
        with patch.object(m,'read_tip',side_effect=tip),patch.object(m,'proof',return_value={}):
            m.collect_race(race,fetch,Path('.'),clock=lambda:now[0])
        return m,race,read,departure

    def test_majority_does_not_wait_for_optional_fourth_or_fifth(self):
        for package in ('comparaison_r1','tony_artillan_3_5'):
            with self.subTest(package=package):
                m,r,read,departure=self.collect(package)
                self.assertEqual(len(read),3)
                self.assertTrue(r['groups'])
                self.assertLess(datetime.fromisoformat(r['groups_frozen_at']),departure)

    def test_two_source_account_still_requires_both(self):
        m,r,read,_=self.collect('tony_artillan_2')
        self.assertEqual(set(read),{'geny','canalturf'})
        self.assertIn('accord_geny_canalturf',r['groups'])

    def test_late_vote_is_not_promoted_to_majority(self):
        for package in ('comparaison_r1','tony_artillan_3_5'):
            m,r,read,_=self.collect(package,late_third=True)
            self.assertEqual(len(r['tips']),2)
            self.assertFalse(r['groups'])
            self.assertIn('incomplet',missing_control_reason(r).lower())

    def test_partial_three_votes_classified_by_rule_even_without_fourth(self):
        m,r,_,_=self.collect('comparaison_r1')
        self.assertIsNone(missing_control_reason(r))
        self.assertEqual(r['groups']['majorite_3_ou_4']['number'],12)

    def test_outside_urgent_window_all_sources_are_observed(self):
        for package in PACKAGES:
            m,r,read,_=self.collect(package,seconds=300)
            self.assertEqual(len(read),len(m.SITES))

    def test_nearest_future_course_is_selected(self):
        now=datetime.fromisoformat('2026-11-06T14:00:00+01:00')
        races=[{'id':str(n),'departure':(now+timedelta(seconds=n)).isoformat()} for n in (120,40,-5,200)]
        self.assertEqual(urgent_course({'races':races},now)['id'],'40')

    def test_pending_settlement_precedes_observations(self):
        for package in PACKAGES:
            m=importlib.import_module(package+'.main')
            state={'date':'2026-11-06','races':[
                {'id':'R1C1','c':1,'departure':'2026-11-06T12:00:00+01:00','tips':{}},
                {'id':'R1C2','c':2,'departure':'2026-11-06T13:00:00+01:00','tips':{}}],
                'solutions':{'account':{'bets':[{'race_id':'R1C2','status':'EN_ATTENTE'}]}}}
            f=Mock();calls=[]
            def payload(url):
                calls.append(url)
                return {'participants':[]} if url.endswith('/participants') else []
            f.json.side_effect=payload
            with patch.object(m,'datetime') as dt,patch.object(m,'settle',return_value=False):
                dt.now.return_value=datetime.fromisoformat('2026-11-06T14:00:00+01:00')
                dt.fromisoformat.side_effect=datetime.fromisoformat
                m.settle_state(state,f,Path('.'),pending_only=True)
            self.assertTrue(calls)
            self.assertTrue(all('/C2/' in url for url in calls))


class RecoveryTests(unittest.TestCase):
    def state(self,status='EN_ATTENTE'):
        return {'date':'2026-11-06','solutions':{'account':{'bets':[{
            'race_id':'R1C1','number':9,'stake_cents':10000,'status':status,
            'telegram_fingerprint':'abc','telegram_receipts':[{'message_id':1,'date':1}]}]}}}

    def archive(self, files):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for name,obj in files.items():z.writestr(name,json.dumps(obj))
        return buf.getvalue()

    def test_restore_receipts_before_next_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);state=self.state()
            payload=self.archive({'2026-11-06/state.json':state,'notifications.json':{'notifications':[{'fingerprint':'abc','status':'SENT'}]}})
            recovery.restore_archive(p,payload)
            self.assertEqual(json.loads((p/'2026-11-06/state.json').read_text()),state)
            self.assertEqual(json.loads((p/'notifications.json').read_text())['notifications'][0]['status'],'SENT')

    def test_existing_settlement_never_downgraded(self):
        current=self.state('PERDU');current['solutions']['account']['bets'][0].update(return_cents=0,profit_cents=-10000)
        restored=self.state();recovery.preserve_financial_state(current,restored)
        self.assertEqual(restored,current)

    def test_conflicting_or_missing_bet_blocks_restore(self):
        current=self.state();restored=self.state()
        restored['solutions']['account']['bets'][0]['stake_cents']=20000
        with self.assertRaises(RuntimeError):recovery.preserve_financial_state(current,restored)

    def test_unsafe_paths_and_missing_outbox_rejected(self):
        for files in ({'../escape':{}},{'2026-11-06/state.json':self.state()}):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError):recovery.restore_archive(Path(tmp),self.archive(files))
                self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_no_new_run_after_unrecoverable_predecessor(self):
        prior={'id':10,'status':'completed','conclusion':'failure'}
        responses=[{'workflow_runs':[prior]},{'artifacts':[]},
                   {'jobs':[{'steps':[{'name':'Collecte et bilan independants','conclusion':'failure'}]}]}]
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'11'}),patch.object(recovery,'api',side_effect=responses):
            with self.assertRaises(RuntimeError):recovery.recover_previous('comparaison_r1')

    def test_successful_probe_cannot_hide_failed_collection(self):
        runs=[{'id':10,'status':'completed','conclusion':'success'}, {'id':9,'status':'completed','conclusion':'failure'}]
        responses=[{'workflow_runs':runs},{'artifacts':[]},{'jobs':[{'steps':[{'name':'Collecte et bilan independants','conclusion':'skipped'}]}]},
                   {'artifacts':[{'id':77,'name':'comparaison-r1-9','expired':False}]},b'zip']
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GITHUB_RUN_ID':'11'}),patch.object(recovery,'api',side_effect=responses),patch.object(recovery,'restore_archive') as restore,patch.object(recovery,'Path') as path:
            data=Path(tmp);path.return_value.__truediv__.return_value=data
            self.assertTrue(recovery.recover_previous('comparaison_r1'))
            restore.assert_called_once_with(data,b'zip')

    def test_archive_failure_requests_only_one_recovery_child(self):
        fixed=datetime.fromisoformat('2026-11-06T14:00:00+01:00')
        for attempt,expected in [('0',1),('1',0)]:
            with tempfile.TemporaryDirectory() as tmp:
                cwd=os.getcwd();os.chdir(tmp)
                try:
                    p=Path('comparaison_r1/data/2026-11-06');p.mkdir(parents=True)
                    (p/'state.json').write_text(json.dumps({'date':'2026-11-06','races':[{'departure':'2026-11-06T14:15:00+01:00'}]}))
                    with patch.dict(os.environ,{'RECOVERY_ATTEMPT':attempt}),patch.object(worker,'recover_previous',return_value=False),patch.object(worker,'datetime') as dt,patch.object(worker.subprocess,'run',return_value=Mock(returncode=0)),patch.object(worker,'checkpoint',side_effect=RuntimeError('push failed')),patch.object(worker,'dispatch') as dispatch:
                        dt.now.return_value=fixed;dt.fromisoformat.side_effect=datetime.fromisoformat
                        with self.assertRaises(RuntimeError):worker.run('comparaison_r1',persist=True,continue_run=True)
                        self.assertEqual(dispatch.call_count,expected)
                        if expected:dispatch.assert_called_once_with('comparaison_r1',recovery_attempt=1)
                finally:os.chdir(cwd)


if __name__=='__main__':unittest.main()
