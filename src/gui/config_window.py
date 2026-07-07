# gui/config_window.py
# Finestra di modifica di config.json (VAD, filtro, API Groq)

import os
import json
import tkinter as tk
from .theme import *
from config import BASE_DIR

class ConfigWindow:
    def __init__(self, master, app_ref):
        self.master = master
        self.app = app_ref
        self.window = tk.Toplevel(master)
        self.window.title("⚙️ Configurazione - ATC Transcriber")
        self.window.geometry("620x520")
        self.window.minsize(500, 400)
        self.window.configure(bg=BG)
        self.window.transient(master)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.config_path = os.path.join(BASE_DIR, "config.json")
        self.config_data = self._load_config()
        self.entries = {}
        self._build_ui()

    def _load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _build_ui(self):
        main_frame = tk.Frame(self.window, bg=BG)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(main_frame, text="Modifica Configurazione", font=TITLE_FONT,
                 fg=ACCENT_CYAN, bg=BG).pack(anchor="w", pady=(0, 15))

        # Canvas con scroll
        canvas = tk.Canvas(main_frame, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, pady=(0, 15))
        scrollbar.pack(side="right", fill="y", pady=(0, 15))

        scrollable_frame.grid_columnconfigure(0, weight=0, minsize=200)
        scrollable_frame.grid_columnconfigure(1, weight=1)

        row = 0

        # --- Sezione VAD ---
        lbl_section = tk.Label(scrollable_frame, text="Voice Activity Detection (VAD)",
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
            lbl = tk.Label(scrollable_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(scrollable_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Sezione Filtro ---
        lbl_section = tk.Label(scrollable_frame, text="Filtro Passa-Banda",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        filter_params = [
            ("filter_enabled", "Abilitato (true/false)", self.config_data.get("filter", {}).get("enabled", True)),
            ("band_min", "Band min (Hz)", self.config_data.get("filter", {}).get("band_min", 300)),
            ("band_max", "Band max (Hz)", self.config_data.get("filter", {}).get("band_max", 3400)),
        ]
        for key, label, default_value in filter_params:
            lbl = tk.Label(scrollable_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(scrollable_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Sezione API Groq ---
        lbl_section = tk.Label(scrollable_frame, text="API Groq",
                               font=FONT_BOLD, fg=ACCENT_CYAN, bg=BG)
        lbl_section.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 5))
        row += 1

        api_params = [
            ("model", "Modello", self.config_data.get("api", {}).get("groq", {}).get("model", "whisper-large-v3")),
            ("timeout_s", "Timeout (s)", self.config_data.get("api", {}).get("groq", {}).get("timeout_s", 10)),
            ("max_concurrent_requests", "Max concurrent requests", self.config_data.get("api", {}).get("groq", {}).get("max_concurrent_requests", 5)),
            ("use_flac", "Usa FLAC (true/false)", self.config_data.get("api", {}).get("groq", {}).get("use_flac", True)),
        ]
        for key, label, default_value in api_params:
            lbl = tk.Label(scrollable_frame, text=label, font=FONT, fg=FG, bg=BG, anchor="w")
            lbl.grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = tk.Entry(scrollable_frame, font=FONT, bg="#05070a", fg=FG,
                             insertbackground=FG, relief="flat", bd=0)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.insert(0, str(default_value))
            self.entries[key] = entry
            row += 1

        # --- Pulsanti ---
        btn_container = tk.Frame(main_frame, bg=BG)
        btn_container.pack(fill="x", pady=(15, 5), padx=30)

        btn_container.grid_columnconfigure(0, weight=1)
        btn_container.grid_columnconfigure(1, weight=0)
        btn_container.grid_columnconfigure(2, weight=1)

        tk.Button(btn_container, text="🔄 APPLICA", command=self._apply_config,
                  bg=ACCENT_CYAN, fg="#04140a", font=FONT_BOLD, relief="flat",
                  padx=20, pady=8, cursor="hand2").grid(row=0, column=1, pady=(0, 10))

        tk.Button(btn_container, text="✅ OK", command=self._save_and_close,
                  bg=ACCENT_GREEN, fg="#04140a", font=FONT_BOLD, relief="flat",
                  padx=20, pady=8, cursor="hand2").grid(row=1, column=1, pady=(0, 0))

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
            "api": {
                "groq": {
                    "model": self.entries["model"].get(),
                    "timeout_s": int(self.entries["timeout_s"].get()),
                    "max_concurrent_requests": int(self.entries["max_concurrent_requests"].get()),
                    "use_flac": self.entries["use_flac"].get().lower() == "true",
                }
            }
        }

    def _save_config_with_patch(self, patch):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}

        if "vad" in patch:
            if "vad" not in config:
                config["vad"] = {}
            config["vad"].update(patch["vad"])
        if "filter" in patch:
            if "filter" not in config:
                config["filter"] = {}
            config["filter"].update(patch["filter"])
        if "api" in patch:
            if "api" not in config:
                config["api"] = {}
            if "groq" in patch["api"]:
                if "groq" not in config["api"]:
                    config["api"]["groq"] = {}
                for key, value in patch["api"]["groq"].items():
                    config["api"]["groq"][key] = value

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

        return config

    def _update_entries_from_config(self, config):
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
        self.entries["filter_enabled"].delete(0, tk.END)
        self.entries["filter_enabled"].insert(0, str(config.get("filter", {}).get("enabled", True)))
        self.entries["band_min"].delete(0, tk.END)
        self.entries["band_min"].insert(0, str(config.get("filter", {}).get("band_min", 300)))
        self.entries["band_max"].delete(0, tk.END)
        self.entries["band_max"].insert(0, str(config.get("filter", {}).get("band_max", 3400)))
        self.entries["model"].delete(0, tk.END)
        self.entries["model"].insert(0, config.get("api", {}).get("groq", {}).get("model", "whisper-large-v3"))
        self.entries["timeout_s"].delete(0, tk.END)
        self.entries["timeout_s"].insert(0, str(config.get("api", {}).get("groq", {}).get("timeout_s", 10)))
        self.entries["max_concurrent_requests"].delete(0, tk.END)
        self.entries["max_concurrent_requests"].insert(0, str(config.get("api", {}).get("groq", {}).get("max_concurrent_requests", 5)))
        self.entries["use_flac"].delete(0, tk.END)
        self.entries["use_flac"].insert(0, str(config.get("api", {}).get("groq", {}).get("use_flac", True)))

    def _apply_config(self):
        try:
            patch = self._get_patch_from_entries()
            updated_config = self._save_config_with_patch(patch)
            self.app._reload_config()
            self._update_entries_from_config(updated_config)
            self.app.error_label.config(text="✅ Configurazione applicata (finestra rimane aperta).", fg=ACCENT_GREEN)
        except Exception as e:
            self.app.error_label.config(text=f"❌ Errore durante l'applicazione: {e}", fg=ACCENT_RED)

    def _save_and_close(self):
        try:
            patch = self._get_patch_from_entries()
            updated_config = self._save_config_with_patch(patch)
            self.app._reload_config()
            self.window.destroy()
            self.app.error_label.config(text="✅ Configurazione salvata e applicata.", fg=ACCENT_GREEN)
        except Exception as e:
            self.app.error_label.config(text=f"❌ Errore durante il salvataggio: {e}", fg=ACCENT_RED)

    def on_close(self):
        self.window.destroy()