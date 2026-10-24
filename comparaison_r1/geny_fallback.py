"""Genybet is a transport fallback for the single Geny editorial vote."""
from datetime import datetime
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from .sources import INDEX,locate,parse,text,title_key,horse_name

def parse_genybet(body,url,race,horses):
    s=BeautifulSoup(body,'html.parser');crumb=s.select_one('.breadcrumb')
    day=datetime.fromisoformat(race['date']).strftime('%d-%m-%Y')
    if not crumb or not crumb.find('a',href='/reunions/'+day+'#R1'):
        raise ValueError('Date/R1 Genybet non concordante')
    label=text(crumb.find_all('a')[-1]);m=re.fullmatch(r'C(\d+)\s*-\s*(.+)',label)
    if not m or int(m[1])!=race['c'] or title_key(m[2])!=title_key(race['title']):
        raise ValueError('Course/titre Genybet non concordant')
    labels=[x for x in s.select('.page-separator') if text(x)=='Pronostic de Geny']
    blocks=[x.find_next('div',class_='pronostic') for x in labels]
    blocks=[x for x in blocks if x is not None and x.select_one('.pronostic-chevaux')]
    if len(blocks)!=1:raise ValueError('Rubrique éditoriale Geny absente ou ambiguë')
    heads=[h for h in blocks[0].find_all('th') if text(h)=='Préférés']
    if len(heads)!=1:raise ValueError('Classement Geny ambigu')
    row=heads[0].find_parent('table').select_one('tbody tr')
    number=text(row.select_one('.race_number')) if row else ''
    name=text(row.select_one('.horse_name a')) if row else ''
    if not number.isdigit():raise ValueError('Premier choix Geny absent')
    n=int(number);h=next((h for h in horses if h['numPmu']==n),None)
    if not h or horse_name(name)!=horse_name(h['nom']):raise ValueError('Identité PMU Genybet incorrecte')
    return {'site':'geny','number':n,'name':h['nom'],'source_url':url,'source_host':'genybet.fr',
            'fallback':True,'definition':'Premier Préféré du Pronostic de Geny sur Genybet (secours)',
            'identity_check':'date_rc_title_number_name','source_title':m[2]}

def read_tip(site,f,race,horses):
    try:
        u=locate(site,f.get(INDEX[site].format(date=race['date'])),race)
        body=f.get(u);tip=parse(site,body,u,race,horses)
        return u,body,tip
    except (ValueError,KeyError,TypeError,requests.RequestException) as error:
        if site!='geny':raise
        failure=type(error).__name__+': '+str(error).split('\n')[0][:160]
    day=datetime.fromisoformat(race['date']).strftime('%d-%m-%Y')
    index='https://www.genybet.fr/reunions/'+day
    soup=BeautifulSoup(f.get(index),'html.parser');ids=set()
    for a in soup.find_all('a',href=True):
        m=re.fullmatch(r'/courses/(?:resultats|partants-pronostics)/(\d+)',a['href'])
        if m and title_key(text(a))==title_key(race['title']):ids.add(m[1])
    if len(ids)!=1:raise ValueError('Course Genybet absente ou ambiguë')
    u='https://www.genybet.fr/courses/partants-pronostics/'+ids.pop()
    body=f.get(u);tip=parse_genybet(body,u,race,horses)
    tip['primary_failure']=failure
    return u,body,tip
