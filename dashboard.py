"""Read-only counter and planning page. Listens only on this computer."""
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from metrics import read

ROOT=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path.split('?')[0]=='/api/status':
            payload={k:read(v) for k,v in [('supervisor','supervisor.json'),('worker','status.json'),('totals','totals.json'),('bait','bait.json'),('presence','presence.json')]}
            payload['now']=time.time();data=json.dumps(payload).encode();content='application/json'
        elif self.path in ('/','/Counter.html'):
            data=(ROOT/'Counter.html').read_bytes();content='text/html; charset=utf-8'
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',content);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

if __name__=='__main__':
    try:ThreadingHTTPServer(('127.0.0.1',8768),Handler).serve_forever()
    except OSError as e:
        if getattr(e,'winerror',None)!=10048:raise
