import os
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox  # <--- Aggiunto messagebox

from config import load_config
from main import run_pipeline
from events import EventBus


BG = "#0b0f14"
PANEL_BG = "#11161d"
BORDER = "#232c38"
FG = "#d7e2ea"
FG_DIM = "#5b6b7a"
ACCENT_AMBER = "#ffb000"
ACCENT_GREEN = "#37d67a"
ACCENT_RED = "#ff4d4f"
MONO = ("Consolas", 10)
MONO_SMALL = ("Consolas", 8)
MONO_BOLD = ("Consolas", 10, "bold")
TITLE_FONT = ("Consolas", 15, "bold")


# ============================================================================
# FINESTRA DI DEBUG (log in tempo reale)
# ============================================================================
class DebugWindow:
    """Finestra secondaria che mostra i log in tempo reale (tail -f)."""

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
            font=MONO,
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
        """Legge le nuove righe dal file di log ogni 500ms."""
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
            pass  # Evita blocchi se il file è temporaneamente in uso

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

        # DEBUG
        self.debug_enabled = False
        self.debug_window = None

        self._build_ui()
        self.root.after(100, self._poll_events)

    # ------------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------------
    def _build_ui(self):
        self.root.title("ATC Radio Transcriber")
        self.root.geometry("760x620")
        self.root.configure(bg=BG)
        self.root.minsize(640, 480)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ---- Header ----
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(header, text="ATC RADIO TRANSCRIBER", font=TITLE_FONT,
                 fg=ACCENT_AMBER, bg=BG).pack(side="left")

        status_frame = tk.Frame(header, bg=BG)
        status_frame.pack(side="right")
        self.status_dot = tk.Canvas(status_frame, width=12, height=12, bg=BG,
                                     highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 6))
        self._dot = self.status_dot.create_oval(1, 1, 11, 11, fill=FG_DIM, outline="")
        self.status_label = tk.Label(status_frame, text="FERMO", font=MONO_BOLD,
                                      fg=FG_DIM, bg=BG)
        self.status_label.pack(side="left")

        # ---- Controls ----
        controls = tk.Frame(self.root, bg=BG)
        controls.pack(fill="x", padx=16, pady=(0, 10))

        self.start_btn = tk.Button(controls, text="\u25b6  AVVIA", command=self._on_start,
                                    bg=ACCENT_GREEN, fg="#04140a", activebackground="#2fbf6b",
                                    font=MONO_BOLD, relief="flat", padx=14, pady=6,
                                    cursor="hand2", bd=0)
        self.start_btn.pack(side="left")

        self.stop_btn = tk.Button(controls, text="\u25a0  STOP", command=self._on_stop,
                                   bg="#3a1418", fg=ACCENT_RED, activebackground="#54181d",
                                   font=MONO_BOLD, relief="flat", padx=14, pady=6,
                                   cursor="hand2", bd=0, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        # Pulsante DEBUG
        self.debug_btn = tk.Button(
            controls,
            text="🐞 DEBUG OFF",
            bg="#2a2a2a",
            fg=FG_DIM,
            activebackground="#3d3d3d",
            font=MONO_BOLD,
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
            bd=0,
            command=self._toggle_debug
        )
        self.debug_btn.pack(side="left", padx=(8, 0))

        self.mode_label = tk.Label(controls, text="", font=MONO_SMALL, fg=FG_DIM, bg=BG)
        self.mode_label.pack(side="right")

        # ---- VU meter ----
        vu_panel = self._panel("LIVELLO SEGNALE (RMS)")
        self.vu_canvas = tk.Canvas(vu_panel, height=26, bg="#05070a",
                                    highlightthickness=1, highlightbackground=BORDER)
        self.vu_canvas.pack(fill="x", padx=12, pady=(2, 8))
        self.vu_value_label = tk.Label(vu_panel, text="RMS: -    Soglia: -",
                                        font=MONO, fg=FG_DIM, bg=PANEL_BG)
        self.vu_value_label.pack(anchor="w", padx=12, pady=(0, 8))
        self.vu_canvas.bind("<Configure>", lambda e: self._draw_vu())

        # ---- Metrics strip ----
        metrics_panel = self._panel("METRICHE")
        m_row = tk.Frame(metrics_panel, bg=PANEL_BG)
        m_row.pack(fill="x", padx=12, pady=(2, 12))
        self.metric_labels = {}
        for key, label in [("submitted", "INVIATI"), ("completed", "COMPLETATI"),
                            ("failed", "FALLITI"), ("avg_time", "T.MEDIO"),
                            ("queue_size", "CODA")]:
            col = tk.Frame(m_row, bg=PANEL_BG)
            col.pack(side="left", expand=True, fill="x")
            tk.Label(col, text=label, font=MONO_SMALL, fg=FG_DIM, bg=PANEL_BG).pack(anchor="w")
            val = tk.Label(col, text="0", font=MONO_BOLD, fg=FG, bg=PANEL_BG)
            val.pack(anchor="w")
            self.metric_labels[key] = val

        # ---- Transcript ----
        transcript_panel = self._panel("TRASCRIZIONE", expand=True)
        self.transcript = scrolledtext.ScrolledText(
            transcript_panel, wrap="word", bg="#05070a", fg=ACCENT_GREEN,
            insertbackground=FG, font=MONO, relief="flat", padx=10, pady=8,
            state="disabled", bd=0
        )
        self.transcript.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        self.transcript.tag_configure("dim", foreground=FG_DIM)
        self.transcript.tag_configure("ts", foreground=FG_DIM)

        self.error_label = tk.Label(self.root, text="", font=MONO_SMALL, fg=ACCENT_RED,
                                     bg=BG, anchor="w", justify="left", wraplength=720)
        self.error_label.pack(fill="x", padx=16, pady=(0, 12))

    def _panel(self, title, expand=False):
        wrap = tk.Frame(self.root, bg=PANEL_BG, highlightthickness=1,
                         highlightbackground=BORDER)
        wrap.pack(fill="both" if expand else "x", padx=16, pady=6, expand=expand)
        tk.Label(wrap, text=title, font=MONO_SMALL, fg=FG_DIM,
                 bg=PANEL_BG).pack(anchor="w", padx=12, pady=(8, 2))
        return wrap

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
    # AZIONI
    # ------------------------------------------------------------------------
    def _on_start(self):
        if self.running:
            return
        self.error_label.config(text="")
        try:
            config = load_config()
        except SystemExit:
            self.error_label.config(
                text="Errore: config.json non trovato oppure GROQ_API_KEY non impostata."
            )
            return

        groq_cfg = config.get("api", {}).get("groq", {})
        mode = "RADIO (bypass VAD)" if config.get("radio", {}).get("bypass_vad") else "VAD classico"
        self.mode_label.config(
            text=f"Modello: {groq_cfg.get('model', '?')}   |   Modalità: {mode}"
        )

        self.stop_event = threading.Event()
        self.worker = threading.Thread(
            target=self._pipeline_thread, args=(config,), daemon=True
        )
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("IN ASCOLTO", ACCENT_GREEN)
        self.worker.start()

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

        # --- CHIEDE CONFERMA PER IL SALVATAGGIO (OPZIONALE) ---
        if messagebox.askyesno("Salva trascrizione", "Vuoi salvare la trascrizione in un file .txt?"):
            self._save_transcript()
        else:
            self.error_label.config(text="Trascrizione non salvata.")

        self.stop_event.set()
        self.stop_btn.config(state="disabled")
        self._set_status("ARRESTO IN CORSO...", FG_DIM)

    def _save_transcript(self):
        """Salva il contenuto dell'area di trascrizione in un file .txt con timestamp."""
        transcript_text = self.transcript.get("1.0", "end-1c").strip()

        if not transcript_text:
            self.error_label.config(text="Nessuna trascrizione da salvare.")
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
            # Reset del colore dopo 5 secondi
            self.root.after(5000, lambda: self.error_label.config(fg=ACCENT_RED))
        except Exception as e:
            self.error_label.config(text=f"❌ Errore durante il salvataggio: {e}")

    def _set_status(self, text, color):
        self.status_label.config(text=text, fg=color)
        self.status_dot.itemconfig(self._dot, fill=color)

    # ------------------------------------------------------------------------
    # DEBUG TOGGLE
    # ------------------------------------------------------------------------
    def _toggle_debug(self):
        """Attiva/disattiva la modalità debug e apre/chiude la finestra di log."""
        self.debug_enabled = not self.debug_enabled

        if self.debug_enabled:
            self.debug_btn.config(
                text="🐞 DEBUG ON",
                bg=ACCENT_AMBER,
                fg="#14100a"
            )
            import logging
            logging.getLogger("AudioTranscriber").setLevel(logging.DEBUG)

            self.debug_window = DebugWindow(self.root)
        else:
            self.debug_btn.config(
                text="🐞 DEBUG OFF",
                bg="#2a2a2a",
                fg=FG_DIM
            )
            import logging
            logging.getLogger("AudioTranscriber").setLevel(logging.INFO)

            if self.debug_window:
                self.debug_window.on_close()
                self.debug_window = None

    # ------------------------------------------------------------------------
    # POLLING EVENTI
    # ------------------------------------------------------------------------
    def _poll_events(self):
        for kind, data in self.bus.poll_all():
            if kind == "rms":
                self._last_rms = data.get("value", 0.0)
                self._last_threshold = data.get("threshold", self._last_threshold)
                accepted = data.get("accepted", True)
                accepted_label = "\u25cf ACCETTATO" if accepted else "\u25cb SILENZIO (scartato)"
                self.vu_value_label.config(
                    text=(f"RMS: {self._last_rms:.1f}    Soglia: {self._last_threshold:.1f}    "
                          f"{accepted_label}"),
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
                self.error_label.config(text=f"Errore: {data.get('message', '')}")
            elif kind == "stopped":
                self.running = False
                self.start_btn.config(state="normal")
                self.stop_btn.config(state="disabled")
                self._set_status("FERMO", FG_DIM)

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

    # ------------------------------------------------------------------------
    # CHIUSURA
    # ------------------------------------------------------------------------
    def on_close(self):
        if self.running:
            self.stop_event.set()
        if self.debug_window:
            self.debug_window.on_close()
        self.root.destroy()


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