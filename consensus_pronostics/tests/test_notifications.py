import json,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from notify import notify,admissible,format_message,chunks
from collector import parse,consensus
FIX=Path(__file__).parent/'fixtures'
class DeliveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.now=datetime(2026,10,13,7,tzinfo=timezone.utc)
  race=json.loads((FIX/'frequence.race.json').read_text());horses={int(n):p for n,p in race['horses'].items()};race['horses']=horses
  row=parse('frequence',(FIX/'frequence.html').read_text(),race)
  self.s={'race':race,'captured_at':self.now.isoformat(),'eligible_before_departure':True,'rows':[row],'consensus':consensus([row],race)}
  folder=self.root/'2026-10-13';folder.mkdir();(folder/'R1C1-070000.json').write_text(json.dumps(self.s))
  self.env=patch.dict('os.environ',{'TELEGRAM_TOKEN':'unit-test','TELEGRAM_CHAT_ID':'configured-test-destination'});self.env.start()
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def ok(self,*args,**kwargs):
  class Response:
   status_code=200
   def json(self):return {'ok':True,'result':{'message_id':42,'date':1791874800}}
  return Response()
 def test_send_receipt_and_suppress_identical_second_delivery(self):
  calls=[]
  def post(*a,**kw):calls.append(kw['json']);return self.ok()
  notify(self.root,post=post,clock=lambda:self.now);notify(self.root,post=post,clock=lambda:self.now)
  self.assertEqual(len(calls),3);self.assertTrue(calls[0]['text'].startswith('🏇 QUINTÉ'))
  ledger=json.loads((self.root/'2026-10-13/notifications.json').read_text());self.assertEqual(ledger[0]['delivery'],'SENT');self.assertEqual(ledger[0]['receipts'][0]['message_id'],42)
 def test_uncertain_send_not_retried(self):
  calls=[]
  def post(*a,**kw):calls.append(1);raise TimeoutError()
  for i in range(2):
   with self.assertRaises(RuntimeError):notify(self.root,post=post,clock=lambda:self.now)
  self.assertEqual(calls,[1])
 def test_departed_and_wrong_day_never_sent(self):
  self.assertFalse(admissible(self.s,self.now+timedelta(days=1)))
  calls=[];notify(self.root,post=lambda *a,**k:calls.append(1),clock=lambda:self.now+timedelta(hours=12));self.assertEqual(calls,[])
 def test_outsider_labels_and_partial_status_present(self):
  t=format_message(self.s);self.assertIn('PROVISOIRE',t);self.assertIn('PUMALIN PARK',t.upper());self.assertIn('tocard',t);self.assertIn('OUTSIDERS',t)
 def test_split_on_lines_without_losing_outsiders(self):
  t=format_message(self.s);parts=chunks(t,limit=400);self.assertEqual('\n'.join(parts),t);self.assertTrue(all(len(p)<=400 for p in parts))
if __name__=='__main__':unittest.main()
