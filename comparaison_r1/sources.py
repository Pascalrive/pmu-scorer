"""Read only publicly delivered HTML; fail closed on changed identity/markup."""
import json
import re
import unicodedata
from urllib.parse import urljoin
from bs4 import BeautifulSoup

SITES = ('turfin', 'canalturf', 'zeturf', 'geny')
INDEX = {'turfin':'https://turfin.fr/programme?date={date}',
         'canalturf':'https://www.canalturf.com/courses_liste_pronostics.php',
         'zeturf':'https://www.canalturf.com/courses_liste_pronostics.php',
         'geny':'https://www.geny.com/'}

def norm(v):
    return re.sub('[^A-Z0-9]', '', unicodedata.normalize('NFKD',str(v)).encode('ascii','ignore').decode().upper())

def text(el):
    return el.get_text(' ',strip=True) if el else ''

def locate(site, body, race):
    base = INDEX[site].format(date=race['date'])
    links = BeautifulSoup(body,'html.parser').find_all('a',href=True)
    choices = set()
    for a in links:
        u=urljoin(base,a['href'])
        if race['date'] not in u:
            continue
        if site in ('canalturf','zeturf'):
            ok='/pronostics-PMU/' in u and norm(text(a.find('strong')))==norm(race['title'])
        elif site=='turfin':
            ok=f'/course/{race["date"]}/r1c{race["c"]}-' in u
        else:
            ok='/partants-pronostics' in u and norm(race['title']) in norm(text(a)) and re.search(r'R1C'+str(race['c'])+r'(?!\d)',norm(text(a)))
        if ok:choices.add(u)
    if len(choices)!=1:raise ValueError('Course datée absente ou ambiguë dans l’index')
    return choices.pop()

def parse(site, body, url, race, horses):
    s=BeautifulSoup(body,'html.parser')
    if race['date'] not in url or norm(race['title']) not in norm(text(s.h1)):
        raise ValueError('Date ou titre non concordant')
    candidates=[];note=''
    if site in ('canalturf','zeturf'):
        if not re.search(r'REUNION1COURSE'+str(race['c'])+r'(?!\d)',norm(text(s.h1.find_next_sibling()))):
            raise ValueError('Réunion/course non concordante')
        block=s.select_one('#tab-prono-ct' if site=='canalturf' else '#tab-prono-zt')
        h=next((h for h in block.find_all('h3') if text(h).startswith('La sélection')),None) if block else None
        container=h.find_next_sibling() if h else None
        for row in container.select('tr') if container else []:
            cells=row.find_all('td')
            if len(cells)>=2 and text(cells[0]).isdigit():
                candidates=[(int(text(cells[0])),text(cells[1]))];break
        note='Sélection ZEturf publiée sur Canalturf' if site=='zeturf' else 'Premier cheval de la sélection Canalturf'
    elif site=='turfin':
        canonical=s.select_one('link[rel=canonical]')
        if not canonical or f'/course/{race["date"]}/r1c{race["c"]}-' not in canonical.get('href',''):
            raise ValueError('Course Turfin non concordante')
        for h in s.find_all('h3'):
            if text(h)=='Le cheval principal':
                b=h.parent.select_one('.princ')
                if b:candidates.append((int(text(b.select_one('.num'))),text(b.select_one('.nom a'))))
        note='Cheval principal Turfin ; classement systématique, même si le site conseille l’abstention'
    else:
        if not re.search(r'R1C'+str(race['c'])+r'(?!\d)',norm(text(s))):
            raise ValueError('Réunion/course Geny non concordante')
        # Public Next.js hydration contains the editorial "geny" object,
        # separate from individual journalists and the press consensus.
        decoder=json.JSONDecoder()
        for script in s.find_all('script'):
            for match in re.finditer(r'self\.__next_f\.push\((\[.*?\])\)',script.text):
                try:payload=json.loads(match[1])
                except ValueError:continue
                if len(payload)<2 or not isinstance(payload[1],str):continue
                for m in re.finditer(r'"geny"\s*:\s*',payload[1]):
                    obj,_=decoder.raw_decode(payload[1][m.end():])
                    if not isinstance(obj,dict):continue
                    rows=(obj.get('metaData') or {}).get('listeBase') or []
                    if rows:candidates.append((int(rows[0]['numero']),rows[0]['nomCheval']))
        note='Premier cheval de listeBase du pronostic éditorial Geny'
    candidates=set(candidates)
    if len(candidates)!=1:raise ValueError('Premier choix absent ou ambigu')
    n,name=candidates.pop()
    horse=next((h for h in horses if h['numPmu']==n),None)
    if horse is None or norm(name)!=norm(horse['nom']):raise ValueError('Numéro/nom PMU non concordant')
    return {'site':site,'number':n,'name':horse['nom'],'source_url':url,'definition':note}
