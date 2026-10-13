import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collector import parse,pmu_odds,display_top5,consensus
from notify import format_messages,quote
FIX=Path(__file__).parent/'fixtures'
class PresentationTests(unittest.TestCase):
 def test_preserve_original_top3_and_read_five_published_horses(self):
  for key in ['canalturf','zeturf','zone','stats','turfprono','rue','frequence']:
   race=json.loads((FIX/(key+'.race.json')).read_text());race['horses']={int(n):p for n,p in race['horses'].items()}
   row=parse(key,(FIX/(key+'.html')).read_text(),race)
   with self.subTest(source=key):self.assertEqual(len(row['top5']),5);self.assertEqual(row['top3'],row['top5'][:3])
 def test_no_five_horses_invented_for_public_base_only(self):
  race=json.loads((FIX/'prono.race.json').read_text());race['horses']={int(n):p for n,p in race['horses'].items()};row=parse('prono',(FIX/'prono.html').read_text(),race)
  self.assertEqual(row['top5'],[16])
 def test_direct_win_odds_preferred_and_reference_explicit(self):
  self.assertEqual(pmu_odds({'dernierRapportDirect':{'typePari':'SIMPLE_GAGNANT','rapport':4.4},'dernierRapportReference':{'rapport':5.5}})['value'],4.4)
  q=pmu_odds({'dernierRapportReference':{'rapport':5.5}});self.assertIn('réf.',quote({'horses':{1:{'pmu_odds':q}}},1))
  self.assertIsNone(pmu_odds({'dernierRapportDirect':{'typePari':'SIMPLE_PLACE','rapport':1.4}}))
  for value in [0,-2,float('nan'),float('inf'),'inconnu']:
   with self.subTest(value=value):self.assertIsNone(pmu_odds({'dernierRapportDirect':{'rapport':value}}))
 def test_three_numbered_sections_have_all_five_choices_and_escape_html(self):
  race=json.loads((FIX/'stats.race.json').read_text());race['horses']={int(n):p for n,p in race['horses'].items()};row=parse('stats',(FIX/'stats.html').read_text(),race)
  race['horses'][3]['nom']='CHEVAL <A & B>';race['horses'][3]['pmu_odds']={'value':4.4,'kind':'direct'}
  s={'race':race,'rows':[row],'consensus':consensus([row],race),'captured_at':'2026-10-12T09:00:00+00:00'}
  parts=format_messages(s);self.assertEqual(len(parts),3);self.assertIn('①',parts[1]);self.assertIn('⑤',parts[1]);self.assertIn('4,4',parts[1]);self.assertIn('&lt;A &amp; B&gt;',parts[1]);self.assertTrue(all(len(p)<3500 for p in parts))
 def test_five_choice_summary_does_not_change_three_choice_trial(self):
  race={'horses':{n:{'nom':str(n),'statut':'PARTANT'} for n in range(1,7)}}
  row={'publisher':'a','top3':[1,2,3],'top5':[1,2,3,4,5],'outsiders':[]}
  baseline=consensus([row],race);self.assertEqual(display_top5([row,row],race)[4]['number'],5);self.assertEqual(consensus([row],race),baseline)
if __name__=='__main__':unittest.main()
