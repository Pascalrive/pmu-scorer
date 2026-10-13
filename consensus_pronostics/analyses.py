"""Frozen five-horse comparison rules, independent from original simple-place trial."""
from collections import Counter
import math
VERSION_ANALYSES='trois-selections-v1-2026-10-13'
STAKE_EUR=2

def build_analyses(rows,race):
 horses={int(n):p for n,p in race['horses'].items()};base=Counter();points=Counter();outs=Counter();seen=set();complete=0
 for row in rows:
  if row['publisher'] in seen:continue
  seen.add(row['publisher']);top=list(dict.fromkeys(row.get('top5',row['top3'])))[:5]
  complete+=len(top)==5
  for rank,n in enumerate(top):
   if horses[n].get('statut')=='PARTANT':base[n]+=1;points[n]+=5-rank
  for n in set(e['number'] for e in row['outsiders']):
   if horses[n].get('statut')=='PARTANT':outs[n]+=1
 def odds(n):
  v=(horses[n].get('pmu_odds') or {}).get('value')
  return float(v) if isinstance(v,(float,int)) and math.isfinite(v) and v>0 else None
 def detail(n):return {'number':n,'name':horses[n]['nom'],'base_votes':base[n],'rank_points':points[n],'outsider_votes':outs[n],'odds':odds(n)}
 stat=sorted(base,key=lambda n:(-base[n],-points[n],n))[:5]
 market=sorted([n for n,p in horses.items() if p.get('statut')=='PARTANT' and odds(n) is not None],key=lambda n:(odds(n),n))[:5]
 seeds=stat[:3];extras=sorted([n for n in outs if n not in seeds and outs[n]>=2],key=lambda n:(-outs[n],odds(n) if odds(n) is not None else float('inf'),n))[:2]
 profiles=[]
 for key,label,numbers,rule in [
  ('statistique','Statistique',stat,'Citations dans les cinq choix ; égalités : points 5–4–3–2–1, puis numéro.'),
  ('cotes','Cotes',market,'Cinq plus petites cotes PMU connues parmi les partants ; égalités : numéro.'),
  ('mixte','Bases + outsiders',seeds+extras,'Trois bases statistiques + deux outsiders distincts cités par au moins deux sources ; égalités outsiders : cote, puis numéro.')]:
  ready=race.get('internet_quinte_available') is True and complete>=5 and len(numbers)==5 and (key!='mixte' or len(seeds)==3 and len(extras)==2)
  profiles.append({'id':key,'label':label,'horses':[detail(n) for n in numbers], 'numbers':numbers,'qualified':ready,'rule':rule,'stake_eur':STAKE_EUR,'market':'E_QUINTE_PLUS'})
 return {'version':VERSION_ANALYSES,'complete_sources':complete,'available_sources':len(seen),'profiles':profiles,'simulation_only':True,'stake_eur':STAKE_EUR,'option_max':False,'progressive_staking':False}
