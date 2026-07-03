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

    La API key Groq, se presente nella variabile d'ambiente GROQ_API_KEY,
    ha sempre precedenza su quella eventualmente presente in config.json.
    Questo evita di dover tenere segreti in chiaro nel file di configurazione.
    """
    print(f"[Config] Cerco file in: {CONFIG_PATH}")

    if not os.path.exists(CONFIG_PATH):
        print(f"\nERRORE: File {CONFIG_PATH} non trovato.")
        print("Crea il file config.json nella stessa cartella di questo programma.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_key = os.environ.get("GROQ_API_KEY")
    if env_key:
        config.setdefault("api", {}).setdefault("groq", {})["api_key"] = env_key

    if not config.get("api", {}).get("groq", {}).get("api_key"):
        print("\nERRORE: nessuna API key Groq trovata.")
        print("Impostala con: export GROQ_API_KEY=\"la-tua-chiave\"  (Linux/macOS)")
        print("            oppure: set GROQ_API_KEY=la-tua-chiave     (Windows cmd)")
        sys.exit(1)

    print("[Config] Caricato con successo.")
    return config
