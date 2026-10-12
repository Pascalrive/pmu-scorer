import copy,json,sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collector import parse,consensus,VERSION
from evaluate import place_return,selected
FIX=Path(__file__).parent/'fixtures'
def fixture(key):
 race=json.loads((FIX/(key+'.race.json')).read_text());race['horses']={int(n):p for n,p in race['horses'].items()};return (FIX/(key+'.html')).read_text(),race
class EditorialTests(unittest.TestCase):
 def test_actual_eight_editorial_excerpts(self):
  expected={'canalturf':[1,11,13],'zeturf':[11,2,15],'zone':[2,1,7],'stats':[3,11,4],'turfprono':[1,2,15],'rue':[3,11,1],'frequence':[14,12,11],'prono':[16]}
  for key,top in expected.items():
   with self.subTest(source=key):
    body,race=fixture(key);row=parse(key,body,race);self.assertEqual(row['top3'],top)
 def test_wrong_course_rejected(self):
  for key in ['canalturf','zeturf','zone','stats','turfprono','rue','frequence','prono']:
   body,race=fixture(key);race['title']='PRIX INEXISTANT'
   with self.subTest(source=key),self.assertRaises(ValueError):parse(key,body,race)
 def test_wrong_date_rejected(self):
  for key in ['zone','stats','turfprono','rue','frequence','prono']:
   body,race=fixture(key);race['date']='2026-10-15'
   with self.subTest(source=key),self.assertRaises(ValueError):parse(key,body,race)
 def test_numeric_name_disagreement_rejected(self):
  body,race=fixture('frequence');race['horses'][14]['nom']='AUTRE CHEVAL'
  with self.assertRaises(ValueError):parse('frequence',body,race)
 def test_outsider_groups_are_explicit(self):
  body,race=fixture('stats');self.assertEqual([e['number'] for e in parse('stats',body,race)['outsiders']],[12,9,2,10])
  body,race=fixture('prono');row=parse('prono',body,race);self.assertEqual(row['top3'],[16]);self.assertEqual(row['outsiders'][0]['number'],4)
 def test_duplicate_publisher_does_not_add_votes(self):
  body,race=fixture('stats');row=parse('stats',body,race)
  a=consensus([row],race);b=consensus([row,copy.deepcopy(row)],race);self.assertEqual(a,b)
 def test_nonrunner_not_promoted_and_no_vote(self):
  body,race=fixture('stats');row=parse('stats',body,race);race['horses'][3]['statut']='NON_PARTANT'
  con=consensus([row],race);self.assertNotIn(3,[e['number'] for e in con['top3']]);self.assertEqual(row['top3'],[3,11,4])
 def test_partial_source_not_counted_for_threshold(self):
  body,race=fixture('prono');con=consensus([parse('prono',body,race)],race);self.assertEqual(con['complete_sources'],0);self.assertFalse(con['qualified'])
class SettlementTests(unittest.TestCase):
 def test_official_dividend_cents_and_multi_digit_number(self):
  ps=[{'numPmu':12,'statut':'PARTANT'}];reports=[{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'12','dividendePourUnEuro':170}]}]
  self.assertEqual(place_return(12,ps,reports),8.5)
  self.assertEqual(place_return(12,ps,[]),None)
 def test_network_market_cannot_be_substituted(self):
  self.assertIsNone(place_return(12,[{'numPmu':12}],[{'typePari':'SIMPLE_PLACE','rapports':[{'combinaison':'12','dividendePourUnEuro':170}]}]))
 def test_nonrunner_refunded(self):
  self.assertEqual(place_return(12,[{'numPmu':12,'statut':'NON_PARTANT'}],[]),5)
 def test_late_and_insufficient_snapshots_excluded(self):
  base={'version':VERSION,'eligible_before_departure':True,'captured_at':'2026-10-12T09:00:00+00:00','race':{'departure':'2026-10-12T12:00:00+00:00'},'consensus':{'qualified':True}}
  late=copy.deepcopy(base);late['captured_at']='2026-10-12T13:00:00+00:00'
  low=copy.deepcopy(base);low['consensus']['qualified']=False
  self.assertIsNone(selected([late,low]));self.assertEqual(selected([base,late]),base)
if __name__=='__main__':unittest.main()
