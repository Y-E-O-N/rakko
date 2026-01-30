from http.server import BaseHTTPRequestHandler
import json

# Vercel Python Runtime
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            from instagrapi import Client

            # Read request body
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))

            username = data.get('username', '').strip()
            password = data.get('password', '')

            if not username or not password:
                self.send_error_response(400, "Username and password required")
                return

            # Login to Instagram
            client = Client()
            client.delay_range = [1, 3]
            client.login(username, password)

            # Get session settings
            settings = client.get_settings()

            # Return session as JSON
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            response = {
                'success': True,
                'session': settings
            }
            self.wfile.write(json.dumps(response, default=str).encode('utf-8'))

        except Exception as e:
            self.send_error_response(500, str(e))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def send_error_response(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = {'success': False, 'error': message}
        self.wfile.write(json.dumps(response).encode('utf-8'))
