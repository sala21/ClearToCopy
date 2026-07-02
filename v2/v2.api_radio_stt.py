import json
import os
import collections
import queue
import sys
import threading
import io
import wave
import numpy as np
import pyaudio
import webrtcvad
from faster_whisper import WhisperModel
import requests



def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

def load_config():
    print(f"[Config] Cerco file in: {CONFIG_PATH}")

    if not os.path.exists(CONFIG_PATH):
        print(f"\nERRORE: File {CONFIG_PATH} non trovato.")
        print("Crea il file config.json nella stessa cartella di questo programma.")
        print("Esempio di contenuto minimo:")
        print("""
{
    "api": {
        "groq": {
            "api_key": "gsk_la_tua_chiave_qui"
        }
    }
}
        """)
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    print("[Config] Caricato con successo.")
    return config

    """
    Carica la configurazione dal file JSON.
    Se il file non esiste, stampa un errore e termina.
    """
    CONFIG_FILE = "config.json"
    print(f"[Config] Cerco file in: {CONFIG_FILE}")

    if not os.path.exists(CONFIG_FILE):
        print(f"\nERRORE: File {CONFIG_FILE} non trovato.")
        print("Crea il file config.json nella stessa cartella di questo script.")
        sys.exit(1)   # Termina senza creare file

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    print("[Config] Caricato con successo.")
    return config

config = load_config()

# === Estrai parametri con get() ===

# API Groq
API_KEY = config.get("api", {}).get("groq", {}).get("api_key", "")
GROQ_MODEL = config.get("api", {}).get("groq", {}).get("model", "whisper-large-v3")
GROQ_URL = config.get("api", {}).get("groq", {}).get("url", "https://api.groq.com/openai/v1/audio/transcriptions")

# Modello locale (fallback)
LOCAL_MODEL = config.get("local", {}).get("model", "base")
LOCAL_DEVICE = config.get("local", {}).get("device", "cpu")
LOCAL_COMPUTE_TYPE = config.get("local", {}).get("compute_type", "int8")

# Audio
RATE = config.get("audio", {}).get("rate", 16000)
CHANNELS = config.get("audio", {}).get("channels", 1)
FRAME_DURATION_MS = config.get("audio", {}).get("frame_duration_ms", 30)
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)  # Calcolato da RATE e FRAME_DURATION_MS

# VAD (Voice Activity Detection)
VAD_AGGRESSIVENESS = config.get("vad", {}).get("aggressiveness", 2)
SILENCE_TIMEOUT_S = config.get("vad", {}).get("silence_timeout_s", 1.2)
MAX_UTTERANCE_S = config.get("vad", {}).get("max_utterance_s", 20.0)

# Filtro passa-banda (opzionale)
APPLY_FILTER = config.get("filter", {}).get("enabled", False)
FILTRO_BANDA_MIN = config.get("filter", {}).get("band_min", 300)
FILTRO_BANDA_MAX = config.get("filter", {}).get("band_max", 3400)

# Durata minima del segmento da trascrivere (in secondi)
MIN_SEGMENT_DURATION_S = config.get("min_segment_duration_s", 1.2)

# ====================================================================
#  INIZIALIZZAZIONE
# ====================================================================

print("Caricamento modello locale (fallback)...")
local_model = WhisperModel(LOCAL_MODEL, device=LOCAL_DEVICE, compute_type=LOCAL_COMPUTE_TYPE)
print("Modello locale pronto.")

vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

# Code con limite per evitare accumulo di memoria
audio_queue = queue.Queue(maxsize=200)        # frame in arrivo dal microfono
transcribe_queue = queue.Queue(maxsize=2)     # segmenti da trascrivere
stop_event = threading.Event()

p = pyaudio.PyAudio()

# ====================================================================
#  FUNZIONI DI SERVIZIO
# ====================================================================

def audio_to_wav_bytes(audio_np):
    """
    Converte un array float32 [-1,1] in un file WAV (16kHz mono, 16-bit PCM) in memoria.
    Restituisce i bytes del file WAV completo.
    """
    audio_int16 = (audio_np * 32767).astype(np.int16)
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(RATE)
            wf.writeframes(audio_int16.tobytes())
        return wav_io.getvalue()

def apply_bandpass_filter(audio_np):
    """Filtro FIR leggero 300‑3400 Hz (opzionale)."""
    if not APPLY_FILTER:
        return audio_np
    try:
        from scipy import signal
        b = signal.firwin(65, [FILTRO_BANDA_MIN, FILTRO_BANDA_MAX], fs=RATE, pass_zero=False)
        return signal.lfilter(b, [1.0], audio_np)
    except Exception:
        return audio_np

# ====================================================================
#  TRASCRIZIONE VIA API GROQ
# ====================================================================

def transcribe_with_groq(audio_np):
    """
    Invia l'audio a Groq per la trascrizione.
    Restituisce il testo oppure None in caso di errore.
    """
    if not API_KEY:
        print("[Groq] Chiave API mancante nel config.json.")
        return None

    wav_bytes = audio_to_wav_bytes(audio_np)
    files = {
        "file": ("audio.wav", wav_bytes, "audio/wav"),
    }
    data = {
        "model": GROQ_MODEL,
        "language": "en",
        "response_format": "json",
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
    }

    try:
        resp = requests.post(GROQ_URL, headers=headers, files=files, data=data, timeout=30)
        if resp.status_code != 200:
            print(f"[Groq] Errore HTTP {resp.status_code}: {resp.text}")
            return None
        result = resp.json()
        text = result.get("text", "").strip()
        return text if text else None
    except requests.exceptions.Timeout:
        print("[Groq] Timeout della richiesta.")
        return None
    except Exception as e:
        print(f"[Groq] Errore generico: {e}")
        return None

# ====================================================================
#  TRASCRIZIONE LOCALE (FALLBACK)
# ====================================================================

INITIAL_PROMPT = (
    "ATC radio transmission, aviation phraseology, pilot and tower control. "
    "Aircraft callsigns, runway numbers, headings, flight levels, and altitudes. "
    "Keywords: cleared to land, line up and wait, hold short, taxi via, squawk, "
    "maintain, radar contact, wind, knots, QNH, altimeter, ILS approach, flight level. "
    "Phonetic alphabet: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, "
    "Juliett, Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, "
    "Uniform, Victor, Whiskey, X-ray, Yankee, Zulu. "
    "Numbers and digits: zero, one, two, tree, four, fife, six, seven, eight, niner, hundred, thousand."
)

def transcribe_local(audio_np):
    """Usa Faster‑Whisper in locale."""
    try:
        segments, _ = local_model.transcribe(
            audio_np,
            beam_size=1,               # veloce
            language="en",
            initial_prompt=INITIAL_PROMPT,
        )
        full_text = " ".join(seg.text for seg in segments).strip()
        return full_text if full_text else None
    except Exception as e:
        print(f"[Locale] Errore: {e}")
        return None

# ====================================================================
#  THREAD WORKER PER LA TRASCRIZIONE
# ====================================================================

def transcribe_worker():
    while not stop_event.is_set():
        try:
            audio_np = transcribe_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if audio_np is None:
            break

        # Applica filtro (se attivo)
        audio_np = apply_bandpass_filter(audio_np)

        # Prova prima l'API Groq
        text = transcribe_with_groq(audio_np)

        # Se fallisce, usa il modello locale
        if text is None:
            print("[Fallback] Uso modello locale...")
            text = transcribe_local(audio_np)

        if text:
            print(text)
        else:
            print("[Trascrizione] Nessun testo riconosciuto.")
        print("-" * 40)

    print("[Worker] Terminato.")

# ====================================================================
#  CALLBACK AUDIO (PyAudio)
# ====================================================================

def audio_callback(in_data, frame_count, time_info, status):
    try:
        if audio_queue.qsize() < audio_queue.maxsize:
            audio_queue.put(in_data)
    except queue.Full:
        pass
    return (None, pyaudio.paContinue)

# ====================================================================
#  AVVIO STREAM
# ====================================================================

stream = p.open(format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
                stream_callback=audio_callback)

worker_thread = threading.Thread(target=transcribe_worker, daemon=True)
worker_thread.start()

print("\n=== ASCOLTO ATTIVO ===")
print(f"API primaria: Groq ({GROQ_MODEL})")
print("Fallback: modello locale (Faster-Whisper)")
print("Premi Ctrl+C per terminare.\n")

# ====================================================================
#  LOGICA VAD E GESTIONE SEGMENTI
# ====================================================================

triggered = False
num_padding_frames = int(300 / FRAME_DURATION_MS)          # 300 ms di pre‑roll
ring_buffer = collections.deque(maxlen=num_padding_frames)

num_silence_frames = int(SILENCE_TIMEOUT_S * 1000 / FRAME_DURATION_MS)
ring_buffer_silence = collections.deque(maxlen=num_silence_frames)

max_voiced_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_DURATION_MS)
voiced_frames = []

def flush_voiced_frames():
    global voiced_frames
    if not voiced_frames:
        return
    audio_data = b"".join(voiced_frames)
    voiced_frames = []
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        transcribe_queue.put(audio_np, timeout=1.0)
    except queue.Full:
        print("[Attenzione] Coda trascrizione piena, segmento perso.")

# ====================================================================
#  LOOP PRINCIPALE
# ====================================================================

try:
    stream.start_stream()
    while stream.is_active() and not stop_event.is_set():
        try:
            frame = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        is_speech = vad.is_speech(frame, RATE)

        if not triggered:
            ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in ring_buffer if speech)
            if num_voiced > 0.6 * ring_buffer.maxlen:
                triggered = True
                print("\n[Radio -> Trasmissione Iniziata...]")
                for f, _ in ring_buffer:
                    voiced_frames.append(f)
                ring_buffer.clear()
        else:
            voiced_frames.append(frame)
            ring_buffer_silence.append(is_speech)

            num_unvoiced = sum(1 for speech in ring_buffer_silence if not speech)
            end_of_transmission = num_unvoiced == ring_buffer_silence.maxlen
            forced_cutoff = len(voiced_frames) >= max_voiced_frames

            if end_of_transmission or forced_cutoff:
                if forced_cutoff and not end_of_transmission:
                    print("[Radio -> Trasmissione lunga, taglio forzato per elaborazione parziale...]")
                else:
                    print("[Radio -> Fine Trasmissione. Elaborazione testo...]")

                ring_buffer_silence.clear()
                flush_voiced_frames()

                if forced_cutoff and not end_of_transmission:
                    triggered = True
                else:
                    triggered = False

except KeyboardInterrupt:
    print("\nChiusura del programma in corso...")
finally:
    stop_event.set()
    stream.stop_stream()
    stream.close()
    p.terminate()
    transcribe_queue.put(None)
    worker_thread.join(timeout=3.0)
    print("Programma terminato.")