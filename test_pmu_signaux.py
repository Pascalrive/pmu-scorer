import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import pmu_signaux as q
import pmu_tracking as tracking
import pmu_scorer as scorer
import pmu_notifier as notifier
import pronos_gratuit as presse


def chevaux():
    return [dict(num_partant=n, nom_cheval=name, score_total=score, musique=music,
                 cote_jour=initial, cote_actuel=current)
            for n, name, score, music, initial, current in [
                (6, 'CAMBRONNE', 57.2, '1pAp2p4p4p', 32, 17),
                (2, 'HYPERCORE', 57.0, '4p2p1p7p', 43, 16),
                (3, 'ANSSIO', 56.2, '1p2p2p3p', 2.7, 4.6),
                (5, 'TIPINSO', 56.1, '2p5p2p2p', 3.8, 3),
                (4, 'SWINGUER', 55.8, '4p5p2p1p', 4.8, 5.4),
                (7, 'ZELZARI', 53.7, '7p2p1p1p', 5.7, 3.5)]]


class SignauxTests(TestCase):
    def test_alert_reperes_cambronne_not_every_dropping_horse(self):
        self.assertEqual([p['nom_cheval'] for p in q.alerter_outsiders(chevaux())], ['CAMBRONNE'])

    def test_lio_is_not_silenced_at_6_point_1(self):
        p = dict(num_partant=3, nom_cheval='LIO DE LA PLATA', score_total=52.4,
                 musique='1p(25)2p6p', cote_jour=8.3, cote_actuel=6.1)
        self.assertEqual(len(q.alerter_outsiders([p])), 1)
        self.assertEqual(q.alerter_outsiders([{**p, 'cote_jour': 0}]), [])
        self.assertEqual(q.alerter_outsiders([{**p, 'cote_actuel': 6}]), [])

    def test_alert_does_not_add_any_advised_bet(self):
        hs = chevaux(); selection = [hs[3], hs[5]]
        exp = q.preparer_experience(hs, selection, 6, ['SIMPLE_PLACE', 'COUPLE_ORDRE'])
        text = 'COURSE R1C1 — DEPART 23h59\n' + '\n'.join(
            tracking.formater_selection(selection, 6, True, ['SIMPLE_PLACE', 'COUPLE_ORDRE']) + q.formater_alertes(exp['alertes']))
        event = tracking.analyser_message(text, tracking.datetime.now(tracking.TZ))
        self.assertEqual(event['paris'], exp['reference']['paris'])
        self.assertEqual(event['choix'], exp['reference']['choix'])
        self.assertEqual(event['paris'][1]['type'], 'COUPLE_ORDRE')
        self.assertEqual([x['num'] for x in exp['variante_outsider']['choix']], ['6', '5'])
        self.assertEqual(sum(float(b['mise']) for b in event['paris']), 10)
        self.assertEqual(sum(float(b['mise']) for b in exp['variante_outsider']['paris']), 10)

    def test_one_bet_reference_has_one_bet_shadow(self):
        hs = chevaux()
        exp = q.preparer_experience(hs, [hs[3]], 6, ['SIMPLE_PLACE', 'COUPLE_ORDRE'])
        self.assertEqual(len(exp['reference']['paris']), 1)
        self.assertEqual(len(exp['variante_outsider']['paris']), 1)

    def test_new_alert_is_not_suppressed_by_same_primary_advice(self):
        hs = chevaux(); selection = [hs[3], hs[5]]
        exp = q.preparer_experience(hs, selection, 6, ['SIMPLE_PLACE', 'COUPLE_ORDRE'])
        prev = {'event': exp['reference']}
        maj = {'top2_final': selection, 'paris_disponibles': ['SIMPLE_PLACE', 'COUPLE_ORDRE'], 'experience': exp}
        self.assertTrue(notifier.conseil_change(maj, 6, prev))
        prev['experience'] = exp
        self.assertFalse(notifier.conseil_change(maj, 6, prev))

    def test_scorer_deferrage_does_not_confuse_protection_with_bare_feet(self):
        for code, flag, score in [
            ('DEFERRE_ANTERIEURS_POSTERIEURS', True, 80),
            ('PROTEGE_ANTERIEURS_POSTERIEURS', False, 50),
            ('PROTEGE_ANTERIEURS_DEFERRRE_POSTERIEURS', True, 65),
            ('DEFERRE_ANTERIEURS_PROTEGE_POSTERIEURS', True, 58),
            ('DA', True, 58), ('', None, 50)]:
            with self.subTest(code=code):
                self.assertEqual(q.deferrage_officiel({'deferre': code})['deferre'], flag)
                self.assertEqual(scorer.score_deferre_pmu({'deferre': code}), score)

    def test_markets_are_official_and_active(self):
        market = {'hasEParis': True, 'paris': [{'typePari': 'E_SIMPLE_PLACE', 'enVente': True},
                   {'typePari': 'E_COUPLE_ORDRE'}, {'typePari': 'COUPLE_GAGNANT'},
                   {'typePari': 'E_COUPLE_PLACE', 'enVente': False}]}
        self.assertEqual(q.marches_internet(market), ['COUPLE_ORDRE', 'SIMPLE_PLACE'])
        self.assertEqual(q.marches_internet({**market, 'hasEParis': False}), [])
        self.assertEqual(q.marches_internet({}), [])
        self.assertNotIn('PARI :', '\n'.join(tracking.paris_affiches(chevaux()[:2], 6, [])))

    def test_ordered_couple_keeps_the_exact_order(self):
        tables = tracking.tables_rapports([{'typePari':'E_COUPLE_ORDRE', 'rapports':[
            {'combinaison':'6-2', 'dividendePourUnEuro':1000}]}])
        ps = [dict(numPmu=6, statut='PARTANT', ordreArrivee=1), dict(numPmu=2, statut='PARTANT', ordreArrivee=2)]
        b = {'type':'COUPLE_ORDRE', 'numeros':['6','2'], 'mise':'5.00'}
        self.assertEqual(tracking.regler_pari(b, ps, tables)['retour'], '50.00')
        self.assertEqual(tracking.regler_pari({**b, 'numeros':['2','6']}, ps, tables)['retour'], '0.00')

    def test_definitive_dividends_settle_unranked_known_runner(self):
        tables = tracking.tables_rapports([{'typePari':'E_SIMPLE_PLACE', 'rapports':[
            {'combinaison':'6', 'dividendePourUnEuro':180}]}])
        b = {'type':'SIMPLE_PLACE', 'numeros':['3'], 'mise':'5.00'}
        self.assertEqual(tracking.regler_pari(b, [{'numPmu':3,'statut':'PARTANT'}], tables, definitif=True)['statut'], 'PERDU')
        self.assertEqual(tracking.regler_pari(b, [{'numPmu':3}], tables, definitif=True)['statut'], 'EN_ATTENTE')

    def test_shadow_requires_confirmed_matching_reference_and_same_budget(self):
        hs = chevaux();exp = q.preparer_experience(hs, [hs[3]], 6, ['SIMPLE_PLACE'])
        record = {'delivery':'SENT', 'event':exp['reference'], 'experience':exp}
        ps = [{'numPmu': p['num_partant'], 'nom':p['nom_cheval'], 'statut':'PARTANT'} for p in hs]
        tables = tracking.tables_rapports([{'typePari':'E_SIMPLE_PLACE', 'rapports':[{'combinaison':'6', 'dividendePourUnEuro':980}]}])
        result = tracking.regler_experience(record, ps, tables)
        self.assertTrue(result['complet']);self.assertEqual(result['reference']['retour'], '0.00')
        self.assertEqual(result['variante_outsider']['retour'], '49.00')
        self.assertIsNone(tracking.regler_experience({**record, 'delivery':'UNCERTAIN'}, ps, tables))
        self.assertIsNone(tracking.regler_experience({**record, 'event':{**record['event'],'choix':[]}}, ps, tables))

    def test_report_compares_only_matching_budgets_without_adding_shadow_gains(self):
        hs = chevaux();exp = q.preparer_experience(hs, [hs[3]], 6, ['SIMPLE_PLACE'])
        now = tracking.datetime(2026,10,11,17,47,tzinfo=tracking.TZ)
        text = 'COURSE R6C5 — DEPART 18h05\nDATE : 2026-10-11\nLYON LA SOIE\nTEST\n' + '\n'.join(tracking.formater_selection([hs[3]],6,True,['SIMPLE_PLACE']))
        record = dict(id='experience-test',delivery='SENT',sent_at=now.isoformat(),event=tracking.analyser_message(text,now),experience=exp,sha256='test')
        meta = dict(numReunion=6,numOrdre=5,hippodrome={'libelleLong':'LYON LA SOIE'},libelle='TEST',paris=[{'typePari':'E_SIMPLE_PLACE'}])
        ps = [{'numPmu': p['num_partant'], 'nom':p['nom_cheval'], 'statut':'PARTANT'} for p in hs]
        payload = [{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'6','dividendePourUnEuro':980}]}]
        def fetch(path):
            return payload if 'rapports' in path else {'participants':ps} if path.endswith('participants') else meta
        message, audit = tracking.bilan([record],'20261011',fetch)
        self.assertEqual(audit[0]['retour'],'0.00')
        self.assertIn('retours 0.00 EUR ; solde -5.00',message)
        self.assertIn('Variante outsider non conseillee : mises 5.00 EUR ; retours 49.00 EUR',message)

    def test_unsupported_legacy_market_is_excluded_not_pending_forever(self):
        hs = chevaux();now = tracking.datetime(2026,10,11,17,47,tzinfo=tracking.TZ)
        text = 'COURSE R6C5 — DEPART 18h05\nDATE : 2026-10-11\nLYON LA SOIE\nTEST\n' + '\n'.join(tracking.formater_selection([hs[0],hs[3]],6,True))
        record = dict(id='legacy-test',delivery='SENT',sent_at=now.isoformat(),event=tracking.analyser_message(text,now),sha256='test')
        meta = dict(numReunion=6,numOrdre=5,hippodrome={'libelleLong':'LYON LA SOIE'},libelle='TEST',paris=[{'typePari':'E_SIMPLE_PLACE'},{'typePari':'E_COUPLE_ORDRE'}])
        ps = [{'numPmu': p['num_partant'], 'nom':p['nom_cheval'], 'statut':'PARTANT'} for p in hs]
        payload = [{'typePari':'E_SIMPLE_PLACE','rapports':[{'combinaison':'6','dividendePourUnEuro':980}]}]
        message, audit = tracking.bilan([record],'20261011',lambda path:payload if 'rapports' in path else {'participants':ps} if path.endswith('participants') else meta)
        self.assertEqual(audit[1]['statut'],'NON_PROPOSE')
        self.assertIn('mises 5.00 EUR',message)
        self.assertIn('Paris non proposes exclus des mises : 1',message)


class SourceTests(TestCase):
    def test_course_link_uses_title_not_clock_and_distance_text(self):
        html = (Path(__file__).parent/'tests/fixtures/canalturf-selection.html').read_text()
        url = 'https://www.canalturf.com/pronostics-PMU/2026-10-12/marseille-borely/420324_prix-jean-claude-napoli.html'
        index = f'<a href="{url}">1 12:00 <strong>PRIX JEAN-CLAUDE NAPOLI</strong> PLAT 1200m 6</a>'
        ps = [dict(num=n,nom=name) for n,name in [(1,'AZAMRA'),(2,'LA BELLE ISOLA'),(3,'LUDWIG DER ZWEITE'),(4,'MORNING DEW'),(5,'LA BARAKA')]]
        with patch.object(presse, 'http_get', side_effect=[index,html]):
            result = presse.scrape_canalturf('2026-10-12',1,1,ps,nom_course='PRIX JEAN-CLAUDE NAPOLI')
        self.assertEqual(result.rangs['MORNING DEW'],1)

    def test_exact_selection_ignores_partants_table_and_other_race(self):
        html = (Path(__file__).parent/'tests/fixtures/canalturf-selection.html').read_text()
        ps = [dict(num=n,nom=name) for n,name in [(1,'AZAMRA'),(2,'LA BELLE ISOLA'),(3,'LUDWIG DER ZWEITE'),(4,'MORNING DEW'),(5,'LA BARAKA')]]
        result = presse.selection_canalturf(html, 1, 1, 'PRIX JEAN-CLAUDE NAPOLI', ps)
        self.assertEqual(result, {'MORNING DEW':1,'LA BARAKA':2,'AZAMRA':3,'LA BELLE ISOLA':4})
        self.assertEqual(presse.selection_canalturf(html, 1, 2, 'PRIX JEAN-CLAUDE NAPOLI', ps), {})
        self.assertEqual(presse.selection_canalturf(html, 1, 1, 'AUTRE PRIX', ps), {})
        self.assertEqual(presse.selection_canalturf(html.replace('MORNING DEW','AUTRE CHEVAL'), 1, 1, 'PRIX JEAN-CLAUDE NAPOLI', ps), {})

    def test_one_source_never_becomes_five_citations(self):
        source = presse.ResultatSource('canalturf',20,{'A':1,'B':2})
        with patch.object(presse, 'scrape_canalturf', return_value=source):
            result = presse.get_pronostics_gratuit('2026-10-12',1,1,'TEST',[{'nom':'A','num':1}])
        self.assertEqual(result['citations']['A'],1)
        with patch.object(scorer, 'get_pronostics_gratuit', return_value=result):
            parsed = scorer.get_pronostics_externes('2026-10-12',1,1,'TEST',[{'nom':'A','numPmu':1}], 'PLAT')
        self.assertEqual(parsed['citations']['A'],1)
        self.assertEqual(parsed['nb_sources'],1)

    def test_missing_citation_evidence_is_not_reconstructed_from_score(self):
        with patch.object(scorer, 'get_pronostics_gratuit', return_value={'scores':{'A':100},'nb_sources':1}):
            result = scorer.get_pronostics_externes('2026-10-12',1,1,'TEST',[{'nom':'A','numPmu':1}], 'PLAT')
        self.assertEqual(result['citations'], {})
