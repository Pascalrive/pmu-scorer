import json
import unittest
from comparaison_r1.sources import parse


class GenyPayload(unittest.TestCase):
    def page(self, number=13, name='Nancy des Places'):
        data = {'comment': 'Quatrième place (dead-heat avec [Five Lands (5)]).',
                'geny': {'metaData': {'listeBase': [{'numero': number, 'nomCheval': name}]}}}
        payload = json.dumps([1, json.dumps(data)])
        return '<h1>Prix de l’Elevage</h1><p>R1C5</p><script>self.__next_f.push(' + payload + ')</script>'

    def test_comment_delimiter_does_not_truncate_json(self):
        race = {'date': '2026-10-25', 'c': 5, 'title': 'PRIX DE L’ELEVAGE'}
        url = 'https://www.geny.com/course/1693862-2026-10-25-saint-cloud/partants-pronostics'
        horses = [{'numPmu': 13, 'nom': 'NANCY DES PLACES'}]
        tip = parse('geny', self.page(), url, race, horses)
        self.assertEqual(tip['number'], 13)
        with self.assertRaises(ValueError):
            parse('geny', self.page(name='Other Horse'), url, race, horses)
        with self.assertRaises(ValueError):
            parse('geny', self.page(), url, {**race, 'c': 6}, horses)
