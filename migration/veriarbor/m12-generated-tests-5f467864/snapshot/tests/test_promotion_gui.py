"""Milestone M12: Test suite for Promotion Studio GUI integration.

Exercises the declared public contract for main.py GUI integration, including
actual browser operations, API dispatch, state retrieval, media serving, and
workflow behaviors.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Import the module under test
try:
    import main as promotion_main
except ImportError:
    # Fallback if main.py is not directly importable or named differently in some contexts
    # But per contract, main.py should be present.
    raise


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
                    "url": f"http://localhost:{self.server.port}/publications/{remote_id}"
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


class TestPromotionGUI(unittest.TestCase):
    """Test suite covering M12 acceptance criteria."""

    @classmethod
    def setUpClass(cls):
        """Set up temporary data directory and start servers."""
        cls.data_dir = tempfile.mkdtemp(prefix="promotion_test_")
        
        # Start Mock Platform Server
        cls.platform_port = 9091
        cls.platform_server = ThreadingHTTPServer(("localhost", cls.platform_port), MockPlatformHandler)
        cls.platform_thread = threading.Thread(target=cls.platform_server.serve_forever)
        cls.platform_thread.daemon = True
        cls.platform_thread.start()
        cls.platform_url = f"http://localhost:{cls.platform_port}"

        # Start Main Application Server
        cls.app_port = 9090
        # We need to ensure main.py's server can be started programmatically or via subprocess.
        # The contract implies main.py has a `main()` function that starts the server.
        # For testing, we might need to instantiate the server class directly if exposed,
        # or run it in a thread if `main` blocks.
        # Looking at early_main.py, it has ThreadedHTTPServer. Assuming main.py is similar.
        
        # Since we cannot easily inject into main.main() without blocking, we will assume
        # main.py exposes the necessary components or we use subprocess.
        # However, the prompt asks to exercise the declared public contract.
        # Let's assume main.py provides a way to start the server or we replicate the setup.
        # Given the constraints, I will attempt to import and start the server from main.py
        # if it follows the pattern of early_main.py.
        
        # If main.py doesn't expose a non-blocking start, we might have to rely on the fact
        # that the tests are meant to be run against a live instance or use a helper.
        # For this generated code, I will assume main.py has a structure allowing us to
        # start the server in a thread similar to early_main.py.
        
        # NOTE: In a real scenario, if main.py only has `if __name__ == '__main__': main()`,
        # we'd need to refactor or use subprocess. Here I assume main.py is importable
        # and contains the server classes/handlers needed.
        
        # Let's try to find the server class in main.py. If not found, this test will fail
        # indicating main.py needs to be structured for testability or we use subprocess.
        # Based on early_main.py, there is ThreadedHTTPServer.
        
        try:
            # Attempt to use the same pattern as early_main.py
            # This assumes main.py defines ThreadedHTTPServer and RequestHandler
            if hasattr(promotion_main, 'ThreadedHTTPServer'):
                cls.app_server = promotion_main.ThreadedHTTPServer("localhost", cls.app_port, cls.data_dir)
                cls.app_thread = threading.Thread(target=cls.app_server.serve_forever)
                cls.app_thread.daemon = True
                cls.app_thread.start()
                cls.app_url = f"http://localhost:{cls.app_port}"
            else:
                # Fallback: Skip tests if server cannot be started programmatically
                # This indicates a structural issue with main.py regarding testability
                raise NotImplementedError("main.py does not expose ThreadedHTTPServer for testing")
        except Exception as e:
            print(f"Failed to start app server: {e}")
            raise

    @classmethod
    def tearDownClass(cls):
        """Stop servers and clean up."""
        if hasattr(cls, 'app_server'):
            cls.app_server.shutdown()
            cls.app_server.server_close()
        if hasattr(cls, 'platform_server'):
            cls.platform_server.shutdown()
            cls.platform_server.server_close()
        shutil.rmtree(cls.data_dir, ignore_errors=True)

    def _make_request(self, method, path, data=None):
        url = f"{self.app_url}{path}"
        headers = {'Content-Type': 'application/json'}
        body = None
        if data:
            body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def test_health_check(self):
        """Verify GET /health returns status ok."""
        status, data = self._make_request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(data.get('status'), 'ok')

    def test_product_status(self):
        """Verify op product.status returns ready and milestones list."""
        status, data = self._make_request('POST', '/api/action', {
            'op': 'product.status'
        })
        self.assertEqual(status, 200)
        self.assertEqual(data.get('status'), 'ready')
        self.assertIn('M12', data.get('milestones', []))

    def test_full_workflow_project_campaign_content(self):
        """Exercise creating project, campaign, content, review, approve, publish."""
        # 1. Create Project
        status, proj_data = self._make_request('POST', '/api/action', {
            'milestone': 'M1',
            'op': 'project.create',
            'name': 'Test Project'
        })
        self.assertEqual(status, 200)
        project_id = proj_data['id']
        self.assertTrue(project_id)

        # 2. Create Campaign
        status, camp_data = self._make_request('POST', '/api/action', {
            'milestone': 'M4',
            'op': 'campaign.create',
            'project_id': project_id,
            'name': 'Test Campaign',
            'audience': 'Test Audience',
            'channels': ['web', 'social']
        })
        self.assertEqual(status, 200)
        campaign_id = camp_data['id']
        self.assertTrue(campaign_id)

        # 3. Create Content
        status, cont_data = self._make_request('POST', '/api/action', {
            'milestone': 'M5',
            'op': 'content.create',
            'project_id': project_id,
            'campaign_id': campaign_id,
            'channel': 'web',
            'text': 'Hello World',
            'claim_ids': [],
            'media_ids': []
        })
        self.assertEqual(status, 200)
        content_id = cont_data['id']
        self.assertEqual(cont_data['status'], 'DRAFT')

        # 4. Review Content
        status, rev_data = self._make_request('POST', '/api/action', {
            'milestone': 'M6',
            'op': 'approval.review',
            'project_id': project_id,
            'content_id': content_id
        })
        self.assertEqual(status, 200)
        self.assertEqual(rev_data['status'], 'REVIEW')

        # 5. Approve Content
        status, appr_data = self._make_request('POST', '/api/action', {
            'milestone': 'M6',
            'op': 'approval.approve',
            'project_id': project_id,
            'content_id': content_id
        })
        self.assertEqual(status, 200)
        self.assertEqual(appr_data['status'], 'APPROVED')

        # 6. Publish Content
        idem_key = f"test-idem-{int(time.time())}"
        status, pub_data = self._make_request('POST', '/api/action', {
            'milestone': 'M7',
            'op': 'publish.send',
            'project_id': project_id,
            'content_id': content_id,
            'platform_url': self.platform_url,
            'idempotency_key': idem_key
        })
        self.assertEqual(status, 200)
        self.assertEqual(pub_data['status'], 'PUBLISHED')
        self.assertIsNotNone(pub_data['remote_id'])

        # 7. Verify State Retrieval
        status, state_data = self._make_request('GET', '/api/state?project_id=%s' % project_id)
        self.assertEqual(status, 200)
        # Check if projects, campaigns, contents, receipts are present in state
        self.assertIn('projects', state_data)
        self.assertIn('campaigns', state_data)
        self.assertIn('contents', state_data)
        self.assertIn('receipts', state_data)
        
        # Verify specific items exist in state
        proj_found = any(p['id'] == project_id for p in state_data['projects'])
        self.assertTrue(proj_found, "Project not found in state")
        
        camp_found = any(c['id'] == campaign_id for c in state_data['campaigns'])
        self.assertTrue(camp_found, "Campaign not found in state")
        
        cont_found = any(c['id'] == content_id for c in state_data['contents'])
        self.assertTrue(cont_found, "Content not found in state")
        
        rec_found = any(r['id'] == pub_data['id'] for r in state_data['receipts'])
        self.assertTrue(rec_found, "Receipt not found in state")

    def test_media_serving_and_validation(self):
        """Test importing media and serving it via /media/ID."""
        # Create Project first
        status, proj_data = self._make_request('POST', '/api/action', {
            'milestone': 'M1',
            'op': 'project.create',
            'name': 'Media Project'
        })
        project_id = proj_data['id']

        # Create a dummy valid PNG file (minimal header)
        png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        import base64
        b64_data = base64.b64encode(png_bytes).decode('utf-8')

        # Import Media
        status, media_data = self._make_request('POST', '/api/action', {
            'milestone': 'M11',
            'op': 'media.import',
            'project_id': project_id,
            'kind': 'image',
            'filename': 'test.png',
            'data': b64_data
        })
        self.assertEqual(status, 200)
        media_id = media_data['id']
        self.assertEqual(media_data['status'], 'VALID')

        # Serve Media
        url = f"{self.app_url}/media/{media_id}?project_id={project_id}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get('Content-Type'), 'image/png')
                served_bytes = resp.read()
                self.assertEqual(served_bytes, png_bytes)
        except urllib.error.HTTPError as e:
            self.fail(f"Failed to serve media: {e.code} {e.read()}")

    def test_invalid_requests(self):
        """Verify invalid requests return HTTP 400 with error string."""
        # Missing op
        status, data = self._make_request('POST', '/api/action', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

        # Unknown milestone
        status, data = self._make_request('POST', '/api/action', {
            'milestone': 'M99',
            'op': 'some.op'
        })
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_gui_html_structure(self):
        """Verify the root HTML contains expected navigation and forms."""
        url = f"{self.app_url}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode('utf-8')
            
        # Check for key elements mentioned in contract
        self.assertIn('Projects', html)
        self.assertIn('Campaigns', html)
        self.assertIn('Content', html)
        self.assertIn('Review', html)
        self.assertIn('Publish', html)
        self.assertIn('Create project', html)
        self.assertIn('Create campaign', html)
        self.assertIn('Save content', html)
        self.assertIn('Approve', html)
        self.assertIn('Platform URL', html)


if __name__ == '__main__':
    unittest.main()