import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404); return
        result={'service':'ultima-gold-test','live_orders_enabled':False}
        for name in ('runtime-state.json','ultima-probe.json'):
            try: result[name]=json.loads((Path('/data')/name).read_text())
            except (OSError, ValueError): pass
        body=json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
HTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
