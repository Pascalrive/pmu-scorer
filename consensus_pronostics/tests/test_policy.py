import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyses import build_analyses
from evaluate_analyses import select_sent
from two_of_four import select_ticket
from notify import format_messages

class ConsensusPolicyTests(unittest.TestCase):
 def sample(self):
  race={'date':'2026-11-02','id':'R1C1','title':'TEST','departure':'2026-11-02T15:00:00+01:00','internet_quinte_available':True,'internet_2sur4_available':True,'horses':{n:{'nom':str(n),'statut':'PARTANT','pmu_odds':{'value':n+2,'kind':'direct'}} for n in range(1,8)}}
  rows=[{'publisher':str(i),'top3':[1,2,3],'top5':[1,2,3,4,5],'outsiders':[{'number':6},{'number':7}]} for i in range(5)]
  return {'race':race,'analyses':build_analyses(rows,race),'captured_at':'2026-11-02T14:00:00+01:00','eligible_before_departure':True,'consensus':{'outsiders':[{'number':6,'votes':5}]}}
 def test_only_cotes_allocates_money(self):
  s=self.sample();self.assertEqual([p['stake_eur'] for p in s['analyses']['profiles']],[0,2,0]);self.assertEqual([p['stake_eur'] for p in s['analyses']['two_of_four']],[0,0,0])
 def test_no_disabled_ticket_even_with_valid_receipts(self):
  from datetime import datetime
  s=self.sample();ts=int(datetime.fromisoformat(s['captured_at']).timestamp())+1
  ledger=[{'delivery':'SENT','snapshot_capture':s['captured_at'],'analyses':s['analyses'],'financial_profiles':['cotes'],'sent_at':'2026-11-02T14:00:01+01:00','receipts':[{'message_id':1,'date':ts}]}]
  self.assertIsNotNone(select_sent([s],ledger,'cotes'))
  for key in ('statistique','mixte'):self.assertIsNone(select_sent([s],ledger,key))
  for key in ('statistique','cotes','mixte'):self.assertIsNone(select_ticket([s],ledger,key))
  del ledger[0]['financial_profiles'];self.assertIsNone(select_sent([s],ledger,'cotes'))
 def test_display_labels_observations_without_three_euro_stakes(self):
  text='\n'.join(format_messages(self.sample()))
  self.assertIn('2 €',text);self.assertIn('mise 0 €',text);self.assertNotIn('mise 3 €',text);self.assertNotIn('TROIS SÉLECTIONS',text)
 def test_zero_stake_observations_need_confirmed_delivery(self):
  import json,tempfile
  from datetime import datetime
  from unittest.mock import Mock
  from evaluate import observation_rows
  s=self.sample();ts=int(datetime.fromisoformat(s['captured_at']).timestamp())+1
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'2026-11-02';folder.mkdir()
   ledger=[{'delivery':'SENT','snapshot_capture':s['captured_at'],'analyses':s['analyses'],'financial_profiles':['cotes'],'receipts':[{'message_id':1,'date':ts}]}]
   lp=folder/'notifications.json';lp.write_text(json.dumps(ledger))
   rows=observation_rows(root,{('2026-11-02','R1C1'):[s]},Mock())
   self.assertEqual(len(rows),2);self.assertTrue(all(r['mise']==0 and r['retour'] is None and r['net'] is None for r in rows))
   ledger[0]['delivery']='UNCERTAIN';lp.write_text(json.dumps(ledger))
   self.assertEqual(observation_rows(root,{('2026-11-02','R1C1'):[s]},Mock()),[])
