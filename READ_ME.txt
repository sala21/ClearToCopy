-----------------------------
SET-UP AMBIENTE
-----------------------------
1. Crea un nuovo ambiente virtuale:     python -m venv venv

2. Attivalo:    venv\Scripts\activate

3. Installa le dipendenze:      pip install -r requirements.txt



-----------------------------
FLUSSO LOGICO v2_api_version (Modulare)
-----------------------------

[Microfono / Radio]
│
▼ (Ogni 30ms)
[AudioCapture] (audio.py)
│   • Riceve i frame da PyAudio via callback
│   • Li mette in una coda (audio_queue)
│
▼ (Loop Principale in main.py)
[main.py]
│   • Preleva frame da audio_queue
│   • Li passa a VADProcessor
│
▼
[VADProcessor] (vad.py)
│   • Processa ogni frame con WebRTC VAD
│   • Buffer circolare per i 300ms di pre‑roll
│   • Rileva inizio/fine della voce
│   • Quando rileva un segmento completo:
│       • Calcola la durata
│       • Se > min_segment_duration_s, lo invia al callback
│
▼ (Callback)
[on_segment_ready()]
│   • Riceve l'array audio (float32 normalizzato)
│   • Lo passa a Transcriber.enqueue()
│
▼
[Transcriber] (transcriber.py)
│   • Accoda il segmento in transcribe_queue
│   • Thread worker dedicato elabora in background:
│
│   ┌─────────────────────────────────┐
│   │  THREAD WORKER                  │
│   │  1. Preleva segmento dalla coda │
│   │  2. Applica filtro (opzionale)  │
│   │  3. Prova API Groq (primaria)   │
│   │  4. Se fallisce → modello locale│
│   │  5. Anti‑loop (evita ripetizioni)│
│   │  6. Stampa il risultato         │
│   └─────────────────────────────────┘
│
▼
[OUTPUT] Trascrizione in tempo reale
│   • Testo formattato (numeri convertiti in cifre)
│   • Log separati da "---"
│
▼
[FINE] Ctrl+C per terminare pulitamente
│   • Stop stream audio
│   • Termina thread worker
│   • Rilascia risorse PyAudio



-----------------------------
FLUSSO LOGICO v1
-----------------------------

[Radio/Microfono]
│
▼ (Ogni 30ms)
[audio_callback] ──> Mette in coda (audio_queue)
│
▼ (Loop Principale)
[Controllo VAD] ──> C'è voce?
│
├──> NO ──> Aspetta e tieni gli ultimi 300ms nel buffer circolare.
│
└──> SÌ ──> Attiva Registrazione (triggered=True)
│
├──> Accumula audio in memoria
│
└──> Rilevato 1 secondo di silenzio?
│
└──> SÌ ──> Unisci l'audio, convertilo in decimali e passalo a Whisper.