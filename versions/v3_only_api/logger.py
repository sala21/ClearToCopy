import logging
import sys
import json
import os

# =============================================
# CARICA CONFIGURAZIONE PER IL DEBUG
# =============================================
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
debug_config = {
    "enabled": False,
    "log_to_file": True,
    "console_level": "INFO"
}

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
        debug_config.update(config.get("debug", {}))
except Exception:
    # Se il file non esiste o non contiene la sezione debug, usa i default
    pass

# =============================================
# CONFIGURAZIONE DEL LOGGER
# =============================================
logger = logging.getLogger("AudioTranscriber")
logger.setLevel(logging.DEBUG)  # Il logger raccoglie TUTTO

# --- Handler per la console (schermo) ---
console_handler = logging.StreamHandler(sys.stdout)
console_level = debug_config.get("console_level", "INFO").upper()
if debug_config.get("enabled", False):
    console_handler.setLevel(logging.DEBUG)   # Se debug attivo, mostra tutto
else:
    console_handler.setLevel(getattr(logging, console_level, logging.INFO))

console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# --- Handler per il file (opzionale) ---
if debug_config.get("log_to_file", True):
    file_handler = logging.FileHandler("transcriber.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # Il file registra SEMPRE tutto
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

# =============================================
# FUNZIONE DI COMODO
# =============================================
def get_logger():
    return logger

# Stampa un messaggio iniziale per confermare la modalità
if debug_config.get("enabled", False):
    logger.debug("🐞 MODALITÀ DEBUG ATTIVA - Tutti i messaggi sono visibili a schermo.")
else:
    logger.info("Modalità normale (debug disattivato). Per attivarlo, imposta 'enabled': true in config.json")