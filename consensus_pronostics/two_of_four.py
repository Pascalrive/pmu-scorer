"""Prospective 100% 2sur4 tickets: one distinct account per profile."""
import argparse,json,re
from collections import defaultdict
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path

START='2026-10-19'
VERSION='2sur4-v1-2026-10-19'
STAKE=3
MARKET='E_DEUX_SUR_QUATRE'

def tickets(analyses,race):
    if race.get('date','')<START:return []
    out=[]
    for p in analyses['profiles']:
        ns=p['numbers'][:2]
        ready=p['qualified'] and len(set(ns))==2 and race.get('internet_2sur4_available') is True
        out.append({'version':VERSION,'profile':p['id'],'numbers':ns,'stake_eur':STAKE,
                    'market':MARKET,'percentage':100,'qualified':ready})
    return out

def numbers(row):
    v=row.get('combinaison',[])
    return [int(n) for n in v] if isinstance(v,list) else [int(n) for n in re.findall(r'\d+',str(v))]

def payout(ns,participants,reports):
    if len(ns)!=2 or len(set(ns))!=2:return None
    people={p['numPmu']:p for p in participants}
    if any(n not in people for n in ns):return None
    markets=[m for m in reports if m.get('typePari')==MARKET] if isinstance(reports,list) else []
    if len(markets)!=1:return None
    m=markets[0]
    if m.get('rembourse'):return Decimal(STAKE)
    # Partial non-runner dividends need a specific official report: keep unresolved.
    if any(people[n].get('statut') in ('NON_PARTANT','NONPARTANT') for n in ns):return None
    rows=m.get('rapports',[])
    # PMU also publishes zero-valued "5-NP" placeholders. They belong to
    # non-runner tickets, not to the ordinary two-partant market evaluated here.
    rows=[r for r in rows if not re.fullmatch(r'(?:\d+-NP|NP-\d+)',str(r.get('combinaison','')).strip(),re.IGNORECASE)]
    if not rows:return None
    try:
        rates=[Decimal(str(r['dividendePourUnEuro'])) for r in rows]
        if any(not d.is_finite() or d<=0 for d in rates):return None
        combos=[numbers(r) for r in rows]
        if any(len(c)!=2 or len(set(c))!=2 for c in combos):return None
    except (KeyError,ValueError,TypeError,InvalidOperation):return None
    hits=[i for i,c in enumerate(combos) if set(c)==set(ns)]
    if len(hits)>1:return None
    return (rates[hits[0]]*STAKE/100).quantize(Decimal('.01')) if hits else Decimal(0)

def select_ticket(snaps,ledger,profile):
    valid=[]
    for s in snaps:
        if s['race']['date']<START or not s.get('eligible_before_departure') or s['captured_at']>=s['race']['departure']:continue
        ts=s.get('analyses',{}).get('two_of_four',[])
        t=next((t for t in ts if t['profile']==profile and t.get('version')==VERSION and t.get('qualified')),None)
        if not t:continue
        if any(r.get('delivery')=='SENT' and r.get('sent_at','9999')<s['race']['departure'] and r.get('snapshot_capture')==s['captured_at'] and r.get('analyses')==s.get('analyses') for r in ledger):valid.append((s,t))
    return max(valid,key=lambda pair:pair[0]['captured_at']) if valid else None

def evaluate(root):
    from collector import Fetcher,API,norm
    f=Fetcher();groups=defaultdict(list);rows=[]
    for path in root.glob('*/R*.json'):
        s=json.loads(path.read_text())
        if s['race']['date']>=START:groups[(s['race']['date'],s['race']['id'])].append(s)
    for (day,ident),snaps in sorted(groups.items()):
        lp=root/day/'notifications.json';ledger=json.loads(lp.read_text()) if lp.exists() else []
        for profile in ('statistique','cotes','mixte'):
            selected=select_ticket(snaps,ledger,profile)
            if not selected:continue
            s,t=selected;race=s['race'];future=datetime.now(timezone.utc)<datetime.fromisoformat(race['departure'])
            people=[];reports=[];ret=None
            url=API+date.fromisoformat(day).strftime('%d%m%Y')+f'/R{race["r"]}/C{race["c"]}'
            if not future:
                try:
                    people=f.json(url+'/participants')['participants'];reports=f.json(url+'/rapports-definitifs?specialisation=INTERNET')
                    by={p['numPmu']:p for p in people}
                    if all(norm(by.get(n,{}).get('nom'))==norm(race['horses'][str(n)]['nom']) for n in t['numbers']):ret=payout(t['numbers'],people,reports)
                except Exception:pass
            rows.append({'date':day,'course':ident,'strategie':profile,'numeros':t['numbers'],'mise':STAKE,
                         'retour':float(ret) if ret is not None else None,'net':float(ret-STAKE) if ret is not None else None,
                         'statut':'AVANT_COURSE' if future else ('REGLE' if ret is not None else 'EN_ATTENTE'),
                         'capture':s['captured_at'],'version':VERSION,'result_url':url+'/rapports-definitifs?specialisation=INTERNET',
                         'rangs':[next((p.get('ordreArrivee') for p in people if p['numPmu']==n),None) for n in t['numbers']]})
    root.mkdir(parents=True,exist_ok=True)
    (root/'BILAN_2SUR4.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    lines=['# Consensus — 2 sur 4 à 100 %','', '3 € par paire et par variante ; 9 € pour trois variantes complètes. Comptes séparés même si les paires sont identiques. Simulation uniquement. Début le 19/10/2026, uniquement après envoi Telegram confirmé avant départ.','', '| Date | Variante | Paire | Mise | Retour | Net | Statut |','|---|---|---|---:|---:|---:|---|']
    for r in rows:lines.append(f'| {r["date"]} | {r["strategie"]} | {r["numeros"]} | 3 € | {r["retour"]} | {r["net"]} | {r["statut"]} |')
    lines+=['','| Variante | Réglés | Attente | Mises réglées | Retours | Net | ROI réglé |','|---|---:|---:|---:|---:|---:|---:|']
    for key in ('statistique','cotes','mixte'):
        rs=[r for r in rows if r['strategie']==key];done=[r for r in rs if r['statut']=='REGLE']
        stake=STAKE*len(done);ret=sum(Decimal(str(r['retour'])) for r in done);net=ret-stake
        roi=f'{100*net/stake:+.2f} %' if stake else '—'
        lines.append(f'| {key} | {len(done)} | {len(rs)-len(done)} | {stake:.2f} | {ret:.2f} | {net:.2f} | {roi} |')
    (root/'BILAN_2SUR4.md').write_text('\n'.join(lines))
    print('2SUR4_TRACKED',len(rows))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='consensus_pronostics/data');a=p.parse_args();evaluate(Path(a.output))

