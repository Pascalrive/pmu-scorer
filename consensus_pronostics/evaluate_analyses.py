"""Separate three-profile Quinté trial: confirmed pre-race selections only."""
import argparse,json,re
from collections import defaultdict
from datetime import datetime,date,timezone
from decimal import Decimal
from pathlib import Path
from analyses import VERSION_ANALYSES,STAKE_EUR
from collector import Fetcher,API,norm

def combo(row):
 v=row.get('combinaison',[])
 return [int(n) for n in v] if isinstance(v,list) else [int(n) for n in re.findall(r'\d+',str(v))]

def quinte_return(numbers,participants,reports):
 """One five-horse ticket in published order, without Option Max. Fail closed."""
 if len(numbers)!=5 or len(set(numbers))!=5:return None
 people={p['numPmu']:p for p in participants}
 if any(n not in people for n in numbers):return None
 market=next((m for m in reports if m.get('typePari')=='E_QUINTE_PLUS'),None)
 if not market:return None
 if market.get('rembourse'):return Decimal(STAKE_EUR)
 if any(people[n].get('statut') in ('NON_PARTANT','NONPARTANT') for n in numbers):return None
 rows=market.get('rapports',[])
 if not any('DESORDRE' in norm(r.get('libelle','')) for r in rows):return None
 matches=defaultdict(list)
 chosen=set(numbers)
 for r in rows:
  label=norm(r.get('libelle',''));ns=combo(r);category=None
  if 'DESORDRE' in label and len(ns)==5 and set(ns)==chosen:category=3
  elif 'ORDRE' in label and 'DESORDRE' not in label and ns==numbers:category=4
  elif 'BONUS4' in label and len(ns)==4 and set(ns).issubset(chosen):category=2
  elif 'BONUS3' in label and len(ns)==3 and set(ns).issubset(chosen):category=1
  if category is not None:matches[category].append(r)
 if not matches:return Decimal('0')
 winners=matches[max(matches)]
 # Ambiguous dead-heat or special cases must not manufacture an exact ROI.
 if len(winners)!=1:return None
 dividend=winners[0].get('dividendePourUnEuro')
 if dividend is None:return None
 return Decimal(str(dividend))/100*STAKE_EUR

def select_sent(snaps,ledger):
 valid=[]
 for s in snaps:
  a=s.get('analyses')
  if not a or a.get('version')!=VERSION_ANALYSES or not s.get('eligible_before_departure') or s['captured_at']>=s['race']['departure']:continue
  if not all(p['qualified'] for p in a['profiles']):continue
  if any(r.get('delivery')=='SENT' and r.get('sent_at','9999')<s['race']['departure'] and r.get('snapshot_capture')==s['captured_at'] and r.get('analyses')==a for r in ledger):valid.append(s)
 return max(valid,key=lambda s:s['captured_at']) if valid else None

def evaluate(root):
 f=Fetcher();groups=defaultdict(list);rows=[]
 for path in root.glob('*/R*.json'):
  s=json.loads(path.read_text());groups[(s['race']['date'],s['race']['id'])].append(s)
 for (day,ident),snaps in sorted(groups.items()):
  ledgerpath=root/day/'notifications.json';ledger=json.loads(ledgerpath.read_text()) if ledgerpath.exists() else []
  s=select_sent(snaps,ledger)
  if not s:continue
  race=s['race'];future=datetime.now(timezone.utc)<datetime.fromisoformat(race['departure']);participants=[];reports=[]
  if not future:
   prefix=API+date.fromisoformat(day).strftime('%d%m%Y')+f'/R{race["r"]}/C{race["c"]}'
   try:participants=f.json(prefix+'/participants')['participants'];reports=f.json(prefix+'/rapports-definitifs?specialisation=INTERNET')
   except Exception:pass
  by={p['numPmu']:p for p in participants}
  for profile in s['analyses']['profiles']:
   ns=profile['numbers'];identity=all(norm(by.get(n,{}).get('nom',''))==norm(race['horses'][str(n)]['nom']) for n in ns)
   retour=quinte_return(ns,participants,reports) if identity and not future else None
   hits=sum(isinstance(by.get(n,{}).get('ordreArrivee'),int) and 1<=by[n]['ordreArrivee']<=5 for n in ns) if participants and sum(isinstance(p.get('ordreArrivee'),int) and 1<=p['ordreArrivee']<=5 for p in participants)>=5 else None
   rows.append({'date':day,'course':ident,'strategie':profile['id'],'numeros':ns,'capture':s['captured_at'],'version':VERSION_ANALYSES,'mise':STAKE_EUR,'retour':float(retour) if retour is not None else None,'statut':'AVANT_COURSE' if future else ('REGLE' if retour is not None else 'EN_ATTENTE'),'chevaux_dans_les_cinq':hits})
 root.mkdir(parents=True,exist_ok=True);(root/'BILAN_TROIS_SELECTIONS.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 lines=['# Trois sélections de cinq chevaux — bilan indépendant','','Simulation à mise fixe : 2 € par variante complète, aucun pari exécuté, aucun rattrapage des pertes. Seules les courses avec les trois variantes complètes et confirmées sur Telegram avant départ sont comparées. Dernier envoi confirmé admissible. Quinté Internet sans Option Max, ticket dans l’ordre affiché ; règlement officiel Ordre, Désordre ou Bonus selon le rapport applicable. Cas non résolus, notamment non-partants et rapports ambigus : en attente.','', '| Date | Variante | Numéros | Couverture des cinq premiers | Mise | Retour | Statut |','|---|---|---|---:|---:|---:|---|']
 for row in rows:lines.append('| '+row['date']+' | '+row['strategie']+' | '+' – '.join(map(str,row['numeros']))+' | '+str(row['chevaux_dans_les_cinq'] if row['chevaux_dans_les_cinq'] is not None else '—')+' | 2 € | '+(f'{row["retour"]:.2f} €' if row['retour'] is not None else '—')+' | '+row['statut']+' |')
 lines+=['','## Comparaison cumulée','','| Variante | Courses | En attente | Mises réglées | Retours réglés | ROI complet |','|---|---:|---:|---:|---:|---|']
 for key in ('statistique','cotes','mixte'):
  rs=[r for r in rows if r['strategie']==key];done=[r for r in rs if r['statut']=='REGLE'];pending=len(rs)-len(done);stake=Decimal(STAKE_EUR*len(done));ret=sum((Decimal(str(r['retour'])) for r in done),Decimal('0'))
  roi=f'{(ret-stake)/stake*100:+.2f} %' if stake and not pending else 'INCOMPLET'
  lines.append(f'| {key} | {len(rs)} | {pending} | {stake:.2f} € | {ret:.2f} € | {roi} |')
 (root/'BILAN_TROIS_SELECTIONS.md').write_text('\n'.join(lines));print(f'TROIS_SELECTIONS_TRACKED {len(rows)}')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',default='consensus_pronostics/data');a=p.parse_args();evaluate(Path(a.output))
