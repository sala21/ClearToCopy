-----------------------------
SET-UP AMBIENTE
-----------------------------
1. Crea un nuovo ambiente virtuale:     python -m venv venv
2. Attivalo:    venv\Scripts\activate
3. Installa le dipendenze:      pip install -r requirements.txt


-----------------------------
FLUSSO LOGICO v3 (Solo API, Concorrente + GUI)
-----------------------------

[Microfono / Radio]
│
▼ (Ogni 30ms)
[AudioCapture] (audio.py)
│   • Riceve i frame da PyAudio via callback
│   • Li mette in una coda (audio_queue)
│
▼ (Loop Principale in main.py o avviato da GUI)
[main.py / GUI Thread]
│   • Preleva frame da audio_queue
│   • Li passa a VADProcessor
│   • Eventi -> EventBus -> GUI
│
▼
[VADProcessor] (vad.py)
│   • Processa ogni frame con WebRTC VAD (aggressiveness configurabile)
│   • Buffer circolare per i 300ms di pre‑roll (contatore O(1))
│   • Rileva inizio/fine della voce (nessun log a console)
│   • Quando rileva un segmento:
│       • Calcola la durata
│       • Se > `min_segment_duration_s` (letto da config.json, default 0.6s)
│       • Normalizza il picco (AGC)
│       • Lo invia al callback
│
▼ (Callback)
[on_segment_ready()]
│   • Riceve l'array audio (int16)
│   • Lo passa a Transcriber.enqueue()
│
▼
[Transcriber] (transcriber.py)
│   • Accoda il segmento in transcribe_queue (illimitata)
│   • Thread "dispatcher" preleva e smista SENZA bloccarsi:
│
│   ┌────────────────────────────────────────────┐
│   │  DISPATCHER THREAD                          │
│   │  1. Preleva segmento dalla coda             │
│   │  2. Lo sottomette al ThreadPoolExecutor     │
│   │     (max_concurrent_requests da config, def.5)│
│   └────────────────────────────────────────────┘
│                       │
│                       ▼ (in parallelo, N worker)
│   ┌────────────────────────────────────────────┐
│   │  GROQ WORKER (uno per segmento in volo)     │
│   │  1. Applica filtro passa-banda (opzionale)  │
│   │  2. Chiamata API Groq (whisper-large-v3)    │
│   │     • timeout configurabile (def. 10s)      │
│   │     • formato FLAC (se soundfile installato)│
│   │     • NESSUN fallback locale                │
│   │  3. Anti-loop (lock su last_text condiviso) │
│   │  4. Invia risultato al printer thread       │
│   └────────────────────────────────────────────┘
│                       │
│                       ▼
│   ┌────────────────────────────────────────────┐
│   │  PRINTER THREAD (riordino cronologico)      │
│   │  • Riceve i risultati da tutti i worker     │
│   │  • Li riordina tramite min-heap             │
│   │  • Stampa in ordine di sequenza originale   │
│   │  • Invia anche all'EventBus per la GUI      │
│   └────────────────────────────────────────────┘
│
▼
[OUTPUT]
│   • Console: trascrizione in tempo reale (ordinata)
│   • GUI: area di testo con timestamp
│   • EventBus: metriche, RMS, stato
│
▼
[GESTIONE FINE SESSIONE]
│   • [STOP] in GUI:
│       • Ferma il VAD e il microfono
│       • Chiede se salvare la trascrizione (da buffer)
│       • Se SÌ → salva in `transcript_YYYYMMDD_HHMMSS.txt`
│       • Se NO → svuota il buffer
│       • Gestisce i log di debug (se attivi)
│       • Ferma i thread in modo pulito
│
▼
[DEBUG]
│   • [DEBUG ON]:
│       • Il logger passa a livello DEBUG
│       • I messaggi DEBUG sono scritti in `transcriber.log`
│       • Si apre una finestra di log in tempo reale
│       • Allo STOP (o alla disattivazione), chiede se salvare i log
│       • Se SÌ → rinomina `transcriber.log` in `debug_YYYYMMDD_HHMMSS.log`
│       • Se NO → cancella `transcriber.log`
│   • [DEBUG OFF]:
│       • Il logger torna a livello INFO
│       • La finestra di debug si chiude


DIFFERENZE CHIAVE vs v2:
  • Rimosso completamente il fallback locale (faster-whisper) → solo Groq
  • Da 1 worker thread sequenziale a pool concorrente (ThreadPoolExecutor)
  • API key: prima da config.json, ora da variabile d'ambiente GROQ_API_KEY (con fallback a config.json)
  • Timeout HTTP ridotto da 30s a 10s (configurabile)
  • min_segment_duration_s: ora letto correttamente da config.json (default 0.6s)
  • Filtro passa-banda: pre-calcolato in __init__ (non più ricalcolato per ogni segmento)
  • Pipeline audio: mantiene il formato int16 il più a lungo possibile (evita conversioni inutili)
  • VAD: contatore scorrevole O(1) invece di O(k) per frame
  • Normalizzazione del picco (AGC) nel VAD per alzare il volume di segnali deboli
  • Aggiunta interfaccia GUI con controlli, metriche, VU meter, debug e salvataggio
  • Logging strutturato con buffer e gestione su richiesta
  • Modalità "radio" (bypass VAD) per test su file o segnali particolari