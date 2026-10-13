"""Daily Telegram delivery, with separate receipts and no imports from PMU scorer."""
import argparse,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

TZ=ZoneInfo('Europe/Paris')

def horse(race,n):
 p=race['horses'].get(str(n),race['horses'].get(n,{}))
 return f'{n} {p.get("nom", "?")}' + (' (NP)' if p.get('statut')!='PARTANT' else '')

def format_message(s):
 race=s['race'];con=s['consensus'];lines=[f'🐎 CONSENSUS — {race["date"]}',f'{race["id"]} — {race["title"]}', 'Départ : '+datetime.fromisoformat(race['departure']).astimezone(TZ).strftime('%Hh%M'), 'Programme indépendant — simulation uniquement.',f'{con["complete_sources"]}/8 sources avec trois choix publiés.','', 'CHOIX PAR SOURCE — 1er / 2e / 3e']
 from collector import SOURCES
 by={r['source']:r for r in s['rows']}
 for key,(name,url) in SOURCES.items():
  row=by.get(key);top=[horse(race,n) for n in row['top3']] if row else []
  top+=['—']*(3-len(top));lines.append(name+' : '+' / '.join(top))
 lines+=['','CONSENSUS PRINCIPAL — points 3–2–1']
 for x in con['top3']:lines.append(f'{x["number"]} {x["name"]} — {x["points"]} points, {x["votes"]} sources')
 lines+=['','OUTSIDERS / TOCARDS / COUPS DE FOLIE']
 for row in s['rows']:
  if row['outsiders']:lines.append(row['name']+' : '+' ; '.join(horse(race,e['number'])+' — '+e['label'] for e in row['outsiders']))
 lines+=['','CUMUL DES OUTSIDERS EXPLICITES']
 for x in con['outsiders']:lines.append(f'{x["number"]} {x["name"]} — {x["votes"]} source(s)')
 if not con['qualified']:lines+=['','PROVISOIRE : moins de cinq sources complètes ; exclu du bilan simulé.']
 lines+=['','Les choix manquants restent vides. Mises simulées : 5 € en simple placé sur le premier du consensus si ≥5 sources complètes ; outsider séparé si ≥2 citations. Aucun pari exécuté.']
 return '\n'.join(lines)

def admissible(s,now):
 return s['race']['date']==now.astimezone(TZ).date().isoformat() and s.get('eligible_before_departure') and datetime.fromisoformat(s['captured_at'])<datetime.fromisoformat(s['race']['departure']) and now<datetime.fromisoformat(s['race']['departure'])

def chunks(message,limit=3500):
 parts=[];current=''
 for line in message.splitlines():
  if len(line)>limit:raise ValueError('Ligne Telegram trop longue')
  if current and len(current)+len(line)+1>limit:parts.append(current);current=''
  current+=('\n' if current else '')+line
 if current:parts.append(current)
 return parts

def notify(root,now=None,post=requests.post,clock=lambda:datetime.now(timezone.utc)):
 now=now or clock();folder=root/now.astimezone(TZ).date().isoformat()
 token=os.environ.get('TELEGRAM_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
 if not token or not chat:raise RuntimeError('Configuration Telegram absente')
 paths=sorted(folder.glob('R*.json'));latest={}
 for path in paths:
  s=json.loads(path.read_text())
  if admissible(s,now):
   ident=s['race']['id']
   if ident not in latest or s['captured_at']>latest[ident]['captured_at']:latest[ident]=s
 if not latest:print('CONSENSUS_NO_UPCOMING_SNAPSHOT');return
 ledger_path=folder/'notifications.json';ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
 persist=lambda:ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
 failed=False
 for ident,s in latest.items():
  message=format_message(s);fingerprint=hashlib.sha256(message.encode()).hexdigest()
  prior=[r for r in ledger if r['fingerprint']==fingerprint]
  if any(r['delivery']=='SENT' for r in prior):print(f'CONSENSUS_ALREADY_SENT {ident}');continue
  if any(r['delivery'] in ('PENDING','UNCERTAIN') for r in prior):
   print(f'CONSENSUS_DELIVERY_UNCERTAIN {ident} — contrôle manuel nécessaire');failed=True;continue
  record={'date':s['race']['date'],'course':ident,'snapshot_capture':s['captured_at'],'fingerprint':fingerprint,'text':message,'delivery':'PENDING','receipts':[]};ledger.append(record);persist()
  for part in chunks(message):
   # Check departure again before each send. Never retry a timeout automatically.
   if clock()>=datetime.fromisoformat(s['race']['departure']):record['delivery']='BLOCKED_AFTER_START';failed=True;break
   try:
    response=post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':chat,'text':part,'disable_web_page_preview':True},timeout=25)
    body=response.json()
   except Exception:
    record['delivery']='UNCERTAIN';failed=True;break
   if response.status_code!=200 or body.get('ok') is not True:
    record['delivery']='REFUSED';failed=True;break
   result=body['result'];record['receipts'].append({'message_id':result['message_id'],'date':result['date']});persist()
  else:record['delivery']='SENT';record['sent_at']=datetime.fromtimestamp(record['receipts'][-1]['date'],timezone.utc).isoformat();print(f'CONSENSUS_TELEGRAM_SENT {ident} messages='+','.join(str(r['message_id']) for r in record['receipts']))
  persist()
 if failed:raise RuntimeError('Envoi consensus non confirmé ; consulter les reçus indépendants')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',default='consensus_pronostics/data');args=p.parse_args();notify(Path(args.output))
