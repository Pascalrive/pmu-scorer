"""Independent daily R1 observation and official settlement runner."""
import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from .sources import SITES, INDEX, locate, parse, norm
from .model import START, END, STRATEGIES, account, reserve, freeze, groups, settle, summary
from .telegram import send

ROOT=Path(__file__).parent
TZ=ZoneInfo('Europe/Paris')
API='https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)

class Fetcher:
    def __init__(self):self.cache={};self.audit=[]
    def get(self,url):
        if url not in self.cache:
            try:
                r=requests.get(url,timeout=20,headers={'User-Agent':'Comparaison-R1-Research/1.0'})
                self.audit.append({'url':url,'status':r.status_code,'at':datetime.now(TZ).isoformat()})
                r.raise_for_status()
                self.cache[url]=r.text
            except requests.RequestException:
                self.cache[url]=None
                raise
        if self.cache[url] is None:raise ValueError('Source inaccessible lors de ce passage')
        return self.cache[url]
    def json(self,url):return json.loads(self.get(url))

def proof(folder,url,body):
    digest=hashlib.sha256(body.encode()).hexdigest()
    target=folder/'preuves'/(digest+'.gz');target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():target.write_bytes(gzip.compress(body.encode(),mtime=0))
    return {'url':url,'sha256':digest,'file':'preuves/'+target.name}

def meeting(day,f):
    url=API+day.replace('-','')[6:8]+day.replace('-','')[4:6]+day[:4]
    p=f.json(url)['programme']
    candidates=[r for r in p['reunions'] if r['numOfficiel']==1 and r.get('pays',{}).get('code')=='FRA']
    if len(candidates)!=1:raise ValueError('R1 française absente')
    r=candidates[0]
    return {'date':day,'venue':r['hippodrome']['libelleCourt'],'solutions':{k:{'bets':[]} for k in STRATEGIES},'races':[
        {'date':day,'id':f'R1C{c["numOrdre"]}','c':c['numOrdre'],'title':c['libelle'],
         'departure':datetime.fromtimestamp(c['heureDepart']/1000,TZ).isoformat(),
         'market':c.get('hasEParis') is not False and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('enVente') is not False for x in c.get('paris',[])),
         'tips':{},'groups':{},'errors':{}}
        for c in sorted(r['courses'],key=lambda c:c['heureDepart'])],'notifications':[]}

def base_url(day,c):
    return API+datetime.fromisoformat(day).strftime('%d%m%Y')+f'/R1/C{c}'

def collect_race(race,f,folder,clock=lambda:datetime.now(TZ)):
    now=clock();delta=(datetime.fromisoformat(race['departure'])-now).total_seconds()
    if not 0<delta<=3600:return
    base=base_url(race['date'],race['c'])
    meta=f.json(base)
    if (meta.get('numReunion')!=1 or meta.get('numOrdre')!=race['c'] or norm(meta.get('libelle'))!=norm(race['title'])
        or meta.get('heureDepart')!=int(datetime.fromisoformat(race['departure']).timestamp()*1000)):
        raise ValueError('Horaire ou identité officielle modifié : collecte suspendue')
    race['market']=meta.get('hasEParis') is not False and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('enVente') is not False for x in meta.get('paris',[]))
    horses=f.json(base+'/participants')['participants']
    for site in SITES:
        if site in race['tips']:continue
        try:
            index=INDEX[site].format(date=race['date'])
            u=locate(site,f.get(index),race);body=f.get(u)
            tip=parse(site,body,u,race,horses)
            tip['evidence']=proof(folder,u,body)
            tip['official_evidence']=proof(folder,base+'/participants',f.get(base+'/participants'))
            horse=next(h for h in horses if h['numPmu']==tip['number'])
            if freeze(race,site,tip,horse,clock()):race['errors'].pop(site,None)
        except (ValueError,KeyError,TypeError,requests.RequestException) as e:
            race['errors'][site]={'type':type(e).__name__,'reason':str(e).split('\n')[0][:200],'at':clock().isoformat()}
    if not race['groups'] and clock()<datetime.fromisoformat(race['departure']):
        race['groups']=groups(race['tips'])
        if race['groups']:race['groups_frozen_at']=clock().isoformat()

def euros(c):return f'{c/100:.2f} €'

def race_message(r):
    lines=[f'🔎 COMPARATIF R1 — {r["date"]}',f'{r["id"]} · {datetime.fromisoformat(r["departure"]).strftime("%Hh%M")} · {r["title"]}',
           'Choix observés — mises progressives annoncées dans le suivi des solutions', '']
    for site in SITES:
        t=r['tips'].get(site)
        if not t:lines.append(f'{site.upper()} : indisponible');continue
        q=t.get('odds') or {}
        lines.append(f'{site.upper()} : N°{t["number"]} {t["name"]} · cote {q.get("rapport","—")}'+(' · non jouable' if not t['playable'] else ''))
        if 'return_cents' in t:lines.append(f'  Résultat du choix : {t["status"]}')
    primary=[(k,g) for k,g in r['groups'].items() if k.startswith('accord_')]
    if primary:
        k,g=primary[0];lines+=['',f'🤝 ACCORD {len(g["sites"])}/4 : N°{g["number"]}', ' + '.join(g['sites'])]
    else:lines+=['','Accord : absent, égalité 2–2 ou quatre sources non disponibles.']
    lines+=['Les choix sont figés avant départ. ZEturf est lu dans sa rubrique sur Canalturf.','Cotes indicatives ; règlement aux rapports définitifs PMU INTERNET.']
    return '\n'.join(lines)

def live_report(state):
    lines=['💶 COMPARATIF R1 — SUIVI DES MISES',state['date']+' · '+state['venue'],
           'Simulation · 100 € ; +100 € après perte ; retour 100 € après gain.',
           'Arrêt à +200 € NET ; plafond 800 € de mises/jour/solution.', '']
    for key in STRATEGIES:
        sol=state['solutions'][key];a=account(sol)
        lines.append(key.replace('_',' ').upper())
        if sol['bets']:
            b=sol['bets'][-1]
            lines.append(f'{b["race_id"]} N°{b["number"]} {b["name"]} · mise {euros(b["stake_cents"])} · {b["status"]}')
            if 'return_cents' in b:lines.append('Retour '+euros(b['return_cents'])+' · net du pari '+euros(b['profit_cents']))
        else:lines.append('Aucun pari engagé')
        lines.append('Net réglé du jour '+euros(a['profit_cents'])+' · engagé '+euros(a['committed_cents'])+' / 800 €')
        lines.append('Statut : '+a['stop'] if a['stop'] else 'Prochaine mise conditionnelle : '+euros(a['next_stake_cents']))
        lines.append('')
    lines.append('Chaque solution a son budget propre. Remboursements inclus dans le plafond. Aucun pari réel.')
    return '\n'.join(lines)

def report(b):
    lines=['📊 COMPARATIF R1 — BILAN CUMULÉ',f'{START} → {END} · mises progressives virtuelles',
           '100 € ; +100 € après perte ; retour 100 € après gain. Cible +200 € net/jour ; plafond mises 800 €/jour/solution.',
           f'{b["races"]} courses enregistrées · {b["common_settled_races"]} communes réglées',
           '', 'CLASSEMENT PAR BÉNÉFICE NET SIMULÉ']
    def line(name,s):
        return f'{name} : {s["wins"]}/{s["wins"]+s["losses"]} gagnants · ROI {s["roi_percent"] if s["roi_percent"] is not None else "—"} % · net {euros(s["profit_cents"])} · {s["pending"]} en attente'
    for key in b['ranking_by_net_profit']:
        s=b['solutions'][key]
        lines.append(line(key.replace('_',' '),s)+f' · objectif atteint {s["days_target_reached"]}/{s["days_active"]} jours actifs')
    lines+=['','QUALITÉ DES CHOIX — MÊMES COURSES, INDÉPENDAMMENT DES ARRÊTS']
    for site in SITES:
        s=b['common'][site];lines.append(f'{site} : {s["wins"]}/{s["wins"]+s["losses"]} gagnants · {b["individual"][site]["missing_races"]} courses sans choix')
    lines+=['','ACCORDS ENTRE SITES']
    for key in ('accord_2_sur_4','accord_3_sur_4','accord_4_sur_4','majorite_3_ou_4'):
        if key in b['agreements']:
            s=b['agreements'][key];lines.append(f'{key.replace("_"," ")} : {s["wins"]}/{s["wins"]+s["losses"]} choix gagnants (y compris après arrêt des mises)')
        else:lines.append(key.replace('_',' ')+': aucun accord')
    for key,s in b['agreements'].items():
        if key.startswith('groupe_'):lines.append(f'{key[7:]} : {s["wins"]}/{s["wins"]+s["losses"]} choix gagnants')
    lines+=['','ROI sur paris réglés uniquement ; résultats manquants signalés. Les catégories se chevauchent : ne pas additionner leurs mises.',
            'Classement descriptif provisoire, sans preuve automatique de supériorité. Accord 2/4 exclut les égalités 2–2.']
    return '\n'.join(lines)

def run(notify=True,probe=False,root=ROOT):
    now=datetime.now(TZ);day=now.date().isoformat();f=Fetcher();data=root/'data';data.mkdir(parents=True,exist_ok=True)
    notices_path=data/'notifications.json'
    notices=json.loads(notices_path.read_text()) if notices_path.exists() else {'notifications':[]}
    def notify_message(message):
        if notify:
            token,chat=os.environ.get('TELEGRAM_TOKEN'),os.environ.get('TELEGRAM_CHAT_ID')
            if not token or not chat:raise RuntimeError('Configuration Telegram absente')
            send(notices,message,token,chat,lambda:write(notices_path,notices),datetime.now(TZ))
    if START<=day<=END or probe:
        folder=data/day;path=folder/'state.json'
        state=json.loads(path.read_text()) if path.exists() and not probe else meeting(day,f)
        if probe:
            # Diagnose every source on the next available course, without bets.
            race=next((r for r in state['races'] if datetime.fromisoformat(r['departure'])>now),state['races'][-1])
            horses=f.json(base_url(day,race['c'])+'/participants')['participants'];results={}
            for site in SITES:
                try:
                    u=locate(site,f.get(INDEX[site].format(date=day)),race)
                    body=f.get(u);tip=parse(site,body,u,race,horses)
                    results[site]={'status':'OK','tip':tip,'evidence':proof(data/'probe',u,body)}
                except (ValueError,KeyError,TypeError,requests.RequestException) as e:results[site]={'status':'INDISPONIBLE','reason':str(e)[:200]}
            write(data/'probe'/'access.json',{'at':now.isoformat(),'race':race['id'],'results':results,'audit':f.audit})
            notify_message('🔎 COMPARATIF R1 — PRÉPARATION\n16/10 → 15/12/2026 · bilan le 16/12\nTurfin, Canalturf, ZEturf et Geny\n100 € au départ ; +100 € après perte ; retour 100 € après gain.\nArrêt à +200 € NET dans la journée.\nPlafond : 800 € de mises cumulées/jour/solution, remboursements inclus. Si la prochaine mise dépasse le reste, arrêt sans réduction.\n8 solutions indépendantes : 4 sites, accords exacts 2/4, 3/4, 4/4 et majorité 3 ou 4/4.\n\nTest d’accès depuis GitHub :\n'+'\n'.join(k+' : '+v['status'] for k,v in results.items())+'\n\nAucun résultat rétrospectif ni pari réel. Les choix du diagnostic ne comptent pas dans le test.')
            print('PROBE',json.dumps({k:v['status'] for k,v in results.items()}));return
        for race in state['races']:
            try:collect_race(race,f,folder)
            except (ValueError,KeyError,requests.RequestException) as e:race['errors']['official']={'reason':str(e)[:200]}
            write(path,state)
            if race['tips'] and datetime.now(TZ)<datetime.fromisoformat(race['departure']):notify_message(race_message(race))
    states=[]
    for path in sorted(data.glob('????-??-??/state.json')):
        state=json.loads(path.read_text())
        if not START<=state['date']<=END:continue
        for race in state['races']:
            if datetime.now(TZ)<datetime.fromisoformat(race['departure']):continue
            bets=[b for a in state['solutions'].values() for b in a['bets'] if b['race_id']==race['id']]
            if not any(t['status']=='EN_ATTENTE' for t in list(race['tips'].values())+bets):continue
            base=base_url(state['date'],race['c']);u=base+'/rapports-definitifs?specialisation=INTERNET'
            try:
                payload=f.json(u);horses=f.json(base+'/participants')['participants']
                for tip in list(race['tips'].values())+bets:
                    if settle(tip,payload,horses):
                        tip['settled_at']=datetime.now(TZ).isoformat();tip['result_evidence']=proof(path.parent,u,f.get(u))
                        tip['result_participants_evidence']=proof(path.parent,base+'/participants',f.get(base+'/participants'))
                race.pop('settlement_error',None)
            except (ValueError,KeyError,requests.RequestException) as e:race['settlement_error']=type(e).__name__
        # After previous results are settled, engage next eligible course.
        # All solutions progress independently; groups have their own accounts.
        if state['date']==day and START<=day<=END:
            for race in state['races']:
                delta=(datetime.fromisoformat(race['departure'])-datetime.now(TZ)).total_seconds()
                if not 0<delta<=1800:continue
                base=base_url(day,race['c'])
                try:
                    meta=f.json(base)
                    if (meta.get('numReunion')!=1 or meta.get('numOrdre')!=race['c'] or norm(meta.get('libelle'))!=norm(race['title']) or meta.get('heureDepart')!=int(datetime.fromisoformat(race['departure']).timestamp()*1000)):
                        raise ValueError('Identité/horaire modifié avant engagement')
                    race['market']=meta.get('hasEParis') is not False and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('enVente') is not False for x in meta.get('paris',[]))
                    horses=f.json(base+'/participants')['participants']
                    for key in STRATEGIES:
                        voters=[key] if key in SITES else race['groups'].get(key,{}).get('sites',[])
                        if not voters or voters[0] not in race['tips']:continue
                        tip=race['tips'][voters[0]]
                        horse=next((h for h in horses if h['numPmu']==tip['number']),{})
                        reserve(state['solutions'][key],race,tip,horse,datetime.now(TZ),voters)
                except (ValueError,KeyError,requests.RequestException) as e:race['errors']['reservation']={'reason':str(e)[:200]}
        write(path,state);states.append(state)
        if any(a['bets'] for a in state['solutions'].values()):notify_message(live_report(state))
    b=summary(states);b['last_checked_at']=datetime.now(TZ).isoformat()
    write(data/'BILAN.json',b)
    daily={s['date']:summary([s]) for s in states};write(data/'BILANS_JOURNALIERS.json',daily)
    message=report(b);(data/'rapport.txt').write_text(message)
    for s in states:
        (data/s['date']/'rapport.txt').write_text('\n\n'.join(race_message(r) for r in s['races'])+'\n\n'+report(daily[s['date']]))
    # One daily cumulative report at evening; retries deduplicated by content.
    if now.hour>=23 or day>END:notify_message(message)
    write(data/'last_run.json',{'at':now.isoformat(),'audit':f.audit})
    print('COMPARATIF',b['races'],b['common_settled_races'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');p.add_argument('--probe',action='store_true');a=p.parse_args()
    run(notify=not a.dry_run,probe=a.probe)
