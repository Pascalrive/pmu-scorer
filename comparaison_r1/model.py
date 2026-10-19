"""Progressive-stake prospective comparison, integer cents, no actual bets."""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
import math
import re
from .sources import SITES, norm

START='2026-10-16'
END='2026-12-15'
BASE=10000
STAKES=(10000,20000,15000,15000,20000)
BUDGET=120000

def daily_budget(day):
    return BUDGET if day>='2026-10-19' else 80000

TARGET=20000
TARGET_EFFECTIVE_DATE='2026-10-18'

FULL_DAY_FROM='2026-10-19'

def stop_at_target(day):
    return day<FULL_DAY_FROM

def daily_target(day):
    return TARGET if day>=TARGET_EFFECTIVE_DATE else 50000

COMBINATIONS=tuple('groupe_'+'+'.join(sorted(c)) for size in (2,3,4) for c in combinations(SITES,size))
# Only this account can engage stakes; other groups remain descriptive.
STRATEGIES=('majorite_3_ou_4',)
SETTLED={'GAGNE','PERDU','REMBOURSE'}

def freeze(race, site, tip, horse, now):
    if site in race['tips'] or not START<=race['date']<=END:
        return False
    delta=(datetime.fromisoformat(race['departure'])-now).total_seconds()
    if not 0<delta<=3600 or horse['numPmu']!=tip['number'] or norm(horse['nom'])!=norm(tip['name']):
        return False
    if horse.get('statut') not in ('PARTANT','NON_PARTANT'):return False
    race['tips'][site]={**tip,'captured_at':now.isoformat(),
        'odds':horse.get('dernierRapportDirect') or horse.get('dernierRapportReference'),
        'stake_cents':0,
        'playable':horse['statut']=='PARTANT' and race['market'],
        'status':'EN_ATTENTE' if horse['statut']=='PARTANT' and race['market'] else 'NON_JOUE'}
    return True

def groups(tips):
    # Denominator always four: missing source is never an abstention vote.
    if set(tips)!=set(SITES) or any(not t.get('playable') for t in tips.values()):return {}
    by=defaultdict(list)
    for site in SITES:by[tips[site]['number']].append(site)
    ranked=sorted(by.items(),key=lambda x:-len(x[1]))
    n,voters=ranked[0];count=len(voters)
    if count<2 or (len(ranked)>1 and len(ranked[1][1])==count):return {}
    result={f'accord_{count}_sur_4':{'number':n,'sites':voters}}
    if count>=3:result['majorite_3_ou_4']={'number':n,'sites':voters}
    # Exact combination prevents double counting a unanimous race as six pairs.
    result['groupe_'+'+'.join(sorted(voters))]={'number':n,'sites':voters}
    return result

def split_pair(tips):
    if set(tips)!=set(SITES) or any(not t.get('playable') for t in tips.values()):return []
    by=defaultdict(list)
    for site in SITES:by[tips[site]['number']].append(site)
    return [{'number':n,'sites':v} for n,v in sorted(by.items())] if len(by)==2 and all(len(v)==2 for v in by.values()) else []

def place_plan(race):
    """Fixed place stakes; the explicitly approved exception is date-scoped."""
    if race['date']<'2026-10-19':return []
    tips=race['tips']
    if race['date']=='2026-10-19' and race['id']=='R1C6':
        if set(tips)!=set(SITES) or any(not t.get('playable') for t in tips.values()):return []
        picks=[]
        for number,name in ((7,'VINGT SEPT'),(11,'BRAMANS')):
            sites=[site for site,t in tips.items() if t['number']==number and norm(t['name'])==norm(name)]
            if not sites:return []
            picks.append({'number':number,'sites':sites,'stake_cents':2500,'variant':'exception_2026_10_19_R1C6'})
        return picks
    pair=split_pair(tips)
    if pair:return [{**g,'stake_cents':5000,'variant':'egalite_2_2'} for g in pair]
    g=groups(tips).get('accord_2_sur_4')
    return [{**g,'stake_cents':5000,'variant':'accord_2_1_1'}] if g else []

def place_description(race):
    plan=place_plan(race)
    if not plan:return ''
    label={'egalite_2_2':'ÉGALITÉ 2–2','accord_2_1_1':'ACCORD 2–1–1','exception_2026_10_19_R1C6':'EXCEPTION DU 19/10 — R1C6'}[plan[0]['variant']]
    return '✅ '+label+' : '+' + '.join(f"N°{g['number']} · simple placé {g['stake_cents']/100:.0f} €" for g in plan)

def reserve_split(solution,race,horses,now,place_market):
    pairs=place_plan(race);a=account(solution)
    if race['date']<'2026-10-19' or not START<=race['date']<=END or not place_market or not pairs:return False
    if a['pending_stake_cents'] or a['committed_cents']+sum(g['stake_cents'] for g in pairs)>a['budget_cents']:return False
    if a['stop'] in ('OBJECTIF','SERIE_TERMINEE') or any(b['race_id']==race['id'] for b in solution['bets']):return False
    if not 0<(datetime.fromisoformat(race['departure'])-now).total_seconds()<=1800:return False
    new=[]
    for g in pairs:
        t=race['tips'][g['sites'][0]]
        h=next((h for h in horses if h.get('numPmu')==g['number'] and norm(h.get('nom'))==norm(t['name'])),{})
        if h.get('statut')!='PARTANT' or datetime.fromisoformat(t['captured_at'])>now:return False
        new.append({'race_id':race['id'],'departure':race['departure'],'number':g['number'],'name':t['name'],
                    'stake_cents':g['stake_cents'],'market':'E_SIMPLE_PLACE','variant':g['variant'],'status':'EN_ATTENTE',
                    'reserved_at':now.isoformat(),'source_captured_at':t['captured_at'],'sites':g['sites'],
                    'odds':h.get('dernierRapportDirect') or h.get('dernierRapportReference')})
    solution['bets'].extend(new)
    return True

def settle(tip, payload, horses):
    if tip['status']!='EN_ATTENTE':return False
    horse=next((h for h in horses if h.get('numPmu')==tip['number']),None)
    if not horse or norm(horse.get('nom'))!=norm(tip['name']):return False
    tables=[t for t in payload if t.get('typePari')==tip.get('market','E_SIMPLE_GAGNANT')] if isinstance(payload,list) else []
    if len(tables)!=1:return False
    table=tables[0]
    stake=tip['stake_cents']
    if table.get('rembourse') is True or horse.get('statut')=='NON_PARTANT':
        status,returned='REMBOURSE',stake
    else:
        rows=table.get('rapports') or []
        if not rows:return False
        try:
            rates=[Decimal(str(r['dividendePourUnEuro'])) for r in rows]
        except (KeyError,InvalidOperation,ValueError,TypeError):return False
        if any(not r.is_finite() or r<=0 for r in rates):return False
        if any(not re.fullmatch(r'\d+',str(r.get('combinaison','')).strip()) for r in rows):return False
        winners=[r for r in rows if int(r['combinaison'])==tip['number']]
        if len(winners)>1:return False
        status='GAGNE' if winners else 'PERDU'
        returned=int((stake*Decimal(str(winners[0]['dividendePourUnEuro']))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if winners else 0
    tip.update(status=status,return_cents=returned,profit_cents=returned-stake,rank=horse.get('ordreArrivee'))
    return True

def metrics(tips):
    done=[t for t in tips if t['status'] in SETTLED]
    wins=sum(t['status']=='GAGNE' for t in done)
    losses=sum(t['status']=='PERDU' for t in done)
    stake=sum(t['stake_cents'] for t in done);ret=sum(t['return_cents'] for t in done)
    current=longest=0
    for t in tips:
        if t['status']=='PERDU':current+=1;longest=max(current,longest)
        elif t['status'] not in ('REMBOURSE','NON_JOUE'):current=0
    n=wins+losses
    # Wilson descriptive interval: not a proof of superiority, repeated horses
    # and same-course tips are dependent.
    interval=None
    if n:
        z=1.96;p=wins/n;den=1+z*z/n
        middle=(p+z*z/(2*n))/den
        half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        interval=[round(100*(middle-half),2),round(100*(middle+half),2)]
    return {'recorded':len(tips),'settled':len(done),'wins':wins,'losses':losses,
        'refunds':sum(t['status']=='REMBOURSE' for t in done),
        'pending':sum(t['status']=='EN_ATTENTE' for t in tips),'not_played':sum(t['status']=='NON_JOUE' for t in tips),
        'stake_cents':stake,'return_cents':ret,'profit_cents':ret-stake,
        'roi_percent':round(100*(ret-stake)/stake,2) if stake else None,
        'win_percent':round(100*wins/n,2) if n else None,
        'win_wilson95_percent':interval,'longest_observed_loss_streak':longest}

def account(solution):
    bets=solution['bets'];losses=0
    for b in bets:
        if b.get('market')=='E_SIMPLE_PLACE':continue
        if b['status']=='PERDU':losses+=1
        elif b['status']=='GAGNE':losses=0
    next_stake=STAKES[losses] if losses<len(STAKES) else None
    committed=sum(b['stake_cents'] for b in bets)
    returned=sum(b.get('return_cents',0) for b in bets)
    settled_stakes=sum(b['stake_cents'] for b in bets if b['status'] in SETTLED)
    profit=returned-settled_stakes
    balance=0;peak=0;first_target=None;max_drawdown=0
    batches=defaultdict(list)
    for i,b in enumerate(bets):batches[b.get('race_id',str(i))].append(b)
    for race_id,batch in batches.items():
        if any(b['status'] not in SETTLED for b in batch):break
        balance+=sum(b.get('return_cents',0)-b['stake_cents'] for b in batch)
        peak=max(peak,balance);max_drawdown=max(max_drawdown,peak-balance)
        if first_target is None and balance>=solution.get('target_cents',TARGET):first_target={'race_id':race_id,'profit_cents':balance}
    pending=any(b['status']=='EN_ATTENTE' for b in bets)
    stop='ATTENTE_RESULTAT' if pending else ('OBJECTIF' if solution.get('stop_at_target',True) and profit>=solution.get('target_cents',TARGET) else ('SERIE_TERMINEE' if next_stake is None else ('BUDGET' if committed+next_stake>solution.get('budget_cents',BUDGET) else None)))
    return {'first_target':first_target,'peak_profit_cents':peak,'max_drawdown_cents':max_drawdown,'stop_at_target':solution.get('stop_at_target',True),'target_cents':solution.get('target_cents',TARGET),'committed_cents':committed,'budget_cents':solution.get('budget_cents',BUDGET),'remaining_cents':solution.get('budget_cents',BUDGET)-committed,
            'return_cents':returned,'profit_cents':profit,'next_stake_cents':next_stake,
            'pending_stake_cents':committed-settled_stakes,'consecutive_losses':losses,'stop':stop}

def reserve(solution,race,tip,horse,now,voters=None):
    a=account(solution)
    if a['stop'] or any(b['race_id']==race['id'] for b in solution['bets']):return False
    if not START<=race['date']<=END or not race['market'] or not tip.get('playable'):return False
    delta=(datetime.fromisoformat(race['departure'])-now).total_seconds()
    if not 0<delta<=1800:return False
    if horse.get('statut')!='PARTANT' or horse.get('numPmu')!=tip['number'] or norm(horse.get('nom'))!=norm(tip['name']):return False
    if datetime.fromisoformat(tip['captured_at'])>now:return False
    solution['bets'].append({'race_id':race['id'],'departure':race['departure'],
        'number':tip['number'],'name':tip['name'],'stake_cents':a['next_stake_cents'],
        'status':'EN_ATTENTE','reserved_at':now.isoformat(),'source_captured_at':tip['captured_at'],
        'sites':voters or [tip['site']],'odds':horse.get('dernierRapportDirect') or horse.get('dernierRapportReference')})
    return True

def summary(states):
    races=sorted([r for s in states for r in s['races']],key=lambda r:(r['departure'],r['id']))
    common=[r for r in races if set(r['tips'])==set(SITES) and all(t['status'] in SETTLED for t in r['tips'].values())]
    out={'period':[START,END],'loss_sequence_cents':list(STAKES),'base_stake_cents':BASE,'daily_stake_cap_cents':daily_budget(states[0]['date']) if len(states)==1 else BUDGET,'daily_profit_target_cents':daily_target(states[0]['date']) if len(states)==1 else TARGET,'target_effective_date':TARGET_EFFECTIVE_DATE,'races':len(races),'common_settled_races':len(common),
         'individual':{},'common':{},'agreements':{},'paired_comparisons':{}}
    for site in SITES:
        out['individual'][site]=metrics([r['tips'][site] for r in races if site in r['tips']])
        out['individual'][site]['missing_races']=sum(site not in r['tips'] for r in races)
        out['common'][site]=metrics([r['tips'][site] for r in common])
    categories=defaultdict(list)
    for r in races:
        for key,g in r.get('groups',{}).items():categories[key].append((r,g))
    for key,pairs in categories.items():
        tips=[r['tips'][g['sites'][0]] for r,g in pairs]
        row=metrics(tips)
        eligible=[(r,g) for r,g in pairs if set(r['tips'])==set(SITES) and all(t['status'] in SETTLED for t in r['tips'].values())]
        row['same_race_baselines']={site:metrics([r['tips'][site] for r,g in eligible]) for site in SITES}
        out['agreements'][key]=row
    for a,b in combinations(SITES,2):
        a_only=sum(r['tips'][a]['status']=='GAGNE' and r['tips'][b]['status']=='PERDU' for r in common)
        b_only=sum(r['tips'][b]['status']=='GAGNE' and r['tips'][a]['status']=='PERDU' for r in common)
        out['paired_comparisons'][a+' / '+b]={'a_wins_b_loses':a_only,'b_wins_a_loses':b_only}
    out['solutions']={}
    for key in STRATEGIES:
        accounts=[{**s.get('solutions',{}).get(key,{'bets':[]}),'target_cents':daily_target(s['date']),'stop_at_target':stop_at_target(s['date']),'budget_cents':daily_budget(s['date'])} for s in states]
        row=metrics([b for a in accounts for b in a['bets']])
        row['days_active']=sum(bool(a['bets']) for a in accounts)
        row['days_target_reached']=sum(account(a)['first_target'] is not None for a in accounts)
        row['days_budget_stop']=sum(account(a)['stop']=='BUDGET' for a in accounts)
        row['days_sequence_stop']=sum(account(a)['stop']=='SERIE_TERMINEE' for a in accounts)
        row['max_daily_committed_cents']=max([account(a)['committed_cents'] for a in accounts],default=0)
        row['committed_cents']=sum(account(a)['committed_cents'] for a in accounts)
        row['by_market']={market:metrics([b for a in accounts for b in a['bets'] if b.get('market','E_SIMPLE_GAGNANT')==market]) for market in ('E_SIMPLE_GAGNANT','E_SIMPLE_PLACE')}
        out['solutions'][key]=row
    out['ranking_by_net_profit']=sorted(STRATEGIES,key=lambda k:-out['solutions'][k]['profit_cents'])
    out['daily_accounts']={s['date']:{k:account({**a,'target_cents':daily_target(s['date']),'stop_at_target':stop_at_target(s['date']),'budget_cents':daily_budget(s['date'])}) for k,a in s.get('solutions',{}).items()} for s in states}
    return out
