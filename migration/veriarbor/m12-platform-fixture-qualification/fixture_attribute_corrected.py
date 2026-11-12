class MockPlatformHandler(BaseHTTPRequestHandler):
    """A simple mock platform to handle publish requests during tests."""

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == '/publish':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode('utf-8'))
                idem_key = payload.get('idempotency_key')
                remote_id = f"remote-{idem_key[:8]}"
                response = {
                    "id": remote_id,
                    "remote_id": remote_id,
                    "url": f"http://localhost:{self.server.server_port}/publications/{remote_id}"
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith('/publications/'):
            pub_id = parsed.path.split('/')[-1]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"id": pub_id, "status": "PUBLISHED"}).encode('utf-8'))
        elif parsed.path == '/metrics':
            params = urllib.parse.parse_qs(parsed.query)
            remote_id = params.get('remote_id', [None])[0]
            if remote_id:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "remote_id": remote_id,
                    "views": 100,
                    "impressions": 200,
                    "reactions": 50,
                    "comments": 10
                }).encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()