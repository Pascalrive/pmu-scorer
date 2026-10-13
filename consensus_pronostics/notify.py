"""Daily Telegram delivery, with separate receipts and no imports from PMU scorer."""
import argparse,hashlib,json,os,html
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

TZ=ZoneInfo('Europe/Paris')

def horse(race,n):
 p=race['horses'].get(str(n),race['horses'].get(n,{}))
 return f'{n} {p.get("nom", "?")}' + (' (NP)' if p.get('statut')!='PARTANT' else '')

def quote(race,n):
 p=race['horses'].get(str(n),race['horses'].get(n,{}));q=p.get('pmu_odds')
 if not q:return 'cote indisponible'
 value=f'{q["value"]:g}'.replace('.',',')
 return value + (' (réf.)' if q['kind']=='reference' else '')

def card(race,n):
 return html.escape(horse(race,n))+' · <b>'+html.escape(quote(race,n))+'</b>'

def format_messages(s):
 from collector import SOURCES,display_top5
 race=s['race'];con=s['consensus'];display=s.get('display_top5')
 if display is None:
  r={**race,'horses':{int(n):p for n,p in race['horses'].items()}};display=display_top5(s['rows'],r)
 day=datetime.fromisoformat(race['departure']).astimezone(TZ).strftime('%d/%m/%Y');start=datetime.fromisoformat(race['departure']).astimezone(TZ).strftime('%Hh%M')
 stamp=datetime.fromisoformat(race.get('odds_captured_at',s['captured_at'])).astimezone(TZ).strftime('%Hh%M')
 count=len({r['publisher'] for r in s['rows']});five=sum(len(r.get('top5',r['top3']))==5 for r in s['rows'])
 summary=[f'🏇 QUINTÉ — {day} · 1/3',f'<b>{race["id"]} · Départ {start}</b>',html.escape(race['title']),f'Cotes PMU relevées à {stamp}',f'{count}/8 avis disponibles · {five} sélections de cinq chevaux','', '<b>⭐ LES CINQ CHEVAUX LES PLUS CITÉS</b>']
 for rank,x in enumerate(display,1):summary.append(f'{rank}. <b>N°{x["number"]}</b> '+html.escape(x['name'])+f' · cote <b>{html.escape(quote(race,x["number"]))}</b> · {x["votes"]}/{count} avis')
 summary+=['','<b>⚡ OUTSIDERS CITÉS PAR PLUSIEURS SOURCES</b>']
 shared=[x for x in con['outsiders'] if x['votes']>=2]
 if not shared:summary.append('Aucun outsider cité par au moins deux sources.')
 for x in shared:summary.append(card(race,x['number'])+f' · {x["votes"]} sources')
 if not con['qualified']:summary+=['','PROVISOIRE : moins de cinq sources complètes ; exclu du bilan simulé.']
 if s.get('analyses'):
  summary+=['','<b>🧮 NOTRE ANALYSE — TROIS SÉLECTIONS</b>']
  for profile in s['analyses']['profiles']:
   nums=' – '.join(str(n) for n in profile['numbers'])
   summary.append('<b>'+html.escape(profile['label'])+'</b> : '+nums+('' if profile['qualified'] else ' · INCOMPLET'))
  summary+=['Mixte : trois bases + deux outsiders cités par ≥2 sources.','Comparaison simulée : 2 € par sélection complète, sans Option Max. Mise fixe ; aucune augmentation après une perte.']
 summary+=['','Cotes de simple gagnant, indicatives et évolutives. « réf. » = cote de référence si le direct manque.','Présentation des avis · aucun pari exécuté.']
 detail=[f'📋 QUINTÉ — {day} · 2/3','<b>LES CINQ CHOIX PAR PRONOSTIQUEUR</b>','Ordre publié : ① premier choix → ⑤ cinquième choix.','Chaque ligne : numéro · cheval · cote PMU.']
 by={r['source']:r for r in s['rows']};ranks=['①','②','③','④','⑤']
 for key,(name,url) in SOURCES.items():
  row=by.get(key);detail+=['','<b>'+html.escape(name.replace(' via Canalturf',''))+'</b>']
  if not row:detail.append('Indisponible à ce relevé.');continue
  top=row.get('top5',row['top3'])
  for i,n in enumerate(top):detail.append(ranks[i]+' '+card(race,n))
  if len(top)<5:detail.append(f'↳ {len(top)}/5 choix publics ; autres choix non publiés.')
  if key=='frequence':detail.append('↳ Favori, base, tocard, outsider, puis complément.')
  if key=='turfprono':detail.append('↳ Première chance puis seconde chance, ordre affiché.')
  if key=='zeturf':detail.append('↳ Sélection ZEturf identifiée sur Canalturf.')
 extras=[f'⚡ QUINTÉ — {day} · 3/3','<b>OUTSIDERS, TOCARDS ET COUPS DE FOLIE</b>','Conseils supplémentaires explicitement publiés.']
 for row in s['rows']:
  if not row['outsiders']:continue
  extras+=['','<b>'+html.escape(row['name'].replace(' via Canalturf',''))+'</b>']
  grouped={}
  for e in row['outsiders']:grouped.setdefault(e['number'],[]).append(e['label'])
  for n,labels in grouped.items():extras.append(card(race,n)+' — '+html.escape(' / '.join(labels)))
 extras+=['','Une source compte une seule fois par cheval, même si elle lui donne plusieurs qualificatifs.']
 return ['\n'.join(summary),'\n'.join(detail),'\n'.join(extras)]

def format_message(s):
 return '\n\n'.join(format_messages(s))

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
  record={'date':s['race']['date'],'course':ident,'snapshot_capture':s['captured_at'],'fingerprint':fingerprint,'text':message,'analyses':s.get('analyses'),'delivery':'PENDING','receipts':[]};ledger.append(record);persist()
  parts=[part for section in format_messages(s) for part in chunks(section)]
  for part in parts:
   # Check departure again before each send. Never retry a timeout automatically.
   if clock()>=datetime.fromisoformat(s['race']['departure']):record['delivery']='BLOCKED_AFTER_START';failed=True;break
   try:
    response=post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':chat,'text':part,'disable_web_page_preview':True,'parse_mode':'HTML'},timeout=25)
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
