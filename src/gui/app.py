# gui/app.py
# Applicazione principale (TranscriberGUI) – tutta la logica di stato, pipeline, eventi

import os
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, messagebox
import json
import logging

from config import load_config
from paths import BASE_DIR
from events import EventBus
from logger import archive_log_file, clear_log_file, set_console_debug

from .theme import *
from .debug_window import DebugWindow
from .config_window import ConfigWindow


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
        self.config_window = None

        # Riferimenti ai componenti della pipeline (popolati da run_pipeline)
        self._pipeline_components = {}

        self.transcript_buffer = []
        self.autosave_interval = 10
        self.autosave_thread = None

        self._build_ui()
        self.root.after(100, self._poll_events)

    # ------------------------------------------------------------------------
    # UI – costruzione
    # ------------------------------------------------------------------------
    def _build_ui(self):
        self.root.title("ATC Radio Transcriber")
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

        # Metriche
        metrics_frame = self._card(right_col, "📈 METRICHE")
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
    # Gestione stati UI
    # ------------------------------------------------------------------------
    def _update_status_item(self, label, active, custom_text=None):
        if label not in self.status_items:
            return
        item = self.status_items[label]
        color = ACCENT_GREEN if active else ACCENT_RED
        item["canvas"].itemconfig(item["dot"], fill=color)
        item["active"] = active

        if custom_text is not None:
            text = custom_text
        elif label == "🎤 Microfono":
            text = "ATTIVO" if active else "DISATTIVO"
        else:
            text = "CONNESSA" if active else "DISCONNESSA"
        item["label"].config(text=text)

    def _set_status(self, text, color):
        self.status_label.config(text=text, fg=color)
        self.status_dot.itemconfig(self._dot, fill=color)

    def _update_uptime(self):
        if self.running:
            elapsed = int(time.time() - self._uptime_start)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self.uptime_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._update_uptime)

    # ------------------------------------------------------------------------
    # Finestra di configurazione
    # ------------------------------------------------------------------------
    def _open_config_window(self):
        if self.config_window is None or not self.config_window.window.winfo_exists():
            self.config_window = ConfigWindow(self.root, self)
        else:
            self.config_window.window.lift()

    # ------------------------------------------------------------------------
    # Reload config a caldo
    # ------------------------------------------------------------------------
    def _reload_config(self):
        """Ricarica config.json e applica le modifiche ai componenti attivi (VAD e filtro) senza riavviare."""
        if not self.running:
            self.error_label.config(
                text="⚠️ Pipeline non attiva: avvia prima la trascrizione.",
                fg=ACCENT_AMBER
            )
            return

        vad = self._pipeline_components.get("vad")
        transcriber = self._pipeline_components.get("transcriber")

        if vad is None or transcriber is None:
            self.error_label.config(
                text="⏳ Pipeline non ancora pronta, riprova tra un istante.",
                fg=ACCENT_AMBER
            )
            self.root.after(300, self._reload_config)
            return

        config_path = os.path.join(BASE_DIR, "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            self.error_label.config(text=f"❌ Errore nel caricamento di config.json: {e}", fg=ACCENT_RED)
            return

        # Aggiorna il VAD
        vad_cfg = config.get("vad", {})
        try:
            vad.aggressiveness = vad_cfg.get("aggressiveness", 1)
            vad.silence_timeout_s = vad_cfg.get("silence_timeout_s", 1.0)
            vad.max_utterance_s = vad_cfg.get("max_utterance_s", 15.0)
            vad.min_segment_duration_s = vad_cfg.get("min_segment_duration_s", 0.6)
            vad.activation_ratio = vad_cfg.get("activation_ratio", 0.4)
            vad.vad.set_mode(vad.aggressiveness)
            vad._update_buffers()
            logging.getLogger("AudioTranscriber").info(
                "Parametri VAD aggiornati: aggressiveness=%d, activation_ratio=%.2f",
                vad.aggressiveness, vad.activation_ratio
            )
        except Exception as e:
            self.error_label.config(text=f"⚠️ Errore nell'aggiornamento del VAD: {e}", fg=ACCENT_AMBER)

        # Aggiorna il Transcriber (filtro)
        try:
            filter_cfg = config.get("filter", {})
            transcriber.apply_filter = filter_cfg.get("enabled", False)
            transcriber.band_min = filter_cfg.get("band_min", 300)
            transcriber.band_max = filter_cfg.get("band_max", 3400)
            if transcriber.apply_filter and hasattr(transcriber, 'SCIPY_AVAILABLE') and transcriber.SCIPY_AVAILABLE:
                from scipy import signal
                transcriber._filter_b = signal.firwin(65, [transcriber.band_min, transcriber.band_max],
                                                      fs=transcriber.rate, pass_zero=False)
                transcriber._filter_a = [1.0]
                logging.getLogger("AudioTranscriber").info(
                    "Filtro aggiornato: enabled=%s, band=%d-%d Hz",
                    transcriber.apply_filter, transcriber.band_min, transcriber.band_max
                )
            else:
                logging.getLogger("AudioTranscriber").info("Filtro disabilitato o scipy non disponibile.")
        except Exception as e:
            self.error_label.config(text=f"⚠️ Errore nell'aggiornamento del filtro: {e}", fg=ACCENT_AMBER)

        self._update_gui_from_config(config)

        filter_active = config.get("filter", {}).get("enabled", False)
        filter_text = "300-3400 Hz (ON)" if filter_active else "DISABILITATO"
        self._update_status_item("🔵 Filtro", filter_active, filter_text)

        self.error_label.config(text="✅ Configurazione ricaricata e applicata (VAD e filtro aggiornati).", fg=ACCENT_GREEN)
        logging.getLogger("AudioTranscriber").info("Configurazione ricaricata e applicata.")

    def _update_gui_from_config(self, config):
        groq_cfg = config.get("api", {}).get("groq", {})
        mode = "RADIO (bypass VAD)" if config.get("radio", {}).get("bypass_vad") else "VAD classico"
        self.mode_label.config(
            text=f"Modello: {groq_cfg.get('model', '?')}   •   Modalità: {mode}"
        )
        self.quick_config_labels["Modello"].config(text=groq_cfg.get("model", "Whisper-large-v3"))
        self.quick_config_labels["VAD Sensibilità"].config(text=str(config.get("vad", {}).get("activation_ratio", 0.4)))
        self.quick_config_labels["Worker Groq"].config(text=str(groq_cfg.get("max_concurrent_requests", 5)))

    # ------------------------------------------------------------------------
    # Azioni Start / Stop
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

        self._update_status_item("🎤 Microfono", True, "ATTIVO")
        self._update_status_item("🌐 Groq API", True, "CONNESSA")
        filter_active = config.get("filter", {}).get("enabled", False)
        filter_text = "300-3400 Hz (ON)" if filter_active else "DISABILITATO"
        self._update_status_item("🔵 Filtro", filter_active, filter_text)

        self._uptime_start = time.time()
        self.uptime_label.config(text="00:00:00")

        if self.debug_enabled:
            clear_log_file()

        self._pipeline_components = {}

        self.stop_event = threading.Event()
        self.worker = threading.Thread(
            target=self._pipeline_thread, args=(config,), daemon=True
        )
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("IN ASCOLTO", ACCENT_GREEN)
        self.worker.start()
        self.error_label.config(text="🎤 Ascolto attivo...", fg=ACCENT_GREEN)

    def _on_stop(self):
        if not self.running:
            return

        # Gestione trascrizione
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

        # Gestione debug log
        if self.debug_enabled:
            self._prompt_save_debug_log()

        self.stop_event.set()
        self.stop_btn.config(state="disabled")
        self._set_status("FERMO", FG_DIM)
        self.error_label.config(text="⏹️ Trascrizione terminata.", fg=FG_DIM)

    def _save_transcript_from_buffer(self, filename=None):
        if not self.transcript_buffer:
            return None
        if filename is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"transcript_{timestamp}.txt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(self.transcript_buffer))
            return filename
        except Exception:
            return None

    def _clear_transcript_buffer(self):
        self.transcript_buffer = []
        self.transcript.config(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.config(state="disabled")

    # ------------------------------------------------------------------------
    # Pipeline thread
    # ------------------------------------------------------------------------
    def _pipeline_thread(self, config):
        try:
            from main import run_pipeline
            run_pipeline(
                config,
                event_bus=self.bus,
                stop_event=self.stop_event,
                components_ref=self._pipeline_components
            )
        except Exception as e:
            self.bus.emit("error", message=str(e))
        finally:
            self.bus.emit("stopped")

    # ------------------------------------------------------------------------
    # Debug toggle
    # ------------------------------------------------------------------------
    def _toggle_debug(self):
        self.debug_enabled = not self.debug_enabled
        if self.debug_enabled:
            self.debug_btn.config(text="🐞 DEBUG ON", bg=ACCENT_AMBER, fg="#14100a")
            set_console_debug(True)
            self.debug_window = DebugWindow(self.root)
            self.error_label.config(
                text="🐞 Modalità DEBUG attiva. I log verranno gestiti allo stop.",
                fg=ACCENT_AMBER
            )
        else:
            self.debug_btn.config(text="🐞 DEBUG OFF", bg="#2a2a2a", fg=FG_DIM)
            set_console_debug(False)
            if self.debug_window:
                self.debug_window.on_close()
                self.debug_window = None
            self._prompt_save_debug_log()

    def _prompt_save_debug_log(self):
        """Chiede all'utente se salvare o cancellare il file di log di debug."""
        log_file = "transcriber.log"
        has_content = os.path.exists(log_file) and os.path.getsize(log_file) > 0
        if not has_content:
            self.error_label.config(
                text="ℹ️ Nessun messaggio di debug da salvare.",
                fg=FG_DIM
            )
            return

        if messagebox.askyesno(
            "Salva log di debug",
            "Il file transcriber.log contiene messaggi di debug.\n"
            "Vuoi salvarlo (con timestamp) o eliminarlo?"
        ):
            new_name = archive_log_file()
            if new_name:
                self.error_label.config(
                    text=f"✅ Log di debug salvati in: {new_name}",
                    fg=ACCENT_GREEN
                )
            else:
                self.error_label.config(
                    text="❌ Errore durante il salvataggio dei log.",
                    fg=ACCENT_RED
                )
        else:
            if clear_log_file():
                self.error_label.config(
                    text="ℹ️ Log di debug eliminati.",
                    fg=ACCENT_AMBER
                )
            else:
                self.error_label.config(
                    text="⚠️ Impossibile eliminare il file di log.",
                    fg=ACCENT_RED
                )

    # ------------------------------------------------------------------------
    # Polling eventi (bus → GUI)
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
        if text:
            self.transcript_buffer.append(f"[{ts}] {text}")

    # ------------------------------------------------------------------------
    # Chiusura
    # ------------------------------------------------------------------------
    def on_close(self):
        if self.running:
            self.stop_event.set()
        if self.debug_window:
            self.debug_window.on_close()
        if self.config_window:
            self.config_window.on_close()
        self.root.destroy()