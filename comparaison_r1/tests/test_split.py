import copy,unittest
from datetime import datetime,timedelta
from comparaison_r1.model import split_pair,reserve_split,settle,account
from comparaison_r1.sources import SITES
from comparaison_r1.main import TZ,daily_report,live_report
class SplitTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,19,13,tzinfo=TZ)
  self.tips={s:{'number':n,'name':'H'+str(n),'playable':True,'captured_at':self.now.isoformat()} for s,n in zip(SITES,[1,1,2,2])}
  self.r={'id':'R1C1','date':'2026-10-19','title':'TEST','departure':(self.now+timedelta(minutes=10)).isoformat(),'tips':self.tips,'groups':{}}
  self.horses=[{'numPmu':n,'nom':'H'+str(n),'statut':'PARTANT'} for n in (1,2)]
  self.s={'budget_cents':80000,'bets':[],'stop_at_target':False}
 def test_only_exact_2_2(self):
  self.assertEqual(len(split_pair(self.tips)),2)
  for ns in ([1,1,2,3],[1,1,1,2],[1,1,1,1]):
   t=copy.deepcopy(self.tips)
   for s,n in zip(SITES,ns):t[s]['number']=n
   self.assertEqual(split_pair(t),[])
  del self.tips['geny'];self.assertEqual(split_pair(self.tips),[])
 def test_atomic_pair_budget_dedup_and_previous_pending(self):
  self.assertTrue(reserve_split(self.s,self.r,self.horses,self.now,True))
  self.assertEqual([b['stake_cents'] for b in self.s['bets']],[5000,5000])
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now,True))
  s={'budget_cents':80000,'bets':[{'race_id':'R1C0','stake_cents':75000,'status':'GAGNE','return_cents':75000}]}
  self.assertFalse(reserve_split(s,self.r,self.horses,self.now,True));self.assertEqual(len(s['bets']),1)
  s['bets'][0]['stake_cents']=70000;s['bets'][0]['return_cents']=70000
  self.assertTrue(reserve_split(s,self.r,self.horses,self.now,True))
 def test_nonrunner_missing_market_and_late_are_rejected_atomically(self):
  h=copy.deepcopy(self.horses);h[1]['statut']='NON_PARTANT'
  self.assertFalse(reserve_split(self.s,self.r,h,self.now,True));self.assertEqual(self.s['bets'],[])
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now,False))
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now+timedelta(minutes=10),True))
 def test_place_reports_not_winner_reports_and_no_progression_change(self):
  reserve_split(self.s,self.r,self.horses,self.now,True)
  sg=[{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'1','dividendePourUnEuro':600}]}]
  self.assertFalse(settle(self.s['bets'][0],sg,self.horses))
  sp=[{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'1','dividendePourUnEuro':160},{'combinaison':'3','dividendePourUnEuro':200}]}]
  for b in self.s['bets']:self.assertTrue(settle(b,sp,self.horses))
  self.assertEqual([b['return_cents'] for b in self.s['bets']],[8000,0])
  a=account(self.s);self.assertEqual(a['profit_cents'],-2000);self.assertEqual(a['next_stake_cents'],10000)
  state={'date':'2026-10-19','venue':'TEST','races':[self.r],'solutions':{'majorite_3_ou_4':self.s}}
  for message in (daily_report(state),live_report(state)):
   self.assertIn('N°1 H1',message);self.assertIn('N°2 H2',message)
 def test_pair_is_one_threshold_observation(self):
  reserve_split(self.s,self.r,self.horses,self.now,True)
  self.s['bets'][0].update(status='GAGNE',return_cents=26000)
  self.s['bets'][1].update(status='PERDU',return_cents=0)
  self.assertEqual(account(self.s)['profit_cents'],16000)
  self.assertIsNone(account(self.s)['first_target'])
  self.assertEqual(account(self.s)['peak_profit_cents'],16000)

 def test_new_1200_cap_accepts_last_full_pair_not_half_pair(self):
  from comparaison_r1.model import daily_budget
  self.assertEqual(daily_budget('2026-10-18'),80000)
  self.assertEqual(daily_budget('2026-10-19'),120000)
  s={'budget_cents':daily_budget('2026-10-19'),'stop_at_target':False,'bets':[{'race_id':'R1C0','stake_cents':110000,'return_cents':110000,'status':'GAGNE'}]}
  self.assertTrue(reserve_split(s,self.r,self.horses,self.now,True))
  self.assertEqual(account(s)['committed_cents'],120000)
  self.assertEqual(account(s)['remaining_cents'],0)
  s['bets']=s['bets'][:1];s['bets'][0]['stake_cents']=115000;s['bets'][0]['return_cents']=115000
  self.assertFalse(reserve_split(s,self.r,self.horses,self.now,True))

 def test_two_one_one_single_50_and_budget(self):
  from comparaison_r1.model import place_plan
  for site,n in zip(SITES,[7,7,8,3]):self.tips[site].update(number=n,name='H'+str(n))
  self.horses=[{'numPmu':7,'nom':'H7','statut':'PARTANT'}]
  self.assertEqual([(g['number'],g['stake_cents']) for g in place_plan(self.r)],[(7,5000)])
  self.s['budget_cents']=5000
  self.assertTrue(reserve_split(self.s,self.r,self.horses,self.now,True))
  self.assertEqual(len(self.s['bets']),1)
  self.assertEqual(self.s['bets'][0]['variant'],'accord_2_1_1')
  self.s['bets']=[];self.s['budget_cents']=4999
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now,True))
 def test_exception_is_dated_named_atomic_and_displayed(self):
  from comparaison_r1.model import place_plan,place_description
  self.r['id']='R1C6'
  names={7:'VINGT SEPT',14:'EVER FAST',11:'BRAMANS'}
  for site,n in zip(SITES,[7,14,11,14]):self.tips[site].update(number=n,name=names[n])
  self.horses=[{'numPmu':n,'nom':name,'statut':'PARTANT'} for n,name in names.items()]
  self.assertEqual([(g['number'],g['stake_cents']) for g in place_plan(self.r)],[(7,2500),(11,2500)])
  self.assertIn('EXCEPTION',place_description(self.r))
  self.s['budget_cents']=4999
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now,True))
  self.s['budget_cents']=5000
  self.assertTrue(reserve_split(self.s,self.r,self.horses,self.now,True))
  self.assertEqual([b['number'] for b in self.s['bets']],[7,11])
  self.r['id']='R1C8'
  self.assertEqual([(g['number'],g['stake_cents']) for g in place_plan(self.r)],[(14,5000)])
  self.r['id']='R1C6'
  self.r['date']='2026-10-19';self.tips[SITES[0]]['name']='WRONG HORSE'
  self.assertEqual(place_plan(self.r),[])

 def test_no_new_place_bets_from_oct20(self):
  from comparaison_r1.model import place_plan
  self.r['date']='2026-10-20'
  self.assertEqual(place_plan(self.r),[])
  self.assertFalse(reserve_split(self.s,self.r,self.horses,self.now,True))
  for site,n in zip(SITES,[1,1,2,3]):self.tips[site]['number']=n
  self.assertEqual(place_plan(self.r),[])
