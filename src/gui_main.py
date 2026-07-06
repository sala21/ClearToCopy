import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog  # Aggiunto filedialog
import json
import logging

from config import load_config
from main import run_pipeline
from events import EventBus


# ============================================================================
# PALETTE COLORI
# ============================================================================
BG = "#0b0f14"
PANEL_BG = "#131a24"
CARD_BG = "#1a2533"
BORDER = "#2a3a4a"
FG = "#d7e2ea"
FG_DIM = "#5b7a8a"
ACCENT_CYAN = "#00d4ff"
ACCENT_GREEN = "#37d67a"
ACCENT_RED = "#ff4d4f"
ACCENT_AMBER = "#ffb000"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 8)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_MONO = ("Consolas", 10)
FONT_MONO_SMALL = ("Consolas", 8)
TITLE_FONT = ("Segoe UI", 14, "bold")


# ============================================================================
# FINESTRA DI DEBUG
# ============================================================================
class DebugWindow:
    def __init__(self, master):
        self.window = tk.Toplevel(master)
        self.window.title("Debug Log Log")
        self.window.geometry("600x400")
        self.window.configure(bg=BG)

        self.text = scrolledtext.ScrolledText(
            self.window, wrap="word", bg="#05070a", fg=FG,
            font=FONT_MONO_SMALL, relief="flat", padx=10, pady=10
        )
        self.text.pack(fill="both", expand=True, padx=10, pady=10)
        self.text.config(state="disabled")

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_open = True

    def append_log(self, msg):
        if not self.is_open:
            return
        self.text.config(state="normal")
        self.text.insert("end", msg + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def on_close(self):
        self.is_open = False
        self.window.destroy()


# ============================================================================
# FINESTRA DI CONFIGURAZIONE
# ============================================================================
class ConfigWindow:
    def __init__(self, master, current_config, on_save_callback):
        self.window = tk.Toplevel(master)
        self.window.title("Configurazione Avanzata")
        self.window.geometry("450x550")
        self.window.configure(bg=BG)
        self.window.resizable(False, False)

        self.config = current_config
        self.on_save = on_save_callback

        # Notebook per Tab
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=FG,
                        padding=[12, 4], font=FONT_SMALL)
        style.map("TNotebook.Tab", background=[("selected", CARD_BG)],
                  foreground=[("selected", ACCENT_CYAN)])

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=15, pady=15)

        # Tab Audio & VAD
        tab_audio = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(tab_audio, text=" Audio & VAD ")
        self._build_audio_tab(tab_audio)

        # Tab API & Whisper
        tab_api = tk.Frame(notebook, bg=CARD_BG)
        notebook.add(tab_api, text=" API & Whisper ")
        self._build_api_tab(tab_api)

        # Footer Buttons
        btn_frame = tk.Frame(self.window, bg=BG)
        btn_frame.pack(fill="x", side="bottom", padx=15, pady=(0, 15))

        tk.Button(btn_frame, text="Annulla", command=self.window.destroy,
                  bg="#2a2a2a", fg=FG, activebackground="#3d3d3d", font=FONT,
                  relief="flat", padx=15, pady=5, bd=0).pack(side="right", padx=(10, 0))

        tk.Button(btn_frame, text="Salva Configurazione", command=self._save,
                  bg=ACCENT_CYAN, fg="#04140a", activebackground="#00b8e6", font=FONT_BOLD,
                  relief="flat", padx=15, pady=5, bd=0).pack(side="right")

    def _build_audio_tab(self, frame):
        tk.Label(frame, text="Parametri Acquisizione & Filtri", font=FONT_BOLD, fg=ACCENT_CYAN, bg=CARD_BG).pack(anchor="w", padx=15, pady=(15, 10))
        
        # Audio Rate
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Frequenza di Campionamento (Hz):", fg=FG, bg=CARD_BG).pack(side="left")
        self.rate_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.rate_ent.pack(side="right")
        self.rate_ent.insert(0, str(self.config.get("audio", {}).get("rate", 16000)))

        # Filtro Passa Banda
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=10)
        self.filter_var = tk.BooleanVar(value=self.config.get("audio", {}).get("filter_bandpass", True))
        tk.Checkbutton(r, text="Attiva Filtro Passa-Banda (300-3400 Hz)", variable=self.filter_var,
                       bg=CARD_BG, fg=FG, selectcolor="#05070a", activebackground=CARD_BG,
                       activeforeground=FG).pack(side="left")

        # Sezione VAD
        tk.Label(frame, text="Voice Activity Detection (VAD)", font=FONT_BOLD, fg=ACCENT_CYAN, bg=CARD_BG).pack(anchor="w", padx=15, pady=(20, 10))
        
        # Aggressività VAD
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Aggressività VAD (0-3):", fg=FG, bg=CARD_BG).pack(side="left")
        self.vad_agg_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.vad_agg_ent.pack(side="right")
        self.vad_agg_ent.insert(0, str(self.config.get("vad", {}).get("aggressiveness", 1)))

        # Silence Timeout
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Timeout Silenzio (secondi):", fg=FG, bg=CARD_BG).pack(side="left")
        self.vad_sil_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.vad_sil_ent.pack(side="right")
        self.vad_sil_ent.insert(0, str(self.config.get("vad", {}).get("silence_timeout_s", 1.0)))

        # Max Utterance
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Durata Massima Segmento (sec):", fg=FG, bg=CARD_BG).pack(side="left")
        self.vad_max_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.vad_max_ent.pack(side="right")
        self.vad_max_ent.insert(0, str(self.config.get("vad", {}).get("max_utterance_s", 15.0)))

    def _build_api_tab(self, frame):
        tk.Label(frame, text="Credenziali ed Endpoint Groq", font=FONT_BOLD, fg=ACCENT_CYAN, bg=CARD_BG).pack(anchor="w", padx=15, pady=(15, 10))
        
        # API KEY
        tk.Label(frame, text="Groq API Key:", fg=FG, bg=CARD_BG).pack(anchor="w", padx=15)
        self.api_key_ent = tk.Entry(frame, bg="#05070a", fg=FG, insertbackground=FG, bd=0, font=FONT, show="*")
        self.api_key_ent.pack(fill="x", padx=15, pady=(4, 10))
        self.api_key_ent.insert(0, self.config.get("api", {}).get("groq", {}).get("api_key", ""))

        # Sezione Whisper
        tk.Label(frame, text="Parametri Modello Whisper", font=FONT_BOLD, fg=ACCENT_CYAN, bg=CARD_BG).pack(anchor="w", padx=15, pady=(15, 10))

        # Modello
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Modello Groq:", fg=FG, bg=CARD_BG).pack(side="left")
        self.model_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=22, font=FONT)
        self.model_ent.pack(side="right")
        self.model_ent.insert(0, self.config.get("whisper", {}).get("model", "whisper-large-v3"))

        # Lingua
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Lingua di base (es. 'en', 'it'):", fg=FG, bg=CARD_BG).pack(side="left")
        self.lang_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.lang_ent.pack(side="right")
        self.lang_ent.insert(0, self.config.get("whisper", {}).get("language", "en"))

        # Concorrenza Worker
        r = tk.Frame(frame, bg=CARD_BG)
        r.pack(fill="x", padx=15, pady=4)
        tk.Label(r, text="Thread Concorrenti (Worker):", fg=FG, bg=CARD_BG).pack(side="left")
        self.workers_ent = tk.Entry(r, bg="#05070a", fg=FG, insertbackground=FG, bd=0, width=10, font=FONT)
        self.workers_ent.pack(side="right")
        self.workers_ent.insert(0, str(self.config.get("whisper", {}).get("max_workers", 4)))

    def _save(self):
        try:
            new_cfg = {
                "audio": {
                    "rate": int(self.rate_ent.get()),
                    "channels": self.config.get("audio", {}).get("channels", 1),
                    "frame_duration_ms": self.config.get("audio", {}).get("frame_duration_ms", 30),
                    "filter_bandpass": self.filter_var.get()
                },
                "vad": {
                    "aggressiveness": int(self.vad_agg_ent.get()),
                    "silence_timeout_s": float(self.vad_sil_ent.get()),
                    "max_utterance_s": float(self.vad_max_ent.get()),
                    "min_segment_duration_s": self.config.get("vad", {}).get("min_segment_duration_s", 0.6),
                    "activation_ratio": self.config.get("vad", {}).get("activation_ratio", 0.4)
                },
                "api": {
                    "groq": {
                        "api_key": self.api_key_ent.get().strip()
                    }
                },
                "whisper": {
                    "model": self.model_ent.get().strip(),
                    "language": self.lang_ent.get().strip(),
                    "max_workers": int(self.workers_ent.get())
                },
                "debug": self.config.get("debug", {})
            }

            if not new_cfg["api"]["groq"]["api_key"]:
                raise ValueError("La chiave API Groq è obbligatoria.")

            self.on_save(new_cfg)
            self.window.destroy()
        except Exception as e:
            messagebox.showerror("Errore di Validazione", f"Controlla i campi inseriti:\n{e}", parent=self.window)

    def on_close(self):
        self.window.destroy()


# ============================================================================
# INTERFACCIA PRINCIPALE (GUI)
# ============================================================================
class TranscriberGUI:
    def __init__(self, root):
        self.root = root
        self.config = load_config()

        self.event_bus = EventBus()
        self.stop_event = threading.Event()
        self.pipeline_thread = None
        self.running = False
        self.debug_enabled = False

        self.debug_window = None
        self.config_window = None
        self.transcript_buffer = []

        # Inizializzazione Logger custom per intercettare i log di debug
        root_logger = logging.getLogger("AudioTranscriber")
        from logger import DebugBufferHandler
        self.debug_handler = DebugBufferHandler()
        root_logger.addHandler(self.debug_handler)

        self._build_ui()
        self._sync_quick_config_labels()

        # Inizia il polling degli eventi asincroni
        self.root.after(100, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _card(self, parent, title, height=None, expand=False):
        """Helper per creare un pannello stilizzato ad effetto card."""
        frame = tk.Frame(parent, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)
        if height:
            frame.pack_propagate(False)
            frame.configure(height=height)
        frame.pack(fill="both", expand=expand, pady=(0, 12))

        lbl_frame = tk.Frame(frame, bg=PANEL_BG)
        lbl_frame.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(lbl_frame, text=title, font=FONT_BOLD, fg=FG_DIM, bg=PANEL_BG).pack(side="left")
        return frame

    def _build_ui(self):
        self.root.title("ATC Radio Transcriber")
        
        # Finestra ottimizzata per schermi di PC portatili
        self.root.geometry("960x720") 
        self.root.configure(bg=BG)
        self.root.minsize(820, 500) 

        # HEADER
        header = tk.Frame(self.root, bg=BG, height=50)
        header.pack(fill="x", padx=20, pady=(12, 6))

        tk.Label(header, text="🎙️ ATC RADIO TRANSCRIBER", font=TITLE_FONT,
                 fg=ACCENT_CYAN, bg=BG).pack(side="left")

        status_frame = tk.Frame(header, bg=BG)
        status_frame.pack(side="right")
        self.status_dot = tk.Canvas(status_frame, width=14, height=14, bg=BG, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self._dot = self.status_dot.create_oval(2, 2, 12, 12, fill=FG_DIM, outline="")
        self.status_label = tk.Label(status_frame, text="FERMO", font=FONT_BOLD,
                                     fg=FG_DIM, bg=BG)
        self.status_label.pack(side="left")

        # CONTROLS
        controls = tk.Frame(self.root, bg=BG, height=50)
        controls.pack(fill="x", padx=20, pady=(0, 10))

        # Pulsante unico combinato per AVVIA / STOP
        self.toggle_btn = tk.Button(controls, text="▶  AVVIA", command=self._toggle_transcription,
                                    bg=ACCENT_CYAN, fg="#04140a", activebackground="#00b8e6",
                                    activeforeground="#04140a", font=FONT_BOLD, relief="flat", 
                                    padx=18, pady=8, cursor="hand2", bd=0)
        self.toggle_btn.pack(side="left")

        self.debug_btn = tk.Button(controls, text="🐞 DEBUG OFF", command=self._toggle_debug,
                                   bg="#2a2a2a", fg=FG_DIM, activebackground="#3d3d3d",
                                   font=FONT_BOLD, relief="flat", padx=12, pady=8,
                                   cursor="hand2", bd=0)
        self.debug_btn.pack(side="left", padx=(10, 0))

        self.config_btn = tk.Button(controls, text="⚙️ CONFIG", command=self._open_config_window,
                                   bg="#2a2a2a", fg=ACCENT_GREEN, activebackground="#3d3d3d",
                                   font=FONT_BOLD, relief="flat", padx=10, pady=8,
                                   cursor="hand2", bd=0)
        self.config_btn.pack(side="left", padx=(10, 0))

        self.reload_btn = tk.Button(controls, text="🔄 RICARICA CFG", command=self._reload_config,
                                   bg="#1a2a2a", fg=ACCENT_CYAN, activebackground="#1a3a3a",
                                   font=FONT_BOLD, relief="flat", padx=10, pady=8,
                                   cursor="hand2", bd=0)
        self.reload_btn.pack(side="left", padx=(10, 0))

        self.mode_label = tk.Label(controls, text="", font=FONT_SMALL, fg=FG_DIM, bg=BG)
        self.mode_label.pack(side="right")

        # MAIN PANEL
        main_panel = tk.Frame(self.root, bg=BG)
        main_panel.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # COLONNA SINISTRA (70%)
        left_col = tk.Frame(main_panel, bg=BG)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # VU Meter
        vu_frame = self._card(left_col, "📊 LIVELLO SEGNALE (RMS)", height=80)
        vu_inner = tk.Frame(vu_frame, bg=CARD_BG)
        vu_inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.vu_canvas = tk.Canvas(vu_inner, height=24, bg="#05070a",
                                   highlightthickness=1, highlightbackground=BORDER)
        self.vu_canvas.pack(fill="x", pady=(0, 4))
        self.vu_value_label = tk.Label(vu_inner, text="RMS: -    Soglia: -",
                                       font=FONT_MONO, fg=FG_DIM, bg=CARD_BG)
        self.vu_value_label.pack(anchor="w")
        self.vu_canvas.bind("<Configure>", lambda e: self._draw_vu())

        # Trascrizione
        transcript_frame = self._card(left_col, "📝 TRASCRIZIONE", expand=True)
        self.transcript = scrolledtext.ScrolledText(
            transcript_frame,
            wrap="word",
            bg="#05070a",
            fg=ACCENT_GREEN,
            insertbackground=FG,
            font=FONT_MONO,
            relief="flat",
            padx=12,
            pady=10,
            state="disabled",
            bd=0
        )
        self.transcript.pack(fill="both", expand=True, padx=8, pady=8)
        self.transcript.tag_configure("dim", foreground=FG_DIM)
        self.transcript.tag_configure("ts", foreground=FG_DIM)

        # COLONNA DESTRA (30%)
        right_col = tk.Frame(main_panel, bg=BG, width=260)
        right_col.pack(side="right", fill="y", padx=(10, 0))

        # Configurazione rapida
        config_frame = self._card(right_col, "⚙️ CONFIGURAZIONE RAPIDA")
        cfg_inner = tk.Frame(config_frame, bg=CARD_BG)
        cfg_inner.pack(fill="both", expand=True, padx=8, pady=8)
        params = [
            ("Modello", "Whisper-large-v3"),
            ("Lingua", "Inglese (EN)"),
            ("VAD Sensibilità", "0.4"),
            ("Worker Groq", "5"),
        ]
        self.quick_config_labels = {}
        for label, value in params:
            row = tk.Frame(cfg_inner, bg=CARD_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label+":", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                     width=14, anchor="w").pack(side="left")
            val_lbl = tk.Label(row, text=value, font=FONT_SMALL, fg=FG, bg=CARD_BG,
                               anchor="w")
            val_lbl.pack(side="left")
            self.quick_config_labels[label] = val_lbl

        # Stato sistema
        status_frame2 = self._card(right_col, "📡 STATO SISTEMA")
        st_inner = tk.Frame(status_frame2, bg=CARD_BG)
        st_inner.pack(fill="both", expand=True, padx=8, pady=8)

        self.status_items = {}
        status_config = [
            ("🎤 Microfono", "DISATTIVO", False),
            ("🌐 Groq API", "DISCONNESSA", False),
            ("🔵 Filtro", "300-3400 Hz (ON)", True),
        ]

        for label, initial_text, active in status_config:
            row = tk.Frame(st_inner, bg=CARD_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label+":", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                     width=14, anchor="w").pack(side="left")
            canvas = tk.Canvas(row, width=12, height=12, bg=CARD_BG, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 6))
            color = ACCENT_GREEN if active else ACCENT_RED
            dot = canvas.create_oval(2, 2, 10, 10, fill=color, outline="")
            lbl = tk.Label(row, text=initial_text, font=FONT_SMALL, fg=FG, bg=CARD_BG, anchor="w")
            lbl.pack(side="left")
            self.status_items[label] = {
                "canvas": canvas,
                "dot": dot,
                "label": lbl,
                "active": active
            }

        # Uptime
        row = tk.Frame(st_inner, bg=CARD_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="⏱️ Uptime:", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                 width=14, anchor="w").pack(side="left")
        self.uptime_label = tk.Label(row, text="00:00:00", font=FONT_SMALL, fg=FG, bg=CARD_BG, anchor="w")
        self.uptime_label.pack(side="left")

        # Metriche strutturate in verticale per riga sotto lo Stato Sistema
        metrics_frame = self._card(right_col, "📈 METRICHE")
        m_inner = tk.Frame(metrics_frame, bg=CARD_BG)
        m_inner.pack(fill="both", expand=True, padx=8, pady=8)
        
        self.metric_labels = {}
        for key, label in [("submitted", "Inviati"), ("completed", "Completati"),
                           ("failed", "Falliti"), ("avg_time", "T. Medio"),
                           ("queue_size", "Coda")]:
            row = tk.Frame(m_inner, bg=CARD_BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label + ":", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                     width=14, anchor="w").pack(side="left")
            val = tk.Label(row, text="0", font=FONT_BOLD, fg=FG, bg=CARD_BG, anchor="w")
            val.pack(side="left")
            self.metric_labels[key] = val

        # BARRA DI ERRORE
        self.error_label = tk.Label(self.root, text="✅ Sistema pronto",
                                    font=FONT_SMALL, fg=ACCENT_GREEN,
                                    bg=BG, anchor="w", justify="left")
        self.error_label.pack(fill="x", padx=20, pady=(0, 12))

        self._uptime_start = time.time()
        self._update_uptime()

    def _sync_quick_config_labels(self):
        """Sincronizza i widget informativi a destra con la configurazione corrente."""
        if not hasattr(self, "quick_config_labels"):
            return
        w_cfg = self.config.get("whisper", {})
        v_cfg = self.config.get("vad", {})
        a_cfg = self.config.get("audio", {})

        self.quick_config_labels["Modello"].config(text=w_cfg.get("model", "whisper-large-v3"))
        lang = w_cfg.get("language", "en").upper()
        self.quick_config_labels["Lingua"].config(text=f"Inglese ({lang})" if lang == "EN" else f"Altro ({lang})")
        self.quick_config_labels["VAD Sensibilità"].config(text=str(v_cfg.get("silence_timeout_s", 1.0)) + "s")
        self.quick_config_labels["Worker Groq"].config(text=str(w_cfg.get("max_workers", 4)))

        flt_active = a_cfg.get("filter_bandpass", True)
        self._set_status_item("🔵 Filtro", "300-3400 Hz (ON)" if flt_active else "DISATTIVATO", flt_active)

    def _set_status_item(self, label_key, text, active):
        if label_key in self.status_items:
            item = self.status_items[label_key]
            item["label"].config(text=text)
            color = ACCENT_GREEN if active else ACCENT_RED
            item["canvas"].itemconfig(item["dot"], fill=color)
            item["active"] = active

    def _draw_vu(self, rms_normalized=0.0, threshold_normalized=0.4):
        """Disegna il VU Meter sul Canvas."""
        w = self.vu_canvas.winfo_width()
        h = self.vu_canvas.winfo_height()
        if w <= 10:
            return

        self.vu_canvas.delete("all")
        self.vu_canvas.create_rectangle(0, 0, w, h, fill="#05070a", outline="")

        bar_w = int(w * rms_normalized)
        thresh_x = int(w * threshold_normalized)

        bar_color = ACCENT_GREEN
        if rms_normalized > threshold_normalized:
            bar_color = ACCENT_AMBER
        if rms_normalized > 0.85:
            bar_color = ACCENT_RED

        if bar_w > 0:
            self.vu_canvas.create_rectangle(0, 0, bar_w, h, fill=bar_color, outline="")

        self.vu_canvas.create_line(thresh_x, 0, thresh_x, h, fill="#ffffff", width=2, dash=(4, 2))

    def _update_uptime(self):
        if self.running:
            elapsed = int(time.time() - self._uptime_start)
            hrs = elapsed // 3600
            mins = (elapsed % 3600) // 60
            secs = elapsed % 60
            self.uptime_label.config(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")
        self.root.after(1000, self._update_uptime)

    def _toggle_transcription(self):
        if not self.running:
            self._on_start()
            self.toggle_btn.config(
                text="■  STOP",
                bg="#3a1418",
                fg=ACCENT_RED,
                activebackground="#54181d",
                activeforeground=ACCENT_RED
            )
        else:
            self._on_stop()
            self.toggle_btn.config(
                text="▶  AVVIA",
                bg=ACCENT_CYAN,
                fg="#04140a",
                activebackground="#00b8e6",
                activeforeground="#04140a"
            )

    def _on_start(self):
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self._uptime_start = time.time()

        self.status_dot.itemconfig(self._dot, fill=ACCENT_GREEN)
        self.status_label.config(text="ASCOLTO", fg=ACCENT_GREEN)
        self._set_status_item("🎤 Microfono", "ATTIVO", True)
        self._set_status_item("🌐 Groq API", "PRONTA", True)
        self.error_label.config(text="🎙️ Pipeline avviata in background...", fg=ACCENT_GREEN)

        self.config_btn.config(state="disabled")
        self.reload_btn.config(state="disabled")

        self.pipeline_thread = threading.Thread(
            target=run_pipeline,
            args=(self.config, self.event_bus, self.stop_event),
            daemon=True
        )
        self.pipeline_thread.start()

    def _on_stop(self):
        if not self.running:
            return
        self.running = False
        self.stop_event.set()

        self.status_dot.itemconfig(self._dot, fill=FG_DIM)
        self.status_label.config(text="FERMO", fg=FG_DIM)
        self._set_status_item("🎤 Microfono", "DISATTIVO", False)
        self._set_status_item("🌐 Groq API", "DISCONNESSA", False)
        self.error_label.config(text="⏹️ Pipeline interrotta.", fg=FG_DIM)

        self.config_btn.config(state="normal")
        self.reload_btn.config(state="normal")
        self._draw_vu(0.0, 0.4)
        self.vu_value_label.config(text="RMS: -    Soglia: -")

        # Richiesta di salvataggio a fine sessione
        if self.transcript_buffer:
            risposta = messagebox.askyesno(
                "Salva Trascrizione", 
                "Vuoi salvare la trascrizione di questa sessione su un file di testo?",
                parent=self.root
            )
            if risposta:
                file_path = filedialog.asksaveasfilename(
                    defaultextension=".txt",
                    filetypes=[("File di testo", "*.txt"), ("Tutti i file", "*.*")],
                    title="Salva la trascrizione come...",
                    parent=self.root
                )
                if file_path:
                    try:
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write("\n".join(self.transcript_buffer))
                        self.error_label.config(text=f"💾 Trascrizione salvata in: {os.path.basename(file_path)}", fg=ACCENT_GREEN)
                    except Exception as e:
                        messagebox.showerror("Errore di Salvataggio", f"Impossibile salvare il file:\n{e}", parent=self.root)
            
            # Reset del buffer per la sessione successiva
            self.transcript_buffer = []

    def _toggle_debug(self):
        self.debug_enabled = not self.debug_enabled
        if self.debug_enabled:
            self.debug_btn.config(text="🐞 DEBUG ON", fg=ACCENT_AMBER, bg="#332510")
            if not self.debug_window or not self.debug_window.is_open:
                self.debug_window = DebugWindow(self.root)
        else:
            self.debug_btn.config(text="🐞 DEBUG OFF", fg=FG_DIM, bg="#2a2a2a")
            if self.debug_window:
                self.debug_window.on_close()
                self.debug_window = None

    def _open_config_window(self):
        if self.config_window and tk.Toplevel.winfo_exists(self.config_window.window):
            self.config_window.window.lift()
            return
        self.config_window = ConfigWindow(self.root, self.config, self._on_config_saved)

    def _on_config_saved(self, new_config):
        self.config = new_config
        from config import CONFIG_PATH
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=4)
            self.error_label.config(text="💾 Nuova configurazione salvata e applicata.", fg=ACCENT_GREEN)
            self._sync_quick_config_labels()
        except Exception as e:
            messagebox.showerror("Errore di Salvataggio", f"Impossibile scrivere il file:\n{e}")

    def _reload_config(self):
        try:
            self.config = load_config()
            self._sync_quick_config_labels()
            self.error_label.config(text="🔄 Configurazione ricaricata dal file JSON.", fg=ACCENT_GREEN)
        except Exception as e:
            messagebox.showerror("Errore di Ricaricamento", f"Impossibile ricaricare:\n{e}")

    def _poll_events(self):
        """Raccoglie i messaggi di log e gli eventi thread-safe dall'EventBus."""
        if self.debug_enabled and self.debug_window and self.debug_window.is_open:
            from logger import _debug_buffer, _buffer_lock
            logs_to_print = []
            with _buffer_lock:
                if _debug_buffer:
                    logs_to_print = list(_debug_buffer)
                    _debug_buffer.clear()
            for record in logs_to_print:
                self.debug_window.append_log(f"[{record.asctime}] {record.levelname}: {record.message}")

        events = self.event_bus.poll_all()
        for kind, data in events:
            if kind == "transcript":
                self._append_transcript(data.get("text", ""))
            elif kind == "metrics":
                for k, val in self.metric_labels.items():
                    if k in data:
                        if k == "avg_time":
                            val.config(text=f"{data[k]:.2f}s")
                        else:
                            val.config(text=str(data[k]))
            elif kind == "vu_meter":
                rms = data.get("rms", 0.0)
                thresh = data.get("threshold", 0.4)
                db = data.get("db", -60.0)
                db_th = data.get("db_threshold", -35.0)
                self._draw_vu(rms, thresh)
                self.vu_value_label.config(text=f"RMS: {db:.1f} dB  (Soglia: {db_th:.1f} dB)")
            elif kind == "status":
                self.error_label.config(text=data.get("message", ""), fg=FG)
            elif kind == "pipeline_error":
                self.error_label.config(text=f"❌ Errore: {data.get('message', '')}", fg=ACCENT_RED)
                self.running = False
                self.toggle_btn.config(
                    text="▶  AVVIA",
                    bg=ACCENT_CYAN,
                    fg="#04140a",
                    activebackground="#00b8e6",
                    activeforeground="#04140a"
                )
                self.status_dot.itemconfig(self._dot, fill=ACCENT_RED)
                self.status_label.config(text="ERRORE", fg=ACCENT_RED)
                self._set_status_item("🎤 Microfono", "DISATTIVO", False)
                self._set_status_item("🌐 Groq API", "DISCONNESSA", False)

        self.root.after(100, self._poll_events)

    def _append_transcript(self, text):
        self.transcript.config(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.transcript.insert("end", f"[{ts}] ", "ts")
        if text:
            # NOTA: Corretto in '\n' per permettere a Tkinter di stampare a schermo
            self.transcript.insert("end", f"{text}\n")
        else:
            self.transcript.insert("end", "(nessun testo riconosciuto)\n", "dim")
        self.transcript.see("end")
        self.transcript.config(state="disabled")
        if text:
            self.transcript_buffer.append(f"[{ts}] {text}")

    def on_close(self):
        if self.running:
            self.stop_event.set()
        if self.debug_window:
            self.debug_window.on_close()
        if self.config_window:
            self.config_window.on_close()
        self.root.destroy()


# ============================================================================
# ENTRY POINT
# ============================================================================
def main():
    root = tk.Tk()
    app = TranscriberGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()