import copy
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from comparaison_r1 import main as runner
from comparaison_r1.sources import parse, SITES
from comparaison_r1.model import freeze, groups, settle, metrics, summary, reserve, account

F=Path(__file__).parent/'fixtures'

class SourceTests(unittest.TestCase):
    def test_real_public_pages_same_verified_horse(self):
        race={'date':'2026-10-15','c':4,'title':'PRIX DU JARDIN ANGLAIS'}
        horses=json.loads((F/'participants.json').read_text())
        urls={'turfin':'https://turfin.fr/course/2026-10-15/r1c4-chantilly-prix-du-jardin-anglais',
              'canalturf':'https://www.canalturf.com/pronostics-PMU/2026-10-15/chantilly/420623_prix-du-jardin-anglais.html',
              'geny':'https://www.geny.com/course/1691204-2026-10-15-chantilly-prix-du-jardin-anglais/partants-pronostics'}
        for site in SITES:
            key='canalturf' if site=='zeturf' else site
            body=gzip.decompress((F/(key+'.html.gz')).read_bytes()).decode()
            with self.subTest(site=site):
                tip=parse(site,body,urls[key],race,horses)
                self.assertEqual(tip['number'],5);self.assertEqual(tip['name'],'MONDAY CABARET')
                with self.assertRaises(ValueError):parse(site,body,urls[key],{**race,'c':5},horses)
                with self.assertRaises(ValueError):parse(site,body,urls[key],{**race,'date':'2026-10-16'},horses)
                with self.assertRaises(ValueError):parse(site,body,urls[key],race,[{**h,'nom':'WRONG'} for h in horses])

class Rules(unittest.TestCase):
    def votes(self,nums):return {s:{'number':n,'stake_cents':10000,'playable':True,'status':'EN_ATTENTE','name':f'H{n}'} for s,n in zip(SITES,nums)}
    def test_majority_cases(self):
        for ns,count in [([1,1,2,3],2),([1,1,1,2],3),([1,1,1,1],4)]:
            g=groups(self.votes(ns));self.assertIn(f'accord_{count}_sur_4',g)
            self.assertEqual('majorite_3_ou_4' in g,count>=3)
            self.assertEqual(sum(k.startswith('groupe_') for k in g),1)
    def test_ties_missing_and_non_runner_do_not_create_majority(self):
        self.assertEqual(groups(self.votes([1,1,2,2])),{})
        self.assertEqual(groups(self.votes([1,2,3,4])),{})
        self.assertEqual(groups(self.votes([1,1,1])),{})
        t=self.votes([1,1,1,1]);t['turfin']['playable']=False;self.assertEqual(groups(t),{})
    def test_freeze_time_immutability_and_period(self):
        dep=datetime(2026,10,16,15,tzinfo=timezone.utc)
        r={'date':'2026-10-16','departure':dep.isoformat(),'tips':{},'market':True}
        t={'number':1,'name':'H1'};h={'numPmu':1,'nom':'H1','statut':'PARTANT'}
        self.assertFalse(freeze(r,'geny',t,h,dep))
        self.assertFalse(freeze(r,'geny',t,h,dep-timedelta(hours=2)))
        self.assertTrue(freeze(r,'geny',t,h,dep-timedelta(minutes=30)))
        self.assertFalse(freeze(r,'geny',t,h,dep-timedelta(minutes=20)))
        r['date']='2026-12-16';self.assertFalse(freeze(r,'turfin',t,h,dep-timedelta(minutes=30)))
    def payload(self,rate=230):return [{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'1','dividendePourUnEuro':rate}]}]
    def test_settlement_official_cent_units_not_odds(self):
        t=self.votes([1])['turfin'];t['odds']={'rapport':99}
        self.assertTrue(settle(t,self.payload(),[{'numPmu':1,'nom':'H1','statut':'PARTANT'}]))
        self.assertEqual(t['return_cents'],23000)
        self.assertFalse(settle(t,self.payload(400),[{'numPmu':1,'nom':'H1'}]))
    def test_loss_and_np(self):
        for status,expected in [('PARTANT','PERDU'),('NON_PARTANT','REMBOURSE')]:
            t=self.votes([2])['turfin'];settle(t,self.payload(),[{'numPmu':2,'nom':'H2','statut':status}]);self.assertEqual(t['status'],expected)
    def test_missing_malformed_results_wait(self):
        for p in [[],self.payload('NaN'),self.payload(0),[{'typePari':'SIMPLE_GAGNANT'}]]:
            t=self.votes([1])['turfin'];self.assertFalse(settle(t,p,[{'numPmu':1,'nom':'H1'}]));self.assertEqual(t['status'],'EN_ATTENTE')
    def test_common_cohort_excludes_unsettled_or_missing_source(self):
        t=self.votes([1,1,2,3])
        for tip in t.values():settle(tip,self.payload(),[{'numPmu':n,'nom':f'H{n}'} for n in (1,2,3)])
        r={'id':'R1C1','departure':'2026-10-16T12:00:00+00:00','tips':t,'groups':groups(t)}
        other=copy.deepcopy(r);other['id']='R1C2';del other['tips']['geny']
        b=summary([{'date':'2026-10-16','races':[r,other]}]);self.assertEqual(b['common_settled_races'],1)
        self.assertEqual(b['common']['turfin']['roi_percent'],130)
        self.assertEqual(b['individual']['geny']['missing_races'],1)
    def test_refunds_pending_and_streak(self):
        ts=[{'status':s,'stake_cents':500,'return_cents':v} for s,v in [('PERDU',0),('REMBOURSE',500),('PERDU',0),('GAGNE',1500),('EN_ATTENTE',0)]]
        m=metrics(ts);self.assertEqual(m['longest_observed_loss_streak'],2);self.assertEqual(m['pending'],1);self.assertEqual(m['roi_percent'],0)

class Progressive(unittest.TestCase):
    def reserve_next(self,sol,index):
        now=datetime(2026,10,16,12,tzinfo=timezone.utc)+timedelta(hours=index)
        race={'date':'2026-10-16','id':f'R1C{index+1}','market':True,'departure':(now+timedelta(minutes=15)).isoformat()}
        tip={'site':'geny','number':1,'name':'H1','playable':True,'captured_at':(now-timedelta(minutes=10)).isoformat()}
        horse={'numPmu':1,'nom':'H1','statut':'PARTANT'}
        return reserve(sol,race,tip,horse,now)
    def outcome(self,sol,status,returned):
        b=sol['bets'][-1];b.update(status=status,return_cents=returned,profit_cents=returned-b['stake_cents'])
    def test_five_loss_sequence_totals_800_and_stops(self):
        s={'bets':[]}
        for i,amount in enumerate([10000,20000,15000,15000,20000]):
            self.assertTrue(self.reserve_next(s,i));self.assertEqual(s['bets'][-1]['stake_cents'],amount)
            self.outcome(s,'PERDU',0)
        self.assertFalse(self.reserve_next(s,5));self.assertEqual(account(s)['stop'],'SERIE_TERMINEE')
        self.assertEqual(account(s)['committed_cents'],80000)
        self.assertEqual(account(s)['remaining_cents'],0)
    def test_target_is_net_and_win_resets(self):
        s={'bets':[]};self.reserve_next(s,0);self.outcome(s,'PERDU',0)
        self.reserve_next(s,1);self.outcome(s,'GAGNE',40000)
        self.assertEqual(account(s)['profit_cents'],10000)
        self.assertEqual(account(s)['next_stake_cents'],10000)
        self.assertTrue(self.reserve_next(s,2));self.outcome(s,'GAGNE',50000)
        self.assertEqual(account(s)['profit_cents'],50000)
        self.assertEqual(account(s)['stop'],'OBJECTIF');self.assertFalse(self.reserve_next(s,3))
    def test_pending_blocks_and_independent_reset(self):
        s={'bets':[]};self.assertTrue(self.reserve_next(s,0));self.assertFalse(self.reserve_next(s,1))
        self.assertEqual(account(s)['stop'],'ATTENTE_RESULTAT')
        self.assertTrue(self.reserve_next({'bets':[]},1))
    def test_refund_keeps_next_stake_but_counts_budget(self):
        s={'bets':[]};self.reserve_next(s,0);self.outcome(s,'PERDU',0)
        self.reserve_next(s,1);self.outcome(s,'REMBOURSE',20000)
        self.assertEqual(account(s)['next_stake_cents'],20000);self.assertEqual(account(s)['committed_cents'],30000)
    def test_exact_budget_800_allowed(self):
        s={'bets':[]}
        for i in range(8):
            self.assertTrue(self.reserve_next(s,i));self.outcome(s,'GAGNE',11000)
        self.assertEqual(account(s)['committed_cents'],80000)
        self.assertEqual(account(s)['profit_cents'],8000)
        self.assertFalse(self.reserve_next(s,8))
    def test_identical_sequence_for_all_scenarios_and_combinations(self):
        from comparaison_r1.model import STRATEGIES, COMBINATIONS
        self.assertEqual(STRATEGIES,('majorite_3_ou_4',));self.assertEqual(len(set(COMBINATIONS)),11)
        for key in STRATEGIES:
            with self.subTest(key=key):
                s={'bets':[]}
                for i,amount in enumerate((10000,20000,15000,15000,20000)):
                    self.assertTrue(self.reserve_next(s,i));self.assertEqual(s['bets'][-1]['stake_cents'],amount)
                    self.outcome(s,'PERDU',0)
                self.assertFalse(self.reserve_next(s,5))
    def test_win_reset_does_not_reset_daily_budget(self):
        s={'bets':[]}
        for i in range(3):self.reserve_next(s,i);self.outcome(s,'PERDU',0)
        self.reserve_next(s,3);self.outcome(s,'GAGNE',30000)
        self.assertEqual(account(s)['next_stake_cents'],10000)
        self.assertEqual(account(s)['committed_cents'],60000)
        self.reserve_next(s,4);self.outcome(s,'PERDU',0)
        self.assertEqual(account(s)['stop'],'BUDGET');self.assertFalse(self.reserve_next(s,5))

class Integration(unittest.TestCase):
    def test_http200_rate_limit_stops_further_geny_requests(self):
        from unittest.mock import Mock
        response=Mock(status_code=200,text='<html><title>Trop de requêtes - Geny</title><body>429</body></html>')
        f=runner.Fetcher()
        with patch.object(runner.requests,'get',return_value=response) as get:
            with self.assertRaisesRegex(ValueError,'429'):f.get('https://www.geny.com/a')
            with self.assertRaisesRegex(ValueError,'Limitation'):f.get('https://www.geny.com/b')
            self.assertEqual(get.call_count,1)
    def test_morning_preview_displays_all_sites_without_bets_or_frozen_tips(self):
        now=datetime(2026,10,16,8,tzinfo=runner.TZ)
        r={'date':'2026-10-16','id':'R1C1','c':1,'title':'TEST','departure':(now+timedelta(hours=10)).isoformat(),'market':True,'tips':{},'groups':{},'errors':{}}
        s={'date':r['date'],'venue':'VINCENNES','races':[r],'solutions':{}}
        def collect(race,f,folder,clock,preview=False):
            self.assertTrue(preview)
            race['tips']={site:{'number':i+1,'name':'CHEVAL '+str(i+1),'playable':True,'odds':{'rapport':3.5}} for i,site in enumerate(SITES)}
        with patch.object(runner,'collect_race',collect):
            p=runner.morning_preview(s,None,Path('/tmp'),clock=lambda:now)
        message=runner.preview_report(s,p)
        for name in ('Turfin','Canalturf','ZEturf','Geny'):self.assertIn(name+' : N°',message)
        self.assertTrue(p['complete']);self.assertEqual(r['tips'],{});self.assertEqual(s['solutions'],{})
        self.assertIn('+500 € NET',message)
        self.assertIn('AUCUN PARI',message)
        for pattern,expected in (([1,1,2,2],False),([1,1,2,3],False),([1,1,1,2],True),([1,1,1,1],True)):
            p['races'][0]['tips']={site:{'number':n,'name':'H'+str(n),'playable':True} for site,n in zip(SITES,pattern)}
            rendered=runner.preview_report(s,p)
            self.assertEqual('✅ ADMISSIBLE' in rendered,expected)

    def test_previous_settlement_changes_next_real_reserved_stake(self):
        from comparaison_r1.model import STRATEGIES
        now=datetime(2026,10,16,14,tzinfo=runner.TZ)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return now.astimezone(tz) if tz else now
        horse={'numPmu':5,'nom':'MONDAY CABARET','statut':'PARTANT'}
        def race(c,offset):
            r={'date':'2026-10-16','id':f'R1C{c}','c':c,'title':f'COURSE {c}','market':True,
               'departure':(now+timedelta(minutes=offset)).isoformat(),'tips':{},'groups':{},'errors':{}}
            for site in SITES:
                r['tips'][site]={'site':site,'number':5,'name':horse['nom'],'playable':True,'stake_cents':0,'status':'EN_ATTENTE','captured_at':(now-timedelta(minutes=40)).isoformat()}
            r['groups']=groups(r['tips']);return r
        r1,r2=race(1,-10),race(2,10)
        solutions={k:{'bets':[]} for k in STRATEGIES}
        reserve(solutions['majorite_3_ou_4'],r1,r1['tips']['geny'],horse,now-timedelta(minutes=20))
        state={'date':'2026-10-16','venue':'TEST','races':[r1,r2],'solutions':solutions}
        class FakeFetch:
            audit=[]
            def json(self,u):
                if 'rapports-definitifs' in u:return [{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'1','dividendePourUnEuro':200}]}]
                if u.endswith('/participants'):return {'participants':[horse]}
                r=r1 if '/C1' in u else r2
                return {'numReunion':1,'numOrdre':r['c'],'libelle':r['title'],'heureDepart':int(datetime.fromisoformat(r['departure']).timestamp()*1000),'paris':[{'typePari':'E_SIMPLE_GAGNANT'}]}
            def get(self,u):return json.dumps(self.json(u))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'data/2026-10-16/state.json';runner.write(p,state)
            with patch.object(runner,'datetime',Clock),patch.object(runner,'Fetcher',FakeFetch):runner.run(notify=False,root=root)
            actual=json.loads(p.read_text())['solutions']
            self.assertEqual(actual['majorite_3_ou_4']['bets'][0]['status'],'PERDU')
            self.assertEqual(actual['majorite_3_ou_4']['bets'][1]['stake_cents'],20000)
            self.assertEqual(set(actual),{'majorite_3_ou_4'})
            self.assertEqual(sum(len(s['bets']) for s in actual.values()),2)

if __name__=='__main__':unittest.main()
