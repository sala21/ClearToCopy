# gui/debug_window.py
# Finestra che mostra in tempo reale il file di log

import os
import tkinter as tk
from tkinter import scrolledtext
from .theme import BG, FG, FONT_MONO

class DebugWindow:
    def __init__(self, master):
        self.window = tk.Toplevel(master)
        self.window.title("🐞 Debug Log History")
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