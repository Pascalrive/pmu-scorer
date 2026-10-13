"""Independent public editorial consensus. No production scorer imports or bets."""
import argparse, csv, hashlib, html, json, re, unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from analyses import build_analyses

VERSION = 'consensus-v1-2026-10-12'
API = 'https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'
MONTHS = ['janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre']
DAYS = ['lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche']
SOURCES = {
 'canalturf': ('Canalturf', 'https://www.canalturf.com/courses_liste_pronostics.php'),
 'zeturf': ('ZEturf via Canalturf', 'https://www.canalturf.com/courses_liste_pronostics.php'),
 'zone': ('Zone-Turf', 'https://www.zone-turf.fr/quinte/'),
 'stats': ('Stats-Quinté', 'https://stats-quinte.com/pronostic-quinte-du-jour/'),
 'turfprono': ('Turf-Pronostics', 'https://www.turf-pronostics.com/pronostics-quinte-du-jour-pmu/'),
 'rue': ('Rue des Joueurs', 'https://www.ruedesjoueurs.com/pronostic-quinte.html'),
 'frequence': ('Fréquence Turf', 'https://frequence-turf.fr/'),
 'prono': ('Prono Turf Gratuit', 'https://prono-turf-gratuit.fr/pronostic-quinte-pmu/'),
}

def norm(v):
 return re.sub('[^A-Z0-9]', '', unicodedata.normalize('NFKD',str(v)).encode('ascii','ignore').decode().upper())
def french(d):
 return f'{d.day} {MONTHS[d.month-1]} {d.year}'
def slugdate(d):
 return f'{DAYS[d.weekday()]}-{d.day}-{MONTHS[d.month-1]}-{d.year}'
def text(e):
 return e.get_text(' ',strip=True) if e else ''
def numbers(e):
 return [int(x) for x in re.findall(r'(?<!\d)\d{1,2}(?!\d)',text(e))] if e else []
def unique(v):
 return list(dict.fromkeys(v))
def checked_name(n,name,race):
 if n not in race['horses'] or norm(name)!=norm(race['horses'][n]['nom']):
  raise ValueError(f'numéro/nom non concordant: {n} {name}')
 return n

def identified(s, key, race):
 """Require target date AND course title, scoped to actual article/hero, not related links."""
 d=date.fromisoformat(race['date'])
 if key in ('canalturf','zeturf'):
  h=s.find('h1');info=h.find_next_sibling() if h else None
  return norm(race['title']) in norm(text(h)) and re.search(fr'REUNION{race["r"]}COURSE{race["c"]}(?!\d)', norm(text(info))) is not None
 if key=='turfprono':
  inp=s.select_one('#tppmuDate')
  return bool(inp and inp.get('value')==race['date'] and f'R{race["r"]}C{race["c"]}' in text(s.select_one('#tppmuHeroTitle')) and norm(text(s.select_one('#tppmuHeroMeta')))==norm(race['title']))
 if key=='rue':
  h=s.find('h1');return norm(f'{d.day} {MONTHS[d.month-1]}') in norm(text(h)) and str(d.year) in str(s.find('time')) and norm(race['title'].split(' (')[0]) in norm(text(h)) and race['id'] in norm(text(h))
 if key in ('frequence','prono'):
  h=s.find('h1');content=s.select_one('.entry-content')
  return (norm(french(d)) in norm(text(h)) or norm(f'{d.day:02}/{d.month:02}/{d.year%100:02}') in norm(text(h))) and norm(race['title'].split(' (')[0]) in norm(text(content))
 if key=='stats':
  content=s.select_one('.entry-content') or s
  t=norm(text(content));return norm(french(d)) in t and norm(race['title']) in t and f'REUNION{race["r"]}COURSE{race["c"]}' in t
 if key=='zone':
  # Header precedes the runners, prediction and unrelated articles.
  t=norm(text(s).split('Tous les avis sur les partants')[0])
  return norm(french(d)) in t and norm(race['title']) in t and f'COURSE N°{race["c"]}'.replace(' ','').replace('°','') in t and f'R{race["r"]}' in t
 return False

def parse(key,body,race):
 s=BeautifulSoup(body,'html.parser')
 if not identified(s,key,race):raise ValueError('date/course non concordante')
 ranked=[];extras=[];mode='ordre publié'
 if key in ('canalturf','zeturf'):
  block=s.select_one('#tab-prono-ct' if key=='canalturf' else '#tab-prono-zt')
  h=next((h for h in block.find_all('h3') if text(h).startswith('La sélection')),None) if block else None
  container=h.find_next_sibling() if h else None
  if not container:raise ValueError('sélection éditoriale absente')
  for table in ([container] if container.name=='table' else container.find_all('table')):
   label=text(table.find(['th','thead'])).lower()
   for row in table.select('tr'):
    cells=row.find_all('td')
    if len(cells)>=2 and text(cells[0]).isdigit():
     n=checked_name(int(text(cells[0])),text(cells[1]),race);ranked.append(n)
     if 'outsider' in label:extras.append({'number':n,'label':'Outsider'})
  if key=='canalturf':
   for e in block.find_all(string=re.compile('Coup de folie',re.I)):
    row=e.parent.parent
    for n in numbers(row):
     if n in race['horses']:extras.append({'number':n,'label':'Coup de folie'})
 elif key=='zone':
  row=next((row for row in s.select('tr') if text(row.select_one('.forecaster-name'))=='Zone-Turf.fr'),None)
  ranked=[int(text(e)) for e in row.select('td.number strong')] if row else []
  for e in s.select('td.folie'):
   a=e.find('a');m=re.match(r'(\d+)\s+(.+)',text(a))
   if m:extras.append({'number':checked_name(int(m[1]),m[2],race),'label':'Coup de folie'})
 elif key=='stats':
  table=next((t for t in s.find_all('table') if 'Base en Or' in text(t.find('thead'))),None)
  if table:
   ranked=[int(text(c)) for c in table.select('tbody td') if text(c).isdigit()]
   # Header colspans define precisely which tips are explicitly outsiders.
   pos=0;cells=table.select('tbody td')
   for h in table.select('thead th'):
    span=int(h.get('colspan',1))
    if 'outsider' in text(h).lower():
     extras.extend({'number':int(text(c)),'label':'Outsider'} for c in cells[pos:pos+span] if text(c).isdigit())
    pos+=span
 elif key=='turfprono':
  ranked=numbers(s.select_one('#tppmuFirstChance'))+numbers(s.select_one('#tppmuSecondChance'))
  mode='première chance puis seconde chance (ordre affiché)'
 elif key=='rue':
  h=next((h for h in s.find_all('h3') if 'Notre Pronostic Quinté' in text(h)),None)
  ranked=[int(text(e)) for e in h.parent.select('div div') if text(e).isdigit()] if h else []
  # No outsider invented from article commentary.
 elif key=='frequence':
  h=next((h for h in s.find_all('h3') if text(h)=='Les 4 sélections pour ce Quinté'),None)
  table=h.find_next('table') if h else None
  for c in table.select('td') if table else []:
   m=re.match(r'(\d+)\s*[–—-]\s*(.+)',text(c))
   if m:ranked.append(checked_name(int(m[1]),m[2],race))
  for h in s.find_all('h3'):
   label=text(h)
   if label in ('Le meilleur tocard du Quinté+','L’outsider séduisant'):
    e=h.find_next_sibling('h4');m=re.search(r'(\d+)\s*[–—-]\s*(.+)',text(e))
    if m:extras.append({'number':checked_name(int(m[1]),m[2],race),'label':label})
  h=next((h for h in s.find_all('h3') if text(h)=='Les 4 chevaux incontournables'),None)
  table=h.find_next('table') if h else None
  for c in table.select('td') if table else []:
   m=re.match(r'(\d+)\s*[–—-]\s*(.+)',text(c))
   if m:ranked.append(checked_name(int(m[1]),m[2],race))
  mode='favori, base, tocard, outsider, puis compléments (ordre des rubriques)'
 elif key=='prono':
  h=s.find('h2',id='base');e=h.find_next_sibling('p') if h else None
  m=re.search(r'([\w\s\-\’\']+)\s*\((\d+)\)',text(e))
  if m:ranked=[checked_name(int(m[2]),m[1].strip(),race)]
  h=s.find('h2',id='tocard');e=h.find_next_sibling('p') if h else None
  m=re.search(r'([\w\s\-\’\']+)\s*\((\d+)\)',text(e))
  if m:extras=[{'number':checked_name(int(m[2]),m[1].strip(),race),'label':'Tocard du jour'}]
  mode='base publique uniquement; autres choix non publiés'
 ranked=unique(ranked)
 if not ranked:raise ValueError('aucune sélection explicitement publiée')
 if any(n not in race['horses'] for n in ranked+[e['number'] for e in extras]):raise ValueError('numéro inconnu')
 # Non-runners stay visible but receive no votes; no silent promotion of fourth pick.
 return {'source':key,'publisher':key,'name':SOURCES[key][0],'top3':ranked[:3], 'top5':ranked[:5], 'outsiders':list({(e['number'],e['label']):e for e in extras}.values()),'mode':mode}

def consensus(rows,race):
 points=Counter();votes=Counter();outs=Counter();seen=set();full=0
 for row in rows:
  if row['publisher'] in seen:continue
  seen.add(row['publisher'])
  active=[n for n in row['top3'] if race['horses'][n].get('statut')=='PARTANT']
  if len(row['top3'])==3:full+=1
  for rank,n in enumerate(row['top3']):
   if n in active:points[n]+=3-rank;votes[n]+=1
  for n in set(e['number'] for e in row['outsiders']):
   if race['horses'][n].get('statut')=='PARTANT':outs[n]+=1
 top=sorted(points,key=lambda n:(-points[n],-votes[n],n))[:3]
 return {'complete_sources':full,'qualified':full>=5,'top3':[{'number':n,'name':race['horses'][n]['nom'],'points':points[n],'votes':votes[n]} for n in top], 'outsiders':[{'number':n,'name':race['horses'][n]['nom'],'votes':outs[n]} for n in sorted(outs,key=lambda n:(-outs[n],n))], 'tie_break':'points, citations, numéro croissant; égalité sans valeur prédictive'}

def pmu_odds(p):
 import math
 for field,kind in [('dernierRapportDirect','direct'),('dernierRapportReference','reference')]:
  quote=p.get(field) or {}
  if quote.get('typePari') and 'SIMPLE_GAGNANT' not in quote['typePari']:continue
  try:value=float(quote.get('rapport',0))
  except (TypeError,ValueError):continue
  if math.isfinite(value) and value>0:return {'value':value,'kind':kind,'official_time':quote.get('dateRapport')}
 return None

def display_top5(rows,race):
 votes=Counter();points=Counter();seen=set()
 for row in rows:
  if row['publisher'] in seen:continue
  seen.add(row['publisher'])
  for rank,n in enumerate(unique(row.get('top5',row['top3']))[:5]):
   if race['horses'][n].get('statut')=='PARTANT':votes[n]+=1;points[n]+=5-rank
 return [{'number':n,'name':race['horses'][n]['nom'],'votes':votes[n],'points5':points[n]} for n in sorted(votes,key=lambda n:(-votes[n],-points[n],n))[:5]]

class Fetcher:
 def __init__(self):self.cache={};self.audit=[]
 def get(self,url):
  if url not in self.cache:
   stamp=datetime.now(timezone.utc).isoformat()
   r=requests.get(url,timeout=25,headers={'User-Agent':'PMU-consensus-research/1.0 (+https://github.com/Pascalrive/pmu-scorer)'})
   self.audit.append({'url':url,'http':r.status_code,'retrieved_at':stamp,'sha256':hashlib.sha256(r.content).hexdigest()})
   r.raise_for_status();self.cache[url]=r.text
  return self.cache[url]
 def json(self,url):return json.loads(self.get(url))

def official(d,f):
 programme=f.json(API+d.strftime('%d%m%Y'))['programme']
 races=[]
 for reunion in programme['reunions']:
  if reunion.get('pays',{}).get('code')!='FRA':continue
  for c in reunion['courses']:
   if not any('QUINTE' in p.get('typePari','') for p in c.get('paris',[])):continue
   r=reunion['numOfficiel'];num=c['numOrdre'];ident=f'R{r}C{num}'
   horses=f.json(API+d.strftime('%d%m%Y')+f'/R{r}/C{num}/participants')['participants']
   races.append({'id':ident,'date':d.isoformat(),'r':r,'c':num,'title':c['libelle'],'departure':datetime.fromtimestamp(c['heureDepart']/1000,timezone.utc).isoformat(),'odds_captured_at':datetime.now(timezone.utc).isoformat(),'internet_quinte_available':any(p.get('typePari')=='E_QUINTE_PLUS' and p.get('enVente') is not False and p.get('miseBase')==200 for p in c.get('paris',[])),'horses':{p['numPmu']:{**{k:p.get(k) for k in ('numPmu','nom','statut')},'pmu_odds':pmu_odds(p)} for p in horses}})
 return races

def source_url(key,race,f):
 d=date.fromisoformat(race['date']);base=SOURCES[key][1]
 if key in ('canalturf','zeturf'):
  s=BeautifulSoup(f.get(base),'html.parser')
  candidates=[urljoin(base,a['href']) for a in s.find_all('a',href=True) if f'/pronostics-PMU/{d.isoformat()}/' in a['href'] and norm(race['title'])==norm(text(a.find('strong')))]
  if not candidates:raise ValueError('course absente de l’index daté')
  return candidates[0]
 if key=='frequence':return f'https://frequence-turf.fr/pronostic-quinte-pmu-{slugdate(d)}/'
 if key=='prono':return f'https://prono-turf-gratuit.fr/pronostic-quinte-pmu/base-solide-et-tocard-du-jour-quinte-du-{slugdate(d)}/'
 if key=='rue':
  s=BeautifulSoup(f.get(base),'html.parser')
  candidates=[urljoin(base,a['href']) for a in s.find_all('a',href=True) if ('pronostic-quinte-du-'+DAYS[d.weekday()]+'-'+str(d.day)+'-'+MONTHS[d.month-1]) in a['href'] and race['id'].lower() in a['href'] and 'decrypte' not in a['href']]
  if not candidates:raise ValueError('article daté absent')
  return candidates[0]
 return base

def collect(d,root):
 f=Fetcher();races=official(d,f);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');snapshots=[]
 for race in races:
  rows=[];statuses=[]
  for key in SOURCES:
   try:
    url=source_url(key,race,f);body=f.get(url);row=parse(key,body,race)
    row.update(url=url,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(body.encode()).hexdigest());rows.append(row)
    statuses.append({'source':key,'status':'OK' if len(row['top3'])==3 else 'PARTIEL','url':url})
   except Exception as e:statuses.append({'source':key,'status':'INDISPONIBLE','reason':str(e)[:180]})
  captured=datetime.now(timezone.utc).isoformat()
  snap={'version':VERSION,'captured_at':captured,'eligible_before_departure':captured<race['departure'],'race':race,'rows':rows,'consensus':consensus(rows,race),'display_top5':display_top5(rows,race),'analyses':build_analyses(rows,race),'statuses':statuses,'http_audit':f.audit}
  folder=root/d.isoformat();folder.mkdir(parents=True,exist_ok=True)
  (folder/f'{race["id"]}-{stamp}.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2))
  snapshots.append(snap)
 render(snapshots,root/d.isoformat())
 print(json.dumps([{'course':s['race']['id'],'sources':len(s['rows']),'complete':s['consensus']['complete_sources'],'pre_departure':s['eligible_before_departure'],'status':s['statuses']} for s in snapshots],ensure_ascii=False))
 return snapshots

def render(snapshots,folder):
 folder.mkdir(parents=True,exist_ok=True);lines=['# Consensus des pronostics — '+folder.name,'','Expérience indépendante • aucun pari exécuté • choix manquants non inventés.','']
 csvrows=[]
 for s in snapshots:
  race=s['race'];con=s['consensus'];horses=race['horses']
  label=lambda n:f'{n} {horses[n]["nom"]} (cote '+(str(horses[n]['pmu_odds']['value']) if horses[n].get('pmu_odds') else 'indisponible')+')'+(' (NP)' if horses[n].get('statut')!='PARTANT' else '')
  lines += [f'## {race["id"]} — {race["title"]}', '',f'Collecte : {s["captured_at"]}. Avant départ : {s["eligible_before_departure"]}. Sources complètes : {con["complete_sources"]}/8.', '', '| Source | Choix 1 | Choix 2 | Choix 3 | Choix 4 | Choix 5 | Outsider / trouble-fête |','|---|---|---|---|---|---|---|']
  bysource={r['source']:r for r in s['rows']}
  for key in SOURCES:
   row=bysource.get(key);choices=[label(n) for n in row.get('top5',row['top3'])] if row else []
   choices+=(['—']*(5-len(choices)))
   extras=' ; '.join(label(e['number'])+' — '+e['label'] for e in row['outsiders']) if row else 'Indisponible'
   name=f'[{SOURCES[key][0]}]({row["url"]})' if row else SOURCES[key][0]
   lines.append('| '+' | '.join([name]+choices+[extras or 'Non publié'])+' |')
   csvrows.append({'date':race['date'],'course':race['id'],'source':SOURCES[key][0],'choix1':choices[0],'choix2':choices[1],'choix3':choices[2],'choix4':choices[3],'choix5':choices[4],'outsiders':extras,'url':row['url'] if row else '', 'capture':s['captured_at'],'mode':row['mode'] if row else 'indisponible'})
  lines+=['','### Les cinq chevaux les plus cités dans les cinq choix publiés','','| Cheval | Sources le citant |','|---|---:|']
  lines += [f'| {label(x["number"])} | {x["votes"]} |' for x in s.get('display_top5',[])]
  lines+=['','### Notre analyse — trois sélections de cinq chevaux','','| Variante | Sélection | Simulation |','|---|---|---|']
  for profile in s.get('analyses',{}).get('profiles',[]):
   lines.append('| '+profile['label']+' | '+' – '.join(str(n) for n in profile['numbers'])+' | '+('2 €' if profile['qualified'] else 'INCOMPLET : pas de simulation')+' |')
  lines+=['','### Cumul des trois premiers choix','', '| Cheval | Points 3–2–1 | Sources le citant |','|---|---:|---:|']
  lines += [f'| {x["number"]} {x["name"]} | {x["points"]} | {x["votes"]} |' for x in con['top3']]
  lines+=['','### Cumul des outsiders explicites','','| Cheval | Sources le citant comme outsider |','|---|---:|']
  lines += [f'| {x["number"]} {x["name"]} | {x["votes"]} |' for x in con['outsiders']]
  lines+=['','Évaluable : '+('oui' if con['qualified'] and s['eligible_before_departure'] else 'non — collecte tardive ou moins de cinq sources complètes')+'.','']
  lines+=['<details><summary>Disponibilité des sources et règles de lecture</summary>','']
  for status in s['statuses']:lines.append('- '+SOURCES[status['source']][0]+': '+status['status']+' '+status.get('reason',''))
  for row in s['rows']:lines.append('- '+row['name']+': '+row['mode'])
  lines+=['','</details>','']
 (folder/'TABLEAU.md').write_text('\n'.join(lines))
 with (folder/'TABLEAU.csv').open('w',newline='') as out:
  w=csv.DictWriter(out,fieldnames=list(csvrows[0]) if csvrows else ['date','course','source']);w.writeheader();w.writerows(csvrows)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--date',default=datetime.now(ZoneInfo('Europe/Paris')).date().isoformat());p.add_argument('--output',default='consensus_pronostics/data');args=p.parse_args();collect(date.fromisoformat(args.date),Path(args.output))
