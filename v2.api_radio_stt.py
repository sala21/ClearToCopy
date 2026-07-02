import json
import os
import collections
import queue
import threading
import time
import io
import wave
import base64
import numpy as np
import pyaudio
import webrtcvad
from faster_whisper import WhisperModel
import requests


CONFIG_FILE = "config.json"

def load_config():
    """Carica la configurazione dal file JSON, con valori predefiniti se manca."""
    default_config = {
        "api": {
            "groq": {
                "api_key": "",
                "model": "whisper-large-v3",
                "url": "https://api.groq.com/openai/v1/audio/transcriptions"
            }
        },
        "local": {
            "model": "base",
            "device": "cpu",
            "compute_type": "int8"
        },
        "audio": {
            "rate": 16000,
            "channels": 1,
            "frame_duration_ms": 30
        },
        "vad": {
            "aggressiveness": 2,
            "silence_timeout_s": 1.0,
            "max_utterance_s": 15.0
        },
        "filter": {
            "enabled": True,
            "band_min": 300,
            "band_max": 3400
        }
    }

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # Fusione ricorsiva (sovrascrive le chiavi esistenti)
        for key, value in user_config.items():
            if isinstance(value, dict) and key in default_config:
                default_config[key].update(value)
            else:
                default_config[key] = value
    else:
        print(f"[Config] File {CONFIG_FILE} non trovato. Uso valori predefiniti.")
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        print(f"[Config] Creato file {CONFIG_FILE} di esempio. Inserisci la tua chiave API.")
    
    return default_config

config = load_config()

# Estrai parametri
API_KEY = config["api"]["groq"]["api_key"]
GROQ_MODEL = config["api"]["groq"]["model"]
GROQ_URL = config["api"]["groq"]["url"]

LOCAL_MODEL = config["local"]["model"]
LOCAL_DEVICE = config["local"]["device"]
LOCAL_COMPUTE_TYPE = config["local"]["compute_type"]

RATE = config["audio"]["rate"]
CHANNELS = config["audio"]["channels"]
FRAME_DURATION_MS = config["audio"]["frame_duration_ms"]
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)

VAD_AGGRESSIVENESS = config["vad"]["aggressiveness"]
SILENCE_TIMEOUT_S = config["vad"]["silence_timeout_s"]
MAX_UTTERANCE_S = config["vad"]["max_utterance_s"]

APPLY_FILTER = config["filter"]["enabled"]
FILTRO_BANDA_MIN = config["filter"]["band_min"]
FILTRO_BANDA_MAX = config["filter"]["band_max"]

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