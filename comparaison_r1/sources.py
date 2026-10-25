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

def horse_name(value):
    # Only an explicit, trailing country-of-origin annotation is optional.
    value=re.sub(r'\s*\((?:FR|GB|IRE|GER|USA|CAN|SWE|NOR|DEN|FIN|ITY|ITA|SPA|BEL|HOL|NLD|AUT|SWI|NZ|AUS|JPN)\)\s*$', '', str(value), flags=re.I)
    return norm(value)

def title_key(value):
    value=re.sub(r'\bPX\b','PRIX',str(value),flags=re.I)
    value=re.sub(r'(\d+)\s*(?:ÈME|EME|E)\b',r'\1E',value,flags=re.I)
    return norm(value)

def same_field(rows,horses):
    """Alternative titles require the full numbered PMU field, not one pick."""
    expected={h['numPmu']:horse_name(h['nom']) for h in horses}
    required={h['numPmu']:horse_name(h['nom']) for h in horses
              if h.get('statut') not in ('NON_PARTANT','NONPARTANT')}
    actual={}
    for n,name in rows:
        name=horse_name(name)
        if n in actual and actual[n]!=name:return False
        actual[n]=name
    # Some sites replace the number of a declared non-runner with "NP".
    return len(required)>=2 and required.items()<=actual.items()<=expected.items()

def locate(site, body, race):
    base = INDEX[site].format(date=race['date'])
    links = BeautifulSoup(body,'html.parser').find_all('a',href=True)
    choices = set()
    for a in links:
        u=urljoin(base,a['href'])
        if race['date'] not in u:
            continue
        if site in ('canalturf','zeturf'):
            panel=a.find_parent('div',class_='panel')
            heading=panel.select_one('.panel-title') if panel else None
            rc=(re.search(r'REUNION1(?!\d)',norm(text(heading)))
                and text(a.select_one('.badge'))==str(race['c']))
            # Actual page R/C and PMU field are checked again by parse().
            ok='/pronostics-PMU/' in u and bool(rc)
        elif site=='turfin':
            ok=f'/course/{race["date"]}/r1c{race["c"]}-' in u
        else:
            ok='/partants-pronostics' in u and re.search(r'R1C'+str(race['c'])+r'(?!\d)',norm(text(a)))
        if ok:choices.add(u)
    if len(choices)!=1:raise ValueError('Course datée absente ou ambiguë dans l’index')
    return choices.pop()

def parse(site, body, url, race, horses):
    s=BeautifulSoup(body,'html.parser')
    if race['date'] not in url or s.h1 is None:
        raise ValueError('Date ou titre absent')
    title_matches=bool(title_key(race['title'])) and title_key(race['title']) in title_key(text(s.h1))
    candidates=[];note='';field=[]
    if site in ('canalturf','zeturf'):
        if not re.search(r'REUNION1COURSE'+str(race['c'])+r'(?!\d)',norm(text(s.h1.find_next_sibling()))):
            raise ValueError('Réunion/course non concordante')
        for row in s.select('#TablePartants tbody tr'):
            cells=row.find_all('td',recursive=False)
            if len(cells)>=2 and text(cells[0]).isdigit():
                name=text(cells[1].find('strong'))
                field.append((int(text(cells[0])),re.sub(r'\s*\([HMF]\d+\)\s*$','',name)))
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
            # Comments can contain "])" inside JSON strings. Let the JSON
            # decoder find the array boundary instead of a non-greedy regex.
            for match in re.finditer(r'self\.__next_f\.push\(\s*',script.text):
                try:payload,_=decoder.raw_decode(script.text[match.end():])
                except ValueError:continue
                if not isinstance(payload,list) or len(payload)<2 or not isinstance(payload[1],str):continue
                for m in re.finditer(r'"geny"\s*:\s*',payload[1]):
                    obj,_=decoder.raw_decode(payload[1][m.end():])
                    if not isinstance(obj,dict):continue
                    rows=(obj.get('metaData') or {}).get('listeBase') or []
                    if rows:candidates.append((int(rows[0]['numero']),rows[0]['nomCheval']))
                    for values in (obj.get('metaData') or {}).values():
                        if isinstance(values,list):
                            field.extend((int(r['numero']),r['nomCheval']) for r in values
                                         if isinstance(r,dict) and r.get('numero') is not None and r.get('nomCheval'))
        note='Premier cheval de listeBase du pronostic éditorial Geny'
    if not title_matches and not same_field(field,horses):
        raise ValueError('Titre différent et liste complète des partants non concordante')
    candidates=set(candidates)
    if len(candidates)!=1:raise ValueError('Premier choix absent ou ambigu')
    n,name=candidates.pop()
    horse=next((h for h in horses if h['numPmu']==n),None)
    if horse is None or horse_name(name)!=horse_name(horse['nom']):raise ValueError('Numéro/nom PMU non concordant')
    return {'site':site,'number':n,'name':horse['nom'],'source_url':url,'definition':note,
            'identity_check':'date_rc_title_number_name' if title_matches else 'date_rc_full_numbered_field',
            'source_title':text(s.h1)}

