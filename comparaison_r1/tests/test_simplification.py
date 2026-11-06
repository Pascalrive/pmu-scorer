import copy
import importlib
import json
import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch, Mock
from comparaison_r1.policy import flat_only_reason
from comparaison_r1.worker import checkpoint, dispatch

class SimplificationTests(unittest.TestCase):
    def test_filter_is_prospective_and_fails_closed(self):
        self.assertIsNone(flat_only_reason({'date':'2026-11-01','discipline':'TROT_ATTELE'}))
        self.assertIsNone(flat_only_reason({'date':'2026-11-02','discipline':'PLAT'}))
        for discipline in (None,'TROT_ATTELE','TROT_MONTE','HAIE','STEEPLE_CHASE','CROSS_COUNTRY','GALOP'):
            self.assertTrue(flat_only_reason({'date':'2026-11-02','discipline':discipline}))

    def test_independent_reservation_blocks_unknown_and_trot(self):
        for pkg in ('tony_artillan_2','tony_artillan_3_5'):
            m=importlib.import_module(pkg+'.model')
            now=datetime.fromisoformat('2026-11-02T14:00:00+01:00')
            race={'date':'2026-11-02','id':'R1C1','departure':'2026-11-02T14:15:00+01:00','market':True}
            tip={'number':2,'name':'TEST','playable':True,'captured_at':now.isoformat(),'site':'geny'}
            horse={'numPmu':2,'nom':'TEST','statut':'PARTANT'}
            voters=['geny','canalturf','zeturf']
            race['tips']={k:{**tip,'site':k} for k in voters}
            for discipline in (None,'TROT_ATTELE','HAIE'):
                sol={'bets':[]};r={**race,'discipline':discipline}
                self.assertFalse(m.reserve(sol,r,tip,horse,now,voters=voters));self.assertEqual(sol['bets'],[])
            sol={'bets':[]};self.assertTrue(m.reserve(sol,{**race,'discipline':'PLAT'},tip,horse,now,voters=voters))
            self.assertEqual(sol['bets'][0]['stake_cents'],10000)

    def test_unknown_official_discipline_clears_old_value(self):
        for pkg in ('tony_artillan_2','tony_artillan_3_5'):
            main=importlib.import_module(pkg+'.main')
            now=datetime.fromisoformat('2026-11-02T14:00:00+01:00')
            race={'date':'2026-11-02','id':'R1C1','c':1,'title':'TEST','departure':'2026-11-02T14:15:00+01:00','discipline':'PLAT','errors':{}}
            meta={'numReunion':1,'numOrdre':1,'libelle':'TEST','heureDepart':datetime.fromisoformat(race['departure']).timestamp()*1000}
            main.reconcile_schedule(race,meta,now)
            self.assertIsNone(race['discipline']);self.assertIn('indisponible',main.no_bet_reason({},race))

    def test_clean_index_still_pushes_existing_local_commits(self):
        calls=[]
        def git(args,**kw):calls.append(args);return Mock(returncode=0)
        with patch('comparaison_r1.worker.subprocess.run',side_effect=git):checkpoint('comparaison_r1')
        self.assertTrue(any(x[1]=='push' for x in calls));self.assertFalse(any(x[1]=='commit' for x in calls))

    def test_persist_retries_transient_pull_failure(self):
        pulls=0
        def git(args,**kw):
            nonlocal pulls
            if args[1]=='pull':
                pulls+=1
                if pulls==1:raise subprocess.CalledProcessError(1,args)
            return Mock(returncode=0)
        with patch('comparaison_r1.worker.subprocess.run',side_effect=git):checkpoint('comparaison_r1')
        self.assertEqual(pulls,2)

    def test_relay_probe_has_no_live_collection(self):
        with patch.dict('os.environ',{'GH_TOKEN':'dummy','GITHUB_REPOSITORY':'owner/repo'}),patch('comparaison_r1.worker.urlopen') as op:
            op.return_value.__enter__.return_value.status=204
            dispatch('comparaison_r1',probe=True)
            self.assertEqual(json.loads(op.call_args.args[0].data)['inputs'],{'dry_run':True,'relay_probe':True})
            op.return_value.__enter__.return_value.status=403
            with self.assertRaises(RuntimeError):dispatch('comparaison_r1')

    def test_short_session_requests_relay_and_archives_confirmation(self):
        import os,tempfile
        from pathlib import Path
        from comparaison_r1 import worker
        fixed=datetime.fromisoformat('2026-11-02T14:00:00+01:00')
        with tempfile.TemporaryDirectory() as tmp:
            cwd=os.getcwd();os.chdir(tmp)
            try:
                data=Path('comparaison_r1/data/2026-11-02');data.mkdir(parents=True)
                (data/'state.json').write_text(json.dumps({'date':'2026-11-02','races':[{'departure':'2026-11-02T14:15:00+01:00'}]}))
                with patch.object(worker,'recover_previous',return_value=False),patch.object(worker,'datetime') as dt,patch.object(worker.time,'monotonic',side_effect=[0,600]),patch.object(worker.subprocess,'run',return_value=Mock(returncode=0)),patch.object(worker,'checkpoint') as cp,patch.object(worker,'dispatch') as send:
                    dt.now.return_value=fixed;dt.fromisoformat.side_effect=datetime.fromisoformat
                    worker.run('comparaison_r1',persist=True,continue_run=True)
                    send.assert_called_once_with('comparaison_r1');self.assertEqual(cp.call_count,2)
                self.assertEqual(json.loads(Path('comparaison_r1/data/worker.json').read_text())['status'],'RELAY_ACCEPTED')
            finally:os.chdir(cwd)

