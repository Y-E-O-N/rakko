"""
Instagram Session Generator - Railway 배포용
모바일에서 아이디/비밀번호 입력하면 session.json 다운로드 가능
"""
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
from instagrapi import Client
import json
import io

app = Flask(__name__)
CORS(app)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Instagram Session Generator</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        h1 { text-align: center; margin-bottom: 24px; color: #333; font-size: 20px; }
        .input-group { margin-bottom: 16px; }
        label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
        input {
            width: 100%;
            padding: 14px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
        }
        button:disabled { opacity: 0.6; }
        .message { margin-top: 16px; padding: 12px; border-radius: 8px; text-align: center; }
        .error { background: #fee; color: #c00; }
        .success { background: #efe; color: #060; }
        .loading { display: none; text-align: center; margin-top: 16px; }
        .loading.show { display: block; }
        .spinner {
            width: 30px; height: 30px;
            border: 3px solid #e0e0e0;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .hint { font-size: 12px; color: #888; margin-top: 16px; text-align: center; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Instagram Session Generator</h1>
        <div class="input-group">
            <label>Username</label>
            <input type="text" id="username" placeholder="Instagram username" autocomplete="off">
        </div>
        <div class="input-group">
            <label>Password</label>
            <input type="password" id="password" placeholder="Instagram password" autocomplete="off">
        </div>
        <button onclick="generateSession()">Generate Session</button>
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Logging in...</p>
        </div>
        <div id="message"></div>
        <p class="hint">생성된 세션 파일을 Story Saver에 업로드하세요</p>
    </div>

    <script>
        async function generateSession() {
            const username = document.getElementById('username').value.trim();
            const password = document.getElementById('password').value;

            if (!username || !password) {
                showMessage('Username과 Password를 입력하세요', 'error');
                return;
            }

            document.getElementById('loading').classList.add('show');
            document.getElementById('message').innerHTML = '';

            try {
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Login failed');
                }

                // Download the session file
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'session.json';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                a.remove();

                showMessage('세션 파일 다운로드 완료! Story Saver에 업로드하세요.', 'success');

            } catch (error) {
                showMessage(error.message, 'error');
            } finally {
                document.getElementById('loading').classList.remove('show');
            }
        }

        function showMessage(text, type) {
            document.getElementById('message').innerHTML = `<div class="message ${type}">${text}</div>`;
        }

        // Enter key support
        document.getElementById('password').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') generateSession();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/generate', methods=['POST'])
def generate_session():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400

        # Login to Instagram
        client = Client()
        client.delay_range = [1, 3]
        client.login(username, password)

        # Get session settings
        settings = client.get_settings()

        # Create file-like object
        session_json = json.dumps(settings, indent=2, default=str)
        buffer = io.BytesIO(session_json.encode('utf-8'))
        buffer.seek(0)

        return send_file(
            buffer,
            mimetype='application/json',
            as_attachment=True,
            download_name='session.json'
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
