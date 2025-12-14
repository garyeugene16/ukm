from flask import Flask, render_template, request, Response, jsonify
import threading
import queue
import json
import time
from ui_backend3 import run_chat_session, msg_queue

app = Flask(__name__)
# ==========================================
#    Jalanin kode ini pake python app.py
#   Install flask pake : pip install flask
# ===========================================

# alamat halaman utama website
@app.route('/')
def index():
    # tampilkan file tampilan antarmuka html ke pengguna
    return render_template('index.html')

# alamat untuk menerima perintah mulai dari tombol di website
@app.route('/start_process', methods=['POST'])
def start_process():
    data = request.json # ambil data yang dikirim oleh pengguna lewat website
    story = data.get('story')
    
    # jika ceritanya kosong berikan pesan error
    if not story:
        return jsonify({"status": "error", "message": "Cerita kosong"}), 400

    # siapkan thread baru agar ai berjalan di background
    # ini penting agar website tidak macet saat llm sedang berpikir lama
    # Jalankan backend di thread terpisah
    thread = threading.Thread(target=run_chat_session, args=(story,))
    # mulai jalankan ai di jalur tersebut
    thread.start()

    return jsonify({"status": "started"})

# alamat khusus untuk mengirim teks obrolan secara langsung atau live streaming
@app.route('/stream_logs')
def stream_logs():
    # fungsi pembantu untuk terus menerus mengirim data
    def generate():
        while True:
            try:
                # Ambil data dari queue backend
                message = msg_queue.get(timeout=1.0)
                # kirim pesan tersebut ke website dalam format teks khusus streaming
                yield f"data: {json.dumps(message)}\n\n"
                
                if message['type'] == 'done': # jika pesan isinya tanda selesai maka hentikan perulangan
                    break
            # jika antrean kosong atau ai masih mikir dan belum ada pesan baru
            except queue.Empty:
                # kirim sinyal atau ping agar koneksi tidak putus
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
    # kembalikan respon dengan tipe event stream agar browser tahu ini data live
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    print("Server berjalan di http://localhost:5001")
    app.run(debug=True, port=5001)