# gui/config_window.py
# Finestra di modifica di config.json (VAD, filtro, modello locale, radio)

import os
import json
import tkinter as tk
from .theme import *
from paths import CONFIG_PATH

class ConfigWindow:
    def __init__(self, master, app_ref):
        self.master = master
        self.app = app_ref
        self.window = tk.Toplevel(master)
        self.window.title("⚙️ Configurazione - ClearToCopy")
        self.window.geometry("520x600")
        self.window.minsize(420, 350)
        self.window.configure(bg=BG)
        self.window.transient(master)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.apply_pressed = False

        self.config_data = self._load_config()
        self.entries = {}
        self._build_ui()

    def _load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _build_ui(self):
        main_frame = tk.Frame(self.window, bg=BG)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(main_frame, text="MODIFICA CONFIGURAZIONE", font=TITLE_FONT,
                 fg=ACCENT_CYAN, bg=BG).pack(anchor="w", pady=(0, 15))

        # --- CONTENITORE SCROLLABILE PER I PARAMETRI ---
        canvas_area = tk.Frame(main_frame, bg=BG)
        canvas_area.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_area, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_area, orient="vertical", command=canvas.yview)
        params_frame = tk.Frame(canvas, bg=BG)

        params_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_window = canvas.create_window((0, 0), window=params_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # params_frame deve restare largo quanto il canvas, altrimenti le
        # colonne (in particolare gli Entry a colonna 1) non si espandono.
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Scroll con la rotellina, attivo SOLO mentre il puntatore è sopra
        # il canvas: bind_all permanente resterebbe agganciato a tutta
        # l'app anche dopo la chiusura di questa finestra.
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        self._config_canvas = canvas  # per lo scollegamento di sicurezza in on_close

        params_frame.grid_columnconfigure(0, weight=0, minsize=200)
        params_frame.grid_columnconfigure(1, weight=1)

        row = 0

        # --- Sezione VAD ---
        lbl_section = tk.Label(params_frame, text="Voice Activity Detection (VAD)",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        vad_params = [
            ("aggressiveness", "Aggressiveness (0-3)", self.config_data.get("vad", {}).get("aggressiveness", 1)),
            ("silence_timeout_s", "Silence timeout (s)", self.config_data.get("vad", {}).get("silence_timeout_s", 1.0)),
            ("max_utterance_s", "Max utterance (s)", self.config_data.get("vad", {}).get("max_utterance_s", 15.0)),
            ("min_segment_duration_s", "Min segment duration (s)", self.config_data.get("vad", {}).get("min_segment_duration_s", 0.6)),
            ("activation_ratio", "Activation ratio (0-1)", self.config_data.get("vad", {}).get("activation_ratio", 0.4)),
        ]
        for key, label, default_value in vad_params:
            lbl = tk.Label(params_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(params_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Sezione Filtro ---
        lbl_section = tk.Label(params_frame, text="Filtro Passa-Banda",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        filter_params = [
            ("filter_enabled", "Abilitato (true/false)", self.config_data.get("filter", {}).get("enabled", True)),
            ("band_min", "Band min (Hz)", self.config_data.get("filter", {}).get("band_min", 300)),
            ("band_max", "Band max (Hz)", self.config_data.get("filter", {}).get("band_max", 3400)),
        ]
        for key, label, default_value in filter_params:
            lbl = tk.Label(params_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(params_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Nuova sezione: Modello Locale ---
        lbl_section = tk.Label(params_frame, text="Modello Locale",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        local_model_params = [
            ("model_name", "Nome modello", self.config_data.get("local_model", {}).get("model_name", "openai/whisper-large-v3")),
            ("device", "Device (cpu/cuda)", self.config_data.get("local_model", {}).get("device", "cuda")),
            ("language", "Lingua (es. it, en)", self.config_data.get("local_model", {}).get("language", "it")),
        ]
        for key, label, default_value in local_model_params:
            lbl = tk.Label(params_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(params_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Nuova sezione: Impostazioni Radio ---
        lbl_section = tk.Label(params_frame, text="Impostazioni Radio",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        radio_params = [
            ("radio_enabled", "Modalità radio abilitata (true/false)", self.config_data.get("radio", {}).get("enabled", True)),
            ("bypass_vad", "Usa modalità radio invece del VAD (true/false)", self.config_data.get("radio", {}).get("bypass_vad", False)),
            ("segment_duration_s", "Durata segmento (s)", self.config_data.get("radio", {}).get("segment_duration_s", 3.0)),
            ("overlap_s", "Overlap tra segmenti (s)", self.config_data.get("radio", {}).get("overlap_s", 0.3)),
            ("silence_gate_enabled", "Scarta segmenti silenziosi (true/false)", self.config_data.get("radio", {}).get("silence_gate_enabled", True)),
            ("silence_rms_threshold", "Soglia RMS silenzio", self.config_data.get("radio", {}).get("silence_rms_threshold", 50)),
            ("boundary_search_s", "Ricerca punto di taglio (s)", self.config_data.get("radio", {}).get("boundary_search_s", 0.4)),
            ("boundary_analysis_ms", "Risoluzione ricerca taglio (ms)", self.config_data.get("radio", {}).get("boundary_analysis_ms", 20)),
        ]
        for key, label, default_value in radio_params:
            lbl = tk.Label(params_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(params_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        note = tk.Label(
            params_frame,
            text="⚠️ Cambiare modalità (VAD ↔ Radio) richiede Stop poi Avvia,\n"
                 "non basta 'Ric CFG Live' a pipeline già in corso.",
            font=FONT_SMALL, fg=ACCENT_AMBER, bg=BG, justify="left", anchor="w"
        )
        note.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        # --- Pulsanti (applica e ok), fissi in basso, FUORI dall'area scrollabile ---
        btn_frame = tk.Frame(main_frame, bg=BG)
        btn_frame.pack(fill="x", pady=(10, 0))

        apply_btn = tk.Button(btn_frame, text="🔄 APPLICA", command=self._apply_config,
                              bg=ACCENT_CYAN, fg="#04140a", font=FONT_SMALL,
                              relief="flat", padx=10, pady=4, cursor="hand2", bd=0)
        apply_btn.pack(side="left", padx=(0, 8))

        ok_btn = tk.Button(btn_frame, text="✅ OK", command=self._save_and_close,
                           bg=ACCENT_GREEN, fg="#04140a", font=FONT_SMALL,
                           relief="flat", padx=10, pady=4, cursor="hand2", bd=0)
        ok_btn.pack(side="left")

    def _get_patch_from_entries(self):
        return {
            "vad": {
                "aggressiveness": int(self.entries["aggressiveness"].get()),
                "silence_timeout_s": float(self.entries["silence_timeout_s"].get()),
                "max_utterance_s": float(self.entries["max_utterance_s"].get()),
                "min_segment_duration_s": float(self.entries["min_segment_duration_s"].get()),
                "activation_ratio": float(self.entries["activation_ratio"].get()),
            },
            "filter": {
                "enabled": self.entries["filter_enabled"].get().lower() == "true",
                "band_min": int(self.entries["band_min"].get()),
                "band_max": int(self.entries["band_max"].get()),
            },
            "local_model": {
                "model_name": self.entries["model_name"].get(),
                "device": self.entries["device"].get(),
                "language": self.entries["language"].get(),
            },
            "radio": {
                "enabled": self.entries["radio_enabled"].get().lower() == "true",
                "bypass_vad": self.entries["bypass_vad"].get().lower() == "true",
                "segment_duration_s": float(self.entries["segment_duration_s"].get()),
                "overlap_s": float(self.entries["overlap_s"].get()),
                "silence_gate_enabled": self.entries["silence_gate_enabled"].get().lower() == "true",
                "silence_rms_threshold": float(self.entries["silence_rms_threshold"].get()),
                "boundary_search_s": float(self.entries["boundary_search_s"].get()),
                "boundary_analysis_ms": float(self.entries["boundary_analysis_ms"].get()),
            }
        }

    def _save_config_with_patch(self, patch):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}

        # Aggiorna VAD
        if "vad" in patch:
            if "vad" not in config:
                config["vad"] = {}
            config["vad"].update(patch["vad"])

        # Aggiorna filtro
        if "filter" in patch:
            if "filter" not in config:
                config["filter"] = {}
            config["filter"].update(patch["filter"])

        # Aggiorna modello locale
        if "local_model" in patch:
            if "local_model" not in config:
                config["local_model"] = {}
            config["local_model"].update(patch["local_model"])

        # Aggiorna radio
        if "radio" in patch:
            if "radio" not in config:
                config["radio"] = {}
            config["radio"].update(patch["radio"])

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        return config

    def _update_entries_from_config(self, config):
        # VAD
        self.entries["aggressiveness"].delete(0, tk.END)
        self.entries["aggressiveness"].insert(0, str(config.get("vad", {}).get("aggressiveness", 1)))
        self.entries["silence_timeout_s"].delete(0, tk.END)
        self.entries["silence_timeout_s"].insert(0, str(config.get("vad", {}).get("silence_timeout_s", 1.0)))
        self.entries["max_utterance_s"].delete(0, tk.END)
        self.entries["max_utterance_s"].insert(0, str(config.get("vad", {}).get("max_utterance_s", 15.0)))
        self.entries["min_segment_duration_s"].delete(0, tk.END)
        self.entries["min_segment_duration_s"].insert(0, str(config.get("vad", {}).get("min_segment_duration_s", 0.6)))
        self.entries["activation_ratio"].delete(0, tk.END)
        self.entries["activation_ratio"].insert(0, str(config.get("vad", {}).get("activation_ratio", 0.4)))

        # Filtro
        self.entries["filter_enabled"].delete(0, tk.END)
        self.entries["filter_enabled"].insert(0, str(config.get("filter", {}).get("enabled", True)))
        self.entries["band_min"].delete(0, tk.END)
        self.entries["band_min"].insert(0, str(config.get("filter", {}).get("band_min", 300)))
        self.entries["band_max"].delete(0, tk.END)
        self.entries["band_max"].insert(0, str(config.get("filter", {}).get("band_max", 3400)))

        # Modello locale
        self.entries["model_name"].delete(0, tk.END)
        self.entries["model_name"].insert(0, config.get("local_model", {}).get("model_name", "openai/whisper-large-v3"))
        self.entries["device"].delete(0, tk.END)
        self.entries["device"].insert(0, config.get("local_model", {}).get("device", "cuda"))
        self.entries["language"].delete(0, tk.END)
        self.entries["language"].insert(0, config.get("local_model", {}).get("language", "it"))

        # Radio
        self.entries["radio_enabled"].delete(0, tk.END)
        self.entries["radio_enabled"].insert(0, str(config.get("radio", {}).get("enabled", True)))
        self.entries["bypass_vad"].delete(0, tk.END)
        self.entries["bypass_vad"].insert(0, str(config.get("radio", {}).get("bypass_vad", False)))
        self.entries["segment_duration_s"].delete(0, tk.END)
        self.entries["segment_duration_s"].insert(0, str(config.get("radio", {}).get("segment_duration_s", 3.0)))
        self.entries["overlap_s"].delete(0, tk.END)
        self.entries["overlap_s"].insert(0, str(config.get("radio", {}).get("overlap_s", 0.3)))
        self.entries["silence_gate_enabled"].delete(0, tk.END)
        self.entries["silence_gate_enabled"].insert(0, str(config.get("radio", {}).get("silence_gate_enabled", True)))
        self.entries["silence_rms_threshold"].delete(0, tk.END)
        self.entries["silence_rms_threshold"].insert(0, str(config.get("radio", {}).get("silence_rms_threshold", 50)))
        self.entries["boundary_search_s"].delete(0, tk.END)
        self.entries["boundary_search_s"].insert(0, str(config.get("radio", {}).get("boundary_search_s", 0.4)))
        self.entries["boundary_analysis_ms"].delete(0, tk.END)
        self.entries["boundary_analysis_ms"].insert(0, str(config.get("radio", {}).get("boundary_analysis_ms", 20)))

    def _apply_config(self):
        try:
            patch = self._get_patch_from_entries()
            updated_config = self._save_config_with_patch(patch)
            self.app._reload_config()
            self._update_entries_from_config(updated_config)
            self.apply_pressed = True
            self.app.error_label.config(text="✅ Configurazione applicata (finestra rimane aperta).", fg=ACCENT_GREEN)
        except Exception as e:
            self.app.error_label.config(text=f"❌ Errore durante l'applicazione: {e}", fg=ACCENT_RED)

    def _close_window(self):
        if hasattr(self, "_config_canvas"):
            try:
                self._config_canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
        self.window.destroy()

    def _save_and_close(self):
        try:
            if self.apply_pressed:
                patch = self._get_patch_from_entries()
                updated_config = self._save_config_with_patch(patch)
                self.app._reload_config()
                self._close_window()
                self.app.error_label.config(text="✅ Configurazione salvata e applicata.", fg=ACCENT_GREEN)
            else:
                self._close_window()
        except Exception as e:
            self.app.error_label.config(text=f"❌ Errore durante il salvataggio: {e}", fg=ACCENT_RED)

    def on_close(self):
        self._close_window()