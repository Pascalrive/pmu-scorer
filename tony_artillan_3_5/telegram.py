"""Journal Telegram independant du comparatif R1."""
from datetime import datetime
import hashlib
import requests

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


