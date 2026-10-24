import unittest
from datetime import datetime
from tony_artillan_2.model import groups,account,reserve,settle,START,END
from tony_artillan_2.main import daily_report,preview_report,report
class Protocol(unittest.TestCase):
 def test_votes(self):
  t={'number':7,'playable':True}
  self.assertTrue(groups({'geny':t,'canalturf':t}))
  self.assertFalse(groups({'geny':t}))
  self.assertFalse(groups({'geny':t,'canalturf':dict(t,number=8)}))
  self.assertFalse(groups({'geny':t,'canalturf':dict(t,playable=False)}))
  self.assertTrue(groups({'geny':t,'canalturf':t,'turfin':dict(t,number=8),'zeturf':dict(t,number=8)}))
 def test_progression(self):
  s={'bets':[]};stakes=[10000,20000,15000,15000,20000]
  for n in stakes:
   self.assertEqual(account(s)['next_stake_cents'],n)
   s['bets'].append({'stake_cents':n,'status':'PERDU','return_cents':0})
  self.assertEqual(account(s)['stop'],'SERIE_TERMINEE')
  s['bets'][-1].update(status='GAGNE',return_cents=100000)
  self.assertEqual(account(s)['next_stake_cents'],10000)
  self.assertIsNone(account(s)['stop'])
 def test_pending_budget_refund(self):
  self.assertEqual(account({'bets':[{'stake_cents':10000,'status':'EN_ATTENTE'}]})['stop'],'ATTENTE_RESULTAT')
  s={'bets':[{'stake_cents':115000,'status':'REMBOURSE','return_cents':115000}]}
  self.assertEqual(account(s)['stop'],'BUDGET')
  self.assertEqual(account(s)['next_stake_cents'],10000)
 def test_window_and_end(self):
  race={'id':'R1C1','date':START,'departure':START+'T14:00:00+01:00','market':True}
  tip={'number':7,'name':'TEST','site':'geny','playable':True,'captured_at':START+'T13:10:00+01:00'}
  h={'numPmu':7,'nom':'TEST','statut':'PARTANT'}
  s={'bets':[]}
  self.assertFalse(reserve(s,race,tip,h,datetime.fromisoformat(START+'T14:01:00+01:00')))
  self.assertTrue(reserve(s,race,tip,h,datetime.fromisoformat(START+'T13:40:00+01:00'),['geny','canalturf']))
  self.assertFalse(reserve(s,race,tip,h,datetime.fromisoformat(START+'T13:41:00+01:00')))
  self.assertFalse(reserve({'bets':[]},dict(race,date='2026-11-25'),tip,h,datetime.fromisoformat(START+'T13:40:00+01:00')))
 def test_official_settlement(self):
  t={'number':7,'name':'TEST','stake_cents':10000,'status':'EN_ATTENTE'}
  h=[{'numPmu':7,'nom':'TEST','statut':'PARTANT','ordreArrivee':1}]
  self.assertFalse(settle(t,[],h))
  self.assertEqual(t['status'],'EN_ATTENTE')
  self.assertTrue(settle(t,[{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'7','dividendePourUnEuro':250}]}],h))
  self.assertEqual(t['return_cents'],25000)
if __name__=='__main__':unittest.main()
