"""Five editorial votes. Genybet remains a fallback, never a sixth vote."""
from datetime import date
import re
from urllib.parse import urljoin, urldefrag, urlparse
from bs4 import BeautifulSoup
from comparaison_r1.sources import INDEX, locate, parse, norm, text
from comparaison_r1.geny_fallback import read_tip as read_existing

SITES=('turfin','canalturf','zeturf','geny','zone_turf')
DAYS=('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')
MONTHS=('janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre')
BASE='https://www.zone-turf.fr'

def slug(day):
    d=date.fromisoformat(day)
    return f'{DAYS[d.weekday()]}-{d.day}-{MONTHS[d.month-1]}-{d.year}'

def horse_key(name):
    return norm(re.sub(r'\s*\((?:AR|AQ|IR|FR|GB|IRE|GER|USA|CAN|SWE|NOR|DEN|FIN|ITY|ITA|SPA|BEL|HOL|NLD|AUT|SWI|NZ|AUS|JPN)\)\s*$','',str(name),flags=re.I))

def course_block(body,race):
    soup=BeautifulSoup(body,'html.parser');d=date.fromisoformat(race['date'])
    if norm(f'{d.day} {MONTHS[d.month-1]} {d.year}') not in norm(text(soup)):
        raise ValueError('Date Zone-Turf non concordante')
    blocks=[b for b in soup.select('.bloc.course') if b.select_one('.nomCourse') and re.search(r'R1\s+Course\s+N°\s*'+str(race['c'])+r'(?!\d)',text(b.select_one('.nomCourse')))]
    if len(blocks)!=1:raise ValueError('Course R1 Zone-Turf absente ou ambiguë')
    return blocks[0]

def parse_zone(body,url,race,horses):
    if urlparse(url).netloc!='www.zone-turf.fr':raise ValueError('Hôte Zone-Turf inattendu')
    block=course_block(body,race);fields={}
    for row in block.select('table.engages tr'):
        cells=row.find_all('td',recursive=False);a=row.select_one('.infosGen a[title]')
        if cells and text(cells[0]).isdigit() and a:
            n=int(text(cells[0]));name=horse_key(a['title'])
            if n in fields and fields[n]!=name:raise ValueError('Partants Zone-Turf ambigus')
            fields[n]=name
    expected={h['numPmu']:horse_key(h['nom']) for h in horses}
    required={h['numPmu']:horse_key(h['nom']) for h in horses if h.get('statut')!='NON_PARTANT'}
    if len(required)<2 or not required.items()<=fields.items()<=expected.items():
        raise ValueError('Liste complète des partants Zone-Turf non concordante')
    selections=set()
    for cell in block.select('td.forecaster-name'):
        if text(cell)!='Zone-Turf.fr':continue
        values=[text(x) for x in cell.parent.select('td.number')]
        while values and not values[-1]:values.pop()
        if values and all(v.isdigit() and int(v)>0 for v in values):selections.add(tuple(map(int,values)))
    if len(selections)!=1:raise ValueError('Sélection éditoriale Zone-Turf absente ou ambiguë')
    selection=selections.pop();n=selection[0]
    if len(set(selection))!=len(selection) or any(x not in expected for x in selection):raise ValueError('Numéros Zone-Turf invalides')
    h=next(h for h in horses if h['numPmu']==n)
    return {'site':'zone_turf','number':n,'name':h['nom'],'source_url':url,
            'definition':'Premier cheval de la sélection éditoriale Zone-Turf.fr (hors Top chances)',
            'identity_check':'date_rc_full_numbered_field','source_title':text(block.select_one('.nomCourse'))}

def read_tip(site,f,race,horses):
    if site!='zone_turf':return read_existing(site,f,race,horses)
    index=BASE+'/rapports/'+slug(race['date'])+'/'
    soup=BeautifulSoup(f.get(index),'html.parser')
    urls={BASE+a['href'].replace('/rapports/','/programmes/') for a in soup.find_all('a',href=True)
          if re.fullmatch(r'/rapports/r1-(?!c\d+-)[a-z0-9-]+-\d+\.html',a['href'])}
    if len(urls)!=1:raise ValueError('Réunion 1 Zone-Turf absente ou ambiguë')
    url=urls.pop();body=f.get(url);block=course_block(body,race)
    links={urldefrag(urljoin(url,a['href']))[0] for a in block.find_all('a',href=True)
           if ('/quinte/' in a['href'] or '/pick5/' in a['href']) and '#pronostics' in a['href']}
    if links:
        if len(links)!=1:raise ValueError('Page spécialisée Zone-Turf ambiguë')
        url=links.pop()
        if urlparse(url).netloc!='www.zone-turf.fr' or slug(race['date']) not in url:raise ValueError('Lien Zone-Turf non concordant')
        body=f.get(url)
    return url,body,parse_zone(body,url,race,horses)
