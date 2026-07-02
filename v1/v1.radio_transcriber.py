import collections
import queue
import threading
import numpy as np
import pyaudio
import webrtcvad
from faster_whisper import WhisperModel

# --- CONFIGURAZIONE AUDIO (Rigida per webrtcvad) ---
FORMAT = pyaudio.paInt16       # Audio a 16-bit PCM (Qualità audio: 16 bit)
CHANNELS = 1                   # Mono (Le radio sono mono, non stereo)
RATE = 16000                   # Frequenza a 16kHz richiesta da Whisper e VAD (16.000 campionamenti al secondo (Standard per la voce))
FRAME_DURATION_MS = 30         # Durata del singolo frame da analizzare (10, 20 o 30ms)
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)  # Numero di campioni per frame (480)

# --- CONFIGURAZIONE AI E FILTRI ---
VAD_AGGRESSIVENESS = 2         # Sensibilità del VAD (1=Permissivo, 3=Aggressivo)
SILENCE_TIMEOUT_S = 1.0        # Tempo di silenzio prima di considerare conclusa la trasmissione
MAX_UTTERANCE_S = 15.0         # Taglio forzato: durata massima di una singola trasmissione
LANGUAGE = "en"                # Fissiamo l'inglese aeronautico: evita il language-detection ad ogni segmento
BEAM_SIZE = 1                  # Greedy decoding: molto più veloce su CPU, perdita di accuratezza minima su frasi brevi/standardizzate come il gergo aeronautico

# Prompt iniziale per condizionare l'IA sul gergo aeronautico ed evitare allucinazioni
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

print("Caricamento del modello Faster-Whisper su CPU... (Attendi)")
# Modello 'base': miglior compromesso accuratezza/velocità
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Modello caricato con successo!")

# Inizializzazione del filtro Voice Activity Detection di Google
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

audio_queue = queue.Queue()         # Coda 1: Contiene i micro-frammenti grezzi che arrivano dal microfono
transcribe_queue = queue.Queue()    # Coda 2: Contiene l'intera frase registrata e pronta per l'IA
p = pyaudio.PyAudio()


def audio_callback(in_data, frame_count, time_info, status):
    """Scatta automaticamente ogni 30ms. Prende l'audio dalla radio e lo butta dentro audio_queue"""
    audio_queue.put(in_data)
    return (None, pyaudio.paContinue)


def transcribe_worker():
    """
    Thread dedicato alla trascrizione. Gira in parallelo alla cattura audio, cosi' l'elaborazione di Whisper (anche se lenta) non fa accumulare ritardo sui frame audio in arrivo dal microfono/radio.
    Ciclo infinito che dorme finché la transcribe_queue è vuota. 
    Appena gli arriva un blocco audio completo:
        -chiama Whisper (model.transcribe), 
        -stampa il testo a schermo 
        -torna a dormire in attesa del prossimo audio. 
    """
    while True:
        audio_np = transcribe_queue.get()
        if audio_np is None:  # segnale di chiusura
            break

        segments, info = model.transcribe(
            audio_np,
            beam_size=BEAM_SIZE,
            language=LANGUAGE,
            initial_prompt=INITIAL_PROMPT,
        )

        for segment in segments:
            print(f"{segment.text}")

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

triggered = False
# Buffer circolare per conservare circa 300ms di audio precedente all'attivazione della voce (così da non perdere il segnale ricevuto durante l'esecuzione del codice di funzionamento)
num_padding_frames = int(300 / FRAME_DURATION_MS)
ring_buffer = collections.deque(maxlen=num_padding_frames)

# Calcolo del numero di frame di silenzio necessari per chiudere la trasmissione
num_silence_frames = int(SILENCE_TIMEOUT_S * 1000 / FRAME_DURATION_MS)
ring_buffer_silence = collections.deque(maxlen=num_silence_frames)

# Numero massimo di frame vocali prima del taglio forzato
"""Taglio forzato: Se la frase supera i 15 secondi (MAX_UTTERANCE_S), il programma taglia l'audio per non sovraccaricare la memoria e manda la prima parte all'IA, continuando comunque a registrare il resto."""
max_voiced_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_DURATION_MS)

voiced_frames = []


def flush_voiced_frames():
    """Converte i frame accumulati in un array numpy e li invia al thread di trascrizione."""
    global voiced_frames
    if not voiced_frames:
        return
    
    audio_data = b"".join(voiced_frames)  # Unisce tutti i pezzettini da 30ms in un unico grande file audio in memoria
    voiced_frames = []                    # Svuota la lista per essere pronti alla prossima chiamata
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0 #La scheda audio registra i suoni in formato Int16 (numeri interi che vanno da -32768 a +32767). I modelli di Intelligenza Artificiale come Whisper, invece, vogliono i dati in formato Float32
    transcribe_queue.put(audio_np)


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
