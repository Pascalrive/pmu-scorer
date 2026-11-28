import ast
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import pmu_tracking as p
from pmu_signaux import preparer_experience, marches_internet, formater_alertes

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
META=dict(numReunion=4,numOrdre=2,hippodrome={'libelleLong':'BORDEAUX'},libelle='TEST',paris=[{'typePari':'E_SIMPLE_PLACE'},{'typePari':'E_COUPLE_PLACE'}])
PARTICIPANTS=[dict(numPmu=n,nom={4:'FEEL WELL',12:'WINNIE CEN'}.get(n,'OTHER'),ordreArrivee=rank,statut='PARTANT') for n,rank in ((9,1),(7,2),(2,3),(4,5),(12,6))]

def bet(kind='SIMPLE_PLACE',nums=('9',)):
 return dict(type=kind,numeros=list(nums),mise='5.00')
def record(text=TEXT,sent=NOW,delivery='SENT'):
 return dict(id='test',sent_at=sent.isoformat(),event={**p.analyser_message(text,sent),'identite':{'hippodrome':'BORDEAUX','libelle':'TEST'}},delivery=delivery,sha256=text)
def formatter(name,function):
 tree=ast.parse(Path(__file__).with_name(name).read_text())
 nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function]
 env=dict(formater_alertes=formater_alertes,marches_internet=marches_internet,formater_selection=p.formater_selection,datetime=datetime,TZ_PARIS=p.TZ,paris_affiches=p.paris_affiches,TYPE_CONDITIONS='CONDITIONS',TYPE_INCONNU='AUTRE',PATTERNS_DISPO=False,
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
  msg,a=p.bilan([record()],'20260928',lambda path: PAYLOAD if 'rapports' in path else ({'participants':PARTICIPANTS} if path.endswith('/participants') else META))
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

class CollectionTests(unittest.TestCase):
 def test_block_after_start_without_telegram_call(self):
  with tempfile.TemporaryDirectory() as d:
   self.assertFalse(p.envoyer_trace(TEXT,'test','test',post=lambda *a,**k:self.fail('Late message sent'),journal=d,now=NOW+timedelta(minutes=20)))
   doc=json.loads(next(Path(d).glob('*.json')).read_text())
   self.assertEqual(doc['delivery'],'BLOCKED_AFTER_START')
 def test_explicit_date_prevents_midnight_reinterpretation(self):
  text=TEXT+'\nDATE : 2026-09-27'
  self.assertEqual(p.analyser_message(text,NOW)['date'],'20260927')
  with tempfile.TemporaryDirectory() as d:
   self.assertFalse(p.envoyer_trace(text,'test','test',post=lambda *a,**k:self.fail('Old date sent'),journal=d,now=NOW))
 def test_new_presentation_preserves_bets_and_source(self):
  horses=[dict(num_partant=11,nom_cheval='MOONLIGHT STAR',cote_jour=3,cote_actuel=3.1),dict(num_partant=7,nom_cheval='MILADY',cote_jour=9.1,cote_actuel=5.4)]
  txt='COURSE R1C5 — DEPART 20h45\nACTUALISATION\n'+'\n'.join(p.formater_selection(horses,13,True))
  e=p.analyser_message(txt,NOW)
  self.assertEqual(e['source'],'H15');self.assertEqual(e['paris'][1]['numeros'],['11','7'])
  self.assertIn('-41 %',txt);self.assertNotIn('VALUE BET',txt);self.assertNotIn('Proba',txt)
 def test_passage_windows_never_include_departed_race(self):
  phase=formatter('pmu_notifier.py','phase_collecte')
  for n,expected in [(-1,None),(0,None),(5,'H5'),(15,'H15'),(60,'H60'),(90,None)]:
   self.assertEqual(phase(n),expected)
 def test_missing_odds_not_displayed_as_zero(self):
  txt='\n'.join(p.formater_selection([dict(num_partant=1,nom_cheval='A',cote_jour=0)],10))
  self.assertIn('indisponible',txt);self.assertNotIn('Cote 0',txt)
 def test_snapshot_keeps_excluded_outsiders_without_ranking_change(self):
  tree=ast.parse(Path(__file__).with_name('pmu_notifier.py').read_text())
  node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='actualiser_course')
  env=dict(preparer_experience=preparer_experience,SCRAPING_DISPO=False,extraire_cote=lambda p:p['cote'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),'notifier','exec'),env)
  matin=[dict(nom_cheval='A',num_partant=1,cote_jour=3,score_total=40),dict(nom_cheval='B',num_partant=2,cote_jour=12,score_total=60)]
  result=env['actualiser_course'](matin,'2026-10-03',1,1,'TEST',[dict(nom='A',cote=3),dict(nom='B',cote=12)])
  self.assertEqual(len(result['tous_partants_observes']),2)
  self.assertEqual([c['num_partant'] for c in result['top2_final']],[1])
 def test_unchanged_advice_ignores_odds_only_changes(self):
  fn=formatter('pmu_notifier.py','conseil_change')
  horses=[dict(num_partant=4,nom_cheval='FEEL WELL',cote_jour=3,cote_actuel=4),dict(num_partant=12,nom_cheval='WINNIE CEN',cote_jour=3,cote_actuel=4)]
  self.assertFalse(fn(dict(top2_final=horses),10,record(),day=NOW.date().isoformat()))
  self.assertTrue(fn(dict(top2_final=horses),7,record(),day=NOW.date().isoformat()))
  self.assertTrue(fn(dict(top2_final=horses[::-1]),10,record(),day=NOW.date().isoformat()))
 def test_collection_retries_missing_odds_without_sending(self):
  import logging
  tree=ast.parse(Path(__file__).with_name('pmu_notifier.py').read_text())
  nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('main','phase_collecte')]
  horses=[dict(num_partant='4',nom_cheval='FEEL WELL',cote_jour=3,hippodrome='BORDEAUX',libelle='TEST'),dict(num_partant='12',nom_cheval='WINNIE CEN',cote_jour=3,hippodrome='BORDEAUX',libelle='TEST')]
  calls=[];archives=[];sent=[];state=set()
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return NOW
  env=dict(marches_internet=marches_internet,erreur_identite=p.erreur_identite,erreur_chevaux=p.erreur_chevaux,datetime=Clock,TZ_PARIS=p.TZ,Path=lambda name:Path('/tmp/pmu-no-such-journal-for-tests'),json=json,log=logging.getLogger('test'),SOURCE_CSV=None,
   charger_pronos_matin=lambda d:{('R4','C2'):horses},charger_etat=lambda d:state.copy(),sauver_etat=lambda d,s:state.update(s),
   get_courses_du_jour=lambda d:[dict(nr=4,nc=2,heure_ts=int((NOW+timedelta(minutes=15)).timestamp()*1000),libelle='TEST',hippodrome='BORDEAUX')],
   api_get=lambda url:(calls.append(url) or ({'participants':[dict(numPmu=4,nom='FEEL WELL',cote=0),dict(numPmu=12,nom='WINNIE CEN',cote=3)]} if url.endswith('/participants') else META)),
   extraire_cote=lambda d:d['cote'],archiver_observation=lambda *a,**k:archives.append((a,k)),
   actualiser_course=lambda *a:dict(top2_final=horses),dernieres_selections=lambda *a:{},
   telegram_send=lambda text:sent.append(text))
  exec(compile(ast.Module(body=nodes,type_ignores=[]),'notifier','exec'),env)
  env['main']()
  self.assertEqual(len(calls),3);self.assertEqual(len(archives),2)
  self.assertEqual(sent,[]);self.assertEqual(state,set())



from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pmu_runtime as r
import pmu_tracking as tracking


class RuntimeTests(unittest.TestCase):
    def csv(self, root, day='20261004'):
        path = root / f'pmu_{day}_0900.csv'
        path.write_text('reunion,course,num_partant\nR1,C1,4\n')
        return path

    def test_missing_initial_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            def run(args, check):
                calls.append(args)
                self.assertTrue(check)
                self.csv(root)
            r.assurer_initial('20261004', root, run)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-1], 'pmu_scorer.py')

    def test_existing_initial_is_not_sent_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.csv(root)
            r.assurer_initial('20261004', root, lambda *a, **k: self.fail('No replay'))

    def test_empty_csv_and_silent_scorer_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.csv(root).write_text('reunion,course,num_partant\n')
            with self.assertRaisesRegex(RuntimeError, 'COLLECTE EN ECHEC'):
                r.assurer_initial('20261004', root, lambda *a, **k: None)

    def test_yesterdays_csv_does_not_mask_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.csv(root, '20261003')
            self.assertIsNone(r.csv_du_jour('20261004', root))

    def test_delayed_night_report_keeps_previous_day(self):
        # Regression : le lancement observe a 03h59 ciblait a tort le 4 octobre.
        for hour in (3, 7, 11, 17):
            now = datetime(2026, 10, 4, hour, 59, tzinfo=r.TZ)
            self.assertEqual(r.date_bilan(now, scheduled=True), '20261003')

    def test_explicit_date_and_manual_default(self):
        now = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
        self.assertEqual(r.date_bilan(now), '20261004')
        self.assertEqual(r.date_bilan(now, '20261002', True), '20261002')
        with self.assertRaises(ValueError):
            r.date_bilan(now, '20260230')

    def test_winter_and_summer_transitions(self):
        for month, day, expected in ((3, 29, '20260328'), (10, 25, '20261024'), (1, 1, '20251231')):
            self.assertEqual(r.date_bilan(datetime(2026, month, day, 5, 17, tzinfo=timezone.utc),
                                         scheduled=True), expected)

    def test_empty_report_is_an_alert_not_zero_profit(self):
        message, audit = tracking.bilan([], '20261003', lambda path: self.fail('No fabricated results'))
        self.assertIn('ALERTE SUIVI', message)
        self.assertNotIn('0/0', message)
        self.assertNotIn('+0.00', message)
        self.assertEqual(audit, [])

    def test_collect_does_not_continue_after_failed_recovery(self):
        with patch.object(r, 'datetime') as clock, \
             patch.object(r, 'assurer_initial', side_effect=RuntimeError('absent')), \
             patch.object(r.sys, 'argv', ['pmu_runtime.py', 'collect']), \
             patch.object(r.subprocess, 'run') as run:
            clock.now.return_value = NOW
            with self.assertRaises(RuntimeError):
                r.main()
            run.assert_not_called()



class IdentityRegressionTests(unittest.TestCase):
    def test_duplicate_external_numbers_use_distinct_official_reunions(self):
        import logging
        tree = ast.parse(Path(__file__).with_name('pmu_notifier.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_courses_du_jour')
        course = dict(numOrdre=8, numExterne=18, discipline='ATTELE', heureDepart=1)
        reunions = [dict(numOfficiel=n, numExterne=5, pays={'code':'FRA'}, courses=[course]) for n in (5,6,7)]
        env = dict(marches_internet=marches_internet, api_get=lambda _: {'programme':{'reunions':reunions}}, PAYS_AUTORISES={'FRA'}, DISCIPLINES={'ATTELE'}, log=logging.getLogger('test'))
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'notifier', 'exec'), env)
        self.assertEqual([(c['nr'],c['nc']) for c in env['get_courses_du_jour']('04102026')], [(5,8),(6,8),(7,8)])

    def test_wrong_hippodrome_blocks_report_even_if_horses_match(self):
        row = record()
        row['event']['identite']['hippodrome'] = 'CORDEMAIS'
        msg, audit = p.bilan([row], '20260928', lambda _: META)
        self.assertEqual(audit[0]['statut'], 'IDENTITE_NON_VALIDEE')
        self.assertIn('aucun ROI global', msg)
        self.assertNotIn('ROI simule', msg)

    def test_same_number_different_horse_is_blocked(self):
        participants = deepcopy(PARTICIPANTS)
        participants[-1]['nom'] = 'ANOTHER HORSE'
        msg, audit = p.bilan([record()], '20260928', lambda path: {'participants':participants} if path.endswith('/participants') else META)
        self.assertEqual(audit[0]['statut'], 'IDENTITE_NON_VALIDEE')
        self.assertIn('N12', audit[0]['raison'])

    def test_old_journal_header_can_be_validated_without_rewriting_it(self):
        row = record()
        row['event'].pop('identite')
        row['text'] = 'COURSE R4C2 — DEPART 15h59\nDATE : 2026-09-28\nBORDEAUX\nTEST\n'
        msg, audit = p.bilan([row], '20260928', lambda path: PAYLOAD if 'rapports' in path else ({'participants':PARTICIPANTS} if path.endswith('/participants') else META))
        self.assertEqual([a['statut'] for a in audit], ['PERDU','PERDU'])
        self.assertNotIn('identite', row['event'])

    def test_conflicting_messages_same_second_remain_uncertain(self):
        a, b = record(), record(TEXT.replace('WINNIE CEN','OTHER'))
        self.assertEqual(p.dernieres_selections([a,b], '20260928')['R4C2']['delivery'], 'UNCERTAIN')

    def test_missing_identity_does_not_become_a_financial_result(self):
        msg, audit = p.bilan([record()], '20260928', lambda _: None)
        self.assertEqual(audit[0]['statut'], 'IDENTITE_NON_VALIDEE')

    def test_delayed_night_collection_never_starts_new_day_scorer(self):
        with patch.object(r, 'datetime') as clock, patch.object(r.sys, 'argv', ['pmu_runtime.py','collect']), patch.object(r, 'assurer_initial') as collect, patch.object(r.subprocess, 'run') as run:
            clock.now.return_value = datetime(2026,10,5,1,56,tzinfo=r.TZ)
            r.main()
            collect.assert_not_called()
            run.assert_not_called()

class EmptyDayCoverageTests(unittest.TestCase):
    def programme(self, market):
        return {'programme': {'reunions': [{'numOfficiel': 2, 'pays': {'code': 'FRA'},
            'courses': [{'numOrdre': 2, 'paris': [{'typePari': market, 'enVente': False}]}]}]}}

    def test_closed_market_is_still_evidence_of_a_missed_course(self):
        coverage = p.couverture_sans_envoi('20261127', lambda _: self.programme('E_COUPLE_ORDRE'))
        self.assertEqual(coverage['status'], 'ENVOIS_MANQUANTS')
        self.assertEqual(coverage['courses_eligibles'], ['R2C2'])

    def test_day_without_retained_market_is_not_an_error(self):
        coverage = p.couverture_sans_envoi('20261125', lambda _: self.programme('E_SIMPLE_GAGNANT'))
        self.assertEqual(coverage['status'], 'AUCUNE_COURSE_ELIGIBLE')

    def test_missing_or_partial_programme_never_becomes_zero_bets(self):
        for payload in (None, {}, {'programme': {'reunions': []}},
                        {'programme': {'reunions': [{'pays': {'code': 'FRA'}}]}}):
            self.assertNotEqual(p.couverture_sans_envoi('20261127', lambda _: payload)['status'], 'AUCUNE_COURSE_ELIGIBLE')

    def test_old_rules_are_not_reinterpreted(self):
        from unittest.mock import Mock
        fetch = Mock()
        self.assertEqual(p.couverture_sans_envoi('20261019', fetch)['status'], 'HISTORIQUE_MANQUANT')
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
