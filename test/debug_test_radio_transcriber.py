import collections
import queue
import threading
import time
import sys
import numpy as np
import pyaudio
import webrtcvad
from faster_whisper import WhisperModel

# --- CONFIGURAZIONE AUDIO (Rigida per webrtcvad) ---
FORMAT = pyaudio.paInt16       # Audio a 16-bit PCM
CHANNELS = 1                   # Mono
RATE = 16000                   # Frequenza a 16kHz richiesta da Whisper e VAD
FRAME_DURATION_MS = 30         # Durata del singolo frame (10, 20 o 30ms)
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)  # Numero di campioni per frame (480)

# --- CONFIGURAZIONE AI E FILTRI ---
VAD_AGGRESSIVENESS = 2         # Sensibilità del VAD (1=Permissivo, 3=Aggressivo)
SILENCE_TIMEOUT_S = 1.0        # Tempo di silenzio prima di considerare conclusa la trasmissione
MAX_UTTERANCE_S = 15.0         # Taglio forzato: durata massima di una singola trasmissione
LANGUAGE = "en"                # Fissiamo l'inglese aeronautico: evita il language-detection ad ogni segmento
BEAM_SIZE = 1                  # Greedy decoding: molto più veloce su CPU, perdita di accuratezza minima
                                # su frasi brevi/standardizzate come il gergo aeronautico

# Prompt iniziale per condizionare l'IA sul gergo aeronautico ed evitare allucinazioni
INITIAL_PROMPT = "Roger, Wilco, Tower, Approach, Radar, Information, Flight Level, Runway, Cleared, Maintain."

# --- CONFIGURAZIONE DEBUG ---
DEBUG_RMS = True                # Stampa il volume RMS di ogni frame per diagnosticare il livello del segnale
RMS_LOG_EVERY_N_FRAMES = 10     # Throttling: stampa 1 frame ogni N (a 30ms/frame, 10 = ~3 volte al secondo)

print("Caricamento del modello Faster-Whisper su CPU... (Attendi)")
# Modello 'base': miglior compromesso accuratezza/velocità rispetto a 'tiny' per gergo tecnico,
# ancora sostenibile su CPU in int8
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Modello caricato con successo!")

# Inizializzazione del filtro Voice Activity Detection di Google
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

audio_queue = queue.Queue()
transcribe_queue = queue.Queue()
p = pyaudio.PyAudio()


def audio_callback(in_data, frame_count, time_info, status):
    """Callback di PyAudio per catturare i chunk audio in background senza bloccare il programma"""
    audio_queue.put(in_data)
    return (None, pyaudio.paContinue)


def get_rms(frame):
    """
    Calcola il volume RMS (Root Mean Square) di un frame audio PCM a 16-bit.
    Utile per capire se il segnale in ingresso e' abbastanza forte prima
    ancora di guardare cosa decide il VAD. Per riferimento indicativo:
    - silenzio/rumore di fondo leggero: valori sotto ~50-100
    - voce diretta al microfono: spesso sopra 500-1000+
    - segnale debole/degradato (es. altoparlante -> microfono): puo' restare
      sotto la soglia utile anche quando "a orecchio" si sente qualcosa
    """
    audio_np = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return np.sqrt(np.mean(audio_np ** 2))


def transcribe_worker():
    """
    Thread dedicato alla trascrizione. Gira in parallelo alla cattura audio,
    cosi' l'elaborazione di Whisper (anche se lenta) non fa accumulare ritardo
    sui frame audio in arrivo dal microfono/radio.
    """
    while True:
        item = transcribe_queue.get()
        if item is None:  # segnale di chiusura
            break

        audio_np, end_of_speech_time = item

        segments, info = model.transcribe(
            audio_np,
            beam_size=BEAM_SIZE,
            language=LANGUAGE,
            initial_prompt=INITIAL_PROMPT,
        )

        for segment in segments:
            print(f"📄 TRASCRIZIONE: {segment.text}")

        latency = time.time() - end_of_speech_time
        print(f"   [debug] Latenza fine-frase -> trascrizione: {latency:.2f}s")
        print("-" * 40)


# Apertura dello stream della scheda audio
stream = p.open(format=FORMAT,
                 channels=CHANNELS,
                 rate=RATE,
                 input=True,
                 frames_per_buffer=CHUNK,
                 stream_callback=audio_callback)

# Avvio del thread di trascrizione (daemon: si chiude automaticamente con il programma principale)
worker_thread = threading.Thread(target=transcribe_worker, daemon=True)
worker_thread.start()

print("\n=== ASCOLTO ATTIVO ===")
print("Parla nel microfono o attendi il segnale radio...")

triggered = False
frame_counter = 0  # usato solo per il throttling del log RMS

# Buffer circolare per conservare circa 300ms di audio precedente all'attivazione della voce
num_padding_frames = int(300 / FRAME_DURATION_MS)
ring_buffer = collections.deque(maxlen=num_padding_frames)

# Calcolo del numero di frame di silenzio necessari per chiudere la trasmissione
num_silence_frames = int(SILENCE_TIMEOUT_S * 1000 / FRAME_DURATION_MS)
ring_buffer_silence = collections.deque(maxlen=num_silence_frames)

# Numero massimo di frame vocali prima del taglio forzato
max_voiced_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_DURATION_MS)

voiced_frames = []


def flush_voiced_frames():
    """Converte i frame accumulati in un array numpy e li invia al thread di trascrizione,
    insieme al timestamp del momento in cui il parlato è terminato (per misurare la latenza)."""
    global voiced_frames
    if not voiced_frames:
        return
    end_of_speech_time = time.time()
    audio_data = b"".join(voiced_frames)
    voiced_frames = []
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    transcribe_queue.put((audio_np, end_of_speech_time))


try:
    stream.start_stream()
    while stream.is_active():
        # Timeout sulla get(): evita che il loop resti bloccato per sempre
        # se lo stream si ferma mentre siamo in attesa di un frame
        try:
            frame = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # webrtcvad controlla se il frame contiene voce umana
        is_speech = vad.is_speech(frame, RATE)

        if DEBUG_RMS:
            frame_counter += 1
            if frame_counter % RMS_LOG_EVERY_N_FRAMES == 0:
                rms = get_rms(frame)
                print(f"   [debug] RMS: {rms:7.1f}  |  VAD rileva voce: {is_speech}")

        if not triggered:
            ring_buffer.append((frame, is_speech))
            # Se la maggior parte dei frame recenti contiene voce, attiviamo la registrazione
            num_voiced = sum(1 for _, speech in ring_buffer if speech)
            if num_voiced > 0.6 * ring_buffer.maxlen:
                triggered = True
                print("\n[Radio -> Trasmissione Iniziata...]")
                # Recuperiamo l'audio d'inizio conservato nel buffer circolare per non perdere le prime sillabe
                for f, _ in ring_buffer:
                    voiced_frames.append(f)
                ring_buffer.clear()
        else:
            voiced_frames.append(frame)
            ring_buffer_silence.append(is_speech)

            # Se rileva una sequenza continua di silenzio, chiude il blocco audio
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
                    # Restiamo "triggered" per continuare a catturare il resto della trasmissione
                    triggered = True
                else:
                    triggered = False

except KeyboardInterrupt:
    print("\nChiusura del programma in corso...")
finally:
    stream.stop_stream()
    stream.close()
    p.terminate()
    transcribe_queue.put(None)  # sblocca e chiude il thread di trascrizione
    worker_thread.join(timeout=2.0)