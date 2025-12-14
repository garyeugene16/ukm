from flask import Flask, render_template, request, Response, jsonify
import threading
import queue
import json
import time
from ui_backend import run_chat_session, msg_queue

app = Flask(__name__)
# ==========================================
#    Jalanin kode ini pake python app.py
#   Install flask pake : pip install flask
# ===========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_process', methods=['POST'])
def start_process():
    data = request.json
    story = data.get('story')
    
    if not story:
        return jsonify({"status": "error", "message": "Cerita kosong"}), 400

    # Jalankan backend di thread terpisah
    thread = threading.Thread(target=run_chat_session, args=(story,))
    thread.start()

    return jsonify({"status": "started"})

@app.route('/stream_logs')
def stream_logs():
    def generate():
        while True:
            try:
                # Ambil data dari queue backend
                message = msg_queue.get(timeout=1.0)
                yield f"data: {json.dumps(message)}\n\n"
                
                if message['type'] == 'done':
                    break
            except queue.Empty:
                # Heartbeat agar koneksi tidak putus
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    print("Server berjalan di http://localhost:5000")
    app.run(debug=True, port=5000)