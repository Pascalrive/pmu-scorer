import copy
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from comparaison_r1 import main as m
from comparaison_r1.sources import SITES
from tony_artillan.telegram import report

class FollowupTests(TestCase):
    def setUp(self):
        self.now=datetime(2026,10,17,10,tzinfo=m.TZ)
        self.r={'date':'2026-10-17','id':'R1C1','c':1,'title':'TEST','departure':(self.now+timedelta(minutes=30)).isoformat(),'tips':{},'groups':{},'errors':{}}
    def test_future_delay_audited_but_elapsed_never_reopened(self):
        meta={'numReunion':1,'numOrdre':1,'libelle':'TEST','heureDepart':int((self.now+timedelta(minutes=40)).timestamp()*1000)}
        m.reconcile_schedule(self.r,meta,self.now)
        self.assertEqual(len(self.r['schedule_changes']),1)
        meta['heureDepart']=int((self.now+timedelta(minutes=60)).timestamp()*1000)
        with self.assertRaises(ValueError):m.reconcile_schedule(self.r,meta,self.now+timedelta(minutes=45))
        meta['libelle']='OTHER'
        with self.assertRaises(ValueError):m.reconcile_schedule(self.r,meta,self.now)
    def test_complete_preview_is_refreshed_hourly(self):
        s={'races':[self.r]}
        old=copy.deepcopy(self.r)
        old['tips']={site:{'number':1,'name':'H','playable':True,'odds':None} for site in SITES}
        s['morning_preview']={'complete':True,'version':3,'captured_at':(self.now-timedelta(hours=2)).isoformat(),'races':[old]}
        def collect(r,*args,**kw):
            for t in r['tips'].values():t['odds']={'rapport':2.5}
        with patch.object(m,'collect_race',side_effect=collect) as c:
            p=m.morning_preview(s,None,Path('/tmp'),clock=lambda:self.now)
            self.assertEqual(c.call_count,1)
            self.assertEqual(p['races'][0]['tips']['geny']['odds']['rapport'],2.5)
            m.morning_preview(s,None,Path('/tmp'),clock=lambda:self.now+timedelta(minutes=10))
            self.assertEqual(c.call_count,1)
        self.assertEqual(self.r['tips'],{})
    def test_skipped_due_to_late_settlement(self):
        self.r['groups']={'majorite_3_ou_4':{'number':1,'sites':list(SITES)}}
        b={'departure':self.now.isoformat(),'settled_at':(self.now+timedelta(minutes=35)).isoformat()}
        s={'solutions':{'majorite_3_ou_4':{'bets':[b]}}}
        self.assertIn('Résultat précédent',m.no_bet_reason(s,self.r))
    def test_empty_paris_turf_report_stable_as_courses_pass(self):
        from tony_artillan.model import new_day
        # Minimal score-compatible state: statuses change, notification must not.
        s={'date':'2026-10-17','source_status':'EN_ATTENTE_PARIS_TURF','races':[{'status':'A_VENIR'}]}
        before=report(s)
        s['races'][0]['status']='NON_JOUE'
        self.assertEqual(before,report(s))
        self.assertLess(len(before),500)
