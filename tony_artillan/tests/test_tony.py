from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import requests

from tony_artillan import model as m
from tony_artillan import telegram as t
from tony_artillan.main import run

TZ = ZoneInfo('Europe/Paris')
NOW = datetime(2026,10,15,13,0,tzinfo=TZ)
START = NOW+timedelta(hours=1)


def meeting(r=1):
    return {'numOfficiel':r,'pays':{'code':'FRA'},'hippodrome':{'libelleLong':'CHANTILLY'},
            'courses':[{'numReunion':r,'numOrdre':i,'libelle':f'PRIX {i}',
                        'heureDepart':int((START+timedelta(minutes=35*(i-1))).timestamp()*1000),
                        'paris':[{'typePari':'E_SIMPLE_GAGNANT'}]} for i in range(1,9)]}


def document():
    return {'publisher':'Paris Turf','date':'2026-10-15','r':1,
            'source_url':'https://www.paris-turf.com/source-test', 'captured_at':NOW.isoformat(),
            'races':[{'c':i,'title':f'PRIX {i}','number':2,'name':'CHEVAL TEST'} for i in range(1,9)]}


def horse(**kwargs):
    return {'numPmu':2,'nom':'CHEVAL TEST','statut':'PARTANT', **kwargs}


def state():
    s = m.new_day('2026-10-15',meeting(),NOW)
    tips = m.validate_tips(document(),s,{i:[horse()] for i in range(1,9)},NOW)
    for race in s['races']:
        race['selection'] = tips[race['c']]
    s['source_status'] = 'VERIFIEE'
    return s


def reports(won=True, rate=300):
    return [{'typePari':'E_SIMPLE_GAGNANT','rapports':[
        {'combinaison':'2' if won else '3','dividendePourUnEuro':rate}]}]


class MathTests(unittest.TestCase):
    def test_eight_losses_require_3600_and_max_800(self):
        s = state()
        stakes = []
        for i,race in enumerate(s['races']):
            start = m.stamp(race['departure'])
            self.assertTrue(m.reserve(s['races'],i,start-timedelta(minutes=5),horse()))
            stakes.append(race['stake_cents'])
            self.assertTrue(m.settle(race,reports(False),[horse(ordreArrivee=3)],start+timedelta(minutes=5),'official'))
        self.assertEqual(stakes,[10000,20000,30000,40000,50000,60000,70000,80000])
        score = m.score(s)
        self.assertEqual((score['stake_cents'],score['profit_cents'],score['cash_required_cents'],score['max_stake_cents']),
                         (360000,-360000,360000,80000))
        self.assertEqual(score['roi_percent'],'-100.00')
        self.assertTrue(score['complete'])

    def test_win_resets_even_if_prior_losses_not_recovered(self):
        s = state()
        for i,won in enumerate([False,False,True]):
            race = s['races'][i];start=m.stamp(race['departure'])
            m.reserve(s['races'],i,start-timedelta(minutes=5),horse())
            m.settle(race,reports(won,110),[horse()],start+timedelta(minutes=5),'official')
        self.assertEqual(m.score(s)['profit_cents'],-27000)
        self.assertEqual(m.next_stake(s['races'],3),10000)

    def test_waits_for_preceding_official_result(self):
        s = state()
        self.assertTrue(m.reserve(s['races'],0,START-timedelta(minutes=5),horse()))
        self.assertFalse(m.reserve(s['races'],1,START+timedelta(minutes=30),horse()))
        self.assertIsNone(m.next_stake(s['races'],1))
        self.assertFalse(m.score(s)['complete'])

    def test_stake_cannot_change_after_reservation(self):
        s=state();m.reserve(s['races'],0,NOW,horse())
        self.assertFalse(m.reserve(s['races'],0,NOW+timedelta(minutes=1),horse()))
        self.assertEqual(s['races'][0]['reserved_at'],NOW.isoformat())

    def test_no_reservation_at_or_after_departure(self):
        s=state()
        self.assertFalse(m.reserve(s['races'],0,START,horse()))

    def test_unknown_market_and_non_runner_not_substituted(self):
        for candidate in [None,horse(statut='NON_PARTANT'),horse(nom='AUTRE')]:
            self.assertFalse(m.reserve(state()['races'],0,NOW,candidate))
        s=state();s['races'][0]['market']=False
        self.assertFalse(m.reserve(s['races'],0,NOW,horse()))

    def test_return_is_gross_official_dividend_not_odds(self):
        s=state();r=s['races'][0]
        m.reserve(s['races'],0,NOW,horse(dernierRapportDirect={'rapport':99}))
        m.settle(r,reports(True,230),[horse()],START+timedelta(minutes=5),'official')
        self.assertEqual((r['return_cents'],r['profit_cents']),(23000,13000))
        self.assertEqual(m.next_stake(s['races'],1),10000)

    def test_refund_does_not_reset_loss_sequence(self):
        s=state();r1,r2=s['races'][:2]
        m.reserve(s['races'],0,NOW,horse())
        m.settle(r1,reports(False),[horse()],START+timedelta(minutes=5),'official')
        start=m.stamp(r2['departure'])
        m.reserve(s['races'],1,start-timedelta(minutes=5),horse())
        m.settle(r2,reports(),[horse(statut='NON_PARTANT')],start+timedelta(minutes=5),'official')
        self.assertEqual(r2['return_cents'],20000)
        self.assertEqual(m.next_stake(s['races'],2),20000)

    def test_missing_or_wrong_dividend_units_stay_pending(self):
        for data in [[],reports(True,0),reports(True,-1),reports(True,'NaN'),
                     [{'typePari':'E_SIMPLE_GAGNANT','rapports':[{'combinaison':'2','dividende':230}]}],
                     [{'typePari':'SIMPLE_GAGNANT','rapports':[{'combinaison':'2','dividendePourUnEuro':230}]}]]:
            s=state();race=s['races'][0];m.reserve(s['races'],0,NOW,horse())
            self.assertFalse(m.settle(race,data,[horse()],START+timedelta(minutes=5),'official'))
            self.assertEqual(race['status'],'ENGAGE_VIRTUEL')

    def test_no_double_settlement_or_pre_race_settlement(self):
        s=state();race=s['races'][0];m.reserve(s['races'],0,NOW,horse())
        self.assertFalse(m.settle(race,reports(),[horse()],NOW,'official'))
        self.assertTrue(m.settle(race,reports(),[horse()],START,'official'))
        self.assertFalse(m.settle(race,reports(),[horse()],START,'official'))

    def test_new_day_resets_stake(self):
        self.assertEqual(m.next_stake(m.new_day('2026-10-15',meeting(),NOW)['races'],0),10000)


class SourceTests(unittest.TestCase):
    def test_principal_meeting_preferred_and_ambiguous_fallback_refused(self):
        p={'programme':{'reunions':[meeting(3),meeting(1)]}}
        self.assertEqual(m.choose_meeting(p)['numOfficiel'],1)
        p['programme']['reunions']=[meeting(3),meeting(4)]
        self.assertRaises(ValueError,m.choose_meeting,p)
        p['programme']['reunions']=[meeting(3)]
        self.assertEqual(m.choose_meeting(p)['numOfficiel'],3)

    def test_all_eight_true_first_choices_required_before_c1(self):
        s=m.new_day('2026-10-15',meeting(),NOW);ps={i:[horse()] for i in range(1,9)}
        for key,value in [('date','2026-10-14'),('publisher','Geny'),('r',3),('captured_at',(NOW+timedelta(hours=1)).isoformat())]:
            d=document();d[key]=value
            self.assertRaises(ValueError,m.validate_tips,d,s,ps,NOW)
        d=document();d['races'].pop()
        self.assertRaises(ValueError,m.validate_tips,d,s,ps,NOW)
        self.assertRaises(ValueError,m.validate_tips,document(),s,ps,START)

    def test_runner_and_course_identities_cannot_be_guessed(self):
        s=m.new_day('2026-10-15',meeting(),NOW);ps={i:[horse()] for i in range(1,9)}
        for key,value in [('title','AUTRE PRIX'),('number',8),('name','AUTRE CHEVAL')]:
            d=document();d['races'][0][key]=value
            self.assertRaises(ValueError,m.validate_tips,d,s,ps,NOW)


class TelegramTests(unittest.TestCase):
    def test_dedup_and_confirmed_receipt(self):
        s=state();calls=[]
        class Response:
            status_code=200
            def json(self):return {'ok':True,'result':{'message_id':99,'date':int(NOW.timestamp())}}
        def post(*a,**k):calls.append(1);return Response()
        text=t.report(s)
        self.assertTrue(t.send(s,text,'secret','chat',lambda:None,NOW,post))
        self.assertFalse(t.send(s,text,'secret','chat',lambda:None,NOW,post))
        self.assertEqual(len(calls),len(t.chunks(text)))
        self.assertEqual(s['notifications'][0]['status'],'SENT')
        self.assertNotIn('secret',json.dumps(s['notifications']))

    def test_timeout_is_uncertain_and_not_sent_again(self):
        s=state()
        def post(*a,**k):raise requests.Timeout()
        self.assertFalse(t.send(s,'test','secret','chat',lambda:None,NOW,post))
        self.assertEqual(s['notifications'][0]['status'],'UNCERTAIN')
        self.assertFalse(t.send(s,'test','secret','chat',lambda:None,NOW,lambda *a,**k:self.fail('no resend')))

    def test_blocked_source_report_never_invents_horse_or_score(self):
        s=m.new_day('2026-10-15',meeting(),NOW);message=t.report(s)
        self.assertIn('aucun pari virtuel engagé',message)
        self.assertIn('aucun pari réglé',message)
        self.assertNotIn('ROI final',message)
        self.assertEqual(m.score(s)['stake_cents'],0)


class IntegrationTests(unittest.TestCase):
    def test_missing_source_creates_report_with_zero_bets(self):
        class Fetcher:
            def __init__(self,*a):pass
            def get(self,url):return {'programme':{'reunions':[meeting()]}}
        with tempfile.TemporaryDirectory() as tmp:
            run(now=NOW,root=Path(tmp),notify=False,fetcher_factory=Fetcher)
            s=json.loads((Path(tmp)/'data/2026-10-15/state.json').read_text())
            self.assertEqual(s['source_status'],'EN_ATTENTE_PARIS_TURF')
            self.assertTrue(all('stake_cents' not in r for r in s['races']))
            self.assertTrue((Path(tmp)/'data/BILAN.json').exists())

    def test_import_reservation_settlement_and_next_stake(self):
        class Fetcher:
            def __init__(self,*a):pass
            def get(self,url):
                if url.endswith('/15102026'):return {'programme':{'reunions':[meeting()]}}
                if '/rapports-definitifs' in url:return reports(False)
                if url.endswith('/participants'):return {'participants':[horse()]}
                c=int(url.rsplit('/C',1)[1]);return meeting()['courses'][c-1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'inputs').mkdir();(root/'inputs/2026-10-15.json').write_text(json.dumps(document()))
            run(now=START-timedelta(minutes=20),root=root,notify=False,fetcher_factory=Fetcher)
            path=root/'data/2026-10-15/state.json';s=json.loads(path.read_text())
            self.assertEqual(s['races'][0]['stake_cents'],10000)
            self.assertNotIn('stake_cents',s['races'][1])
            run(now=START+timedelta(minutes=20),root=root,notify=False,fetcher_factory=Fetcher)
            s=json.loads(path.read_text())
            self.assertEqual(s['races'][0]['status'],'PERDU')
            self.assertEqual(s['races'][1]['stake_cents'],20000)
            # Une modification de l'import ne reecrit pas le choix fige.
            (root/'inputs/2026-10-15.json').write_text('{}')
            run(now=START+timedelta(minutes=21),root=root,notify=False,fetcher_factory=Fetcher)
            self.assertEqual(json.loads(path.read_text())['races'][0]['selection']['number'],2)
