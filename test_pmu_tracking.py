import ast
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import pmu_tracking as p

NOW=datetime(2026,9,28,15,44,tzinfo=p.TZ)
TEXT='''ACTUALISATION DE L'ALGORITHME
COURSE : R4C2 — BORDEAUX
HEURE : 15h59 | PLAT
>> PRONOSTIC PRINCIPAL : 🔴 N4. FEEL WELL
>> DEUXIEME CHOIX : 🔴 N12. WINNIE CEN
PARI : Simple Place sur N4 FEEL WELL
COUPLE PLACE (les 2 choix ci-dessus) : N4 FEEL WELL + N12 WINNIE CEN
'''
# Extrait reel API PMU rapports-definitifs INTERNET, 28/09/2026 R4C2.
PAYLOAD=[{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'9','dividendePourUnEuro':1470}]},
 {'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':n,'dividendePourUnEuro':r} for n,r in [('9',290),('7',340),('2',160)]]},
 {'typePari':'E_COUPLE_PLACE','rapports':[{'combinaison':n,'dividendePourUnEuro':r} for n,r in [('9-7',1130),('9-2',1010),('7-2',860),('9-NP',0)]]}]
PARTICIPANTS=[dict(numPmu=n,ordreArrivee=rank,statut='PARTANT') for n,rank in ((9,1),(7,2),(2,3),(4,5),(12,6))]

def bet(kind='SIMPLE_PLACE',nums=('9',)):
 return dict(type=kind,numeros=list(nums),mise='5.00')
def record(text=TEXT,sent=NOW,delivery='SENT'):
 return dict(id='test',sent_at=sent.isoformat(),event=p.analyser_message(text,sent),delivery=delivery,sha256=text)
def formatter(name,function):
 tree=ast.parse(Path(__file__).with_name(name).read_text())
 nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function]
 env=dict(datetime=datetime,TZ_PARIS=p.TZ,paris_affiches=p.paris_affiches,TYPE_CONDITIONS='CONDITIONS',TYPE_INCONNU='AUTRE',PATTERNS_DISPO=False,
 calculer_score_opportunite=lambda d:0,detecter_pattern_gagnant=lambda d:False,classer_niveau_course=lambda c:dict(niveau='CORRECT',emoji='',raison=''),
 est_trot=lambda d:False,evaluer_fiabilite_course=lambda c:'')
 exec(compile(ast.Module(body=nodes,type_ignores=[]),name,'exec'),env)
 return env[function]

class TrackingTests(unittest.TestCase):
 def settle(self,b,ps=None,data=None):
  return p.regler_pari(b,PARTICIPANTS if ps is None else ps,p.tables_rapports(PAYLOAD if data is None else data))
 def test_winner_paid_at_place_dividend(self):
  self.assertEqual(self.settle(bet())['retour'],'14.50')
 def test_horse_specific_dividend(self):
  self.assertEqual(self.settle(bet(nums=('7',)))['retour'],'17.00')
 def test_exact_unordered_couple(self):
  self.assertEqual(self.settle(bet('COUPLE_PLACE',('2','9')))['retour'],'50.50')
 def test_centimes_at_one_euro(self):
  data=[{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'9','dividendePourUnEuro':100}]}]
  self.assertEqual(self.settle(bet(),data=data)['retour'],'5.00')
 def test_missing_reports_no_estimate(self):
  r=self.settle(bet(),data=[]);self.assertEqual(r['statut'],'EN_ATTENTE');self.assertIsNone(r['retour'])
 def test_unknown_units_rejected(self):
  self.assertEqual(p.tables_rapports([{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'9','rapport':290}]}]),{})
 def test_simple_non_partant_refund(self):
  r=self.settle(bet(nums=('3',)),ps=[dict(numPmu=3,statut='NON_PARTANT')]);self.assertEqual((r['statut'],r['retour']),('REMBOURSE','5.00'))
 def test_couple_non_partant_pending(self):
  self.assertEqual(self.settle(bet('COUPLE_PLACE',('9','3')),ps=PARTICIPANTS+[dict(numPmu=3,statut='NON_PARTANT')])['statut'],'EN_ATTENTE')
 def test_couple_non_partant_specific_dividend(self):
  data=deepcopy(PAYLOAD);data[-1]['rapports'][-1]['dividendePourUnEuro']=190
  r=self.settle(bet('COUPLE_PLACE',('9','3')),ps=PARTICIPANTS+[dict(numPmu=3,statut='NON_PARTANT')],data=data)
  self.assertEqual((r['statut'],r['retour']),('REGLE_NP','9.50'))
 def test_race_refund(self):
  self.assertEqual(self.settle(bet(),ps=[],data=[{'typePari':'E_SIMPLE_PLACE','rembourse':True}])['statut'],'REMBOURSE')
 def test_missing_runner_pending(self):
  self.assertEqual(self.settle(bet(),ps=[])['statut'],'EN_ATTENTE')
 def test_disqualification(self):
  self.assertEqual(self.settle(bet(nums=('4',)),ps=[dict(numPmu=4,incident='DISQUALIFIE')])['statut'],'PERDU')
 def test_latest_before_start(self):
  morning=record(TEXT.replace('N12. WINNIE CEN','N9. DANCING EAGLE CEN').replace('N12 WINNIE CEN','N9 DANCING EAGLE CEN'),NOW-timedelta(hours=3))
  late=record(TEXT.replace('WINNIE CEN','OTHER'),NOW+timedelta(minutes=20))
  r=p.dernieres_selections([record(),morning,late],'20260928')
  self.assertEqual(r['R4C2']['event']['choix'][1]['num'],'12')
 def test_failed_update_no_morning_fallback(self):
  r=p.dernieres_selections([record(sent=NOW-timedelta(hours=1)),record(delivery='UNCERTAIN')],'20260928')
  self.assertEqual(r['R4C2']['delivery'],'UNCERTAIN')
 def test_deduplication(self):
  self.assertEqual(len(p.dernieres_selections([record(),record(sent=NOW+timedelta(minutes=1))],'20260928')),1)
 def test_other_date(self):
  self.assertEqual(p.dernieres_selections([record()],'20260929'),{})
 def test_incoherent_selection(self):
  with self.assertRaises(ValueError):p.analyser_message(TEXT.replace('PARI : Simple Place sur N4','PARI : Simple Place sur N9'),NOW)
 def test_real_final_choices_not_morning_winner(self):
  msg,a=p.bilan([record()],'20260928',lambda path: PAYLOAD if 'rapports' in path else {'participants':PARTICIPANTS})
  self.assertEqual([r['statut'] for r in a],['PERDU','PERDU']);self.assertNotIn('DANCING EAGLE',msg);self.assertIn('solde -10.00',msg)
 def test_pending_no_global_roi(self):
  msg,_=p.bilan([record()],'20260928',lambda path:None)
  self.assertIn('aucun ROI global',msg);self.assertNotIn('ROI simule',msg)
 def test_no_journal_no_csv_fallback(self):
  msg,a=p.bilan([],'20260928',lambda path:self.fail('No API expected'))
  self.assertEqual(a,[]);self.assertIn('Aucun historique',msg)
 def test_production_formatters_and_receipts(self):
  h=lambda n,name:dict(num_partant=n,nom_cheval=name,cote_jour=3,cote_actuel=3,nb_partants=10)
  horses=[h(4,'FEEL WELL'),h(12,'WINNIE CEN')]
  c=dict(reunion='R4',course='C2',top5=horses,discipline='PLAT',heure=int(NOW.replace(minute=59).timestamp()*1000))
  morning=formatter('pmu_scorer.py','formater_message_telegram')([c],[],'28/09/2026','MATIN')
  h15=formatter('pmu_notifier.py','formater_message_h15')(dict(nr=4,nc=2,heure_ts=c['heure'],hippodrome='BORDEAUX',libelle='TEST',discipline='PLAT',distance=1400,terrain=''),[{}]*10,dict(top2_final=horses,tous_top5=horses,verdict='CONFIRME'))
  class Response:
   status_code=200
   def json(self):return {'ok':True,'result':{'message_id':123,'date':int(NOW.timestamp())}}
  for text in [morning,h15]:
   with self.subTest(text=text[:20]),tempfile.TemporaryDirectory() as d:
    self.assertTrue(p.envoyer_trace(text,'test','test',post=lambda *a,**kw:Response(),journal=d,now=NOW))
    docs=[json.loads(f.read_text()) for f in Path(d).glob('*.json')];self.assertEqual(len(docs),1)
    self.assertEqual(docs[0]['delivery'],'SENT');self.assertEqual(docs[0]['event']['paris'][1]['numeros'],['4','12'])
    self.assertEqual(docs[0]['event']['source'],'H15' if text==h15 else 'MATIN')
 def test_telegram_failed_body(self):
  class Response:
   status_code=200
   def json(self):return {'ok':False}
  with tempfile.TemporaryDirectory() as d:
   self.assertFalse(p.envoyer_trace(TEXT,'test','test',post=lambda *a,**kw:Response(),journal=d,now=NOW))
   docs=[json.loads(f.read_text()) for f in Path(d).glob('*.json')];self.assertEqual(docs[0]['delivery'],'UNCERTAIN')
 def test_telegram_timeout(self):
  def fail(*a,**kw):raise TimeoutError()
  with tempfile.TemporaryDirectory() as d:self.assertFalse(p.envoyer_trace(TEXT,'test','test',post=fail,journal=d,now=NOW))
 def test_couple_rules(self):
  a=dict(num_partant=2,nom_cheval='A',cote_jour=4);b=dict(num_partant=1,nom_cheval='B',cote_jour=12)
  self.assertEqual(len(p.paris_affiches([a,b],10)),1);self.assertEqual(len(p.paris_affiches([a],10)),1)
  b['cote_jour']=4
  self.assertIn('COUPLE GAGNANT',p.paris_affiches([a,b],7)[1]);self.assertIn('COUPLE PLACE',p.paris_affiches([a,b],8)[1])

if __name__=='__main__':unittest.main()
