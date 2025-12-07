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
    """
    try:
        df = pd.read_excel("ukm_data.xlsx")
        
        # Filter data yang mengandung kata kunci
        # Cari di kolom 'kategori' dan 'nama_ukm'
        # mask = df['kategori'].str.contains(minat, case=False, na=False) | \
        # df['nama_ukm'].str.contains(minat, case=False, na=False)
        
        mask = (
            df['kategori'].str.contains(minat, case=False, na=False) |
            df['nama_ukm'].str.contains(minat, case=False, na=False) |
            df['jenis_kegiatan'].str.contains(minat, case=False, na=False)
        )

        results = df[mask]
        
        if results.empty:
            return "Tidak ditemukan UKM yang sesuai dengan minat tersebut."
        
        # Kembalikan hasil dalam bentuk string agar bisa dibaca LLM
        return results.to_string(index=False)
    except Exception as e:
        return f"ERROR: {str(e)}"
        # return f"Terjadi error saat membaca data: {str(e)}"

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
    Ekstrak 3 hal: 
    1. Minat Utama (Seni, Olahraga, Teknologi, dll).
    2. Tipe Kepribadian (Introvert/Ekstrovert).
    3. Tujuan Pengembangan Diri.
    Tugasmu adalah mengekstrak profil mahasiswa dalam format JSON:
    {
        "interests": [...],
        "personality": "...",
        "goals": [...]
    }
    2. Setelah menghasilkan JSON: Tambahkan satu baris di akhir:  NEXT_AGENT: UKMDataSearcher
    JANGAN menggunakan tag <call>.
    JANGAN memberi penjelasan lain.
    Hanya keluarkan JSON + NEXT_AGENT.
    
    3.Jika kamu TIDAK YAKIN atau TIDAK BISA mengekstrak dengan benar,
    TULIS: FALLBACK
    
    """,
    llm_config=llm_config,
)

# Agen 3: UKM Data Searcher (Pencari Data - Tool Use)
ukm_searcher = AssistantAgent(
    name="UKMDataSearcher",
    system_message="""Kamu bertugas mencari data UKM.
    Input kamu: JSON profil mahasiswa dari ProfileAnalyzer.
    Kamu hanya merespons jika pesan mengandung: NEXT_AGENT: UKMDataSearcher
    Kamu tidak boleh merespons input dari user secara langsung.
    Cara kerja kamu:
    1. Kamu akan menerima pesan dari ProfileAnalyzer yang berisi:
    - JSON profil mahasiswa
    - Baris "NEXT_AGENT: UKMDataSearcher"

    2. Jika pesan TIDAK mengandung JSON atau tidak ada trigger NEXT_AGENT,
    → JANGAN menjawab apa pun.

    3. Jika pesan valid:
    - Baca JSON yang diberikan.
    - Ambil minat utama mahasiswa dari field "interests".
        Jika lebih dari satu, gunakan minat pertama (index 0).
    - Panggil fungsi Python berikut:
        search_ukm_by_interest(minat)

    4. Output kamu HARUS berupa JSON dengan format:
    {
        "profile": {...},
        "ukm_data": "hasil dari fungsi",
        "selected_interest": "minat yang kamu gunakan"
    }

    5. Setelah JSON, tambahkan baris:
    NEXT_AGENT: ScoringAgent

    Aturan wajib:
    - Jangan gunakan tag <call>.
    - Jangan beri penjelasan tambahan di luar JSON.
    - Jangan merespons lebih dari sekali untuk input yang sama.
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
    Input: Profil Mahasiswa (dari ProfileAnalyzer) dan Daftar UKM Kandidat (dari UKMDataSearcher).
    Sumber input:
    - Kamu akan menerima pesan dari UKMDataSearcher.
    - Pesan tersebut berisi JSON (profil mahasiswa + hasil UKM dari Excel)
    - Dan satu baris: NEXT_AGENT: ScoringAgent

    Aturan:
    1. Jika pesan TIDAK mengandung NEXT_AGENT: ScoringAgent,
    → Jangan menjawab apa pun.

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
            {"nama": "...", "alasan": "..."},
            {"nama": "...", "alasan": "..."},
            {"nama": "...", "alasan": "..."}
        ]
    }

    4. Setelah JSON, tambahkan baris:
    NEXT_AGENT: RecommendationWriter

    Larangan:
    - Jangan menggunakan tag <call>.
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
    - Jangan menggunakan <call>.
    - Jangan mengeluarkan JSON.
    - Jangan menjawab lebih dari sekali.
    """,
    llm_config=llm_config,
)

# 4. ORKESTRASI (Group Chat)
groupchat = GroupChat(
    agents=[user_proxy, profile_analyzer, ukm_searcher, scoring_agent, writer_agent],
    messages=[],
    max_round=15,
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