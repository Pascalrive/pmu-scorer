import unittest
from datetime import datetime
from itertools import product
from collections import Counter
from tony_artillan_3_5 import model as m
from tony_artillan_3_5.sources import SITES,parse_zone,slug
from tony_artillan_3_5.main import preview_report,report,confirmed_before

class Protocol(unittest.TestCase):
 def tips(self,nums):return {s:dict(site=s,number=n,name='TEST' if n==7 else 'OTHER',playable=True,captured_at=m.START+'T13:10:00+01:00') for s,n in zip(SITES,nums)}
 def test_telegram_confirmation(self):
  departure=m.START+'T14:00:00+01:00';end=int(datetime.fromisoformat(departure).timestamp())
  receipt=dict(status='SENT',receipts=[dict(date=end-1,message_id=12)])
  self.assertTrue(confirmed_before(receipt,departure))
  self.assertFalse(confirmed_before(dict(receipt,status='UNCERTAIN'),departure))
  self.assertFalse(confirmed_before(dict(receipt,receipts=[]),departure))
  receipt['receipts'].append(dict(date=end,message_id=13))
  self.assertFalse(confirmed_before(receipt,departure))
 def test_delayed_departure_preserves_original_capture_window(self):
  race=dict(departure=m.START+'T13:25:00+01:00',schedule_changes=[dict(old=m.START+'T13:23:00+01:00',new=m.START+'T13:25:00+01:00',checked_at=m.START+'T13:08:49+01:00')])
  now=datetime.fromisoformat(m.START+'T13:09:19+01:00')
  tip=dict(captured_at=m.START+'T12:23:19+01:00')
  self.assertTrue(m.valid_capture_window(race,tip,now))
  self.assertFalse(m.valid_capture_window(race,dict(tip,captured_at=m.START+'T12:22:59+01:00'),now))
  self.assertTrue(m.valid_capture_window(race,dict(tip,departure_at_capture=m.START+'T13:23:00+01:00'),now))
  later=dict(captured_at=m.START+'T13:10:00+01:00')
  self.assertTrue(m.valid_capture_window(race,later,datetime.fromisoformat(m.START+'T13:11:00+01:00')))
  self.assertFalse(m.valid_capture_window(race,later,now))
 def test_vote_partitions(self):
  for nums in product(range(1,5),repeat=5):
   g=m.groups(self.tips(nums));n,votes=Counter(nums).most_common(1)[0]
   self.assertEqual(bool(g),votes>=3)
   if g:self.assertEqual(g['majorite_3_sur_5']['number'],n)
 def test_missing_and_fallback_are_not_votes(self):
  tips=self.tips([7,7,7]);self.assertTrue(m.groups(tips))
  tips=self.tips([7,7]);tips['genybet']=dict(number=7,playable=True)
  self.assertFalse(m.groups(tips))
  tips=self.tips([7,7,7]);tips['zeturf']['playable']=False
  self.assertFalse(m.groups(tips))
 def test_progression_and_limits(self):
  sol={'bets':[]}
  for stake in [10000,20000,15000,15000,20000]:
   self.assertEqual(m.account(sol)['next_stake_cents'],stake)
   sol['bets'].append(dict(stake_cents=stake,status='PERDU',return_cents=0))
  self.assertEqual(m.account(sol)['stop'],'SERIE_TERMINEE')
  sol['bets'][-1].update(status='GAGNE',return_cents=100000)
  self.assertEqual(m.account(sol)['next_stake_cents'],10000)
  self.assertIsNone(m.account(sol)['stop'])
  self.assertEqual(m.account({'bets':[dict(stake_cents=115000,status='REMBOURSE',return_cents=115000)]})['stop'],'BUDGET')
  self.assertEqual(m.account({'bets':[dict(stake_cents=10000,status='EN_ATTENTE')]})['stop'],'ATTENTE_RESULTAT')
 def test_reserve_voters_window_and_end(self):
  tips=self.tips([7,7,7,9,10]);g=m.groups(tips)['majorite_3_sur_5']
  race=dict(date=m.START,id='R1C1',departure=m.START+'T14:00:00+01:00',market=True,tips=tips)
  h=dict(numPmu=7,nom='TEST',statut='PARTANT');now=datetime.fromisoformat(m.START+'T13:40:00+01:00')
  sol={'bets':[]}
  self.assertFalse(m.reserve(sol,race,tips['turfin'],h,now,['turfin','canalturf']))
  self.assertTrue(m.reserve(sol,race,tips['turfin'],h,now,g['sites']))
  self.assertFalse(m.reserve(sol,race,tips['turfin'],h,now,g['sites']))
  tips['zeturf']['captured_at']=m.START+'T12:00:00+01:00'
  self.assertFalse(m.reserve({'bets':[]},race,tips['turfin'],h,now,g['sites']))
  tips['zeturf']['captured_at']=m.START+'T13:10:00+01:00'
  self.assertFalse(m.reserve({'bets':[]},race,tips['turfin'],h,datetime.fromisoformat(m.START+'T14:00:00+01:00'),g['sites']))
  self.assertFalse(m.reserve({'bets':[]},dict(race,date='2026-11-25'),tips['turfin'],h,now,g['sites']))
 def test_no_place_no_missing_loss(self):
  self.assertEqual(m.place_plan({}),[])
  t=dict(number=7,name='TEST',stake_cents=10000,status='EN_ATTENTE');horses=[dict(numPmu=7,nom='TEST',statut='PARTANT')]
  self.assertFalse(m.settle(t,[],horses));self.assertEqual(t['status'],'EN_ATTENTE')
  self.assertTrue(m.settle(t,[dict(typePari='E_SIMPLE_GAGNANT',rapports=[dict(combinaison='7',dividendePourUnEuro=250)])],horses));self.assertEqual(t['return_cents'],25000)
 def test_report_has_five_sites_and_no_stale_label(self):
  race=dict(id='R1C1',departure=m.START+'T14:00:00+01:00',title='TEST',tips=self.tips([7,7,7,9,10]),errors={})
  out=preview_report(dict(date=m.START,venue='TEST'),dict(captured_at=m.START+'T10:00:00+01:00',races=[race]))
  for s in ('Turfin','Canalturf','ZEturf','Geny','Zone-Turf','3/5'):self.assertIn(s,out)
  self.assertNotIn('2/2',out)

class Zone(unittest.TestCase):
 def fixture(self,numbers='7 9'):
  row=''.join('<td class="number">'+n+'</td>' for n in numbers.split())
  return '<p>25 octobre 2026</p><div class="bloc course"><h2 class="nomCourse">R1 Course N°1 : TEST</h2><table class="engages"><tr><td>7</td><td class="infosGen"><a title="TEST"><b>Te.</b></a></td></tr><tr><td>9</td><td class="infosGen"><a title="OTHER (IRE)"><b>Ot.</b></a></td></tr></table><table><tr><td class="forecaster-name">Zone-Turf.fr</td>'+row+'</tr></table></div>'
 def parse(self,body,race=None):
  return parse_zone(body,'https://www.zone-turf.fr/programmes/r1-test-1.html',race or dict(date='2026-10-25',c=1),[dict(numPmu=7,nom='TEST',statut='PARTANT'),dict(numPmu=9,nom='OTHER',statut='PARTANT')])
 def test_full_name_and_exact_editorial(self):
  self.assertEqual(self.parse(self.fixture())['number'],7)
  padded=self.fixture().replace('</tr></table></div>','<td class="number"></td><td class="number"></td></tr></table></div>')
  self.assertEqual(self.parse(padded)['number'],7)
  for bad in [self.fixture('').replace('</div>','<p>Top chances 7 TEST</p></div>'),self.fixture('7 7'),self.fixture().replace('title="OTHER (IRE)"','title="WRONG"'),self.fixture().replace('25 octobre','24 octobre'),self.fixture().replace('R1 Course N°1','R2 Course N°1')]:
   with self.assertRaises(ValueError):self.parse(bad)
 def test_slug(self):self.assertEqual(slug('2026-11-24'),'mardi-24-novembre-2026')
if __name__=='__main__':unittest.main()
