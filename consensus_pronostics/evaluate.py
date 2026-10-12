"""Settle frozen pre-race consensus simulations against PMU INTERNET only."""
import argparse,json
from collections import defaultdict
from datetime import date,datetime,timedelta
from decimal import Decimal
from pathlib import Path
from collector import API, Fetcher, VERSION, norm

def place_return(number,participants,reports):
 p=next((p for p in participants if p['numPmu']==number),None)
 if not p:return None
 if p.get('statut') in ('NON_PARTANT','NONPARTANT'):return Decimal('5')
 market=next((r for r in reports if r.get('typePari')=='E_SIMPLE_PLACE'),None)
 if market is None:return None
 if market.get('rembourse'):return Decimal('5')
 combinations=market.get('rapports',[])
 if not combinations:return None
 for row in combinations:
  combo=row.get('combinaison')
  if str(combo)==str(number) or (isinstance(combo,list) and [str(x) for x in combo]==[str(number)]):
   return Decimal(str(row['dividendePourUnEuro']))/100*5
 # Official final reports contain the winning place combinations; other runners lose.
 return Decimal('0')

def selected(snapshots):
 valid=[s for s in snapshots if s.get('version')==VERSION and s.get('eligible_before_departure') and s['captured_at']<s['race']['departure'] and s['consensus']['qualified']]
 return max(valid,key=lambda s:s['captured_at']) if valid else None

def evaluate(root):
 f=Fetcher();byrace=defaultdict(list)
 for p in root.glob('*/R*.json'):
  s=json.loads(p.read_text());byrace[(s['race']['date'],s['race']['id'])].append(s)
 rows=[]
 for (day,ident),snaps in sorted(byrace.items()):
  snap=selected(snaps)
  if not snap:continue
  race=snap['race'];prefix=API+date.fromisoformat(day).strftime('%d%m%Y')+f'/R{race["r"]}/C{race["c"]}'
  if datetime.fromisoformat(race['departure'])>=datetime.now().astimezone():continue
  try:
   participants=f.json(prefix+'/participants')['participants'];reports=f.json(prefix+'/rapports-definitifs?specialisation=INTERNET')
  except Exception:participants=[];reports=[]
  candidates=[('consensus',snap['consensus']['top3'][0]['number'])]
  outsiders=snap['consensus']['outsiders']
  if outsiders and outsiders[0]['votes']>=2:candidates.append(('outsider',outsiders[0]['number']))
  for arm,number in candidates:
   actual=next((p for p in participants if p['numPmu']==number),{})
   concordant=norm(actual.get('nom',''))==norm(race['horses'][str(number)]['nom'])
   retour=place_return(number,participants,reports) if concordant else None
   p=next((p for p in participants if p['numPmu']==number),{})
   rows.append({'date':day,'course':ident,'strategie':arm,'numero':number,'nom':race['horses'][str(number)]['nom'],'capture':snap['captured_at'],'sources':snap['consensus']['complete_sources'],'mise':5,'retour':float(retour) if retour is not None else None,'statut':'REGLE' if retour is not None else 'EN_ATTENTE','ordre_arrivee':p.get('ordreArrivee')})
 (root/'BILAN.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 lines=['# Bilan indépendant du consensus','','Simulation : 5 € en simple placé sur le premier du consensus (≥5 sources complètes). Groupe outsider distinct : 5 € sur le plus cité explicitement (≥2 sources). Aucun pari exécuté. Dernière collecte admissible avant départ. Rapports PMU INTERNET définitifs exclusivement.','', '| Date | Stratégie | Paris | En attente | Mises réglées | Retours réglés | ROI |','|---|---|---:|---:|---:|---:|---|']
 groups=defaultdict(list)
 for row in rows:groups[(row['date'],row['strategie'])].append(row)
 for (day,arm),rs in sorted(groups.items()):
  settled=[r for r in rs if r['statut']=='REGLE'];pending=len(rs)-len(settled);stake=5*len(settled);ret=sum(Decimal(str(r['retour'])) for r in settled)
  roi=f'{(ret-Decimal(stake))/Decimal(stake)*100:+.2f} %' if stake and not pending else 'INCOMPLET'
  lines.append(f'| {day} | {arm} | {len(rs)} | {pending} | {stake:.2f} € | {ret:.2f} € | {roi} |')
 if not rows:lines+=['','Aucune course admissible déjà réglable. Les collectes après départ servent uniquement à vérifier les lecteurs des sites.']
 (root/'BILAN.md').write_text('\n'.join(lines))
 print(f'{len(rows)} simulations, {sum(r["statut"]=="EN_ATTENTE" for r in rows)} en attente')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',default='consensus_pronostics/data');a=p.parse_args();evaluate(Path(a.output))
