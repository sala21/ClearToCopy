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
    pass

# =============================================
# FUNZIONI PER LA GESTIONE DEL FILE DI LOG
# =============================================
LOG_FILE = "transcriber.log"

def archive_log_file():
    """Rinomina il file di log con timestamp e restituisce il nuovo nome."""
    if not os.path.exists(LOG_FILE):
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"debug_{timestamp}.log"
    try:
        os.rename(LOG_FILE, new_name)
        return new_name
    except Exception as e:
        return None

def clear_log_file():
    """Svuota il file di log (cancella il contenuto)."""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
            return True
        except Exception:
            return False
    return False

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
    file_handler = logging.FileHandler("transcriber.log", mode='w', encoding="utf-8")
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