import os
import pandas as pd
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# 1. KONFIGURASI LLM (Ollama Local)
model = 'llama3.2:3b'
llm_config = {
    "model": model, 
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1", 
    "temperature":0.5, 
    "price": [0.0, 0.0], 
}

# 2. DEFINISI TOOLS (Fungsi Python untuk Agen)
def search_ukm_by_interest(minat: str) -> str:
    """
    Mencari UKM berdasarkan kata kunci minat (misal: 'Seni', 'Olahraga', 'Teknologi').
    Membaca data dari ukm_data.xlsx.
    Sekarang mencari di SEMUA kolom teks yang relevan.
    """
    try:
        df = pd.read_excel("ukm_data.xlsx")
        df = df.astype(str)
        # # Filter data yang mengandung kata kunci
        # # Cari di kolom 'kategori' dan 'nama_ukm'
        # # mask = df['kategori'].str.contains(minat, case=False, na=False) | \
        # # df['nama_ukm'].str.contains(minat, case=False, na=False)
        
        # mask = (
        #     df['kategori'].str.contains(minat, case=False, na=False) |
        #     df['nama_ukm'].str.contains(minat, case=False, na=False) |
        #     df['jenis_kegiatan'].str.contains(minat, case=False, na=False)
        # )
        
        # Filter data yang mengandung kata kunci di BANYAK kolom
        # Kita tambahkan pencarian di 'deskripsi' dan 'nilai_utama'
        mask = (
            df['kategori'].str.contains(minat, case=False, na=False) |
            df['nama_ukm'].str.contains(minat, case=False, na=False) |
            df['jenis_kegiatan'].str.contains(minat, case=False, na=False) |
            df['deskripsi'].str.contains(minat, case=False, na=False) |
            df['nilai_utama'].str.contains(minat, case=False, na=False)
        )

        results = df[mask]
        
        if results.empty:
            return f"DATA_NOT_FOUND: Tidak ditemukan UKM dengan kata kunci '{minat}'. Coba kata kunci yang lebih umum seperti 'Seni', 'Olahraga', atau 'Teknologi'."
        
        # Kembalikan hasil dalam bentuk string agar bisa dibaca LLM
        # return results.to_string(index=False)
        return results.to_json(orient="records")
    except Exception as e:
        return f"ERROR: {str(e)}"

# 3. DEFINISI AGEN

# Agen 1: User Proxy (Perantara User)
user_proxy = UserProxyAgent(
    name="User_Student",
    system_message="A human student looking for UKM recommendations.",
    code_execution_config={"work_dir": "coding", "use_docker": False},
    human_input_mode="TERMINATE",
    is_termination_msg=lambda x: "TERMINATE" in x.get("content", ""),
)

# Daftarkan fungsi ke user_proxy agar bisa dieksekusi
user_proxy.register_function(
    function_map={"search_ukm_by_interest": search_ukm_by_interest}
)

# Agen 2: Profile Analyzer (Psikolog)
profile_analyzer = AssistantAgent(
    name="ProfileAnalyzer",
    system_message="""Kamu adalah Ahli Psikologi Mahasiswa. 
    Kamu HANYA merespons jika pesan berasal dari User_Student
    Ekstrak 3 hal dari input user: 
    1. Minat Utama. PENTING: Ubah minat user menjadi Kategori Umum yang mungkin ada di kampus.
       Contoh: 
       - "Coding/Komputer" -> Ubah jadi "Teknologi"
       - "Gambar/Desain/Musik" -> Ubah jadi "Seni"
       - "Basket/Lari" -> Ubah jadi "Olahraga"
       - "Organisasi/Bisnis" -> Ubah jadi "Sosial" atau "Akademik"
       
       JANGAN gunakan kata spesifik seperti "Desain Grafis" untuk pencarian, gunakan kata seperti "Seni" atau "Kreatif".

    2. Tipe Kepribadian (Introvert/Ekstrovert).
    3. Tujuan Pengembangan Diri.

    Tugasmu adalah mengekstrak profil mahasiswa dalam format JSON:
    {
        "minat": ["Seni"],  <-- Pastikan ini satu kata kategori umum
        "kepribadian": "...",
        "goals": [...]
    }
    Setelah menghasilkan JSON: Tambahkan satu baris di akhir:  NEXT_AGENT: UKMDataSearcher
    JANGAN memberi penjelasan lain.
    Hanya keluarkan JSON + NEXT_AGENT.
    
    Jika kamu TIDAK YAKIN atau TIDAK BISA mengekstrak dengan benar,
    TULIS: FALLBACK
    
    """,
    llm_config=llm_config,
)

# Agen 3: UKM Data Searcher (Pencari Data - Tool Use)
ukm_searcher = AssistantAgent(
    name="UKMDataSearcher",
    system_message="""Kamu bertugas mencari data UKM.
    Input kamu: JSON profil mahasiswa dari ProfileAnalyzer.
    Trigger kamu: Kamu hanya merespons jika pesan mengandung NEXT_AGENT: UKMDataSearcher
    Kamu tidak boleh merespons input dari user secara langsung.
    
    PROSEDUR KERJA:
    1. Cek apakah ada trigger. Jika tidak, diam.
    2. Gabungkan semua minat dari profil menjadi string dengan pemisah '|'.
       Contoh: "Seni|Desain|Foto"
    3. Jalankan tool: search_ukm_by_interest(minat_gabungan)
    4. Tunggu hasil eksekusi tool.

    FORMAT OUTPUT (SANGAT KETAT):
    Kamu HARUS mengembalikan JSON dengan format ini:
    {
        "profile": <COPY_PASTE_PROFILE_INPUT>,
        "ukm_data": "<COPY_PASTE_HASIL_TOOL_MENTAH_MENTAH>",
        "selected_interest": "..."
    }

    ATURAN MATI (DO NOT BREAK):
    1. Field "ukm_data" HARUS berisi STRING MENTAH dari output fungsi. 
    2. JANGAN mencoba merapikan, meringkas, atau mengubah data UKM menjadi object/list baru. 
    3. Jika output tool adalah tabel teks berantakan, MASUKKAN APA ADANYA ke dalam string "ukm_data".
    4. Dilarang mengarang nama UKM atau deskripsi yang tidak muncul di output tool.

    Setelah menghasilkan JSON: Tambahkan satu baris di akhir:  NEXT_AGENT: ScoringAgent

    LARANGAN KERAS:
    - JANGAN memilihkan 1 UKM. Biarkan ScoringAgent yang memilih.
    - JANGAN meringkas output fungsi. Jika fungsi mengembalikan 10 baris, masukkan 10 baris itu ke JSON.
    - Jangan beri penjelasan tambahan di luar JSON.
    """,
    llm_config=llm_config,
)

# Daftarkan signature fungsi ke ukm_searcher agar dia tahu cara panggilnya
ukm_searcher.register_function(
    function_map={"search_ukm_by_interest": search_ukm_by_interest}
)

# Agen 4: Scoring Agent (Penilai Kecocokan)
scoring_agent = AssistantAgent(
    name="ScoringAgent",
    system_message=""" Kamu adalah agen penilai kecocokan UKM, yakni agen scoring.
    Kamu hanya merespons jika pesan mengandung: NEXT_AGENT: ScoringAgent
    ATURAN WAJIB:
    1. HANYA gunakan data UKM yang diberikan oleh UKMDataSearcher.
    2. JANGAN PERNAH mengarang nama UKM yang tidak ada di data Excel.
    3. Jika data UKM kosong atau "DATA_NOT_FOUND", output JSON dengan array "best_ukm" kosong.
    Sumber input:
    - Kamu akan menerima pesan dari UKMDataSearcher.
    - Pesan tersebut berisi JSON (profil mahasiswa + hasil UKM dari Excel)
    - Dan satu baris: NEXT_AGENT: ScoringAgent
    

    Aturan:
    1. Jika pesan TIDAK mengandung NEXT_AGENT: ScoringAgent, Jangan menjawab apa pun.

    2. Jika pesan valid:
    - Baca JSON yang diberikan.
    - Field yang tersedia:
        profile
        ukm_data
        selected_interest
    - Gunakan "ukm_data" untuk memilih 3 UKM terbaik.
    - Penilaian berdasarkan:
        • kecocokan personality
        • kecocokan goals
        • relevansi interest

    3. Output kamu HARUS dalam format JSON berikut:

    {
        "profile": {...},
        "best_ukm": [
            {"nama ukm": "...", "alasan": "..."},
            {"nama ukm": "...", "alasan": "..."},
            {"nama ukm": "...", "alasan": "..."}
        ]
    }

    4. Setelah JSON, tambahkan baris:
    NEXT_AGENT: RecommendationWriter

    Larangan:
    - Jangan berikan penjelasan lain di luar JSON + NEXT_AGENT.
    - Jangan merespons lebih dari sekali untuk input yang sama.
    """,
    llm_config=llm_config,
)

# Agen 5: Writer (Penulis Laporan)
writer_agent = AssistantAgent(
    name="RecommendationWriter",
    system_message="""Kamu adalah Konselor Akademik yang bijak dan persuasif.
    Kapan kamu harus berbicara:
    - Kamu HANYA merespons jika pesan mengandung: NEXT_AGENT: RecommendationWriter
    - Jika tidak ada trigger itu, JANGAN menjawab apa pun.

    Input dari ScoringAgent akan berupa JSON:
    {
        "profile": {...},
        "best_ukm": [...]
    }

    Tugasmu:
    1. Buat rekomendasi UKM final berdasarkan data JSON.
    2. Jelaskan alasan psikologis dan manfaat dari masing-masing UKM.
    3. Gunakan bahasa yang ramah, hangat, dan mudah dipahami mahasiswa.
    4. Format tulisan:
    - Sapaan ramah
    - Analisis singkat profil mahasiswa
    - Rekomendasi Top 3 UKM beserta alasan kenapa cocok secara psikologis
    - Pesan motivasi dan penutup

    5. Akhiri output dengan tepat satu kata:
    TERMINATE

    Larangan:
    - Jangan mengeluarkan JSON.
    - Jangan menjawab lebih dari sekali.
    """,
    llm_config=llm_config,
)

# 4. ORKESTRASI (Group Chat)
# Definisikan siapa boleh bicara ke siapa (Sesuai Diagram Alur)
allowed_transitions = {
    user_proxy: [profile_analyzer],       # User HANYA boleh lanjut ke ProfileAnalyzer
    profile_analyzer: [ukm_searcher],     # ProfileAnalyzer HANYA boleh lanjut ke Searcher
    ukm_searcher: [scoring_agent],        # Searcher HANYA boleh lanjut ke Scoring
    scoring_agent: [writer_agent],        # Scoring HANYA boleh lanjut ke Writer
    writer_agent: [user_proxy],           # Writer kembalikan ke User (untuk Terminate)
}
groupchat = GroupChat(
    agents=[user_proxy, profile_analyzer, ukm_searcher, scoring_agent, writer_agent],
    messages=[],
    max_round=10,
    allowed_or_disallowed_speaker_transitions=allowed_transitions,
    speaker_transitions_type="allowed",
    speaker_selection_method="auto" # Biarkan LLM memilih siapa yang bicara selanjutnya
)

manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)

# 5. INPUT USER & START

print("=== SISTEM REKOMENDASI UKM ===")
print("Silakan tuliskan deskripsi diri Anda.")
print("Ketik 'DONE' jika sudah selesai menulis.\n")

lines = []
while True:
    line = input()
    if line.strip().upper() == "DONE":
        break
    lines.append(line)

user_input = "\n".join(lines)

print("\nMemulai Sistem Rekomendasi UKM...\n")

user_proxy.initiate_chat(
    manager,
    message=user_input
)