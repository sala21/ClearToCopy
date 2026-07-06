import logging
import sys
import json
import os
import threading
from datetime import datetime

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

LOG_FILE = "transcriber.log"

def archive_log_file():
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
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
            return True
        except Exception:
            return False
    return False

_debug_buffer = []
_buffer_lock = threading.Lock()

def get_debug_buffer():
    with _buffer_lock:
        content = _debug_buffer.copy()
        _debug_buffer.clear()
        return content

def clear_debug_buffer():
    with _buffer_lock:
        _debug_buffer.clear()

def save_debug_buffer_to_file():
    content = get_debug_buffer()
    if not content:
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"debug_{timestamp}.log"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        return filename
    except Exception:
        return None

logger = logging.getLogger("AudioTranscriber")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_level = debug_config.get("console_level", "INFO").upper()
console_handler.setLevel(getattr(logging, console_level, logging.INFO))
console_formatter = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

if debug_config.get("log_to_file", True):
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

class DebugBufferHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setLevel(logging.DEBUG)

    def emit(self, record):
        if record.levelno == logging.DEBUG:
            with _buffer_lock:
                _debug_buffer.append(self.format(record))

debug_buffer_handler = DebugBufferHandler()
debug_formatter = logging.Formatter(
    '%(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
debug_buffer_handler.setFormatter(debug_formatter)
logger.addHandler(debug_buffer_handler)

def get_logger():
    return logger