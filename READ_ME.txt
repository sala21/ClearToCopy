-----------------------------
SET-UP AMBIENTE
-----------------------------
1. Crea un nuovo ambiente virtuale:     python -m venv venv

2. Attivalo:    venv\Scripts\activate

3. Installa le dipendenze:      pip install -r requirements.txt


-----------------------------
FLUSSO LOGICO v3 (Solo API, Concorrente)
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
│   • Rileva inizio/fine della voce (nessun log a console)
│   • Quando rileva un segmento completo:
│       • Calcola la durata
│       • Se > min_segment_duration_s (ora letto correttamente da vad.min_segment_duration_s, non più bloccato sul default), lo invia al callback
│
▼ (Callback)
[on_segment_ready()]
│   • Riceve l'array audio (float32 normalizzato)
│   • Lo passa a Transcriber.enqueue()
│
▼
[Transcriber] (transcriber.py)
│   • Accoda il segmento in transcribe_queue (illimitata)
│   • Thread "dispatcher" preleva e smista SENZA bloccarsi:
│
│   ┌───────────────────────────────────────────┐
│   │  DISPATCHER THREAD                         │
│   │  1. Preleva segmento dalla coda            │
│   │  2. Lo sottomette al ThreadPoolExecutor     │
│   │     (max_concurrent_requests worker, def. 3)│
│   └───────────────────────────────────────────┘
│                       │
│                       ▼ (in parallelo, N worker)
│   ┌───────────────────────────────────────────┐
│   │  GROQ WORKER (uno per segmento in volo)     │
│   │  1. Applica filtro passa-banda (opzionale)  │
│   │  2. Chiama API Groq (whisper-large-v3)      │
│   │     timeout configurabile (def. 10s)        │
│   │  3. NESSUN fallback locale: se Groq fallisce│
│   │     o va in timeout, il segmento è perso     │
│   │     (loggato, non ritentato)                │
│   │  4. Anti-loop (lock su last_text condiviso) │
│   │  5. Stampa il risultato                      │
│   └───────────────────────────────────────────┘
│
▼
[OUTPUT] Trascrizione in tempo reale
│   • Più segmenti possono essere trascritti in parallelo
│   • L'ordine di stampa segue l'ordine di completamento
│     della richiesta HTTP, non necessariamente l'ordine
│     cronologico di arrivo del segmento
│   • Log separati da "---"
│
▼
[FINE] Ctrl+C per terminare pulitamente
│   • Stop stream audio
│   • Stop dispatcher thread
│   • executor.shutdown(wait=True): attende che i worker
│     Groq già in corso finiscano prima di uscire
│   • Rilascia risorse PyAudio

DIFFERENZE CHIAVE vs v2:
  • Rimosso completamente il fallback locale (faster-whisper) → solo Groq
  • Da 1 worker thread sequenziale a pool concorrente (ThreadPoolExecutor)
    → i segmenti non si accodano più dietro una chiamata Groq lenta
  • API key non più in config.json in chiaro → letta da GROQ_API_KEY
    (variabile d'ambiente), con priorità sul file se presente
  • Timeout HTTP ridotto da 30s a 10s (configurabile)
  • min_segment_duration_s: bug corretto (prima letto dal punto sbagliato
    del JSON, restava sempre al default 1.2s) + default abbassato a 0.6s
  • Rimossi i print "[Radio -> Trasmissione Iniziata/Fine...]" da vad.py




-----------------------------
FLUSSO LOGICO v2_api_version (con fallback)
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