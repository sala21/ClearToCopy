import logging
import sys
import json
import os
from datetime import datetime
from paths import CONFIG_PATH, LOG_FILE

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


def archive_log_file():
    """Rinomina il file di log con timestamp e restituisce il nuovo nome."""
    if not os.path.exists(LOG_FILE):
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"debug_{timestamp}.log"
    try:
        os.rename(LOG_FILE, new_name)
        return new_name
    except Exception:
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
logger.setLevel(logging.DEBUG)  # Il logger raccoglie SEMPRE tutto: il
# filtraggio di cosa mostrare avviene sui singoli handler (console/file),
# non qui. Se questo livello venisse abbassato a INFO, i record DEBUG
# verrebbero scartati PRIMA di raggiungere qualsiasi handler, rompendo
# sia la console sia il file contemporaneamente — per questo la GUI non
# deve mai toccare 'logger.setLevel(...)' (vedi set_console_debug sotto).

# --- Livello di base della console, preso da config.json ---
_BASE_CONSOLE_LEVEL = getattr(
    logging, debug_config.get("console_level", "INFO").upper(), logging.INFO
)

# --- Handler per la console (schermo) ---
console_handler = logging.StreamHandler(sys.stdout)
# FIX: rispetta anche il flag 'debug.enabled' di config.json all'avvio
# (in precedenza veniva ignorato e si partiva sempre da console_level).
if debug_config.get("enabled", False):
    console_handler.setLevel(logging.DEBUG)
else:
    console_handler.setLevel(_BASE_CONSOLE_LEVEL)

console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# --- Handler per il file (opzionale) ---
if debug_config.get("log_to_file", True):
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding="utf-8")
    # FIX: il file deve registrare SEMPRE tutto, compreso il DEBUG,
    # indipendentemente da cosa viene mostrato a console. In una versione
    # precedente questo era stato impostato a INFO, quindi la DebugWindow
    # nella GUI (che tail-a proprio questo file) non mostrava mai i
    # messaggi di debug anche con "DEBUG ON".
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
else:
    file_handler = None


def set_console_debug(enabled):
    """
    Attiva/disattiva la verbosità DEBUG sulla SOLA console, senza toccare
    il logger principale (che resta sempre a DEBUG) né il file_handler
    (che deve continuare a registrare sempre tutto). Questa è l'unica
    funzione che la GUI deve usare per il toggle del debug — non deve mai
    chiamare logging.getLogger("AudioTranscriber").setLevel(...)
    direttamente, altrimenti rompe la registrazione su file.
    """
    console_handler.setLevel(logging.DEBUG if enabled else _BASE_CONSOLE_LEVEL)


def get_logger():
    return logger