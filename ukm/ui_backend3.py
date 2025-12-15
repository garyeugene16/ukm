import sys
import os
import queue
import pandas as pd
import json
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# antrian untuk menyimpan pesan yang akan dikirim ke tampilan pengguna
msg_queue = queue.Queue()

# kelas khusus untuk menangkap teks yang biasanya muncul di layar hitam atau terminal
class IOQueue:
    # fungsi ini jalan otomatis setiap ada teks yang mau dicetak
    def write(self, message):
        text = message.strip()
        # jika teksnya tidak kosong maka proses
        if text:
            # Filter hanya pesan sistem internal autogen yang tidak perlu
            if "Context" in text: 
                return
            
            # masukkan pesan ke antrean agar bisa dibaca di layar aplikasi
            msg_queue.put({"type": "log", "content": text})

    def flush(self):
        pass

# pengaturan llm yang akan dipakai
llm_config = {
    "model": 'llama3.2:3b', # nama model ai yang digunakan
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1",  # alamat server di komputer sendiri
    "temperature": 0.3, # tingkat kreativitas ai, rendah berarti lebih patuh aturan
    "max_tokens": 8192, # batas maksimal panjang jawaban
    "price": [0.0, 0.0], 
}

# fungsi untuk mencari data ukm dari file excel
def get_ukm_data_from_excel(keywords: str) -> str:
    try:
        # Tampilkan log ke UI
        print(f"\n[SYSTEM] Sedang mencari di UKM_DATA... Kata Kunci: {keywords}")
        
        base_dir = os.path.dirname(__file__)
        file_path = os.path.join(base_dir, "ukm_data.xlsx")
        print(f"\n[SYSTEM] Sedang mencari di {file_path}... Kata Kunci: {keywords}")
        
        df = pd.read_excel(file_path) # baca file excel yang berisi daftar ukm
        df = df.fillna("Tidak disebutkan") # isi data yang kosong dengan tulisan tidak disebutkan agar tidak error
        df = df.astype(str) # ubah semua format data menjadi teks
        
        search_terms = [k.strip().lower() for k in keywords.split(",")] # pecah kata kunci pencarian berdasarkan tanda koma dan huruf kecilkan
        all_results = pd.DataFrame()

        # lakukan pencarian untuk setiap kata kunci
        for term in search_terms:
            # jika kata kuncinya semua maka ambil semua data
            if term in ["all", "semua", ""]:
                mask = [True] * len(df)
            else:
                # cari kecocokan kata di nama, kategori, deskripsi, atau nilai utama
                mask = (
                    df['nama_ukm'].str.lower().str.contains(term) |
                    df['kategori'].str.lower().str.contains(term) |
                    df['jenis_kegiatan'].str.lower().str.contains(term) |
                    df['deskripsi'].str.lower().str.contains(term) |
                    df['nilai_utama'].str.lower().str.contains(term)
                )
            matched = df[mask] # ambil data yang cocok
            all_results = pd.concat([all_results, matched]) # gabungkan hasil pencarian ini dengan hasil sebelumnya
        
        all_results = all_results.drop_duplicates(subset=['nama_ukm']) # hapus data ukm yang muncul ganda atau kembar

        # jika hasil pencarian kosong berikan pesan status kosong
        if all_results.empty:
            return "DATABASE_STATUS: KOSONG. Tidak ada UKM yang cocok dengan kriteria. TERMINATE"
        
        # Ambil maksimal 10 agar LLM punya pilihan lebih banyak
        limit = 10
        final_results = all_results.head(limit)
        
        return f"DATABASE_RESULT:\n{final_results.to_json(orient='records')}"

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
    
    # Return True agar LLM tidak dipanggil, melainkan hasil ini yang dipakai
    return True, excel_result

# kelas khusus untuk mengatur urutan bicara agen secara kaku
class FiveAgentStrictChat(GroupChat):
    # fungsi untuk memilih siapa yang bicara selanjutnya
    def select_speaker(self, last_speaker, selector):
        def get_agent(name):
            for agent in self.agents:
                if agent.name == name: return agent
            return self.agents[0]

        if last_speaker.name == "User_Student":
            return get_agent("ProfileAnalyzer")

        if last_speaker.name == "ProfileAnalyzer":
            return get_agent("UKMDataSearcher")
        
        if last_speaker.name == "UKMDataSearcher":
            # Jika hasil search mengandung TERMINATE, maka stop (kembali ke User_Student)
            # Pesan terakhir ada di self.messages[-1]
            if self.messages:
                last_content = self.messages[-1].get('content', '')
                if "TERMINATE" in last_content:
                    return get_agent("User_Student")

            return get_agent("ScoringAgent")

        if last_speaker.name == "ScoringAgent":
            return get_agent("RecommendationWriter")

        if last_speaker.name == "RecommendationWriter":
            return get_agent("User_Student") # Selesai
        # kondisi standar kembali ke murid
        return get_agent("User_Student")

# fungsi utama untuk menjalankan sesi obrolan
def run_chat_session(user_story):
    # simpan pengaturan layar asli komputer
    original_stdout = sys.stdout
    # alihkan tampilan layar ke sistem antrean kita
    sys.stdout = IOQueue()
    
    try:
        # --- DEFINISI 5 AGEN ---

        # agen 1 pengguna sebagai murid
        user = UserProxyAgent(
            name="User_Student",
            system_message="Student.",
            human_input_mode="NEVER", #tidak ada input dari manusia
            code_execution_config=False,
            is_termination_msg=lambda x: "TERMINATE" in x.get("content", "") # chat berhenti jika ada kata terminate
        )

        # agen 2 analis profil bertugas ekstrak minat
        profile = AssistantAgent(
            name="ProfileAnalyzer",
            # perintah untuk hanya mengeluarkan kata kunci
            system_message="""Tugas: Analisis cerita user dan ekstrak TOPIK KEGIATAN konkret (Contoh: Basket, Koding, Teater, Musik). 
            HINDARI kata sifat umum/soft-skill seperti 'Tim', 'Sosial', 'Belajar', 'Kreatif' kecuali jika itu adalah satu-satunya petunjuk.
            Fokus pada Kata Benda/Subjek.
            Output HANYA kata kunci dipisah koma.
            Contoh: Fotografi, Teknologi, Seni Rupa.""",
            llm_config=llm_config,
        )

        # 3. UKM Data Searcher (Executor)
        # # agen pencarian data
        searcher = UserProxyAgent(
            name="UKMDataSearcher",
            system_message="Executor Pencarian Data.",
            human_input_mode="NEVER",
            code_execution_config=False, 
        )
        
        # pasang fungsi perantara ke agen ini agar dia menjalankan kode untuk mencari di excel
        searcher.register_reply(
            trigger=lambda x: True, # Selalu trigger ketika giliran dia
            reply_func=searcher_auto_reply, 
            position=0
        )

        # agen 4 penilai bertugas memilih ukm terbaik dari hasil pencarian
        scoring = AssistantAgent(
            name="ScoringAgent",
            # perintah untuk memilih maksimal 3 ukm dan format json
            system_message="""Kamu adalah Advisor Kampus. 
            
            Tugasmu:
            1. Analisis data JSON "DATABASE_RESULT" yang diberikan UKMDataSearcher.
            2. Pilih MAKSIMAL 3 UKM yang paling relevan dengan minat user.
            3. Jika minat user beragam, pilih variasi kategori.
            4. PASTIKAN JSON valid dan lengkap. Jangan biarkan terpotong. 

            Format Output Wajib (JSON Murni):
            ```json
            {
                "recommendations": [
                    {
                        "name": "Nama UKM 1",
                        "schedule": "Jadwal",
                        "reason": "Alasan singkat & padat kenapa cocok (maks 2 kalimat)"
                    },
                     {
                        "name": "Nama UKM 2",
                        "schedule": "Jadwal",
                        "reason": "Alasan singkat & padat kenapa cocok (maks 2 kalimat)"
                    },
                    {
                        "name": "Nama UKM 3",
                        "schedule": "Jadwal",
                        "reason": "Alasan singkat & padat kenapa cocok (maks 2 kalimat)"
                    }
                ]
            }
            ```
            JANGAN menulis TERMINATE. Cukup berikan JSON saja agar Writer bisa membacanya.
            """,
            llm_config=llm_config,
        )

        # 5. Writer Agent
        # agen 5 penulis bertugas merangkai kata kata manis untuk user
        writer = AssistantAgent(
            name="RecommendationWriter",
            system_message="""Kamu adalah Konselor Akademik.
            
            Tugas:
            1. Baca JSON rekomendasi dari ScoringAgent.
            2. Tulis surat rekomendasi yang personal dan memotivasi untuk mahasiswa tersebut.
            
            PENTING (WAJIB AGAR SISTEM BEKERJA):
            Setelah selesai menulis surat, kamu HARUS menyalin ulang JSON rekomendasi persis seperti yang diberikan ScoringAgent di bagian paling bawah.
            Gunakan format tag khusus: ```json_final ... ```
            
            Contoh Output Kamu:
            "Halo, berdasarkan minatmu blablabla...." (Surat Narasi)
            
            Di ikuti dengan data JSON (WAJIB)
            ```json_final
            {
                "recommendations": [...]
            }
            ```
            
            Akhiri pesanmu dengan kata: TERMINATE
            """,
            llm_config=llm_config,
        )

        # orkestrasi
        # wadah grup obrolan dengan aturan urutan bicara yang kaku
        groupchat = FiveAgentStrictChat(
            agents=[user, profile, searcher, scoring, writer],
            messages=[],
            max_round=10,
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

    except Exception as e: # tangkap error jika ada masalah besar
        msg_queue.put({"type": "log", "content": f"CRITICAL ERROR: {str(e)}"})
    finally:
        sys.stdout = original_stdout
        msg_queue.put({"type": "done", "content": "Selesai"})