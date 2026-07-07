# gui_main.py
# Entry point dell'interfaccia grafica

import tkinter as tk
from gui.app import TranscriberGUI

def main():
    root = tk.Tk()
    app = TranscriberGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()