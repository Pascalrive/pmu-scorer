"""Independent daily R1 observation and official settlement runner."""
import argparse
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from .sources import SITES, INDEX, locate, parse, norm
from .model import daily_budget, daily_target, stop_at_target, split_pair, reserve_split, place_plan, place_description
from .model import START, END, STRATEGIES, account, reserve, freeze, groups, settle, summary
from .telegram import send
from comparaison_r1.geny_fallback import read_tip, unavailable_label
from comparaison_r1.odds import odds_label
from comparaison_r1.run_health import missing_control_reason, remember_preview, urgent_course, live_window

ROOT=Path(__file__).parent
TZ=ZoneInfo('Europe/Paris')
API='https://online.turfinfo.api.pmu.fr/rest/client/61/programme/'
PREVIEW_VERSION=7

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)

class Fetcher:
    def __init__(self):self.cache={};self.audit=[];self.last_geny=None;self.blocked=set()
    def get(self,url):
        if url not in self.cache:
            host=urlparse(url).netloc
            if host in self.blocked:raise ValueError('Limitation de requêtes du site : reprise au prochain passage')
            try:
                if host=='www.geny.com':
                    if self.last_geny is not None:time.sleep(max(0,20-(time.monotonic()-self.last_geny)))
                    self.last_geny=time.monotonic()
                r=requests.get(url,timeout=20,headers={'User-Agent':'Comparaison-R1-Research/1.0'})
                self.audit.append({'url':url,'status':r.status_code,'at':datetime.now(TZ).isoformat()})
                title=BeautifulSoup(r.text,'html.parser').title if host=='www.geny.com' else None
                if r.status_code==429 or (title and 'trop de requ' in title.get_text().lower()):
                    self.blocked.add(host);self.cache[url]=None
                    raise ValueError('Site limité (429) : demandes arrêtées pour ce passage')
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

def reconcile_schedule(race, meta, now):
    if (meta.get('numReunion')!=1 or meta.get('numOrdre')!=race['c']
            or norm(meta.get('libelle'))!=norm(race['title'])):
        raise ValueError('Identité officielle modifiée : collecte suspendue')
    old=datetime.fromisoformat(race['departure'])
    new=datetime.fromtimestamp(meta['heureDepart']/1000,TZ)
    if new!=old:
        # Never reopen an elapsed betting window, even when a delay is announced late.
        if now>=old or now>=new or new.date()!=old.date():
            raise ValueError('Horaire modifié après fermeture de la fenêtre : mise suspendue')
        race.setdefault('schedule_changes',[]).append({'old':old.isoformat(),'new':new.isoformat(),'checked_at':now.isoformat()})
        race['departure']=new.isoformat()
    race['errors'].pop('official',None)
    race['errors'].pop('reservation',None)

def no_bet_reason(state,race):
    if race.get('delivery_attempt') and race.get('no_bet_reason'):
        return race['no_bet_reason']
    for key in ('reservation','official'):
        if key in race.get('errors',{}):return race['errors'][key]['reason']
    missing=missing_control_reason(race)
    if missing:return missing
    if not race.get('groups',{}).get('majorite_3_ou_4') and not place_plan(race):
        return 'Accord inférieur à 3/4 ou sources incomplètes' if race['date']>='2026-10-20' else 'Aucun accord exploitable (majorité, 2–2 ou 2–1–1)'
    bets=state.get('solutions',{}).get('majorite_3_ou_4',{}).get('bets',[])
    preceding=[b for b in bets if b['departure']<race['departure']]
    if preceding:
        last=preceding[-1]
        if not last.get('settled_at') or last['settled_at']>=race['departure']:
            return 'Résultat précédent non enregistré avant départ'
    reason=account({'bets':preceding,'target_cents':daily_target(state['date']),'stop_at_target':stop_at_target(state['date']),'budget_cents':daily_budget(state['date'])})['stop']
    return {'OBJECTIF':'Objectif net atteint','BUDGET':'Budget restant insuffisant','SERIE_TERMINEE':'Cinq pertes successives'}.get(reason,'Aucun engagement enregistré avant départ ; passage manqué ou contrôle bloqué')

def collect_race(race,f,folder,clock=lambda:datetime.now(TZ),preview=False):
    now=clock();delta=(datetime.fromisoformat(race['departure'])-now).total_seconds()
    if delta<=0 or (not preview and delta>3600):return
    if not preview:race['final_check_started_at']=now.isoformat()
    base=base_url(race['date'],race['c'])
    meta=f.json(base)
    reconcile_schedule(race,meta,now)
    race['market']=meta.get('hasEParis') is not False and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('enVente') is not False for x in meta.get('paris',[]))
    horses=f.json(base+'/participants')['participants']
    for site in SITES:
        remaining=(datetime.fromisoformat(race['departure'])-clock()).total_seconds()
        if remaining<=0:break
        if not preview and remaining<=120 and race.get('groups',{}).get('majorite_3_ou_4'):
            break
        if site in race['tips']:
            if preview:
                t=race['tips'][site]
                horse=next((h for h in horses if h['numPmu']==t['number'] and norm(h['nom'])==norm(t['name'])),None)
                if horse:
                    t['odds']=horse.get('dernierRapportDirect') or horse.get('dernierRapportReference')
                    t['playable']=horse.get('statut')=='PARTANT' and race['market']
                    t['odds_checked_at']=clock().isoformat()
                else:t['playable']=False
            continue
        try:
            u,body,tip=read_tip(site,f,race,horses)
            evidence=proof(folder,u,body)
            race.setdefault('source_checks',{})[site]=evidence
            tip['evidence']=evidence
            tip['official_evidence']=proof(folder,base+'/participants',f.get(base+'/participants'))
            horse=next(h for h in horses if h['numPmu']==tip['number'])
            if preview and clock()<datetime.fromisoformat(race['departure']):
                race['tips'][site]={**tip,'captured_at':clock().isoformat(),'stake_cents':0,
                    'status':'APERÇU','playable':horse.get('statut')=='PARTANT' and race['market'],
                    'odds':horse.get('dernierRapportDirect') or horse.get('dernierRapportReference')}
                race['errors'].pop(site,None)
            elif not preview and freeze(race,site,tip,horse,clock()):
                race['errors'].pop(site,None)
                # freeze accepted this vote before departure; never wait for a slow optional source.
                race['groups']=groups(race['tips'])
                if race['groups']:race['groups_frozen_at']=race['tips'][site]['captured_at']
        except (ValueError,KeyError,TypeError,requests.RequestException) as e:
            race['errors'][site]={'type':type(e).__name__,'reason':str(e).split('\n')[0][:200],'at':clock().isoformat()}
            if hasattr(e,'source_status'):race['errors'][site]['source_status']=e.source_status
    if not preview and clock()<datetime.fromisoformat(race['departure']):
        race['final_check_completed_at']=clock().isoformat()
        observed=groups(race['tips'])
        if observed!=race['groups']:
            race['groups']=observed
            if observed:race['groups_frozen_at']=clock().isoformat()

def euros(c):return f'{c/100:.2f} €'

def morning_preview(state,f,folder,clock=lambda:datetime.now(TZ)):
    import copy
    previous=state.get('morning_preview',{})
    if previous.get('version')==PREVIEW_VERSION and previous.get('captured_at') and (clock()-datetime.fromisoformat(previous['captured_at'])).total_seconds()<3600:return previous
    races=[]
    for original in state['races']:
        if datetime.fromisoformat(original['departure'])<=clock():continue
        race=copy.deepcopy(original);race.pop('preview_observations',None);race.update(tips={},groups={},errors={})
        # Refresh editorial choices as well as odds; old previews are not votes.
        try:
            collect_race(race,f,folder,clock,preview=True)
        except (ValueError,KeyError,requests.RequestException) as e:race['errors']['official']={'reason':str(e)[:200]}
        remember_preview(original,race,groups(race['tips']),clock())
        races.append(race)
    result={'version':PREVIEW_VERSION,'captured_at':clock().isoformat(),'races':races,
            'complete':bool(races) and all(set(r['tips'])==set(SITES) for r in races)}
    state['morning_preview']=result
    return result

def preview_report(state,preview):
    lines=['🌅 TONY ARTILLAN — MAJORITÉ 3 OU 4/4' if state['date']>='2026-10-20' else '🌅 TONY ARTILLAN — MAJORITÉ ET SIMPLES PLACÉS',state['date']+' · '+state['venue'],
           'Aperçu et cotes contrôlés à '+datetime.fromisoformat(preview['captured_at']).strftime('%Hh%M')+'. Vérification dans la dernière heure avant départ.',
           'Mises : 100 → 200 → 150 → 150 → 200 € après pertes. Gain : retour 100 €.',
           ('3/4 ou 4/4 : un simple gagnant progressif. Aucun pari placé ; accords 2–2 et 2–1–1 exclus.' if state['date']>='2026-10-20' else '3/4 ou 4/4 : simple gagnant progressif. Égalité 2–2 : 50 € placés par cheval. Accord 2–1–1 : 50 € placés sur le cheval cité deux fois. Exception R1C6 du 19/10 : 25 € placés sur le 7 et le 11.'),
           'Un seul compte : repère +200 € NET, sans arrêt à ce seuil depuis le 19/10 ; plafond 1 200 € de mises. Simulation uniquement.','']
    names={'turfin':'Turfin','canalturf':'Canalturf','zeturf':'ZEturf','geny':'Geny'}
    for race in preview['races']:
        lines.append(f'{race["id"]} · {datetime.fromisoformat(race["departure"]).strftime("%Hh%M")} — {race["title"]}')
        for site in SITES:
            t=race['tips'].get(site)
            if t:
                quote=(t.get('odds') or {}).get('rapport','—')
                lines.append(f'{names[site]}'+(' (secours Genybet)' if t.get('fallback') else '')+f' : N°{t["number"]} {t["name"]} · {odds_label(t)}'+(' · NON PARTANT / non jouable' if not t['playable'] else ''))
            else:lines.append(names[site]+' : '+unavailable_label(race,site))
        g=groups(race['tips']).get('majorite_3_ou_4')
        if place_plan(race):lines.append(place_description(race))
        elif g:lines.append(f'✅ ADMISSIBLE {len(g["sites"])}/4 : N°{g["number"]} — un seul pari potentiel')
        else:lines.append('⏭ AUCUN PARI : moins de trois premiers choix concordants et validés sur les quatre sites' if state['date']>='2026-10-20' else '⏭ AUCUN PARI : aucun accord exploitable ou exception indisponible')
        lines.append('')
    lines.append('Seules les courses admissibles font avancer la progression, sous réserve du résultat précédent et des limites quotidiennes.')
    lines.append('Aucune mise engagée par cet aperçu. ZEturf : sélection attribuée à ZEturf sur Canalturf. Les choix définitifs et mises seront envoyés avant chaque départ.')
    return '\n'.join(lines)

def race_message(r):
    lines=[f'🔎 TONY ARTILLAN — {r["date"]}',f'{r["id"]} · {datetime.fromisoformat(r["departure"]).strftime("%Hh%M")} · {r["title"]}',
           'Choix observés — majorité 3/4 ou 4/4, simple gagnant uniquement' if r['date']>='2026-10-20' else 'Choix observés — majorité SG ou accords 2–2 / 2–1–1 en SP', '']
    for site in SITES:
        t=r['tips'].get(site)
        if not t:lines.append(site.upper()+' : '+unavailable_label(r,site));continue
        q=t.get('odds') or {}
        lines.append(f'{site.upper()}'+(' (secours Genybet)' if t.get('fallback') else '')+f' : N°{t["number"]} {t["name"]} · {odds_label(t)}'+(' · non jouable' if not t['playable'] else ''))
        if 'return_cents' in t:lines.append(f'  Résultat du choix : {t["status"]}')
    g=r['groups'].get('majorite_3_ou_4')
    if place_plan(r):lines+=['',place_description(r)+' · sous réserve du budget.']
    elif g:lines+=['',f'✅ ADMISSIBLE {len(g["sites"])}/4 : N°{g["number"]}', ' + '.join(g['sites']), 'Un seul pari potentiel, selon budget et résultat précédent.']
    else:lines+=['','⏭ AUCUN PARI : moins de trois premiers choix concordants et validés sur les quatre sites.' if r['date']>='2026-10-20' else '⏭ AUCUN PARI : aucun accord exploitable ou exception indisponible.']
    lines+=['Les choix sont figés avant départ. ZEturf est lu dans sa rubrique sur Canalturf.','Cotes indicatives ; règlement aux rapports définitifs PMU INTERNET.']
    return '\n'.join(lines)

def live_report(state):
    lines=['💶 TONY ARTILLAN — SUIVI DES MISES',state['date']+' · '+state['venue'],
           'Simulation · Pertes successives : 100 → 200 → 150 → 150 → 200 €, puis arrêt. Gain : retour 100 €.',
           (f'Arrêt à +{daily_target(state["date"])/100:.0f} € NET' if stop_at_target(state['date']) else 'Repère +200 € NET, sans arrêt au seuil')+f' ; plafond {daily_budget(state["date"])/100:.0f} € de mises/jour, compte unique.', '']
    for key in STRATEGIES:
        sol=state['solutions'][key];a=account(sol)
        lines.append('COMPTE UNIQUE — MAJORITÉ SG' if state['date']>='2026-10-20' else 'COMPTE UNIQUE — MAJORITÉ SG + SIMPLES PLACÉS')
        if sol['bets']:
            latest=sol['bets'][-1]['race_id']
            for b in [b for b in sol['bets'] if b['race_id']==latest]:
                kind='Simple placé' if b.get('market')=='E_SIMPLE_PLACE' else 'Simple gagnant'
                lines.append(f'{b["race_id"]} N°{b["number"]} {b["name"]} · {kind} · mise {euros(b["stake_cents"])} · {b["status"]}')
                if 'return_cents' in b:lines.append('Retour '+euros(b['return_cents'])+' · net du pari '+euros(b['profit_cents']))
        else:lines.append('Aucun pari engagé')
        lines.append('Net réglé du jour '+euros(a['profit_cents'])+' · engagé '+euros(a['committed_cents'])+' / '+euros(a['budget_cents']))
        finished=all(datetime.now(TZ)>=datetime.fromisoformat(r['departure']) for r in state['races'])
        lines.append('Réunion terminée — aucune nouvelle mise.' if finished else ('Statut : '+a['stop'] if a['stop'] else 'Prochaine mise SG conditionnelle : '+euros(a['next_stake_cents'])))
        if state['date']=='2026-10-19' and a['stop']=='BUDGET' and a['remaining_cents']>=5000:
            lines.append('Budget insuffisant pour le prochain SG ; un pari placé fixe reste possible si sa mise totale tient dans le solde disponible.')
        lines.append('')
    played={b['race_id'] for b in state['solutions']['majorite_3_ou_4']['bets']}
    skipped=[r for r in state['races'] if r['id'] not in played and r.get('no_bet_reason')]
    if skipped:
        lines.append('COURSES NON JOUÉES')
        lines.extend(r['id']+' : '+r['no_bet_reason'] for r in skipped)
    lines.append('Un seul compte : majorité 3/4 ou 4/4 en simple gagnant uniquement depuis le 20/10. Les SP du 19/10 restent dans les bilans historiques. Remboursements inclus dans le plafond. Aucun pari réel.')
    return '\n'.join(lines)

def daily_report(state):
    sol=state['solutions']['majorite_3_ou_4'];a=account(sol)
    lines=['📅 TONY ARTILLAN — BILAN DU JOUR',state['date']+' · '+state['venue'],
           'Simulation majorité SG uniquement depuis le 20/10 · toutes les courses observées',
           ('Repère +200 € : les mises continuent après ce seuil.' if not stop_at_target(state['date']) else 'Ancienne règle : arrêt au seuil de la journée.'),
           f'Plafond {daily_budget(state["date"])/100:.0f} € et arrêt après cinq pertes successives conservés.','']
    running=0;peak=0;first=None;max_drawdown=0
    for r in state['races']:
        lines.append(r['id']+' — '+r['title'])
        arrival=r.get('official_arrival',[])
        lines.append('Arrivée : '+(' · '.join(str(h['rank'])+'e N°'+str(h['number'])+' '+h['name'] for h in arrival) if arrival else 'EN ATTENTE — arrivée non vérifiée'))
        batch=[b for b in sol['bets'] if b['race_id']==r['id']];g=r.get('groups',{}).get('majorite_3_ou_4')
        if batch:
            for b in batch:
                kind='SP' if b.get('market')=='E_SIMPLE_PLACE' else 'SG'
                lines.append(f'N°{b["number"]} {b["name"]} · {kind} · mise {euros(b["stake_cents"])} · {b["status"]}')
                if 'return_cents' in b:lines.append('Retour '+euros(b['return_cents'])+' · net '+euros(b['profit_cents']))
                else:lines.append('Rapport en attente — net non calculé')
            if all('return_cents' in b for b in batch):
                running+=sum(b['profit_cents'] for b in batch);peak=max(peak,running);max_drawdown=max(max_drawdown,peak-running)
                if first is None and running>=a['target_cents']:first={'race':r['id'],'profit':running}
                lines.append('Cumul après la course : '+euros(running))
        else:
            if g:
                tip=r['tips'][g['sites'][0]]
                lines.append(f'Choix majorité : N°{g["number"]} · '+tip['status'])
            lines.append('Non joué : '+(r.get('no_bet_reason') or 'course à venir / engagement non confirmé'))
        lines.append('')
    settled_stake=a['committed_cents']-a['pending_stake_cents']
    lines+=['TOTAL DU JOUR : mises engagées '+euros(a['committed_cents'])+' · retours réglés '+euros(a['return_cents']),
            'NET RÉGLÉ : '+euros(a['profit_cents'])+' · ROI '+(f'{100*a["profit_cents"]/settled_stake:+.2f} %' if settled_stake else 'non calculable'),
            'Mises en attente : '+euros(a['pending_stake_cents']),
            'Premier seuil atteint : '+(first['race']+' à '+euros(first['profit']) if first else 'non atteint'),
            'Maximum du solde réglé : '+euros(peak)+' · recul maximal depuis un sommet : '+euros(max_drawdown)]
    if first:lines.append('Écart final / arrêt au premier seuil : '+euros(a['profit_cents']-first['profit']))
    lines.append('Les courses sans mise ne sont pas ajoutées rétroactivement au résultat financier.')
    return '\n'.join(lines)

def report(b):
    lines=['📊 TONY ARTILLAN — BILAN CUMULÉ',f'{START} → {END} · mises progressives virtuelles',
           'Pertes successives : 100 → 200 → 150 → 150 → 200 €, puis arrêt. Gain : retour 100 €. Repère +200 € net/jour : arrêt le 18/10, observation sans arrêt au seuil depuis le 19/10 (500 € avant le 18/10) ; plafond mises 1 200 €/jour, compte unique.',
           f'{b["races"]} courses enregistrées · {b["common_settled_races"]} communes réglées',
           '', 'BILAN FINANCIER — TONY ARTILLAN (SG + SP)']
    def line(name,s):
        return f'{name} : {s["wins"]}/{s["wins"]+s["losses"]} gagnants · ROI {s["roi_percent"] if s["roi_percent"] is not None else "—"} % · net {euros(s["profit_cents"])} · {s["pending"]} en attente'
    for key in b['ranking_by_net_profit']:
        s=b['solutions'][key]
        lines.append(line('Tony Artillan',s)+f' · objectif atteint {s["days_target_reached"]}/{s["days_active"]} jours actifs')
    for market,stats in b['solutions']['majorite_3_ou_4'].get('by_market',{}).items():
        lines.append(line('Majorité SG' if market=='E_SIMPLE_GAGNANT' else 'Simples placés fixes',stats))
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
    lines+=['','ROI sur paris réglés uniquement ; résultats manquants signalés. Les autres catégories sont descriptives, sans mise.',
            'Classement descriptif provisoire, sans preuve automatique de supériorité. Accord 2/4 exclut les égalités 2–2.']
    return '\n'.join(lines)

def confirmed_before(receipt,departure):
    if not receipt or receipt.get('status')!='SENT' or not receipt.get('receipts'):return False
    end=datetime.fromisoformat(departure).timestamp()
    return all(type(r.get('date')) is int and type(r.get('message_id')) is int and r['date']<end for r in receipt['receipts'])


def settle_state(state,f,folder,pending_only=False):
    pending_ids={b['race_id'] for a in state.get('solutions',{}).values() for b in a['bets'] if b['status']=='EN_ATTENTE'}
    for race in sorted(state['races'],key=lambda r:r['id'] not in pending_ids):
        if pending_only and race['id'] not in pending_ids:continue
        if urgent_course(state,datetime.now(TZ)) and race['id'] not in pending_ids:continue
        if datetime.now(TZ)<datetime.fromisoformat(race['departure']):continue
        bets=[b for a in state['solutions'].values() for b in a['bets'] if b['race_id']==race['id']]
        if race.get('official_arrival') and not any(t['status']=='EN_ATTENTE' for t in list(race['tips'].values())+bets):continue
        base=base_url(state['date'],race['c']);u=base+'/rapports-definitifs?specialisation=INTERNET'
        try:
            payload=f.json(u);horses=f.json(base+'/participants')['participants']
            if isinstance(payload,list) and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('rapports') for x in payload):
                race['official_arrival']=[{'number':h['numPmu'],'name':h['nom'],'rank':h['ordreArrivee']} for h in sorted(horses,key=lambda h:h.get('ordreArrivee') or 999) if isinstance(h.get('ordreArrivee'),int) and 1<=h['ordreArrivee']<=5]
                race['arrival_evidence']=proof(folder,base+'/participants',f.get(base+'/participants'))
            for tip in list(race['tips'].values())+bets:
                if settle(tip,payload,horses):
                    tip['settled_at']=datetime.now(TZ).isoformat();tip['result_evidence']=proof(folder,u,f.get(u))
                    tip['result_participants_evidence']=proof(folder,base+'/participants',f.get(base+'/participants'))
            race.pop('settlement_error',None)
        except (ValueError,KeyError,requests.RequestException) as e:race['settlement_error']=type(e).__name__

def run(notify=True,probe=False,root=ROOT,announce=False):
    now=datetime.now(TZ);day=now.date().isoformat();f=Fetcher();data=root/'data';data.mkdir(parents=True,exist_ok=True)
    notices_path=data/'notifications.json'
    notices=json.loads(notices_path.read_text()) if notices_path.exists() else {'notifications':[]}
    def notify_message(message):
        if notify:
            token,chat=os.environ.get('TELEGRAM_TOKEN'),os.environ.get('TELEGRAM_CHAT_ID')
            if not token or not chat:raise RuntimeError('Configuration Telegram absente')
            send(notices,message,token,chat,lambda:write(notices_path,notices),datetime.now(TZ))
            fingerprint=hashlib.sha256(message.encode()).hexdigest()
            return next((n for n in reversed(notices['notifications']) if n['fingerprint']==fingerprint),None)
    if day>='2026-10-19':
        notify_message('🔄 TONY ARTILLAN — RETOUR À LA MAJORITÉ\nÀ partir du 20/10/2026 : un simple gagnant uniquement si au moins 3 des 4 premiers choix sont identiques en R1.\nAucun nouveau pari placé, ni accord 2–2 ou 2–1–1.\nMises après pertes : 100 → 200 → 150 → 150 → 200 €, puis arrêt ; gain : retour à 100 €.\nPlafond 1 200 €/jour. +200 € reste un repère sans arrêt.\nLes paris du 19/10 restent dans le bilan. Simulation uniquement.')
    if announce:
        notify_message('🔄 TONY ARTILLAN — RÈGLE CORRIGÉE\n16/10 → 15/12/2026\n\nSuite après pertes successives :\n1. 100 €\n2. 200 €\n3. 150 €\n4. 150 €\n5. 200 € puis arrêt\n\nAprès un gain : retour à 100 €.\nRepère : +200 € NET par jour, sans arrêt à ce seuil depuis le 19/10.\nPlafond : 1 200 € de mises cumulées par jour/scénario, remboursements inclus. Aucun dépassement ni réduction de mise.\n\nUn seul compte : pari simple gagnant uniquement si au moins 3 des 4 sites donnent le même premier choix. Aucun pari individuel ni doublon par combinaison. Simulation uniquement.\nLes égalités 2–2 sont jouées en simples placés : 50 € par cheval. Bilan final le 16 décembre.')
        return
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
            notify_message('🔎 TONY ARTILLAN — PRÉPARATION\n16/10 → 15/12/2026 · bilan le 16/12\nTurfin, Canalturf, ZEturf et Geny\nPertes successives : 100 → 200 → 150 → 150 → 200 €, puis arrêt. Gain : retour 100 €.\nRepère +200 € NET, sans arrêt à ce seuil depuis le 19/10.\nPlafond : 1 200 € de mises cumulées/jour/solution, remboursements inclus. Si la prochaine mise dépasse le reste, arrêt sans réduction.\nUn seul compte : majorité 3 ou 4/4 uniquement. Autres catégories observées sans mise.\n\nTest d’accès depuis GitHub :\n'+'\n'.join(k+' : '+v['status'] for k,v in results.items())+'\n\nAucun résultat rétrospectif ni pari réel. Les choix du diagnostic ne comptent pas dans le test.')
            print('PROBE',json.dumps({k:v['status'] for k,v in results.items()}));return
        settle_state(state,f,folder,pending_only=True)
        write(path,state)
        for race in sorted(state['races'],key=lambda r:r['departure']):
            urgent=urgent_course(state,datetime.now(TZ))
            if urgent and race['id']!=urgent['id']:continue
            try:collect_race(race,f,folder)
            except (ValueError,KeyError,requests.RequestException) as e:race['errors']['official']={'reason':str(e)[:200]}
            write(path,state)
            if race['tips'] and datetime.now(TZ)<datetime.fromisoformat(race['departure']) and not urgent_course(state,datetime.now(TZ)):
                notify_message(race_message(race))
    states=[]
    current_path=data/day/'state.json'
    history_deferred=live_window(json.loads(current_path.read_text()),datetime.now(TZ)) if current_path.exists() else False
    for path in sorted(data.glob('????-??-??/state.json'),key=lambda p:(p.parent.name!=day,p.parent.name)):
        state=json.loads(path.read_text())
        if not START<=state['date']<=END:continue
        if state['date']!=day and history_deferred:
            states.append(state)
            continue
        for key in STRATEGIES:
            state.setdefault('solutions',{}).setdefault(key,{'bets':[]})
            state['solutions'][key]['budget_cents']=daily_budget(state['date'])
            state['solutions'][key]['target_cents']=daily_target(state['date'])
            state['solutions'][key]['stop_at_target']=stop_at_target(state['date'])
        settle_state(state,f,path.parent)
        played={b['race_id'] for a in state['solutions'].values() for b in a['bets']}
        for race in state['races']:
            if race['id'] not in played and datetime.now(TZ)>=datetime.fromisoformat(race['departure']):
                race['no_bet_reason']=no_bet_reason(state,race)
        # After previous results are settled, engage next eligible course.
        # Place stakes share the account but do not advance the SG progression.
        if state['date']==day and START<=day<=END:
            for race in state['races']:
                delta=(datetime.fromisoformat(race['departure'])-datetime.now(TZ)).total_seconds()
                if not 0<delta<=1800:continue
                base=base_url(day,race['c'])
                try:
                    f.cache.pop(base,None)
                    f.cache.pop(base+'/participants',None)
                    meta=f.json(base)
                    reconcile_schedule(race,meta,datetime.now(TZ))
                    race['market']=meta.get('hasEParis') is not False and any(x.get('typePari')=='E_SIMPLE_GAGNANT' and x.get('enVente') is not False for x in meta.get('paris',[]))
                    horses=f.json(base+'/participants')['participants']
                    place_market=meta.get('hasEParis') is not False and any(p.get('typePari')=='E_SIMPLE_PLACE' and p.get('enVente') is not False for p in meta.get('paris',[]))
                    if place_plan(race) or (race['date']=='2026-10-19' and race['id']=='R1C6'):
                        if reserve_split(state['solutions']['majorite_3_ou_4'],race,horses,datetime.now(TZ),place_market):race.pop('no_bet_reason',None)
                        continue
                    for key in STRATEGIES:
                        voters=[key] if key in SITES else race['groups'].get(key,{}).get('sites',[])
                        if not voters or voters[0] not in race['tips']:continue
                        tip=race['tips'][voters[0]]
                        horse=next((h for h in horses if h['numPmu']==tip['number']),{})
                        import copy
                        candidate=copy.deepcopy(state)
                        if reserve(candidate['solutions'][key],race,tip,horse,datetime.now(TZ),voters):
                            message=live_report(candidate)
                            receipt=notify_message(message)
                            if confirmed_before(receipt,race['departure']):
                                bet=candidate['solutions'][key]['bets'][-1]
                                bet['telegram_fingerprint']=receipt['fingerprint']
                                bet['telegram_receipts']=receipt['receipts']
                                state['solutions'][key]['bets'].append(bet)
                                race.pop('no_bet_reason',None)
                                write(path,state)
                            else:
                                race['no_bet_reason']='Envoi Telegram avant départ non confirmé ; aucune mise comptabilisée'
                                race['delivery_attempt']={'at':datetime.now(TZ).isoformat(),'status':receipt['status'] if receipt else 'DRY_RUN'}
                        else:
                            race['last_reservation_check']={'at':datetime.now(TZ).isoformat(),'stop':account(state['solutions'][key])['stop']}
                except (ValueError,KeyError,requests.RequestException) as e:race['errors']['reservation']={'reason':str(e)[:200]}
        played={b['race_id'] for b in state['solutions']['majorite_3_ou_4']['bets']}
        for race in state['races']:
            if race['id'] not in played and datetime.now(TZ)>=datetime.fromisoformat(race['departure']):
                race['no_bet_reason']=no_bet_reason(state,race)
        write(path,state);states.append(state)
        if state['date']==day and any(a['bets'] for a in state['solutions'].values()):notify_message(live_report(state))
    if not probe:
        for state in states:
            if state['date']!=day:continue
            folder=data/day;path=folder/'state.json'
            preview=morning_preview(state,f,folder) if now.hour>=7 and not urgent_course(state,datetime.now(TZ),seconds=600) else {}
            write(path,state)
            if preview.get('races'):
                preview_text=preview_report(state,preview)
                (folder/'apercu.txt').write_text(preview_text)
                notify_message(preview_text)
    b=summary(states);b['last_checked_at']=datetime.now(TZ).isoformat()
    write(data/'BILAN.json',b)
    daily={s['date']:summary([s]) for s in states};write(data/'BILANS_JOURNALIERS.json',daily)
    message=report(b);(data/'rapport.txt').write_text(message)
    for s in states:
        (data/s['date']/'rapport.txt').write_text('\n\n'.join(race_message(r) for r in s['races'])+'\n\n'+report(daily[s['date']]))
    for s in states:
        text=daily_report(s)
        (data/s['date']/'bilan_du_jour.txt').write_text(text)
        if s['date']==day and s['races'] and now>=max(datetime.fromisoformat(r['departure']) for r in s['races']):
            notify_message(text)
    # One daily cumulative report at evening; retries deduplicated by content.
    if now.hour>=23 or day>END:notify_message(message)
    write(data/'last_run.json',{'at':now.isoformat(),'audit':f.audit})
    print('COMPARATIF',b['races'],b['common_settled_races'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');p.add_argument('--probe',action='store_true');p.add_argument('--announce',action='store_true');a=p.parse_args()
    run(notify=not a.dry_run,probe=a.probe,announce=a.announce)




