import copy,json,sys,unittest
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyses import build_analyses,VERSION_ANALYSES
from evaluate_analyses import quinte_return,select_sent
from notify import format_messages
from collector import consensus
class ThreeRulesTests(unittest.TestCase):
 def sample(self):
  horses={n:{'nom':str(n),'statut':'PARTANT','pmu_odds':{'value':n+2,'kind':'direct'}} for n in range(1,9)}
  rows=[{'publisher':str(i),'top3':[1,2,3],'top5':[1,2,3,4,5],'outsiders':[{'number':6,'label':'tocard'},{'number':7,'label':'folie'}]} for i in range(5)]
  return rows,{'horses':horses,'internet_quinte_available':True}
 def test_three_profiles_have_distinct_numbers_and_fixed_budget(self):
  rows,race=self.sample();a=build_analyses(rows,race)
  self.assertEqual(a['profiles'][0]['numbers'],[1,2,3,4,5]);self.assertEqual(a['profiles'][1]['numbers'],[1,2,3,4,5]);self.assertEqual(a['profiles'][2]['numbers'],[1,2,3,6,7])
  self.assertTrue(all(p['qualified'] and p['stake_eur']==2 for p in a['profiles']));self.assertFalse(a['progressive_staking'])
 def test_duplicate_source_not_double_counted(self):
  rows,race=self.sample();self.assertEqual(build_analyses(rows,race),build_analyses(rows+[rows[0]],race))
 def test_one_outsider_is_not_filled_with_unrecommended_horse(self):
  rows,race=self.sample()
  for r in rows:r['outsiders']=[{'number':6,'label':'tocard'}]
  a=build_analyses(rows,race);self.assertEqual(a['profiles'][2]['numbers'],[1,2,3,6]);self.assertFalse(a['profiles'][2]['qualified'])
 def test_unknown_odds_and_nonrunners_are_excluded(self):
  rows,race=self.sample();race['horses'][1]['statut']='NON_PARTANT';race['horses'][2]['pmu_odds']=None
  a=build_analyses(rows,race);self.assertNotIn(1,a['profiles'][0]['numbers']);self.assertNotIn(1,a['profiles'][1]['numbers']);self.assertNotIn(2,a['profiles'][1]['numbers'])
 def test_telegram_includes_three_rules_and_fixed_simulation(self):
  rows,race=self.sample();race.update(date='2026-10-13',id='R1C1',title='TEST',departure='2026-10-13T11:55:00+00:00')
  a=build_analyses(rows,race);s={'race':race,'rows':rows,'analyses':a,'consensus':consensus(rows,race),'captured_at':'2026-10-13T09:00:00+00:00'}
  for i,r in enumerate(rows):r.update(source='stats',name='Source '+str(i))
  text=format_messages(s)[0]
  for label in ['Statistique','Cotes','Bases + outsiders','2 €']:self.assertIn(label,text)
  self.assertIn('1 – 2 – 3 – 6 – 7',text)

class QuintéSettlementTests(unittest.TestCase):
 def people(self):return [{'numPmu':n,'statut':'PARTANT'} for n in range(1,9)]
 def reports(self):
  return [{'typePari':'E_QUINTE_PLUS','rapports':[
   {'libelle':'e-Quinté+ Ordre','combinaison':'1-2-3-4-5','dividendePourUnEuro':100000},
   {'libelle':'e-Quinté+ Désordre','combinaison':'1-2-3-4-5','dividendePourUnEuro':20000},
   {'libelle':'e-Bonus 4sur5','combinaison':'1-2-3-4','dividendePourUnEuro':850},
   {'libelle':'e-Bonus 3','combinaison':'1-2-3','dividendePourUnEuro':710}]}]
 def test_order_disorder_and_bonus_not_added_together(self):
  self.assertEqual(quinte_return([1,2,3,4,5],self.people(),self.reports()),2000)
  self.assertEqual(quinte_return([5,4,3,2,1],self.people(),self.reports()),400)
  self.assertEqual(quinte_return([1,2,3,4,8],self.people(),self.reports()),17)
  self.assertEqual(quinte_return([1,2,3,7,8],self.people(),self.reports()),Decimal('14.2'))
  self.assertEqual(quinte_return([4,5,6,7,8],self.people(),self.reports()),0)
 def test_missing_internet_market_and_nonrunner_stay_unresolved(self):
  r=self.reports();r[0]['typePari']='QUINTE_PLUS';self.assertIsNone(quinte_return([1,2,3,4,5],self.people(),r))
  ps=self.people();ps[0]['statut']='NON_PARTANT';self.assertIsNone(quinte_return([1,2,3,4,5],ps,self.reports()))
 def test_only_matching_confirmed_predeparture_selection_is_eligible(self):
  rows,race=ThreeRulesTests().sample();race.update(departure='2026-10-13T11:55:00+00:00');a=build_analyses(rows,race)
  s={'race':race,'captured_at':'2026-10-13T09:00:00+00:00','eligible_before_departure':True,'analyses':a}
  receipt={'delivery':'SENT','sent_at':'2026-10-13T09:01:00+00:00','snapshot_capture':s['captured_at'],'analyses':a}
  self.assertIsNone(select_sent([s],[]));self.assertEqual(select_sent([s],[receipt]),s)
  receipt['sent_at']='2026-10-13T12:00:00+00:00';self.assertIsNone(select_sent([s],[receipt]))
if __name__=='__main__':unittest.main()
