import json
import os
import sys

def get_base_dir():
    """Restituisce la directory dello script (o dell'eseguibile se frozen)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def load_config():
    """
    Carica la configurazione dal file JSON.
    Se il file non esiste, stampa un messaggio di errore e termina.
    """
    print(f"[Config] Cerco file in: {CONFIG_PATH}")

    if not os.path.exists(CONFIG_PATH):
        print(f"\nERRORE: File {CONFIG_PATH} non trovato.")
        print("Crea il file config.json nella stessa cartella di questo programma.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    print("[Config] Caricato con successo.")
    return config