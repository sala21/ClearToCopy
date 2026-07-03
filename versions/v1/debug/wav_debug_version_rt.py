import collections
import queue
import threading
import time
import sys
import os
import wave
import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

# --- CONFIGURAZIONE AUDIO (Rigida per webrtcvad) ---
FORMAT_BYTES_PER_SAMPLE = 2    # Corrisponde a pyaudio.paInt16 (16-bit PCM)
CHANNELS = 1                   # Mono
RATE = 16000                   # Frequenza a 16kHz richiesta da Whisper e VAD
FRAME_DURATION_MS = 30         # Durata del singolo frame (10, 20 o 30ms)
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)  # Numero di campioni per frame (480)

# --- CONFIGURAZIONE FILE INPUT ---
WAV_FILE_PATH = "test.wav"  # <--- INSERISCI QUI IL NOME O IL PERCORSO DEL TUO FILE .WAV

# --- CONFIGURAZIONE AI E FILTRI ---
VAD_AGGRESSIVENESS = 3         # Sensibilità del VAD (1=Permissivo, 3=Aggressivo)
SILENCE_TIMEOUT_S = 0.5       # Tempo di silenzio prima di considerare conclusa la trasmissione
MAX_UTTERANCE_S = 15.0         # Taglio forzato: durata massima di una singola trasmissione
LANGUAGE = "en"                # Fissiamo l'inglese aeronautico
BEAM_SIZE = 1                  # Greedy decoding per massima velocità su CPU

# Prompt iniziale per condizionare l'IA sul gergo aeronautico
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

# --- CONFIGURAZIONE DEBUG ---
DEBUG_RMS = True                # Stampa il volume RMS di ogni frame
RMS_LOG_EVERY_N_FRAMES = 10     # Throttling dei log RMS

print("Caricamento del modello Faster-Whisper su CPU... (Attendi)")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("Modello caricato con successo!")

# Inizializzazione del filtro Voice Activity Detection di Google
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

transcribe_queue = queue.Queue()


def get_rms(frame):
    """Calcola il volume RMS di un frame audio PCM a 16-bit."""
    audio_np = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return np.sqrt(np.mean(audio_np ** 2))


def transcribe_worker():
    """Thread dedicato alla trascrizione asincrona."""
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
            print(f"{segment.text}")

        latency = time.time() - end_of_speech_time
        print(f"   [debug] Latenza fine-frase -> trascrizione: {latency:.2f}s")
        print("-" * 40)


# Avvio del thread di trascrizione
worker_thread = threading.Thread(target=transcribe_worker, daemon=True)
worker_thread.start()

# --- VERIFICA E APERTURA DEL FILE WAV ---
if not os.path.exists(WAV_FILE_PATH):
    print(f"❌ Errore: Il file '{WAV_FILE_PATH}' non esiste. Verifica il percorso.")
    sys.exit(1)

try:
    wf = wave.open(WAV_FILE_PATH, 'rb')
except Exception as e:
    print(f"❌ Errore nell'apertura del file WAV: {e}")
    sys.exit(1)

# Controllo rigidità parametri richiesti dal VAD
if wf.getnchannels() != CHANNELS or wf.getsampwidth() != FORMAT_BYTES_PER_SAMPLE or wf.getframerate() != RATE:
    print("\n❌ ERRORE: Il file WAV non rispetta i parametri rigidi richiesti da webrtcvad.")
    print(f"   Richiesto:  {RATE}Hz, {CHANNELS} Canale (Mono), 16-bit PCM (sampwidth=2)")
    print(f"   Rilevato:   {wf.getframerate()}Hz, {wf.getnchannels()} Canali, {wf.getsampwidth()*8}-bit (sampwidth={wf.getsampwidth()})")
    print("\n💡 Suggerimento: Puoi convertirlo facilmente usando ffmpeg dal terminale:")
    print(f"   ffmpeg -i {WAV_FILE_PATH} -ar 16000 -ac 1 -c:a pcm_s16le file_convertito.wav")
    wf.close()
    sys.exit(1)

print(f"\n=== ELABORAZIONE FILE FILE WAV: {WAV_FILE_PATH} ===")
print("Lettura e simulazione dello streaming in corso...")

triggered = False
frame_counter = 0

# Buffer circolare per catturare l'audio pre-attivazione (300ms)
num_padding_frames = int(300 / FRAME_DURATION_MS)
ring_buffer = collections.deque(maxlen=num_padding_frames)

# Buffer per rilevamento silenzio di fine trasmissione
num_silence_frames = int(SILENCE_TIMEOUT_S * 1000 / FRAME_DURATION_MS)
ring_buffer_silence = collections.deque(maxlen=num_silence_frames)

# Taglio forzato per trasmissioni lunghe
max_voiced_frames = int(MAX_UTTERANCE_S * 1000 / FRAME_DURATION_MS)

voiced_frames = []


def flush_voiced_frames():
    global voiced_frames
    if not voiced_frames:
        return
    end_of_speech_time = time.time()
    audio_data = b"".join(voiced_frames)
    voiced_frames = []
    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    transcribe_queue.put((audio_np, end_of_speech_time))


try:
    # Leggiamo il file a blocchi grandi quanto 1 CHUNK (480 campioni = 960 byte)
    while True:
        frame = wf.readframes(CHUNK)
        if not frame or len(frame) < CHUNK * FORMAT_BYTES_PER_SAMPLE:
            # Fine del file WAV
            break

        # webrtcvad controlla se il frame contiene voce umana
        is_speech = vad.is_speech(frame, RATE)

        if DEBUG_RMS:
            frame_counter += 1
            if frame_counter % RMS_LOG_EVERY_N_FRAMES == 0:
                rms = get_rms(frame)
                print(f"   [debug] RMS: {rms:7.1f}  |  VAD rileva voce: {is_speech}")

        if not triggered:
            ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in ring_buffer if speech)
            if num_voiced > 0.6 * ring_buffer.maxlen:
                triggered = True
                print("\n[Radio -> Trasmissione Iniziata (Rilevata nel file)...]")
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

        # OPZIONALE: Rallenta il ciclo per emulare la riproduzione in tempo reale.
        # Senza questa riga, il file viene letto alla massima velocità della CPU.
        # time.sleep(FRAME_DURATION_MS / 1000.0)

    # Se il file finisce mentre c'è ancora dell'audio accumulato nell'ultimo segmento, svuotalo
    if triggered and voiced_frames:
        print("[Radio -> Fine File Raggiunta. Elaborazione ultimo segmento rimasto...]")
        flush_voiced_frames()

    print("\n=== FINE FILE AUDIO ===")
    print("In attesa che Whisper completi le ultime trascrizioni in coda...")
    
    # Attendiamo che la coda di trascrizione si svuoti prima di chiudere il programma
    while not transcribe_queue.empty():
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nInterruzione da parte dell'utente...")
finally:
    wf.close()
    transcribe_queue.put(None)  # Ferma il thread di trascrizione
    worker_thread.join(timeout=2.0)
    print("Programma terminato correttamente.")