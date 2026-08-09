"""Manual, single-run, read-only local IMAP Agent."""
from __future__ import annotations
import argparse, email, imaplib, os, sys
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
import json
from dotenv import load_dotenv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from manual_capture.email_processing import candidate_subject, dedup_key, email_excerpt

load_dotenv(ROOT / '.env')
def local_api_url() -> str:
    fastapi_port = os.getenv('FASTAPI_PORT', '8000')
    return f'http://127.0.0.1:{fastapi_port}/api/email-events'

def decoded(value):
    return ''.join((part.decode(charset or 'utf-8','replace') if isinstance(part,bytes) else part) for part,charset in decode_header(value or ''))
def text_part(message):
    for part in message.walk():
        if part.get_content_type()=='text/plain' and 'attachment' not in (part.get('Content-Disposition','')):
            return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8','replace') if part.get_payload(decode=True) else ''
    return ''
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--once',action='store_true'); parser.add_argument('--dry-run',action='store_true'); args=parser.parse_args()
    if not args.once: parser.error('only --once is supported')
    required=('IMAP_SERVER','IMAP_EMAIL','IMAP_PASSWORD')
    if not all(os.getenv(key) for key in required): print('IMAP 尚未配置，请检查 .env'); return 2
    try: client=imaplib.IMAP4_SSL(os.environ['IMAP_SERVER'],993,timeout=20)
    except (OSError, imaplib.IMAP4.error):
        print('IMAP 连接失败，请检查网络、服务器地址和本机访问权限'); return 1
    try:
        client.login(os.environ['IMAP_EMAIL'],os.environ['IMAP_PASSWORD'])
        # NetEase may reject anonymous third-party IMAP sessions as unsafe.
        # This standard IMAP ID extension identifies this local read-only client.
        try:
            imaplib.Commands.setdefault('ID', ('AUTH', 'SELECTED'))
            client._simple_command('ID', '("name" "GoodJobAI" "version" "1.0")')
        except (imaplib.IMAP4.error, KeyError): pass
        selected,selected_data=client.select('INBOX', readonly=True)
        if selected != 'OK': print('无法以只读方式选择 INBOX（服务器状态：' + str(selected_data)[:160] + '）'); return 1
        status,data=client.uid('search',None,'SINCE',(datetime.now()-timedelta(days=7)).strftime('%d-%b-%Y'))
        count=created=deduplicated=0
        for uid in (data[0].split() if status=='OK' else [])[:50]:
            ok,raw=client.uid('fetch',uid,'(BODY.PEEK[HEADER] BODY.PEEK[TEXT])'); message=email.message_from_bytes(b''.join(item[1] for item in raw if isinstance(item,tuple)))
            subject=decoded(message.get('Subject'));
            if not candidate_subject(subject): continue
            count+=1
            if args.dry_run: continue
            received=(parsedate_to_datetime(message.get('Date')) if message.get('Date') else datetime.now()).isoformat(); key,key_type=dedup_key('INBOX','unknown',uid.decode(),message.get('Message-ID'),subject,message.get('From',''),received)
            payload={'dedup_key':key,'key_type':key_type,'subject':subject[:300],'snippet':email_excerpt(text_part(message)),'received_at':received,'message_id':message.get('Message-ID'),'sender_domain':(message.get('From','').split('@')[-1].split('>')[0])}
            token=os.getenv('IMAP_AGENT_TOKEN','');
            if not token: print('IMAP Agent Token 尚未配置，请检查 .env'); return 2
            request=Request(local_api_url(),data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
            response=json.loads(urlopen(request,timeout=35).read().decode('utf-8'))
            if response.get('created'):
                created+=1
            else:
                deduplicated+=1
        print(f'candidate emails: {count}; dry-run={args.dry_run}')
        print('sync-diagnostics: '+json.dumps({'candidate_count':count,'created_count':created,'deduplicated_count':deduplicated},ensure_ascii=False))
    finally: client.logout()
    return 0
if __name__=='__main__': sys.exit(main())
