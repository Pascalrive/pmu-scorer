import unittest
from unittest.mock import patch
import requests
from comparaison_r1.geny_fallback import parse_genybet,read_tip

HTML='''<div class="breadcrumb"><a href="/reunions/24-10-2026#R1">Compiègne</a><a>C3 - Prix de Beaune</a></div><div class="page-separator">Pronostic de Geny</div><div class="pronostic"><div class="pronostic-chevaux"><table><thead><tr><th>Préférés</th></tr></thead><tbody><tr><td class="race_number">8</td><td class="horse_name"><a>Lady Ange Win</a></td></tr></tbody></table></div></div>'''
R={'date':'2026-10-24','c':3,'title':'PRIX DE BEAUNE'}
H=[{'numPmu':8,'nom':'LADY ANGE WIN'}]
class Fake:
 def __init__(self):self.urls=[]
 def get(self,url):
  self.urls.append(url)
  if 'geny.com' in url:raise requests.ConnectionError('unavailable')
  if '/reunions/' in url:return '<a href="/courses/partants-pronostics/123">Prix de Beaune</a>'
  return HTML
class Fallback(unittest.TestCase):
 def test_primary_priority(self):
  f=Fake()
  with patch('comparaison_r1.geny_fallback.INDEX',{'geny':'https://primary/{date}'}),patch('comparaison_r1.geny_fallback.locate',return_value='https://primary/course'),patch('comparaison_r1.geny_fallback.parse',return_value={'site':'geny','number':2}):
   self.assertEqual(read_tip('geny',f,R,H)[2]['number'],2)
  self.assertFalse(any('genybet' in u for u in f.urls))
 def test_fallback_one_vote(self):
  t=read_tip('geny',Fake(),R,H)[2]
  self.assertEqual(t['site'],'geny');self.assertTrue(t['fallback']);self.assertEqual(t['number'],8)
  self.assertIn('ConnectionError',t['primary_failure'])
 def test_other_source_no_fallback(self):
  f=Fake()
  with patch('comparaison_r1.geny_fallback.locate',side_effect=ValueError('failed')):
   with self.assertRaises(ValueError):read_tip('canalturf',f,R,H)
  self.assertFalse(any('genybet' in u for u in f.urls))
 def test_wrong_identity_rejected(self):
  for old,new in [('24-10-2026','23-10-2026'),('#R1','#R2'),('C3 -','C4 -'),('Prix de Beaune','Prix autre'),('Lady Ange Win','Other Horse'),('Pronostic de Geny','Pronostic des joueurs'),('Préférés','Favoris des joueurs')]:
   with self.subTest(old=old),self.assertRaises(ValueError):parse_genybet(HTML.replace(old,new),'url',R,H)
 def test_ambiguous_index_rejected(self):
  f=Fake();f.get=lambda u:'<a href="/courses/partants-pronostics/123">Prix de Beaune</a><a href="/courses/partants-pronostics/124">Prix de Beaune</a>'
  with patch('comparaison_r1.geny_fallback.locate',side_effect=ValueError('failed')):
   with self.assertRaises(ValueError):read_tip('geny',f,R,H)


 def test_failed_backup_keeps_both_errors(self):
  from comparaison_r1.geny_fallback import GenyFallbackError
  f=Fake();original=f.get
  f.get=lambda u: HTML.split('<div class="page-separator">')[0] + '<div class="post-extra pronostic"><span class="horse">8</span></div>' if '/courses/' in u else original(u)
  with self.assertRaises(GenyFallbackError) as caught:read_tip('geny',f,R,H)
  self.assertTrue(caught.exception.source_status['fallback_attempted'])
  self.assertIn('ConnectionError',caught.exception.source_status['primary_failure'])
  self.assertIn('Rubrique éditoriale',caught.exception.source_status['fallback_failure'])
  self.assertTrue(any('genybet.fr/courses/' in u for u in f.urls) or any('genybet.fr/reunions/' in u for u in f.urls))
