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
    """
    Rinomina il file di log corrente con un timestamp e ne riapre uno nuovo
    con lo stesso nome, per continuare a scrivere.

    IMPORTANTE: passa dalla STESSA istanza di 'file_handler' (chiudi ->
    rinomina -> riapri, lo stesso pattern usato internamente da
    logging.handlers.RotatingFileHandler.doRollover()) invece di rinominare
    il file con un handle indipendente. Su Windows, rinominare/troncare un
    file che 'file_handler' ha ancora aperto può fallire silenziosamente o
    disallineare lo stream del logger, impedendo ulteriori scritture per il
    resto della sessione (il sintomo tipico: il file di log resta vuoto e
    la GUI non chiede più di salvarlo).
    """
    if file_handler is None or not os.path.exists(LOG_FILE):
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"debug_{timestamp}.log"
    try:
        file_handler.acquire()
        try:
            file_handler.close()
            os.rename(LOG_FILE, new_name)
            file_handler.stream = file_handler._open()
        finally:
            file_handler.release()
        return new_name
    except Exception:
        return None

def clear_log_file():
    """
    Svuota il file di log corrente TRAMITE lo stream già aperto dal logger
    (seek a inizio file + truncate), invece di aprirne uno indipendente:
    vedi la nota in archive_log_file() sul perché è importante su Windows.
    """
    if file_handler is None:
        return False
    try:
        file_handler.acquire()
        try:
            file_handler.stream.seek(0)
            file_handler.stream.truncate()
            file_handler.stream.flush()
        finally:
            file_handler.release()
        return True
    except Exception:
        return False


# =============================================
# CONFIGURAZIONE DEL LOGGER
# =============================================
logger = logging.getLogger("AudioTranscriber")
logger.setLevel(logging.DEBUG)  #NON MODIFICARE

# --- Livello di base della console, preso da config.json ---
_BASE_CONSOLE_LEVEL = getattr(
    logging, debug_config.get("console_level", "INFO").upper(), logging.INFO
)

# --- Handler per la console (schermo) ---
console_handler = logging.StreamHandler(sys.stdout)
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
    Attiva/disattiva la verbosità DEBUG sulla SOLA console
    """
    console_handler.setLevel(logging.DEBUG if enabled else _BASE_CONSOLE_LEVEL)

def get_logger():
    return logger