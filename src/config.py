import json
import os
import sys
from logger import get_logger

logger = get_logger()

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def load_config():
    logger.info("Cerco file in: %s", CONFIG_PATH)
    if not os.path.exists(CONFIG_PATH):
        logger.error("File %s non trovato.", CONFIG_PATH)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_key = os.environ.get("GROQ_API_KEY")
    if env_key:
        config.setdefault("api", {}).setdefault("groq", {})["api_key"] = env_key

    if not config.get("api", {}).get("groq", {}).get("api_key"):
        logger.error("Nessuna API key Groq trovata.")
        sys.exit(1)

    logger.info("Configurazione caricata con successo.")
    return config