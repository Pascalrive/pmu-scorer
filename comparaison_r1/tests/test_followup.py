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
        s['morning_preview']={'complete':True,'version':m.PREVIEW_VERSION,'captured_at':(self.now-timedelta(hours=2)).isoformat(),'races':[old]}
        def collect(r,*args,**kw):
            self.assertEqual(r['tips'],{})
            r['tips']={site:{'number':2,'name':'NEW CHOICE','playable':True,'odds':{'rapport':2.5}} for site in SITES}
        with patch.object(m,'collect_race',side_effect=collect) as c:
            p=m.morning_preview(s,None,Path('/tmp'),clock=lambda:self.now)
            self.assertEqual(c.call_count,1)
            self.assertEqual(p['races'][0]['tips']['geny']['odds']['rapport'],2.5)
            self.assertEqual(p['races'][0]['tips']['geny']['number'],2)
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

    def test_target_observed_without_stopping_from_oct19(self):
        from comparaison_r1.model import account,stop_at_target
        s={'stop_at_target':stop_at_target('2026-10-19'),'bets':[{'race_id':'R1C1','stake_cents':10000,'return_cents':35000,'status':'GAGNE'}]}
        self.assertIsNone(account(s)['stop'])
        s['bets'].append({'race_id':'R1C2','stake_cents':10000,'return_cents':0,'status':'PERDU'})
        a=account(s)
        self.assertEqual(a['profit_cents'],15000)
        self.assertEqual(a['first_target']['profit_cents'],25000)
        self.assertEqual(a['peak_profit_cents'],25000)
        self.assertEqual(a['max_drawdown_cents'],10000)
        s['stop_at_target']=stop_at_target('2026-10-18');s['bets'].pop()
        self.assertEqual(account(s)['stop'],'OBJECTIF')

    def test_daily_report_includes_unplayed_arrival_and_financial_total(self):
        r=copy.deepcopy(self.r);r['official_arrival']=[{'number':2,'name':'WINNER','rank':1}];r['no_bet_reason']='Pas de majorité'
        s={'date':'2026-10-19','venue':'TEST','races':[r],'solutions':{'majorite_3_ou_4':{'bets':[],'stop_at_target':False}}}
        message=m.daily_report(s)
        self.assertIn('WINNER',message);self.assertIn('Pas de majorité',message);self.assertIn('0.00 €',message)
