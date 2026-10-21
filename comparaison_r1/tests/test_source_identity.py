import gzip
import json
from pathlib import Path
from unittest import TestCase
from comparaison_r1.sources import parse, locate, horse_name

F=Path(__file__).parent/'fixtures'

class IdentityTests(TestCase):
    def test_country_suffix_is_optional_but_number_and_name_are_not(self):
        race={'date':'2026-10-21','c':1,'title':'TEST'}
        body='<h1>TEST</h1><p>Réunion 1 Course 1</p><div id="tab-prono-zt"><h3>La sélection</h3><table><tr><td>10</td><td>FREEDOM</td></tr></table></div>'
        url='https://www.canalturf.com/pronostics-PMU/2026-10-21/test.html'
        tip=parse('zeturf',body,url,race,[{'numPmu':10,'nom':'FREEDOM (NOR)'}])
        self.assertEqual(tip['name'],'FREEDOM (NOR)')
        for h in ({'numPmu':11,'nom':'FREEDOM (NOR)'},{'numPmu':10,'nom':'FREE WORLD (NOR)'}):
            with self.assertRaises(ValueError):parse('zeturf',body,url,race,[h])
        self.assertNotEqual(horse_name('FREEDOM (II)'),horse_name('FREEDOM'))

    def test_index_uses_date_meeting_and_course_even_when_title_is_abbreviated(self):
        race={'date':'2026-10-21','c':6,'title':'ABBREVIATED'}
        def panel(r,c,day='2026-10-21',suffix='one'):
            return f'<div class="panel"><h2 class="panel-title">Réunion {r} - TOULOUSE</h2><a href="/pronostics-PMU/{day}/{suffix}.html"><span class="badge">{c}</span><strong>OTHER TITLE</strong></a></div>'
        html=panel(2,6)+panel(1,5)+panel(1,6,'2026-10-20')+panel(1,6)
        self.assertTrue(locate('canalturf',html,race).endswith('/2026-10-21/one.html'))
        with self.assertRaises(ValueError):locate('canalturf',html+panel(1,6,suffix='two'),race)
        with self.assertRaises(ValueError):locate('canalturf',panel(11,6),race)

    def test_alternative_title_requires_entire_numbered_field(self):
        horses=json.loads((F/'participants.json').read_text())
        for site in ('canalturf','zeturf','geny'):
            source='canalturf' if site=='zeturf' else site
            body=gzip.decompress((F/(source+'.html.gz')).read_bytes()).decode()
            url=f'https://example.test/2026-10-15/{site}'
            race={'date':'2026-10-15','c':4,'title':'ABBREVIATED OFFICIAL TITLE'}
            tip=parse(site,body,url,race,horses)
            self.assertEqual(tip['number'],5)
            self.assertEqual(tip['identity_check'],'date_rc_full_numbered_field')
            changed=[dict(h) for h in horses]
            next(h for h in changed if h['numPmu']!=5)['nom']='WRONG HORSE'
            with self.assertRaises(ValueError):parse(site,body,url,race,changed)
            with self.assertRaises(ValueError):parse(site,body,url,{**race,'c':5},horses)
