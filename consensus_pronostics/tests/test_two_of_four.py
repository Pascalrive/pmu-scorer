import copy,sys,unittest
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from two_of_four import tickets,payout,select_ticket,MARKET
class TwoOfFourTests(unittest.TestCase):
 def people(self):return [{'numPmu':n,'statut':'PARTANT'} for n in range(1,12)]
 def reports(self):return [{'typePari':MARKET,'rapports':[{'combinaison':c,'dividendePourUnEuro':1520} for c in ['4-5','4-9','4-10','5-9','5-10','9-10']]}]
 def test_full_stake_official_cents_and_order_irrelevant(self):
  self.assertEqual(payout([5,4],self.people(),self.reports()),Decimal('45.60'))
  self.assertEqual(payout([1,4],self.people(),self.reports()),0)
 def test_no_estimate_for_missing_invalid_or_nonrunner_reports(self):
  self.assertIsNone(payout([4,5],self.people(),[]))
  r=self.reports();r[0]['rapports'][0]['dividendePourUnEuro']='NaN'
  self.assertIsNone(payout([4,5],self.people(),r))
  ps=self.people();ps[3]['statut']='NON_PARTANT'
  self.assertIsNone(payout([4,5],ps,self.reports()))
  self.assertEqual(payout([4,5],ps,[{'typePari':MARKET,'rembourse':True}]),3)
 def test_three_tickets_use_two_first_and_do_not_retrofit(self):
  a={'profiles':[{'id':k,'numbers':[4,5,6,7,8],'qualified':True} for k in ('statistique','cotes','mixte')]}
  race={'date':'2026-10-19','internet_2sur4_available':True}
  ts=tickets(a,race);self.assertEqual(len(ts),3);self.assertEqual(sum(t['stake_eur'] for t in ts),9)
  self.assertTrue(all(t['numbers']==[4,5] and t['qualified'] for t in ts))
  race['date']='2026-10-18';self.assertEqual(tickets(a,race),[])
  race['date']='2026-10-19';race['internet_2sur4_available']=False
  self.assertFalse(any(t['qualified'] for t in tickets(a,race)))
 def test_requires_explicit_new_ticket_confirmed_before_departure(self):
  race={'date':'2026-10-19','departure':'2026-10-19T12:00:00+00:00','internet_2sur4_available':True}
  a={'profiles':[{'id':'statistique','numbers':[1,2,3,4,5],'qualified':True}]};a['two_of_four']=tickets(a,race)
  s={'race':race,'captured_at':'2026-10-19T10:00:00+00:00','eligible_before_departure':True,'analyses':a}
  self.assertIsNone(select_ticket([s],[],'statistique'))
  ledger=[{'delivery':'SENT','sent_at':'2026-10-19T10:01:00+00:00','snapshot_capture':s['captured_at'],'analyses':copy.deepcopy(a)}]
  self.assertIsNotNone(select_ticket([s],ledger,'statistique'))
  ledger[0]['sent_at']='2026-10-19T12:01:00+00:00'
  self.assertIsNone(select_ticket([s],ledger,'statistique'))
