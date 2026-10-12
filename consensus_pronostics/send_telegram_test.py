"""Single explicitly requested demonstration; never enters betting journals."""
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
import requests

def main():
 request=json.loads(Path('consensus_pronostics/telegram_test_request.json').read_text())
 if datetime.now(timezone.utc)>=datetime.fromisoformat(request['expires_at'].replace('Z','+00:00')):
  print('TEST_EXPIRE — aucun envoi');return
 if os.environ.get('GITHUB_RUN_ATTEMPT','1')!='1':
  print('RELANCE — aucun second envoi');return
 token=os.environ.get('TELEGRAM_TOKEN');chat=os.environ.get('TELEGRAM_CHAT_ID')
 if not token or not chat:raise RuntimeError('Configuration Telegram absente')
 message=request['text']
 if len(message)>3900 or not message.startswith('🧪 TEST'):raise RuntimeError('Message de test invalide')
 # Exactly one request. Never log exceptions containing a token-bearing URL.
 try:
  response=requests.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':chat,'text':message,'disable_web_page_preview':True},timeout=25)
  body=response.json()
 except Exception:
  raise RuntimeError('Envoi non confirmé ; ne pas relancer automatiquement') from None
 if response.status_code!=200 or body.get('ok') is not True:
  raise RuntimeError('Telegram a refusé le message de test')
 result=body['result'];receipt={'request_id':request['id'],'delivery':'SENT','message_id':result['message_id'],'date':result['date']}
 Path('consensus_pronostics/telegram_test_receipt.json').write_text(json.dumps(receipt,indent=2))
 print('TELEGRAM_TEST_SENT message_id='+str(result['message_id']))
if __name__=='__main__':main()
