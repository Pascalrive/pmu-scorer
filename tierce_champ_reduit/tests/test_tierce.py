import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from tierce_champ_reduit.model import ARMS, confirmed, prepare, settle, tickets, totals
from tierce_champ_reduit.run import deliver

NOW = datetime(2026, 11, 19, 12, 30, tzinfo=timezone.utc)


def snapshot():
    horses = {n: {'nom': f'CHEVAL {n}', 'numPmu': n, 'statut': 'PARTANT',
                  'pmu_odds': {'value': n+1., 'kind': 'direct', 'official_time': int(NOW.timestamp()*1000)}}
              for n in range(1, 13)}
    rows = []
    for i, top in enumerate(([1,2,3,4,5], [1,2,3,4,6], [1,2,3,4,7], [1,2,3,6,7], [1,2,5,6,7])):
        rows.append({'publisher': f'source{i}', 'top5': top, 'url': 'https://example.org/source',
                     'sha256': 'verified', 'retrieved_at': NOW.isoformat(),
                     'outsiders': [{'number': 11}, {'number': 12}]})
    return {'captured_at': NOW.isoformat(), 'rows': rows, 'race': {
        'id': 'R1C1', 'r': 1, 'c': 1, 'date': '2026-11-19', 'title': 'TEST',
        'departure': (NOW+timedelta(minutes=30)).isoformat(), 'horses': horses,
        'internet_tierce_available': True, 'odds_captured_at': NOW.isoformat()}}


def record():
    s = snapshot()
    r = {'selection': prepare(s, NOW)[0], 'race': s['race'], 'frozen_at': NOW.isoformat(),
         'send_started_at': NOW.isoformat(), 'sent_at': NOW.isoformat(), 'delivery': 'SENT',
         'receipt': {'message_id': 10, 'date': int(NOW.timestamp())}}
    return r


def official(podium=(1, 2, 3)):
    return {'course': {'arriveeDefinitive': True, 'ordreArrivee': [[n] for n in podium]},
            'participants': {'participants': [{'numPmu': n, 'statut': 'PARTANT'} for n in range(1,13)]},
            'reports': [{'typePari': 'E_TIERCE', 'miseBase': 100, 'rembourse': False,
                         'rapports': [{'rangCombinaisonPayable': 1, 'combinaison': list(podium), 'dividendePourUnEuro': 20000},
                                      {'rangCombinaisonPayable': 2, 'combinaison': list(podium), 'dividendePourUnEuro': 3000}]}]}


class SelectionTests(unittest.TestCase):
    def test_fixed_costs_and_positions(self):
        a, b = prepare(snapshot(), NOW)
        self.assertEqual((a['stake_cents'], b['stake_cents']), (3000, 5600))
        self.assertEqual(len({tuple(t) for t in b['tickets']}), 56)
        self.assertTrue(all(t[0] == 1 and len(set(t)) == 3 for t in b['tickets']))

    def test_market_favourite_not_editorial_first(self):
        s = snapshot(); s['race']['horses'][8]['pmu_odds']['value'] = 1.1
        self.assertEqual(prepare(s, NOW)[0]['base'], 8)

    def test_missing_direct_odds_abstains(self):
        s = snapshot(); s['race']['horses'][12]['pmu_odds']['kind'] = 'reference'
        with self.assertRaises(ValueError): prepare(s, NOW)

    def test_old_pmu_timestamp_abstains(self):
        s = snapshot(); s['race']['horses'][1]['pmu_odds']['official_time'] -= 901000
        with self.assertRaises(ValueError): prepare(s, NOW)

    def test_duplicate_publisher_not_extra_vote(self):
        s = snapshot(); s['rows'][-1]['publisher'] = 'source0'
        with self.assertRaises(ValueError): prepare(s, NOW)

    def test_incomplete_variant_does_not_block_other(self):
        s = snapshot()
        for row in s['rows']: row['outsiders'] = [{'number': 7}, {'number': 12}]
        a, b = prepare(s, NOW)
        self.assertEqual(a['stake_cents'], 3000)
        self.assertEqual(b['stake_cents'], 0)
        self.assertTrue(b['reason'])

    def test_no_outsiders_no_invented_complement(self):
        s = snapshot()
        for row in s['rows']: row['outsiders'] = []
        self.assertTrue(all(not x['tickets'] for x in prepare(s, NOW)))

    def test_after_start_and_wrong_date_rejected(self):
        for later in [NOW+timedelta(minutes=30), NOW+timedelta(days=1)]:
            with self.assertRaises(ValueError): prepare(snapshot(), later)

    def test_market_absent(self):
        s = snapshot(); s['race']['internet_tierce_available'] = False
        with self.assertRaises(ValueError): prepare(s, NOW)


class SettlementTests(unittest.TestCase):
    def test_base_wins_one_ordre_one_desordre(self):
        result = settle(record(), official())
        self.assertEqual(result['returns_cents'], 23000)
        self.assertEqual(result['net_cents'], 20000)
        self.assertEqual((result['winning_tickets'], result['losing_tickets']), (2, 28))

    def test_base_second_two_desordre(self):
        result = settle(record(), official((2,1,3)))
        self.assertEqual(result['returns_cents'], 6000)
        self.assertEqual(result['net_cents'], 3000)

    def test_base_off_podium_loses_after_official(self):
        result = settle(record(), official((2,3,4)))
        self.assertEqual(result['net_cents'], -3000)
        self.assertEqual(result['losing_tickets'], 30)

    def test_missing_results_not_loss(self):
        self.assertEqual(settle(record(), {})['status'], 'EN_ATTENTE')

    def test_provisional_arrival_waits(self):
        o = official(); o['course']['arriveeDefinitive'] = False
        self.assertEqual(settle(record(), o)['status'], 'EN_ATTENTE')

    def test_np_waits_for_special_settlement(self):
        o = official(); o['participants']['participants'][0]['statut'] = 'NON_PARTANT'
        self.assertEqual(settle(record(), o)['status'], 'EN_ATTENTE')

    def test_dead_heat_waits(self):
        o = official(); o['course']['ordreArrivee'][0].append(4)
        self.assertEqual(settle(record(), o)['status'], 'EN_ATTENTE')

    def test_refund(self):
        o = official(); o['reports'][0]['rembourse'] = True
        result = settle(record(), o)
        self.assertEqual((result['returns_cents'], result['net_cents']), (3000, 0))
        self.assertEqual(result['refunded_tickets'], 30)

    def test_no_receipt_no_stake(self):
        r = record(); r['delivery'] = 'UNCERTAIN'
        self.assertEqual(settle(r, official())['status'], 'NON_COMPTABILISE')
        self.assertEqual(totals([r], r['selection']['id'])['engaged_cents'], 0)

    def test_late_receipt_and_late_response_rejected(self):
        for field in ('receipt', 'sent_at', 'frozen_at'):
            r = record()
            if field == 'receipt': r[field]['date'] += 1800
            else: r[field] = r['race']['departure']
            self.assertFalse(confirmed(r))

    def test_pending_excluded_from_roi(self):
        r = record(); p = copy.deepcopy(r)
        r['result'] = settle(r, official())
        p['result'] = {'status': 'EN_ATTENTE'}
        result = totals([r, p], r['selection']['id'])
        self.assertEqual((result['stake_cents'], result['engaged_cents'], result['pending']), (3000, 6000, 1))
        self.assertEqual(result['roi_percent'], 666.67)


class DeliveryTests(unittest.TestCase):
    def fresh(self):
        r = record()
        for k in ('delivery', 'receipt', 'send_started_at', 'sent_at'): r.pop(k)
        return r

    def test_pending_saved_before_send_and_no_duplicate(self):
        r = self.fresh(); observed = []
        def save(): observed.append(r['delivery'])
        def send(text):
            self.assertEqual(observed, ['PENDING'])
            return {'message_id': 42, 'date': int(NOW.timestamp())}
        sender = Mock(side_effect=send)
        deliver(r, save, sender, lambda: NOW)
        deliver(r, save, sender, lambda: NOW)
        self.assertEqual(sender.call_count, 1)
        self.assertTrue(confirmed(r))

    def test_timeout_not_resent(self):
        r = self.fresh(); sender = Mock(side_effect=TimeoutError())
        deliver(r, lambda: None, sender, lambda: NOW)
        deliver(r, lambda: None, sender, lambda: NOW)
        self.assertEqual(r['delivery'], 'UNCERTAIN')
        self.assertEqual(sender.call_count, 1)

    def test_archive_failure_prevents_message(self):
        r = self.fresh(); sender = Mock()
        with self.assertRaises(RuntimeError):
            deliver(r, Mock(side_effect=RuntimeError('archive')), sender, lambda: NOW)
        sender.assert_not_called()

    def test_cutoff_prevents_send(self):
        r = self.fresh(); sender = Mock()
        deliver(r, lambda: None, sender, lambda: NOW+timedelta(minutes=29))
        sender.assert_not_called()


if __name__ == '__main__':
    unittest.main()
