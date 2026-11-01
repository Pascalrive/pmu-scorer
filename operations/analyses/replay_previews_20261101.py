"""Read-only counterfactual. Never imported by a betting program.

Use the last Telegram-confirmed predeparture preview for each course. Assume its
choices would survive final checks and each result would settle before the next
eligible course. These assumptions are NOT proof of executable historical bets.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re

PACKAGES=('comparaison_r1','tony_artillan_2','tony_artillan_3_5')
STAKES=(10000,20000,15000,15000,20000)
DATE='2026-11-01'

def selections(notices):
    result={}
    for notice in notices:
        text=notice.get('text','')
        if not text.startswith('🌅') or DATE not in text or notice.get('status')!='SENT':continue
        receipts=notice.get('receipts',[])
        if not receipts or any(type(x.get('date')) is not int for x in receipts):continue
        sent=max(x['date'] for x in receipts)
        for match in re.finditer(r'(R1C\d+) · (\d\dh\d\d) — ([^\n]+)\n(.*?)(?=\nR1C\d+ ·|\nSeules les courses|\Z)',text,re.S):
            race,hour,title,block=match.groups()
            departure=datetime.fromisoformat(DATE+'T'+hour.replace('h',':')+':00+01:00')
            if sent>=departure.timestamp():continue
            tips={m.group(1):int(m.group(2)) for m in re.finditer(r'^(Turfin|Canalturf|ZEturf|Geny|Zone-Turf)(?: \(secours Genybet\))? : N°(\d+) [^\n]+$',block,re.M) if 'NON PARTANT' not in m.group(0)}
            if race not in result or sent>result[race]['sent_epoch']:
                result[race]={'race':race,'title':title,'departure':departure.isoformat(),'tips':tips,'sent_epoch':sent,'fingerprint':notice['fingerprint'],'message_ids':[x['message_id'] for x in receipts]}
    return result

def replay(package,notices,officials):
    picks=selections(notices);losses=0;committed=returned=0;rows=[];pending=False
    for c in range(1,10):
        rid=f'R1C{c}';p=picks.get(rid);row={'race':rid}
        if not p:row['reason']='Aperçu pré-départ absent';rows.append(row);continue
        row.update(p)
        counts=Counter(p['tips'].values())
        majority=[n for n,k in counts.items() if k>=3]
        if package=='tony_artillan_2':
            n=p['tips'].get('Geny');chosen=n if n is not None and n==p['tips'].get('Canalturf') else None
        else:chosen=majority[0] if len(majority)==1 else None
        row['selection']=chosen
        official=officials.get(rid,{})
        horses=official.get('participants',{}).get('participants',[])
        row['arrival']=[h['numPmu'] for h in sorted(horses,key=lambda h:h.get('ordreArrivee') or 999) if isinstance(h.get('ordreArrivee'),int) and 1<=h['ordreArrivee']<=5]
        if chosen is None:row['reason']='Accord insuffisant'
        elif pending:row['reason']='Résultat précédent manquant'
        elif losses>=5:row['reason']='Arrêt après cinq pertes successives'
        elif committed+STAKES[losses]>120000:row['reason']='Plafond de mises'
        else:
            stake=STAKES[losses];row['stake_cents']=stake;committed+=stake
            horse=next((h for h in horses if h.get('numPmu')==chosen),{})
            row['horse']=horse.get('nom');row['rank']=horse.get('ordreArrivee');row['incident']=horse.get('incident')
            payload=official.get('reports',[])
            tables=[t for t in payload if t.get('typePari')=='E_SIMPLE_GAGNANT'] if isinstance(payload,list) else []
            if len(tables)!=1 or not tables[0].get('rapports'):
                row['status']='EN_ATTENTE';pending=True
            elif horse.get('statut')=='NON_PARTANT' or tables[0].get('rembourse'):
                row.update(status='REMBOURSE',return_cents=stake,net_cents=0);returned+=stake
            else:
                rates=[x['dividendePourUnEuro'] for x in tables[0]['rapports'] if str(x.get('combinaison'))==str(chosen)]
                ret=round(stake*rates[0]/100) if rates else 0
                row.update(status='GAGNE' if rates else 'PERDU',return_cents=ret,net_cents=ret-stake)
                returned+=ret;losses=0 if rates else losses+1
        rows.append(row)
    settled=[x for x in rows if 'return_cents' in x]
    settled_stake=sum(x['stake_cents'] for x in settled)
    net=returned-settled_stake
    return {'program':package,'hypothetical':True,'stake_cents':committed,'settled_stake_cents':settled_stake,'return_cents':returned,'net_settled_cents':net,'pending_stake_cents':committed-settled_stake,'roi_settled_percent':100*net/settled_stake if settled_stake else None,'wins':sum(x['status']=='GAGNE' for x in settled),'losses':sum(x['status']=='PERDU' for x in settled),'rows':rows}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('officials');args=ap.parse_args()
    raw=json.loads(Path(args.officials).read_text());officials={x['race']:x for x in raw}
    print(json.dumps([replay(p,json.loads(Path(p+'/data/notifications.json').read_text())['notifications'],officials) for p in PACKAGES],ensure_ascii=False,indent=2))
