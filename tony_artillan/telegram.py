"""Presentation et recus Telegram propres a Tony Artillan."""
from datetime import datetime
import hashlib
import requests
from .model import score, next_stake, stamp


def euros(cents):
    return f'{cents/100:,.2f}'.replace(',', ' ').replace('.', ',')+' €'


def report(state):
    s = score(state)
    if state.get('source_status') != 'VERIFIEE' and not any(r.get('stake_cents') for r in state['races']):
        return ('⏸ PARIS TURF — ANCIEN PROGRAMME EN ATTENTE\n'+state['date']+
                '\nAucun pronostic Paris Turf vérifié : aucun pari virtuel engagé ; aucun pari réglé.\n'
                'Le programme actif COMPARATIF R1 — MAJORITÉ 3 OU 4/4 est distinct.\n'
                'Pas de nouvel envoi de ce rappel aujourd’hui tant que la source reste indisponible.')
    lines = ['🏇 TONY ARTILLAN — SIMULATION', f"{state['date']} · R{state['r']} · {state['venue']}",
             'Simple gagnant · premier choix Paris Turf uniquement',
             '100 € au départ ; +100 € par perte ; retour à 100 € après un gain.',
             'Remboursement : mise inchangée. Nouvelle journée : départ à 100 €.', '']
    if state.get('source_status') != 'VERIFIEE':
        lines += ['⏸ PRONOSTICS PARIS TURF INDISPONIBLES',
                  'Les huit premiers choix ne sont pas vérifiés : aucun pari virtuel engagé.', '']
        if state.get('source_error'):
            lines += ['Contrôle de la source : '+state['source_error'], '']
    labels = {'A_VENIR':'À venir', 'ENGAGE_VIRTUEL':'Engagé virtuellement',
              'GAGNE':'✅ Gagné', 'PERDU':'❌ Perdu', 'REMBOURSE':'↩ Remboursé', 'NON_JOUE':'⏭ Non joué'}
    cumulative = 0
    for i, race in enumerate(state['races']):
        start = stamp(race['departure']).strftime('%Hh%M')
        lines += [f"{race['id']} · {start} — {race['title']}"]
        selection = race.get('selection')
        lines.append(f"Paris Turf : N°{selection['number']} {selection['name']}" if selection else 'Paris Turf : premier choix non vérifié')
        if 'stake_cents' in race:
            lines.append('Mise figée : '+euros(race['stake_cents']))
        elif selection and race['status'] == 'A_VENIR':
            amount = next_stake(state['races'], i)
            lines.append('Prochaine mise : '+euros(amount) if amount is not None else 'Mise conditionnelle : attend le résultat officiel précédent')
        else:
            lines.append('Mise engagée : 0,00 €')
        quote = race.get('odds') or {}
        if quote.get('rapport'):
            lines.append(f"Cote PMU au relevé : {quote['rapport']} (indicative)")
        lines.append(labels[race['status']]+(' — '+race['reason'] if race.get('reason') else ''))
        if 'return_cents' in race:
            lines.append('Retour brut : '+euros(race['return_cents'])+' · net : '+euros(race['profit_cents']))
            cumulative += race['profit_cents']
            lines.append('Solde cumulé réglé : '+euros(cumulative))
        lines.append('')
    lines += [f"SCORE : {s['wins']} gagnant(s) / {s['wins']+s['losses']} pari(s) décisif(s) · {s['refunds']} remboursé(s)",
              'Mises réglées : '+euros(s['stake_cents']), 'Retours bruts : '+euros(s['return_cents']),
              'Solde réglé : '+euros(s['profit_cents']),
              ('ROI '+('final' if s['complete'] else 'du sous-total réglé')+' : '+s['roi_percent']+' %') if s['roi_percent'] is not None else 'ROI : non calculable, aucun pari réglé',
              'Mises en attente : '+euros(s['pending_stake_cents']),
              'Trésorerie virtuelle minimale observée : '+euros(s['cash_required_cents']),
              'Mise maximale engagée : '+euros(s['max_stake_cents']), '',
              'Les mises suivantes restent conditionnelles tant que le rapport précédent manque.',
              'Rapports définitifs PMU INTERNET uniquement. Aucun pari réel exécuté.']
    return '\n'.join(lines)


def chunks(message, limit=3800):
    parts = []; current = ''
    for line in message.splitlines():
        if len(line) > limit:
            raise ValueError('Ligne Telegram trop longue')
        if current and len(current)+len(line)+1 > limit:
            parts.append(current); current = ''
        current += ('\n' if current else '')+line
    if current:
        parts.append(current)
    return parts


def send(state, message, token, chat, save, now, post=requests.post):
    fingerprint = hashlib.sha256(message.encode()).hexdigest()
    old = [r for r in state['notifications'] if r['fingerprint'] == fingerprint]
    if any(r['status'] in {'SENT','PENDING','UNCERTAIN'} for r in old):
        return False
    entry = {'fingerprint':fingerprint, 'status':'PENDING', 'created_at':now.isoformat(),
             'text':message, 'receipts':[]}
    state['notifications'].append(entry); save()
    try:
        for part in chunks(message):
            r = post(f'https://api.telegram.org/bot{token}/sendMessage',
                     json={'chat_id':chat,'text':part,'disable_web_page_preview':True},timeout=20)
            body = r.json()
            if r.status_code != 200 or body.get('ok') is not True:
                # Ne pas renvoyer automatiquement une suite partiellement recue.
                entry['status'] = 'UNCERTAIN' if entry['receipts'] else 'FAILED'
                save(); return False
            receipt = body.get('result', {})
            if not isinstance(receipt.get('message_id'), int) or not isinstance(receipt.get('date'), int):
                raise ValueError('Recu Telegram incomplet')
            entry['receipts'].append({k:receipt[k] for k in ('message_id','date')}); save()
        entry.update(status='SENT', sent_at=datetime.fromtimestamp(entry['receipts'][-1]['date'],now.tzinfo).isoformat())
        save(); return True
    except (requests.RequestException, ValueError):
        entry['status'] = 'UNCERTAIN'; save(); return False
