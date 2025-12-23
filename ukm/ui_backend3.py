import sys
import os
import queue
import pandas as pd
import json
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# Global Queue
msg_queue = queue.Queue()

# kelas khusus untuk menangkap teks yang biasanya muncul di layar hitam atau terminal
class IOQueue:
    # fungsi ini jalan otomatis setiap ada teks yang mau dicetak
    def write(self, message):
        text = message.strip()
        # jika pesan ada
        if text:
            # jika itu pesan dari sistem internal autogen, maka lewati
            if "Context" in text: return
            # masukin message ke queue agar bisa tampil di aplikasi
            msg_queue.put({"type": "log", "content": text})

    def flush(self):
        pass

# konfigurasi LLM yang digunakan dengan platform Ollama
llm_config = {
    "model": 'qwen2.5:3b', 
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1", 
    "temperature": 0.1, 
    "max_tokens": 8000, 
    "price": [0.0, 0.0], 
}

# fungsi untuk mencari data ukm dari file excel
def get_ukm_data_from_excel(keywords: str) -> str:
    try:
        print(f"\n[SYSTEM] Sedang mencari di UKM_DATA... Kata Kunci: {keywords}")
        
        base_dir = os.path.dirname(__file__)
        file_path = os.path.join(base_dir, "ukm_data.xlsx")
        
        df = pd.read_excel(file_path)
        df = df.fillna("Tidak disebutkan")
        df = df.astype(str)
        
        search_terms = [k.strip().lower() for k in keywords.split(",")]
        all_results = pd.DataFrame()

        for term in search_terms:
            if term in ["all", "semua", ""]:
                mask = [True] * len(df)
            else:
                mask = (
                    df['nama_ukm'].str.lower().str.contains(term) |
                    df['kategori'].str.lower().str.contains(term) |
                    df['jenis_kegiatan'].str.lower().str.contains(term) |
                    df['deskripsi'].str.lower().str.contains(term) |
                    df['nilai_utama'].str.lower().str.contains(term)
                )
            matched = df[mask]
            all_results = pd.concat([all_results, matched])
        
        all_results = all_results.drop_duplicates(subset=['nama_ukm'])

        # Jika gak ketemu ukm dengan kata kunci di excel, maka kasih pesan dan terminate
        if all_results.empty:
            return "DATABASE_STATUS: KOSONG. Tidak ada UKM yang cocok dengan kriteria. TERMINATE"
        
        # ambil maksimal 10 untuk konsistensi rekomendasi
        limit = 10
        final_results = all_results.head(limit)
        
        # log untuk kasi tahu ketemu berapa baris
        return f"DATABASE_RESULT:\n{final_results.to_json(orient='records')}"
    # jika terjadi masalah atau error sistem
    except Exception as e:
        return f"SYSTEM ERROR: {str(e)}"

# Fungsi ini untuk di UKMDataSearcher.
# otomatis mengambil pesan terakhir (Keywords dari ProfileAnalyzer),
# mencari di Excel, dan membalas sebagai dirinya sendiri.
def searcher_auto_reply(recipient, messages, sender, config):
    # cek jika belum ada pesan sejarah obrolan maka berhenti
    if not messages:
        return False, None
    
    # ambil pesan terakhir dari agen sebelumnya yaitu profile analyzer
    last_msg = messages[-1]
    last_content = last_msg.get('content', '').strip()
    
    # jalankan fungsi pencarian excel menggunakan kata kunci dari pesan tadi
    excel_result = get_ukm_data_from_excel(last_content)
    
    # return True agar LLM tidak dipanggil, melainkan hasil ini yang dipakai
    return True, excel_result

# kelas khusus untuk mengatur urutan bicara agen secara kaku
class FiveAgentStrictChat(GroupChat):
    # fungsi untuk memilih siapa yang bicara selanjutnya
    def select_speaker(self, last_speaker, selector):
        def get_agent(name):
            for agent in self.agents:
                if agent.name == name: return agent
            return self.agents[0]

        # untuk mengamankan masalah looping
        # jika ada pesan yang mengandung 'json_final', paksa kembali ke User_Student untuk terminasi
        if self.messages:
            last_content = self.messages[-1].get('content', '')
            if "json_final" in last_content or "TERMINATE" in last_content:
                return get_agent("User_Student")

        if last_speaker.name == "User_Student":
            return get_agent("ProfileAnalyzer")
        
        if last_speaker.name == "ProfileAnalyzer":
            return get_agent("UKMDataSearcher")
        
        if last_speaker.name == "UKMDataSearcher":
            # Jika hasil search kosong
            if self.messages:
                last_content = self.messages[-1].get('content', '')
                if "TERMINATE" in last_content:
                    return get_agent("User_Student")
            return get_agent("ScoringAgent")
        
        if last_speaker.name == "ScoringAgent":
            return get_agent("RecommendationWriter")
        
        if last_speaker.name == "RecommendationWriter":
            return get_agent("User_Student")

        return get_agent("User_Student")

# fungsi utama untuk menjalankan sesi obrolan
def run_chat_session(user_story):
    original_stdout = sys.stdout
    sys.stdout = IOQueue()
    
    try:
        # DEFINISI 5 AGEN
        # agen ke-1 pengguna sebagai murid
        user = UserProxyAgent(
            name="User_Student",
            system_message="Student.",
            human_input_mode="NEVER",
            code_execution_config=False,
            # Ini pemicu rem tangan (Stop)
            is_termination_msg=lambda x: "TERMINATE" in x.get("content", "")
        )

        # agen ke-2 yang berperan sebaagai analisis profile berdasarkan input user story pengguna
        profile = AssistantAgent(
            name="ProfileAnalyzer",
            system_message="""Tugas: Kamu adalah penerjemah minat user menjadi KATA KUNCI DATABASE UKM.
            
            PENTING: Jangan gunakan kata umum jika user spesifik. Gunakan tabel di bawah ini sebagai acuan mutlak.
            
            KAMUS PEMETAAN (Input User -> Output Keyword):
            
            [OLAHRAGA]
            - Basket, NBA, Dribble, Ring -> "Basket"
            - Bola, Sepakbola, Futsal, Kiper -> "Futsal"
            - Lari, Fisik, Gym, Sport, Bulu Tangkis, Tennis, Padel -> "Olahraga"
            
            [SENI & MUSIK]
            - Band, Gitar, Drum, Bass, Ngeband -> "Band, Musik"
            - Nyanyi, Vokal, Choir, Suara -> "Paduan Suara"
            - Nari, Dance, Tradisional, Gerak -> "Tari"
            - Foto, Kamera, Video, Editing, Gambar, Desain -> "Fotografi"
            - Akting, Drama, Peran, Panggung, Film -> "Teater"
            
            [TEKNOLOGI & ILMIAH]
            - Koding, Coding, Programmer, Web, App, IT-> "Coding, Teknologi"
            - Robot, Elektro, Rakit, Mekanik -> "Robotika"
            
            [SOSIAL & LAINNYA]
            - Gunung, Hiking, Camping, Hutan, Alam, Outdoor, Staycation, Outing -> "Mapala, Alam"
            - Inggris, Public Speaking, Ngomong, Debat, Pidato -> "Debat"
            - Bisnis, Jualan, Usaha, Dagang, Startup, Saham -> "Entrepreneur"
            - Menulis, Nulis, Berita, Artikel, Jurnalistik, Baca -> "Pers"
            - Medis, P3K, Kesehatan, Dokter, Palang Merah -> "KSR"
            - Islam, Ngaji, Dakwah, Rohis -> "Kerohanian Islam"
            
            ATURAN KERAS:
            1. JANGAN menambah keyword yang tidak disebut user.
            2. Jika user HANYA bicara musik, JANGAN output Coding/Teknologi.
            3. Fokus pada kata benda aktivitas yang disebut user.
            4. Jika minat user TIDAK ADA di kamus (Contoh: Masak, Otomotif, Tidur), JANGAN DIPAKSAKAN ke kategori lain.
            
            CONTOH BENAR:
            User: "Suka musik" -> Band, Musik
            User: "Suka naik gunung" -> Mapala
            
            Output HANYA kata kunci dipisah koma.
            """,
            llm_config=llm_config,
        )
        # agen ke-3 yang berfungsi untuk mencari data ke excel berdasarkan kata kunci dari agen sebelumnya
        searcher = UserProxyAgent(
            name="UKMDataSearcher",
            system_message="Executor Pencarian Data.",
            human_input_mode="NEVER",
            code_execution_config=False, 
        )
        
        searcher.register_reply(
            trigger=lambda x: True,
            reply_func=searcher_auto_reply, 
            position=0
        )

        # agen ke-4 yang berfungsi untuk ranking ukm yang telah di cari oleh agen sebelumnya dan mencocokanya dengan user story
        scoring = AssistantAgent(
            name="ScoringAgent",
            system_message="""Kamu adalah Data Filter.
            
            Tugas:
            1. Dari "DATABASE_RESULT", pilih 2-3 UKM terbaik.
            2. PENTING: Jika keyword user mencakup BERBEDA KATEGORI (Misal: Teknologi DAN Seni), JANGAN pilih Teknologi semua. Ambil 1 Teknologi dan 1 Seni agar seimbang.
            3. Siapkan data alasan kasar.
            
            Output JSON Sederhana (Raw Data):
            ```json
            {
                "selected_data": [
                    {
                        "name": "Nama UKM",
                        "schedule": "Jadwal",
                        "raw_match": "Alasan kasar (cocok keyword apa)"
                    }
                ]
            }
            ```
            JANGAN PAKAI FORMAT json_final. JANGAN TERMINATE.
            """,
            llm_config=llm_config,
        )

        # agen ke-5 adalah agen terakhir yang membuat narasi alasan, dan output data ukm dengan format JSON kustom agar terlihat di aplikasi
        writer = AssistantAgent(
            name="RecommendationWriter",
            system_message="""Kamu adalah Seorang Penulis Yang Handal dan Selalu Menulis kata TERMINATE di setiap akhiran jawabanmu.
            
            Tugas:
            1. Ambil data mentah.
            2. Buat JSON Final untuk UI.
            
            Untuk "long_reason":
            - Gunakan bahasa yang asik dan mengajak.
            - JANGAN meniru contoh secara buta. Sesuaikan dengan topik UKM-nya.
            - Jika UKM Musik, bahas musik. Jika UKM Bola, bahas bola.
            
            FORMAT WAJIB (Sampai ke TERMINATE):
            ```json_final
            {
                "recommendations": [
                    {
                        "name": "...",
                        "schedule": "...",
                        "short_reason": "Headline singkat",
                        "long_reason": "Paragraf persuasif yang relevan dengan UKM tersebut..."
                    }
                ]
            }
            ```
            TERMINATE
            """,
            llm_config=llm_config,
        )
        
        # orkestrasi
        # wadah grup obrolan dengan aturan urutan bicara yang kaku
        groupchat = FiveAgentStrictChat(
            agents=[user, profile, searcher, scoring, writer],
            messages=[],
            max_round=5,
            speaker_selection_method="auto", 
            allow_repeat_speaker=False
        )
        
        # manajer yang mengatur lalu lintas pesan di dalam grup
        manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)

        # mulai percakapan dipancing oleh user dengan cerita awalnya
        user.initiate_chat(
            manager,
            message=user_story
        )
    # untuk catch error ketika terjadi masalah
    except Exception as e:
        msg_queue.put({"type": "log", "content": f"CRITICAL ERROR: {str(e)}"})
    finally:
        sys.stdout = original_stdout
        msg_queue.put({"type": "done", "content": "Selesai"})