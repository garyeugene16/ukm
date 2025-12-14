import sys
import queue
import json
import pandas as pd
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# Global Queue
msg_queue = queue.Queue()

class IOQueue:
    def write(self, message):
        if message.strip():
            # Filter log internal autogen yang membingungkan
            if "TERMINATE" not in message and "Context" not in message:
                msg_queue.put({"type": "log", "content": message})
    def flush(self):
        pass

# Konfigurasi LLM
llm_config = {
    "model": 'llama3.2:3b', 
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1", 
    "temperature": 0.3, # Naikkan sedikit agar Advisor lebih berani bicara
}

# --- TOOL PENCARI DATA (OPTIMIZED) ---
def get_ukm_data_from_excel(keywords: str) -> str:
    try:
        print(f"\n[SYSTEM] MENCARI DI EXCEL: {keywords}...")
        df = pd.read_excel("ukm_data.xlsx")
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
                    df['deskripsi'].str.lower().str.contains(term)
                )
            matched = df[mask]
            all_results = pd.concat([all_results, matched])
        
        all_results = all_results.drop_duplicates(subset=['nama_ukm'])

        if all_results.empty:
            return "DATABASE_STATUS: KOSONG. Tidak ada UKM yang cocok."
        
        # --- OPTIMISASI DATA ---
        # Hanya ambil kolom penting agar LLM tidak pusing baca JSON kepanjangan
        # Pastikan kolom ini ada di Excel kamu. Jika beda, sesuaikan.
        columns_to_keep = ['nama_ukm', 'jadwal_latihan', 'deskripsi', 'nilai_utama']
        
        # Filter kolom jika ada, jika tidak ambil semua
        available_cols = [c for c in columns_to_keep if c in all_results.columns]
        if available_cols:
            final_df = all_results[available_cols]
        else:
            final_df = all_results

        limited_results = final_df.head(3) # Cukup 3 saja biar ringan
        data_json = limited_results.to_json(orient="records")
        
        return f"DATABASE_RESULT (SOURCE OF TRUTH):\n{data_json}"

    except Exception as e:
        return f"SYSTEM ERROR: {str(e)}"

# --- MIDDLEWARE REPLY ---
def keyword_execution_reply(recipient, messages, sender, config):
    last_msg = messages[-1]
    last_content = last_msg.get('content', '').strip()
    last_speaker_name = last_msg.get('name', '')

    if "Intention_Analyst" in last_speaker_name:
        if "DATABASE_RESULT" in last_content: return False, None
        
        print(f"[MIDDLEWARE] Menangkap Keyword: {last_content}")
        excel_result = get_ukm_data_from_excel(last_content)
        return True, excel_result

    return False, None

# --- CLASS CUSTOM GROUPCHAT (WASIT LEBIH TEGAS) ---
class StrictGroupChat(GroupChat):
    def select_speaker(self, last_speaker, selector):
        def get_agent(name):
            for agent in self.agents:
                if agent.name == name: return agent
            return self.agents[0]

        if not self.messages:
            return get_agent("Intention_Analyst")

        last_message = self.messages[-1]
        content = last_message['content']

        # 1. Jika baru saja dapat DATA EXCEL -> Wajib ke Advisor
        if "DATABASE_RESULT" in content:
            return get_agent("Ukm_Advisor")
        
        # 2. Jika Advisor sudah bicara (apapun isinya, bahkan kosong) -> STOP
        if last_speaker.name == "Ukm_Advisor":
            # Paksa pindah ke Executor agar loop berhenti
            return get_agent("System_Executor")

        # 3. Logic Standar
        if "json_final" in content or "TERMINATE" in content:
            return get_agent("System_Executor")

        if last_speaker.name == "Intention_Analyst":
            return get_agent("System_Executor")

        if last_speaker.name == "System_Executor":
            return get_agent("Intention_Analyst")

        return get_agent("Intention_Analyst")

# --- MAIN SESSION ---
def run_chat_session(user_story):
    original_stdout = sys.stdout
    sys.stdout = IOQueue()
    
    try:
        # Agent 1: Analyst
        analyst = AssistantAgent(
            name="Intention_Analyst",
            system_message="Tugas: Baca input, outputkan HANYA 1-2 kata kunci kategori (pisahkan koma). Contoh: Otomotif, Seni.",
            llm_config=llm_config,
        )

        # Agent 2: Proxy / Executor
        user_proxy = UserProxyAgent(
            name="System_Executor",
            system_message="Executor.",
            human_input_mode="NEVER",
            code_execution_config=False, 
        )
        
        user_proxy.register_reply(
            trigger=lambda x: True, 
            reply_func=keyword_execution_reply, 
            position=0
        )

        # Agent 3: Advisor (PROMPT SIMPEL)
        # Kita ubah promptnya agar dia tidak takut salah
        advisor = AssistantAgent(
            name="Ukm_Advisor",
            system_message="""Kamu adalah Advisor Kampus.
            
            Tugasmu:
            1. Analisis data JSON "DATABASE_RESULT".
            2. Pilih MAKSIMAL 2 UKM yang paling relevan dengan minat user.
            3. Jika minat user beragam (misal: olahraga DAN seni), cobalah pilih 1 dari masing-masing kategori jika datanya ada.

            Format Output Wajib (JSON Array):
            
            Halo! Berdasarkan minatmu yang beragam, ini rekomendasi terbaik kami:
            
            ```json_final
            {
                "recommendations": [
                    {
                        "name": "Nama UKM 1",
                        "schedule": "Jadwal UKM 1",
                        "reason": "Alasan kenapa cocok"
                    },
                    {
                        "name": "Nama UKM 2",
                        "schedule": "Jadwal UKM 2",
                        "reason": "Alasan kenapa cocok"
                    }
                ]
            }
            ```
            
            TERMINATE
            """,
            llm_config=llm_config,
        )

        # Inisialisasi GroupChat Custom
        groupchat = StrictGroupChat(
            agents=[user_proxy, analyst, advisor],
            messages=[],
            max_round=8,
            speaker_selection_method="auto", 
            allow_repeat_speaker=False
        )

        manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)

        user_proxy.initiate_chat(
            manager,
            message=user_story
        )

    except Exception as e:
        msg_queue.put({"type": "log", "content": f"CRITICAL ERROR: {str(e)}"})
    finally:
        sys.stdout = original_stdout
        msg_queue.put({"type": "done", "content": "Selesai"})