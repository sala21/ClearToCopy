import json
import os
import sys
from logger import get_logger

from paths import CONFIG_PATH

logger = get_logger()

def load_config():
    logger.info("Cerco file in: %s", CONFIG_PATH)
    if not os.path.exists(CONFIG_PATH):
        logger.error("File %s non trovato.", CONFIG_PATH)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    logger.info("Configurazione caricata con successo.")
    return config