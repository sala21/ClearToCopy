import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

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
        self.window.title("🐞 Debug Log - AeroVoice Transcriber")
        self.window.geometry("700x450")
        self.window.minsize(500, 300)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.text_area = scrolledtext.ScrolledText(
            self.window,
            wrap="word",
            bg="#05070a",
            fg=FG,
            insertbackground=FG,
            font=FONT_MONO,
            relief="flat",
            padx=10,
            pady=8,
            state="disabled",
            bd=0
        )
        self.text_area.pack(fill="both", expand=True, padx=12, pady=12)

        self.log_file = "transcriber.log"
        self.last_pos = 0
        self.running = True
        self._poll_log()

    def _poll_log(self):
        if not self.running:
            return
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, "r", encoding="utf-8") as f:
                    f.seek(self.last_pos)
                    new_content = f.read()
                    self.last_pos = f.tell()
                    if new_content:
                        self.text_area.config(state="normal")
                        self.text_area.insert("end", new_content)
                        self.text_area.see("end")
                        self.text_area.config(state="disabled")
            else:
                if self.last_pos == 0:
                    self.text_area.config(state="normal")
                    self.text_area.insert("end", "[DEBUG] In attesa del file di log...\n")
                    self.text_area.see("end")
                    self.text_area.config(state="disabled")
        except Exception:
            pass
        self.window.after(500, self._poll_log)

    def on_close(self):
        self.running = False
        self.window.destroy()


# ============================================================================
# APPLICAZIONE PRINCIPALE
# ============================================================================
class TranscriberGUI:
    def __init__(self, root):
        self.root = root
        self.bus = EventBus()
        self.stop_event = threading.Event()
        self.worker = None
        self.running = False

        self._last_rms = 0.0
        self._last_threshold = 50.0

        self.debug_enabled = False
        self.debug_window = None

        self._build_ui()
        self.root.after(100, self._poll_events)

        self.transcript_buffer = []  # Buffer per accumulare le righe di trascrizione
        self.transcript_autosave_file = "transcript_autosave.txt"
        self.autosave_interval = 10  # secondi (0 = disabilitato)

    # ------------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------------
    def _build_ui(self):
        self.root.title("ATC Radio Transcriber")
        self.root.geometry("960x660")
        self.root.configure(bg=BG)
        self.root.minsize(820, 540)

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

        self.start_btn = tk.Button(controls, text="▶  AVVIA", command=self._on_start,
                                   bg=ACCENT_CYAN, fg="#04140a", activebackground="#00b8e6",
                                   font=FONT_BOLD, relief="flat", padx=18, pady=8,
                                   cursor="hand2", bd=0)
        self.start_btn.pack(side="left")

        self.stop_btn = tk.Button(controls, text="■  STOP", command=self._on_stop,
                                  bg="#3a1418", fg=ACCENT_RED, activebackground="#54181d",
                                  font=FONT_BOLD, relief="flat", padx=18, pady=8,
                                  cursor="hand2", bd=0, state="disabled")
        self.stop_btn.pack(side="left", padx=(10, 0))

        self.debug_btn = tk.Button(controls, text="🐞 DEBUG OFF", command=self._toggle_debug,
                                   bg="#2a2a2a", fg=FG_DIM, activebackground="#3d3d3d",
                                   font=FONT_BOLD, relief="flat", padx=12, pady=8,
                                   cursor="hand2", bd=0)
        self.debug_btn.pack(side="left", padx=(10, 0))

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

        # Metriche
        metrics_frame = self._card(left_col, "📈 METRICHE")
        m_row = tk.Frame(metrics_frame, bg=CARD_BG)
        m_row.pack(fill="x", padx=8, pady=8)
        self.metric_labels = {}
        for key, label in [("submitted", "INVIATI"), ("completed", "COMPLETATI"),
                           ("failed", "FALLITI"), ("avg_time", "T.MEDIO"),
                           ("queue_size", "CODA")]:
            col = tk.Frame(m_row, bg=CARD_BG)
            col.pack(side="left", expand=True, fill="x")
            tk.Label(col, text=label, font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG).pack(anchor="w")
            val = tk.Label(col, text="0", font=FONT_BOLD, fg=FG, bg=CARD_BG)
            val.pack(anchor="w")
            self.metric_labels[key] = val

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
        for label, value in params:
            row = tk.Frame(cfg_inner, bg=CARD_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label+":", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                     width=14, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=FONT_SMALL, fg=FG, bg=CARD_BG,
                     anchor="w").pack(side="left")

        # Stato sistema (con pallini verdi/rossi)
        status_frame2 = self._card(right_col, "📡 STATO SISTEMA")
        st_inner = tk.Frame(status_frame2, bg=CARD_BG)
        st_inner.pack(fill="both", expand=True, padx=8, pady=8)

        self.status_items = {}  # dizionario per memorizzare canvas e label

        # Lista degli stati: (etichetta, testo iniziale, active iniziale)
        status_config = [
            ("🎤 Microfono", "DISATTIVO", False),
            ("🌐 Groq API", "DISCONNESSA", False),
            ("🔵 Filtro", "300-3400 Hz (ON)", True),  # sempre attivo
        ]

        for label, initial_text, active in status_config:
            row = tk.Frame(st_inner, bg=CARD_BG)
            row.pack(fill="x", pady=2)

            # Etichetta
            tk.Label(row, text=label+":", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                     width=14, anchor="w").pack(side="left")

            # Canvas per il pallino (10x10)
            canvas = tk.Canvas(row, width=12, height=12, bg=CARD_BG, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 6))
            # Disegna il cerchio
            color = ACCENT_GREEN if active else ACCENT_RED
            dot = canvas.create_oval(2, 2, 10, 10, fill=color, outline="")

            # Label per il testo
            lbl = tk.Label(row, text=initial_text, font=FONT_SMALL, fg=FG, bg=CARD_BG, anchor="w")
            lbl.pack(side="left")

            # Salva i riferimenti
            self.status_items[label] = {
                "canvas": canvas,
                "dot": dot,
                "label": lbl,
                "active": active
            }

        # Uptime (senza pallino)
        row = tk.Frame(st_inner, bg=CARD_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="⏱️ Uptime:", font=FONT_SMALL, fg=FG_DIM, bg=CARD_BG,
                 width=14, anchor="w").pack(side="left")
        self.uptime_label = tk.Label(row, text="00:00:00", font=FONT_SMALL, fg=FG, bg=CARD_BG, anchor="w")
        self.uptime_label.pack(side="left")

        # BARRA DI ERRORE
        self.error_label = tk.Label(self.root, text="✅ Sistema pronto",
                                    font=FONT_SMALL, fg=ACCENT_GREEN,
                                    bg=BG, anchor="w", justify="left")
        self.error_label.pack(fill="x", padx=20, pady=(0, 12))

        self._uptime_start = time.time()
        self._update_uptime()

    def _card(self, parent, title, expand=False, height=None):
        frame = tk.Frame(parent, bg=PANEL_BG, highlightthickness=1,
                         highlightbackground=BORDER, relief="flat")
        if expand:
            frame.pack(fill="both", expand=True, pady=4)
        else:
            frame.pack(fill="x", pady=4)
        tk.Label(frame, text=title, font=FONT_SMALL, fg=FG_DIM,
                 bg=PANEL_BG).pack(anchor="w", padx=10, pady=(6, 0))
        return frame

    # ------------------------------------------------------------------------
    # VU METER
    # ------------------------------------------------------------------------
    def _draw_vu(self):
        c = self.vu_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            return

        max_scale = max(self._last_threshold * 6, self._last_rms * 1.2, 200)
        frac = min(1.0, self._last_rms / max_scale)
        fill_w = int(w * frac)

        if self._last_rms < self._last_threshold:
            color = FG_DIM
        elif frac < 0.6:
            color = ACCENT_GREEN
        elif frac < 0.85:
            color = ACCENT_AMBER
        else:
            color = ACCENT_RED

        if fill_w > 0:
            c.create_rectangle(0, 0, fill_w, h, fill=color, outline="")

        thr_frac = min(1.0, self._last_threshold / max_scale)
        thr_x = int(w * thr_frac)
        c.create_line(thr_x, 0, thr_x, h, fill=ACCENT_AMBER, width=2)

    # ------------------------------------------------------------------------
    # GESTIONE STATI (con pallini)
    # ------------------------------------------------------------------------
    def _update_status_item(self, label, active, custom_text=None):
        """
        Aggiorna lo stato di un elemento (Microfono, API, Filtro).
        active: True -> pallino verde, False -> pallino rosso.
        custom_text: se fornito, sovrascrive il testo della label.
        """
        if label not in self.status_items:
            return
        item = self.status_items[label]
        color = ACCENT_GREEN if active else ACCENT_RED
        item["canvas"].itemconfig(item["dot"], fill=color)
        item["active"] = active

        # Aggiorna il testo
        if custom_text is not None:
            text = custom_text
        else:
            text = "ATTIVO" if active else "DISATTIVO" if label == "🎤 Microfono" else "DISCONNESSA"
        item["label"].config(text=text)

    def _update_uptime(self):
        if self.running:
            elapsed = int(time.time() - self._uptime_start)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self.uptime_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._update_uptime)

    # ------------------------------------------------------------------------
    # AZIONI
    # ------------------------------------------------------------------------
    def _on_start(self):
        if self.running:
            return
        self.error_label.config(text="⏳ Avvio in corso...", fg=ACCENT_AMBER)
        try:
            config = load_config()
        except SystemExit:
            self.error_label.config(
                text="❌ Errore: config.json non trovato o GROQ_API_KEY non impostata.",
                fg=ACCENT_RED
            )
            return

        groq_cfg = config.get("api", {}).get("groq", {})
        mode = "RADIO (bypass VAD)" if config.get("radio", {}).get("bypass_vad") else "VAD classico"
        self.mode_label.config(
            text=f"Modello: {groq_cfg.get('model', '?')}   •   Modalità: {mode}"
        )

        # Aggiorna stati: Microfono e API attivi (verde)
        self._update_status_item("🎤 Microfono", True, "ATTIVO")
        self._update_status_item("🌐 Groq API", True, "CONNESSA")

        # Resetta il contatore dell'uptime
        self._uptime_start = time.time()
        self.uptime_label.config(text="00:00:00")

        # Resetta il file di log all'avvio (se debug attivo)
        if self.debug_enabled:
            from logger import clear_log_file
            clear_log_file()

        self.stop_event = threading.Event()
        self.worker = threading.Thread(
            target=self._pipeline_thread, args=(config,), daemon=True
        )
        self.running = True

            # === AVVIA L'AUTOSAVE ===
        if self.autosave_interval > 0:
            self.autosave_thread = threading.Thread(
                target=self._autosave_loop, 
                daemon=True
            )
            self.autosave_thread.start()

        self.start_btn.config(state="disabled")

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("IN ASCOLTO", ACCENT_GREEN)
        self.worker.start()
        self.error_label.config(text="🎤 Ascolto attivo...", fg=ACCENT_GREEN)

    def _pipeline_thread(self, config):
        try:
            run_pipeline(config, event_bus=self.bus, stop_event=self.stop_event)
        except Exception as e:
            self.bus.emit("error", message=str(e))
        finally:
            self.bus.emit("stopped")

    def _on_stop(self):
        if not self.running:
            return
        
        self.running = False  # <--- Questo ferma il loop
        if self.autosave_thread and self.autosave_thread.is_alive():
            self.autosave_thread.join(timeout=1.0)

        # --- Gestione del buffer di trascrizione ---
        if self.transcript_buffer:
            if messagebox.askyesno(
                "Salva trascrizione",
                f"Ci sono {len(self.transcript_buffer)} righe di trascrizione.\n"
                "Vuoi salvarle in un file .txt?"
            ):
                filename = self._save_transcript_from_buffer()
                if filename:
                    self.error_label.config(
                        text=f"✅ Trascrizione salvata in: {filename}",
                        fg=ACCENT_GREEN
                    )
                else:
                    self.error_label.config(
                        text="❌ Errore durante il salvataggio della trascrizione.",
                        fg=ACCENT_RED
                    )
            else:
                # L'utente ha scelto di non salvare: svuota il buffer
                self._clear_transcript_buffer()
                self.error_label.config(
                    text="ℹ️ Trascrizione scartata.",
                    fg=ACCENT_AMBER
                )
        else:
            self.error_label.config(
                text="ℹ️ Nessuna trascrizione da salvare.",
                fg=FG_DIM
            )

        # --- Gestione del debug (come prima) ---
        if self.debug_enabled:
            # ... (codice esistente per il debug) ...
            pass

        self.stop_event.set()
        self.stop_btn.config(state="disabled")
        self._set_status("FERMO", FG_DIM)
        self.error_label.config(text="⏹️ Trascrizione terminata.", fg=FG_DIM)

    def _save_transcript(self):
        transcript_text = self.transcript.get("1.0", "end-1c").strip()
        if not transcript_text:
            self.error_label.config(text="⚠️ Nessuna trascrizione da salvare.", fg=ACCENT_AMBER)
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"transcript_{timestamp}.txt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(transcript_text)
            self.error_label.config(
                text=f"✅ Trascrizione salvata in: {filename}",
                fg=ACCENT_GREEN
            )
            self.root.after(5000, lambda: self.error_label.config(fg=ACCENT_RED))
        except Exception as e:
            self.error_label.config(text=f"❌ Errore durante il salvataggio: {e}", fg=ACCENT_RED)

    def _set_status(self, text, color):
        self.status_label.config(text=text, fg=color)
        self.status_dot.itemconfig(self._dot, fill=color)

    # ------------------------------------------------------------------------
    # DEBUG TOGGLE
    # ------------------------------------------------------------------------
    def _toggle_debug(self):
        self.debug_enabled = not self.debug_enabled
        if self.debug_enabled:
            self.debug_btn.config(text="🐞 DEBUG ON", bg=ACCENT_AMBER, fg="#14100a")
            import logging
            logging.getLogger("AudioTranscriber").setLevel(logging.DEBUG)
            self.debug_window = DebugWindow(self.root)
            self.error_label.config(text="🐞 Modalità DEBUG attiva. I log verranno gestiti allo stop.", fg=ACCENT_AMBER)
        else:
            self.debug_btn.config(text="🐞 DEBUG OFF", bg="#2a2a2a", fg=FG_DIM)
            import logging
            logging.getLogger("AudioTranscriber").setLevel(logging.INFO)
            if self.debug_window:
                self.debug_window.on_close()
                self.debug_window = None

            # Se disattivi il debug, chiedi se salvare il file di log
            import os
            from logger import archive_log_file, clear_log_file
            log_file = "transcriber.log"
            has_content = False
            if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
                has_content = True

            if has_content:
                if messagebox.askyesno(
                    "Salva log di debug",
                    "Ci sono messaggi di debug in sospeso.\n"
                    "Vuoi salvarli prima di disattivare il debug?"
                ):
                    new_name = archive_log_file()
                    if new_name:
                        self.error_label.config(
                            text=f"✅ Log di debug salvati in: {new_name}",
                            fg=ACCENT_GREEN
                        )
                    else:
                        self.error_label.config(
                            text="❌ Errore durante il salvataggio.",
                            fg=ACCENT_RED
                        )
                else:
                    clear_log_file()
                    self.error_label.config(
                        text="ℹ️ Log di debug eliminati.",
                        fg=ACCENT_AMBER
                    )
            self.error_label.config(text="🐞 Debug disattivato.", fg=FG_DIM)

    # ------------------------------------------------------------------------
    # POLLING EVENTI
    # ------------------------------------------------------------------------
    def _poll_events(self):
        for kind, data in self.bus.poll_all():
            if kind == "rms":
                self._last_rms = data.get("value", 0.0)
                self._last_threshold = data.get("threshold", self._last_threshold)
                accepted = data.get("accepted", True)
                accepted_label = "● ACCETTATO" if accepted else "○ SILENZIO (scartato)"
                self.vu_value_label.config(
                    text=f"RMS: {self._last_rms:.1f}    Soglia: {self._last_threshold:.1f}    {accepted_label}",
                    fg=ACCENT_GREEN if accepted else FG_DIM
                )
                self._draw_vu()
            elif kind == "transcript":
                self._append_transcript(data.get("text"))
            elif kind == "metrics":
                for key in ("submitted", "completed", "failed", "queue_size"):
                    if key in data:
                        self.metric_labels[key].config(text=str(data[key]))
                if "avg_time" in data:
                    self.metric_labels["avg_time"].config(text=f"{data['avg_time']:.2f}s")
            elif kind == "error":
                self.error_label.config(text=f"❌ Errore: {data.get('message', '')}", fg=ACCENT_RED)
                self._update_status_item("🌐 Groq API", False, "ERRORE")
            elif kind == "stopped":
                self.running = False
                self.start_btn.config(state="normal")
                self.stop_btn.config(state="disabled")
                self._set_status("FERMO", FG_DIM)
                self._update_status_item("🎤 Microfono", False, "DISATTIVO")
                self._update_status_item("🌐 Groq API", False, "DISCONNESSA")
                self.error_label.config(text="⏹️ Trascrizione terminata.", fg=FG_DIM)

        self.root.after(100, self._poll_events)

    def _append_transcript(self, text):
        self.transcript.config(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.transcript.insert("end", f"[{ts}] ", "ts")
        if text:
            self.transcript.insert("end", f"{text}\n")
        else:
            self.transcript.insert("end", "(nessun testo riconosciuto)\n", "dim")
        self.transcript.see("end")
        self.transcript.config(state="disabled")
        
        # AGGIUNGE AL BUFFER
        if text:
            self.transcript_buffer.append(f"[{ts}] {text}")

    def on_close(self):
        if self.running:
            self.stop_event.set()
        if self.debug_window:
            self.debug_window.on_close()
        self.root.destroy()

    def _save_transcript_from_buffer(self, filename=None):
        """Salva il buffer di trascrizione in un file .txt."""
        if not self.transcript_buffer:
            return None
        
        if filename is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"transcript_{timestamp}.txt"
        
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(self.transcript_buffer))
            return filename
        except Exception as e:
            return None

    def _clear_transcript_buffer(self):
        """Svuota il buffer di trascrizione e resetta l'area di testo."""
        self.transcript_buffer = []
        self.transcript.config(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.config(state="disabled")

    def _autosave_loop(self):
        """Thread che salva periodicamente la trascrizione in un file temporaneo."""
        while self.running:
            time.sleep(self.autosave_interval)
            if self.transcript_buffer:
                try:
                    with open("transcript_autosave.txt", "w", encoding="utf-8") as f:
                        f.write("\n".join(self.transcript_buffer))
                    # (opzionale) messaggio di debug
                    # print(f"[Autosave] Salvate {len(self.transcript_buffer)} righe")
                except Exception as e:
                    print(f"[Autosave] Errore: {e}")


# ============================================================================
# ENTRY POINT
# ============================================================================
def main():
    root = tk.Tk()
    app = TranscriberGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()