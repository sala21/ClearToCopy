# Manuale Tecnico — ATC Radio Transcriber v3 (`v3_only_api`)

**Versione documento:** 1.0
**Versione codebase di riferimento:** v3_only_api (solo backend Groq API, GUI inclusa)

---

## Indice

1. [Panoramica generale](#1-panoramica-generale)
2. [Architettura del sistema](#2-architettura-del-sistema)
3. [Requisiti e installazione](#3-requisiti-e-installazione)
4. [Configurazione (`config.json`)](#4-configurazione-configjson)
5. [Moduli del codice](#5-moduli-del-codice)
6. [Modalità operative](#6-modalità-operative)
7. [Pipeline di trascrizione (Groq)](#7-pipeline-di-trascrizione-groq)
8. [Interfaccia grafica (GUI)](#8-interfaccia-grafica-gui)
   8.1 [Struttura visuale](#81-struttura-visuale)
   8.2 [Esecuzione della pipeline](#82-esecuzione-della-pipeline)
   8.3 [Eventi gestiti dalla GUI](#83-eventi-gestiti-dalla-gui)
   8.4 [Salvataggio trascrizioni](#84-salvataggio-trascrizioni)
   8.5 [Debug toggle](#85-debug-toggle)
   8.6 [Finestra di configurazione (ConfigWindow)](#86-finestra-di-configurazione-configwindow)
9. [Sistema di logging e debug](#9-sistema-di-logging-e-debug)
10. [Gestione file e dati sensibili](#10-gestione-file-e-dati-sensibili)
11. [Problemi noti risolti (changelog tecnico)](#11-problemi-noti-risolti-changelog-tecnico)
12. [Troubleshooting](#12-troubleshooting)
13. [Possibili sviluppi futuri](#13-possibili-sviluppi-futuri)

---

## 1. Panoramica generale

**ATC Radio Transcriber** è un'applicazione Python per la trascrizione in tempo reale di comunicazioni radio in banda aeronautica (ATC — Air Traffic Control). Cattura audio da un dispositivo di input (microfono o linea audio collegata a una radio/scanner), lo segmenta, lo pre-elabora e lo invia all'API di trascrizione di **Groq** (modelli Whisper), restituendo il testo trascritto in tempo reale sia su console che su un'interfaccia grafica dedicata.

La versione corrente (**v3**) rappresenta un'evoluzione rispetto alle versioni precedenti (v1, v2):

- **Nessuna inferenza locale**: le versioni precedenti usavano `faster-whisper` in locale come fallback; v3 usa **esclusivamente l'API Groq**, eliminando la complessità e il carico computazionale locale.
- **Elaborazione concorrente**: le richieste all'API sono gestite tramite un pool di thread (`ThreadPoolExecutor`), permettendo più chiamate Groq in parallelo invece di una coda sequenziale.
- **GUI dedicata**: interfaccia grafica in `tkinter` con tema scuro ("AeroVoice"), VU meter, metriche in tempo reale, console di debug e salvataggio automatico/manuale delle trascrizioni.
- **Doppia modalità di segmentazione**: VAD classico (rilevamento vocale) oppure modalità "radio" a finestra temporale fissa con taglio intelligente sui punti di minima energia.

### Casi d'uso tipici

- Monitoraggio e trascrizione di frequenze ATC (torre, avvicinamento, ground) collegando l'uscita audio di uno scanner/ricevitore radio all'ingresso microfonico del PC.
- Test e analisi della qualità di trascrizione su registrazioni riprodotte via altoparlante (con perdita di qualità nota, vedi §12).

---

## 2. Architettura del sistema

```
[Microfono / Radio]
        │  (audio PCM in ingresso)
        ▼
┌─────────────────────┐
│   AudioCapture       │  audio.py
│   (callback PyAudio) │
└─────────┬────────────┘
          │ frame da 30ms → audio_queue (thread-safe)
          ▼
┌─────────────────────────────────────────────┐
│              run_pipeline()                  │  main.py
│  Legge i frame dalla coda e li instrada       │
│  verso una delle due modalità operative:      │
└───────────┬───────────────────┬──────────────┘
            │                   │
   modalità VAD           modalità RADIO
            │                   │
            ▼                   ▼
   ┌────────────────┐   ┌────────────────────┐
   │ VADProcessor    │   │ _run_radio_mode()   │
   │ (vad.py)        │   │ (main.py)           │
   │ Rileva inizio/  │   │ Segmentazione a      │
   │ fine parlato    │   │ finestra fissa con    │
   │                 │   │ taglio su minima       │
   │                 │   │ energia + gate RMS     │
   └────────┬────────┘   └──────────┬─────────┘
            │  segmento audio (int16)          │
            └───────────────┬───────────────────┘
                             ▼
                  ┌─────────────────────┐
                  │   Transcriber        │  transcriber.py
                  │   .enqueue(audio)     │
                  └──────────┬───────────┘
                             ▼
        ┌───────────────────────────────────────────┐
        │  Dispatcher thread                          │
        │  preleva dalla coda e sottomette al pool     │
        └───────────────────┬─────────────────────────┘
                             ▼
        ┌───────────────────────────────────────────┐
        │  N Worker Groq (ThreadPoolExecutor)          │
        │  1. Filtro passa-banda (opzionale)           │
        │  2. Encoding FLAC/WAV                        │
        │  3. Chiamata HTTP API Groq (whisper)         │
        │  4. Anti-loop (dedup testo ripetuto breve)   │
        └───────────────────┬─────────────────────────┘
                             ▼
        ┌───────────────────────────────────────────┐
        │  Printer thread (min-heap di riordino)       │
        │  Ristabilisce l'ordine cronologico dei        │
        │  segmenti anche se le risposte Groq arrivano  │
        │  fuori sequenza (concorrenza)                 │
        └───────────────────┬─────────────────────────┘
                             ▼
              ┌─────────────────────────────┐
              │  Output                       │
              │  • Console (stdout)            │
              │  • EventBus → GUI              │
              └─────────────────────────────┘
```

### Componenti trasversali

- **`EventBus`** (`events.py`): coda thread-safe che disaccoppia la pipeline (thread di background) dalla GUI (thread principale Tkinter). La pipeline non conosce la GUI; la GUI fa polling periodico (`poll_all()`).
- **`config.py`**: caricamento centralizzato di `config.json`, con supporto a `GROQ_API_KEY` da variabile d'ambiente.
- **`logger.py`**: logger unico condiviso (`AudioTranscriber`) con handler separati per console e file.

---

## 3. Requisiti e installazione

### Requisiti di sistema

- Python 3.x (ambiente testato su Windows, vedi `pywin32-ctypes`, `pefile` in `requirements.txt` per il build PyInstaller)
- Un dispositivo di input audio funzionante (microfono o cavo linea da ricevitore radio)
- Connessione internet (per le chiamate API a Groq)
- Una **API key Groq** valida

### Setup ambiente

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
```

### Dipendenze principali (`requirements.txt`)

| Pacchetto | Ruolo |
|---|---|
| `PyAudio` | Cattura audio dal microfono/linea |
| `webrtcvad` | Voice Activity Detection (modalità VAD) |
| `numpy` | Elaborazione array audio |
| `scipy` | Filtro passa-banda FIR |
| `requests` + `urllib3` | Chiamate HTTP verso l'API Groq, con connection pooling |
| `soundfile` *(opzionale ma consigliato)* | Encoding FLAC (riduce il payload upload rispetto a WAV) |
| `PyYAML` | Utilizzo generico di configurazione (se presente) |
| `pyinstaller` | Build eseguibile standalone |
| `setuptools==81.0.0` | **Pinning necessario**: versioni ≥82 rimuovono `pkg_resources`, da cui dipende `webrtcvad`, causando un errore di import su Windows |

### Configurazione API key

L'API key Groq può essere fornita in due modi (in ordine di priorità):

1. **Variabile d'ambiente** `GROQ_API_KEY` (metodo consigliato, non finisce mai su disco/versionamento)
2. Campo `api.groq.api_key` dentro `config.json` (sconsigliato se il repository è condiviso o pubblico)

Se nessuna delle due è presente, l'applicazione termina con errore in avvio (`config.py` → `sys.exit(1)`).

### Avvio

```bash
# Modalità CLI (console)
python main.py

# Modalità GUI
python gui_main.py
```

---

## 4. Configurazione (`config.json`)

Il file `config.json` centralizza tutti i parametri. Essendo JSON puro (senza commenti), la documentazione dei singoli campi è mantenuta a parte in `config_exp.txt`, che riporta la stessa struttura con commenti `//` inline per ogni parametro.

### 4.1 Sezione `api.groq`

| Campo | Default | Descrizione |
|---|---|---|
| `model` | `whisper-large-v3-turbo` | Modello Groq. `-turbo` = più rapido; `whisper-large-v3` = più accurato ma più lento |
| `url` | endpoint Groq trascrizioni | Endpoint HTTP dell'API |
| `timeout_s` | `10` | Timeout per singola richiesta; oltre questo tempo il segmento è considerato perso |
| `max_concurrent_requests` | `5` | Dimensione del `ThreadPoolExecutor` e del pool di connessioni HTTP |
| `reorder_timeout_s` | `3.0` | Tempo massimo di attesa nel buffer di riordino prima di stampare comunque un segmento fuori sequenza |
| `use_flac` | `true` | Se `true`, codifica l'audio in FLAC (payload più piccolo, richiede `soundfile`) |

### 4.2 Sezione `audio`

| Campo | Default | Descrizione |
|---|---|---|
| `rate` | `16000` | Frequenza di campionamento in Hz (16 kHz standard per Whisper) |
| `channels` | `1` | Canali audio (mono, richiesto da Whisper) |
| `frame_duration_ms` | `30` | Durata di ogni frame catturato (granularità VAD/cattura) |

### 4.3 Sezione `vad` (usata solo se `radio.bypass_vad = false`)

| Campo | Default | Descrizione |
|---|---|---|
| `aggressiveness` | `1` | Sensibilità VAD webrtcvad, 0 (permissivo) → 3 (aggressivo) |
| `silence_timeout_s` | `1.0` | Silenzio continuo necessario per chiudere un segmento |
| `max_utterance_s` | `15.0` | Durata massima di un segmento prima del taglio forzato |
| `min_segment_duration_s` | `0.6` | Durata minima sotto la quale il segmento viene scartato (probabile rumore) |
| `activation_ratio` | `0.4` | Frazione minima di frame vocali nella finestra di preroll (300ms) per attivare un segmento |

### 4.4 Sezione `filter`

| Campo | Default | Descrizione |
|---|---|---|
| `enabled` | `true` | Attiva il filtro passa-banda centralizzato in `transcriber.py` |
| `band_min` | `300` | Frequenza minima lasciata passare (Hz) |
| `band_max` | `3400` | Frequenza massima lasciata passare (Hz) — range tipico voce radio/telefonica |

> **Nota architetturale importante**: il filtro passa-banda è applicato **una sola volta**, centralmente, in `Transcriber._process_segment()`. In precedenza esisteva un secondo filtro anche in `preprocess_radio_audio()` (main.py): la doppia applicazione in cascata restringeva la banda oltre il previsto e introduceva distorsione di fase non necessaria. È stato consolidato in un unico punto (vedi §11).

### 4.5 Sezione `debug`

| Campo | Default | Descrizione |
|---|---|---|
| `enabled` | `false` | Se `true`, la console mostra anche i log di livello DEBUG |
| `log_to_file` | `true` | Se `true`, il file `transcriber.log` registra **sempre** tutto, indipendentemente dalla console |
| `console_level` | `INFO` | Livello minimo mostrato a console quando `enabled = false` |

### 4.6 Sezione `radio`

| Campo | Default | Descrizione |
|---|---|---|
| `enabled` | `true` | Attiva la modalità radio (necessaria insieme a `bypass_vad`) |
| `bypass_vad` | `false` | Se `true`, salta il VAD e usa segmentazione a finestra quasi fissa (`_run_radio_mode`) |
| `segment_duration_s` | `3.0` | Durata target di ogni segmento prima della ricerca del punto di taglio ottimale |
| `overlap_s` | `0.3` | Secondi di coda ripetuti come contesto all'inizio del segmento successivo |
| `silence_gate_enabled` | `true` | Se `true`, scarta segmenti sotto la soglia RMS (evita chiamate sprecate e allucinazioni Whisper su silenzio) |
| `silence_rms_threshold` | `50` | Soglia RMS sotto la quale un segmento è considerato silenzio. **Va calibrata sui livelli audio reali del proprio setup** (vedi §11) |
| `boundary_search_s` | `0.4` | Finestra di ricerca (secondi, a ritroso dal bordo) del punto di minima energia per lo spostamento del taglio |
| `boundary_analysis_ms` | `20` | Dimensione delle sotto-finestre di analisi energia durante la ricerca del punto di taglio |

---

## 5. Moduli del codice

### `config.py`
Carica `config.json` da `BASE_DIR` (gestisce sia esecuzione da sorgente che da eseguibile PyInstaller `frozen`). Inietta `GROQ_API_KEY` da variabile d'ambiente se presente, sovrascrivendo eventuale chiave nel file. Termina il programma se manca sia la chiave che il file di config.

### `logger.py`
Configura un logger singolo (`AudioTranscriber`) condiviso da tutti i moduli, con:
- **Handler console**: livello controllato da `debug.console_level` / `debug.enabled`
- **Handler file** (`transcriber.log`, modalità `'w'`, sovrascritto a ogni avvio): registra sempre tutto a livello DEBUG, se `debug.log_to_file = true`
- Funzioni di utilità `archive_log_file()` (rinomina con timestamp) e `clear_log_file()` (svuota il contenuto)

> **Bug noto**: `archive_log_file()` usa `datetime.now()` ma il modulo `datetime` **non è importato** in `logger.py`. Se invocata, questa funzione solleverà `NameError`. Va aggiunto `from datetime import datetime` in testa al file.

### `audio.py` — `AudioCapture`
Wrapper su PyAudio in modalità callback (non bloccante):
- Apre uno stream `paInt16`, mono, con `frames_per_buffer = chunk`
- Il callback (`_callback`) inserisce ogni frame in una `queue.Queue` con dimensione massima (`max_queue_size=200`); se piena, il frame viene silenziosamente scartato (evita blocchi del thread audio in tempo reale)
- `get_frame(timeout)` preleva un frame dalla coda con timeout, restituendo `None` se vuota

### `vad.py` — `VADProcessor`
Implementa la segmentazione basata su Voice Activity Detection di `webrtcvad`:
- **Finestra di preroll** (300ms) gestita con **contatore scorrevole O(1)** (non ricalcola la somma ogni frame, ma aggiorna incrementalmente aggiungendo/rimuovendo un frame alla volta) — attiva il segmento quando la frazione di frame vocali supera `activation_ratio`
- **Buffer vocale pre-allocato** (`numpy.empty`) dimensionato su `max_utterance_s`, scritto per slicing (no `np.append` ripetuto)
- **Finestra di silenzio** anch'essa con contatore O(1): chiude il segmento quando tutta la finestra è silenziosa (`silence_timeout_s`) oppure quando si raggiunge `max_utterance_s` (taglio forzato)
- **AGC (Automatic Gain Control)**: normalizza il picco del segmento a 0.9 del fondo scala prima di passarlo al callback
- Segmenti sotto `min_segment_duration_s` vengono scartati con un warning di log

### `transcriber.py` — `Transcriber`
Il cuore della pipeline di trascrizione. Vedi dettaglio in §7.

### `events.py` — `EventBus`
Coda thread-safe (`queue.Queue`) a basso overhead:
- `emit(kind, **data)`: chiamata da qualunque thread della pipeline (equivalente a un log strutturato)
- `poll_all()`: chiamata **solo dal thread principale Tkinter** (tipicamente ogni 100ms via `root.after()`), svuota la coda e restituisce la lista di eventi
- Se `event_bus = None` ovunque, l'overhead è nullo — comportamento identico alla modalità CLI pura

### `utils.py`
Funzioni di conversione audio:
- `_ensure_int16(audio)`: converte float32/float64 in int16 **con clip preventivo a [-1, 1]**. Fondamentale perché un filtro FIR può generare overshoot anche su segnale già normalizzato (ripple del filtro); senza clip, la conversione diretta in int16 causa *wraparound* (es. 1.05 → interpretato come valore fortemente negativo), producendo click/scoppi udibili.
- `audio_to_wav_bytes()`: converte in WAV in memoria (`io.BytesIO`)
- `audio_to_flac_bytes()`: converte in FLAC in memoria, richiede `soundfile` (fallisce con `RuntimeError` esplicito se assente)

### `main.py`
Entry point della pipeline. Contiene:
- `preprocess_radio_audio()`: normalizzazione di picco (AGC) + limitatore soft sui picchi (vedi sotto) + normalizzazione finale. **Non applica più il filtro passa-banda** (spostato centralmente in `transcriber.py`).
- `_soft_limiter()`: limitatore "soft-knee" reale — comprime gradualmente l'eccesso sopra una soglia (`threshold=0.3`) con un rapporto configurabile (`ratio=0.5`), invece di un hard-clip che introdurrebbe distorsione armonica udibile su ogni campione oltre soglia.
- `_find_best_cut_point()`: cerca il punto di minima energia RMS in una finestra di ricerca prima del taglio "a tempo fisso", per evitare tagli a metà parola (vedi §6.2).
- `_run_radio_mode()`: loop della modalità radio (bypass VAD).
- `_run_vad_mode()`: loop della modalità VAD classica.
- `run_pipeline(config, event_bus, stop_event)`: funzione condivisa da CLI (`main()`) e GUI (`gui_main.py`), sceglie la modalità in base a `config["radio"]`.

### `gui_main.py`
Interfaccia grafica Tkinter. Vedi dettaglio in §8.

---

## 6. Modalità operative

La scelta tra le due modalità è determinata da `config.json → radio`:

| `radio.enabled` | `radio.bypass_vad` | Modalità attiva |
|---|---|---|
| `false` | — | VAD classico |
| `true` | `false` | VAD classico |
| `true` | `true` | Radio (bypass VAD) |

### 6.1 Modalità VAD classico (`_run_vad_mode`)

Segmenta l'audio in base al **parlato effettivo**, rilevato da `webrtcvad`. Adatta a comunicazioni con pause naturali ben distinte (tipico traffico ATC con transazioni brevi separate da silenzio). Ogni segmento rilevato viene inviato al `Transcriber` tramite callback non appena il VAD rileva la fine della trasmissione o un taglio forzato per durata massima.

### 6.2 Modalità Radio / bypass VAD (`_run_radio_mode`)

Pensata per flussi radio continui (es. frequenze molto trafficate, o dove il VAD fatica a distinguere bene inizio/fine per via di rumore di fondo, squelch, ecc.). Caratteristiche:

1. **Buffer pre-allocato** (`np.empty`), scrittura per slicing — evita ricopie ripetute che si avrebbero con `np.append` ad ogni frame da 30ms.
2. **Segmentazione a durata quasi fissa** (`segment_duration_s`, default 3s), ma il punto di taglio esatto **non è rigido**: `_find_best_cut_point()` cerca, negli ultimi `boundary_search_s` secondi (default 0.4s) prima del bordo, la sotto-finestra (`boundary_analysis_ms`, default 20ms) con energia RMS minima, e sposta lì il taglio. Questo riduce la probabilità di tagliare esattamente a metà di una parola.
   - Il segmento non viene mai accorciato sotto il 60% della durata target (`min_cut_samples`), per evitare segmenti troppo brevi quando il parlato copre l'intera finestra di ricerca senza pause rilevabili.
3. **Gate energetico (silence gate)**: se `silence_gate_enabled = true`, ogni segmento con RMS sotto `silence_rms_threshold` viene scartato **prima** di essere inviato a Groq. Questo evita sia chiamate API sprecate su "dead air", sia le "allucinazioni" tipiche di Whisper quando riceve solo rumore/silenzio (testo plausibile ma inventato).
4. **Overlap tra segmenti** (`overlap_s`): gli ultimi N secondi di un segmento vengono ripetuti come contesto iniziale del segmento successivo, per ridurre ulteriormente il rischio di perdita di parole al confine. **Effetto collaterale noto**: può causare piccole ripetizioni di parole nella trascrizione finale ai bordi dei segmenti; una cucitura testuale (text stitching) più sofisticata risolverebbe il problema ma non è implementata.

---

## 7. Pipeline di trascrizione (Groq)

`Transcriber` (in `transcriber.py`) gestisce l'intero ciclo di vita di ogni segmento audio dopo l'`enqueue()`:

### 7.1 Threading interno

| Thread | Ruolo |
|---|---|
| **Dispatcher** (`_dispatch_loop`) | Preleva dalla coda `transcribe_queue` (illimitata) e sottomette al `ThreadPoolExecutor` senza bloccarsi |
| **N Worker Groq** (pool, `max_concurrent_requests`) | Eseguono `_process_segment()`: filtro → encoding → chiamata HTTP → anti-loop |
| **Printer** (`_printer_loop`) | Riordina i risultati con un min-heap basato sul numero di sequenza (`seq`), garantendo stampa in ordine cronologico anche se le risposte HTTP arrivano fuori ordine per via della concorrenza |
| **Metrics** (`_metrics_loop`) | Logga/emette metriche aggregate ogni 10s (inviati/completati/falliti/tempo medio) e la dimensione della coda ogni 2s (solo debug) |

### 7.2 Riordino cronologico (min-heap)

Ogni segmento riceve un numero di sequenza monotono all'`enqueue()` (`itertools.count()`). Il printer thread mantiene `_next_seq_to_print` e stampa solo quando il segmento con `seq` corrispondente arriva in cima all'heap. Se un segmento è "in ritardo" oltre `reorder_timeout_s`, viene comunque saltato (per evitare stalli indefiniti se una risposta Groq va persa) e si avanza forzatamente il puntatore.

### 7.3 Filtro passa-banda

Se `filter.enabled = true`, viene pre-calcolato **una sola volta** in `__init__` un filtro FIR (`scipy.signal.firwin`, 65 tap, pass-band `band_min`–`band_max` Hz) e applicato ad ogni segmento in `_process_segment()` tramite `signal.lfilter`. L'output viene **clippato** a [-1, 1] subito dopo il filtraggio, prima di passare alla codifica, per prevenire overshoot/ripple del filtro FIR che altrimenti causerebbero wraparound in fase di conversione a int16.

### 7.4 Encoding e upload

- Se `use_flac = true` **e** `soundfile` è disponibile → encoding FLAC (payload ridotto, upload più rapido)
- Altrimenti (o in caso di eccezione durante l'encoding FLAC) → fallback a WAV
- Upload via `requests.Session` con `HTTPAdapter` dedicato: `pool_connections` e `pool_maxsize` dimensionati su `max_concurrent_requests`, per riutilizzare le connessioni TCP/TLS invece di riaprirle ad ogni richiesta

### 7.5 Prompt iniziale (`INITIAL_PROMPT`)

Un prompt esteso e specifico per il dominio ATC viene passato ad ogni chiamata Groq, includendo: fraseologia standard (`cleared to land`, `hold short`, `squawk`, ecc.), alfabeto fonetico NATO completo, e la pronuncia numerica aeronautica (`tree`, `fife`, `niner`...). Questo orienta il modello Whisper verso il vocabolario tecnico corretto, riducendo errori di trascrizione su termini specialistici e callsign.

### 7.6 Anti-loop / deduplica

Se il testo restituito è identico all'ultimo testo trascritto **e** è più corto di 15 caratteri, viene scartato (protetto da lock `_last_text_lock`). Serve a filtrare ripetizioni spurie brevi (es. rumore interpretato come la stessa breve parola più volte di fila).

### 7.7 Gestione errori

- **Timeout HTTP** (`requests.exceptions.Timeout`): loggato come errore, segmento perso (nessun retry automatico nel codice attuale, nonostante la memoria di progetto citi un "retry con backoff esponenziale" — verificare se presente in versioni più recenti non ancora incluse in questi file)
- **Status HTTP ≠ 200**: loggato con i primi 200 caratteri della risposta, segmento perso
- **Eccezioni generiche**: catturate e loggate, segmento perso

### 7.8 Arresto pulito (`stop()`)

Ordine di shutdown: segnala `stop_event` → inserisce un sentinel `None` in coda → attende il dispatcher (join, timeout 3s) → chiude l'executor (`shutdown(wait=True)`, attende tutti i worker in volo) → sveglia il printer (notify) e attende il suo terminare (timeout = `reorder_timeout_s + 1s`) → attende il metrics thread → chiude la sessione HTTP.

---

## 8. Interfaccia grafica (GUI)

`gui_main.py` implementa `TranscriberGUI`, un'interfaccia Tkinter con tema scuro "AeroVoice".

### 8.1 Struttura visuale

- **Header**: titolo + indicatore di stato (pallino colorato + etichetta testuale: FERMO / IN ASCOLTO)
- **Barra controlli**: pulsanti ▶ AVVIA, ■ STOP, 🐞 DEBUG ON/OFF, etichetta modalità attiva
- **Colonna sinistra (70%)**:
  - VU meter (canvas che disegna il livello RMS corrente rispetto alla soglia di silenzio, con linea di soglia visibile e colore che varia verde/ambra/rosso in base al livello)
  - Pannello trascrizione (scrolling, con timestamp per riga)
  - Pannello metriche (inviati, completati, falliti, tempo medio, dimensione coda)
- **Colonna destra (30%)**:
  - Configurazione rapida (sola visualizzazione dei parametri correnti)
  - Stato sistema (pallini verdi/rossi per Microfono, Groq API, Filtro)
  - Uptime

### 8.2 Esecuzione della pipeline

La pipeline viene avviata in un **thread separato** (`_pipeline_thread`) che chiama `run_pipeline(config, event_bus=self.bus, stop_event=self.stop_event)`. Questo mantiene il thread principale Tkinter libero per l'interfaccia. La comunicazione avviene esclusivamente tramite `EventBus`, con polling ogni 100ms (`_poll_events`).

### 8.3 Eventi gestiti dalla GUI

| Evento (`kind`) | Origine | Azione GUI |
|---|---|---|
| `rms` | `_run_radio_mode` | Aggiorna VU meter e testo soglia/accettazione |
| `transcript` | `Transcriber._print_result` | Aggiunge riga alla trascrizione + buffer di salvataggio |
| `metrics` | `Transcriber._metrics_loop` | Aggiorna i contatori nel pannello metriche |
| `error` | Eccezioni nel thread pipeline | Mostra messaggio di errore, segna API come disconnessa |
| `stopped` | Fine pipeline (normale o per eccezione) | Ripristina UI allo stato "fermo" |

### 8.4 Salvataggio trascrizioni

- **Buffer in memoria** (`transcript_buffer`): accumula ogni riga trascritta con timestamp
- **Autosave periodico** (thread `_autosave_loop`, ogni `autosave_interval` secondi, default 10s): scrive l'intero buffer in `transcript_autosave.txt` (sovrascritto ad ogni ciclo)
- **Salvataggio manuale allo STOP**: se il buffer non è vuoto, viene chiesto conferma (`messagebox.askyesno`) prima di scrivere un file `transcript_YYYYMMDD_HHMMSS.txt`; se l'utente rifiuta, il buffer viene svuotato

### 8.5 Debug toggle

Attivando il pulsante DEBUG:
- Il livello del logger passa a `DEBUG` (globalmente, tramite `logging.getLogger("AudioTranscriber").setLevel(...)`)
- Si apre una finestra `Toplevel` (`DebugWindow`) che fa polling del file `transcriber.log` ogni 500ms, mostrando le nuove righe in tempo reale (letture incrementali tramite `seek`/`tell`, senza rileggere l'intero file)

Disattivandolo, se il file di log contiene dati, viene chiesto se archiviarlo (rinominandolo con timestamp) o cancellarlo.

> **Nota di codice**: nel metodo `_toggle_debug`, quando `debug_enabled` diventa `False`, l'ultima riga imposta comunque `self.error_label.config(text="🐞 Debug disattivato.", ...)` **dopo** l'eventuale messaggio di conferma salvataggio — quindi il messaggio "Log salvati in: ..." viene immediatamente sovrascritto e non è mai visibile all'utente. Se serve mostrare l'esito del salvataggio, va rimossa o condizionata l'ultima riga.


#### 8.6 Finestra di configurazione (ConfigWindow)

La GUI include una finestra di modifica dei parametri di `config.json`, accessibile tramite l'apposito pulsante (non mostrato nel codice fornito, ma integrato nell'interfaccia principale). Questa finestra, implementata dalla classe `ConfigWindow`, consente di visualizzare e modificare i parametri di configurazione più rilevanti senza dover editare manualmente il file JSON.

**Struttura dell'interfaccia**

La finestra è suddivisa in tre sezioni principali, ciascuna con i propri campi di input:

*   **Voice Activity Detection (VAD)**: controlla i parametri relativi alla segmentazione vocale (aggressività, timeout di silenzio, durata massima/minima dei segmenti, rapporto di attivazione).
*   **Filtro Passa-Banda**: abilita/disabilita il filtro e ne imposta le frequenze di taglio (minima e massima).
*   **API Groq**: consente di modificare il modello da utilizzare, il timeout delle richieste, il numero massimo di richieste concorrenti e l'abilitazione della codifica FLAC.

**Funzionamento interno**

1.  **Caricamento**: all'apertura, la finestra carica i valori correnti da `config.json`.
2.  **Modifica**: l'utente interagisce con i campi di input.
3.  **Salvataggio (Patch)**: quando l'utente preme **APPLICA** o **OK**, la finestra costruisce un "patch" (un dizionario Python) contenente esclusivamente i valori modificati. Questo patch viene quindi applicato al `config.json` caricato, sovrascrivendo solo le chiavi corrispondenti e preservando il resto della struttura.
4.  **Ricaricamento**: dopo il salvataggio, viene chiamato il metodo `_reload_config()` dell'applicazione principale, che ricarica la configurazione aggiornata nei moduli interni. Questo permette di rendere effettive le modifiche (sebbene, per alcune modifiche come quelle relative al VAD o al filtro, sia necessario riavviare la pipeline di acquisizione).
5.  **Pulsanti**:
    *   **APPLICA**: salva le modifiche su disco, ricarica la configurazione nell'app e mantiene la finestra aperta per ulteriori modifiche o test.
    *   **OK**: esegue le stesse operazioni di `APPLICA` e chiude la finestra.

---

## 9. Sistema di logging e debug

Il logger (`AudioTranscriber`, in `logger.py`) è configurato **una sola volta** all'import del modulo, con livello base `DEBUG` (il filtro effettivo avviene sui singoli handler):

- **Console handler**: rispetta `debug.console_level` (default `INFO`), oppure mostra tutto se `debug.enabled = true`
- **File handler** (`transcriber.log`, opzionale via `debug.log_to_file`): registra **sempre** tutto a livello DEBUG, indipendentemente da cosa è visibile a console — utile per analisi post-mortem senza dover riavviare con debug attivo

### Convenzione dei livelli usati nel codice

- `DEBUG`: dettagli granulari per-segmento (RMS, dimensione coda, numeri di sequenza, tempi di elaborazione) — pensati per diagnosi live durante i test, non per uso quotidiano
- `INFO`: eventi di ciclo di vita (avvio/arresto pipeline, configurazione caricata, filtro pre-calcolato)
- `WARNING`: condizioni anomale ma non bloccanti (segmento troppo breve, timeout nel riordino)
- `ERROR`: fallimenti (errori HTTP, eccezioni, timeout Groq)

---

## 10. Gestione file e dati sensibili

I seguenti file/cartelle **non devono mai essere versionati** su repository Git (pubblici o privati condivisi), perché contengono dati potenzialmente sensibili o non portabili:

| Percorso | Motivo |
|---|---|
| `venv/`, `env/`, `.venv/` | Ambiente virtuale: pesante, non portabile tra sistemi operativi/architetture, ricreabile da `requirements.txt` |
| `transcriber.log`, `*.log` | Contengono il testo completo delle comunicazioni trascritte a livello DEBUG |
| `transcript_*.txt` (incluso `transcript_autosave.txt`) | Trascrizioni salvate, potenzialmente dati sensibili/operativi |
| `config.json` (se contiene `api.groq.api_key` in chiaro) | Esporrebbe la chiave API; usare sempre la variabile d'ambiente `GROQ_API_KEY` quando il repo è condiviso |

**Pattern `.gitignore` raccomandato:**

```gitignore
venv/
env/
.venv/
__pycache__/
*.pyc
*.log
transcriber.log
transcript_*.txt
```

Se questi file sono già stati committati in passato, `.gitignore` non li rimuove retroattivamente: serve `git rm --cached` per smettere di tracciarli da ora in poi, oppure una riscrittura della history (`git filter-repo` / BFG) se devono sparire anche dai commit precedenti e il repository è pubblico.

---

## 11. Problemi noti risolti (changelog tecnico)

Questa sezione documenta le correzioni applicate durante lo sviluppo della v3, utile per capire il "perché" di alcune scelte non ovvie nel codice:

| Problema | Causa | Soluzione applicata |
|---|---|---|
| Tagli a metà parola in modalità radio | Segmentazione a durata rigorosamente fissa, senza considerare i confini naturali del parlato | `_find_best_cut_point()`: ricerca del punto di minima energia RMS in una finestra prima del bordo del segmento |
| Gate di silenzio inefficace | Soglia RMS di default non calibrata sui livelli reali osservati | Soglia (`silence_rms_threshold`) ritarata sui valori RMS osservati in test live (parlato ~218–230, silenzio ~1–5 in un contesto; **va ricalibrata per ogni setup audio**, dato che dipende da guadagno microfono/linea) |
| Overflow int16 / click udibili | Il filtro FIR passa-banda può produrre overshoot (ripple) anche su segnale normalizzato; la conversione diretta a int16 su valori fuori [-1,1] causa wraparound invece di saturazione | Clip esplicito a [-1, 1] subito dopo il filtraggio (`transcriber.py`) e clip di sicurezza in `_ensure_int16()` (`utils.py`) |
| Doppio filtraggio passa-banda | Il filtro era applicato sia in `preprocess_radio_audio()` (main.py) sia in `Transcriber` | Consolidato in un unico punto: solo `Transcriber._process_segment()` applica il filtro; `preprocess_radio_audio()` gestisce solo AGC e limitatore |
| "Compressore" fittizio | Un precedente limitatore era in realtà un hard-clip mascherato da compressore, che introduceva distorsione armonica udibile | Sostituito con `_soft_limiter()`: compressione soft-knee reale, che attenua gradualmente solo l'eccesso oltre soglia mantenendo continuità del segnale |
| `INITIAL_PROMPT` generico | Un prompt generico ("Transcription of aviation radio communication") perdeva gran parte dell'aiuto su terminologia tecnica e alfabeto fonetico | Ripristinato prompt esteso con fraseologia ATC completa, alfabeto NATO e pronuncia numerica aeronautica |
| Log troppo verbosi in produzione | Metriche stampate a livello che intasava la console anche in uso normale | Spostate a livello `debug` |
| `webrtcvad` non si importa su Windows | Dipende da `pkg_resources`, rimosso in `setuptools ≥ 82` | Pin esplicito `setuptools==81.0.0` in `requirements.txt` |

---

## 12. Troubleshooting

| Sintomo | Possibile causa | Verifica / soluzione |
|---|---|---|
| Il programma termina subito con "Nessuna API key Groq trovata" | Manca `GROQ_API_KEY` come variabile d'ambiente e manca `api.groq.api_key` in `config.json` | Impostare `set GROQ_API_KEY=...` (Windows) o `export GROQ_API_KEY=...` (Linux/Mac) prima dell'avvio |
| Nessun segmento viene mai inviato in modalità radio | `silence_rms_threshold` troppo alto rispetto ai livelli audio reali del proprio setup | Attivare debug, osservare i valori RMS loggati (`Segmento radio ACCETTATO/SCARTATO: RMS ...`) e ritarare la soglia in `config.json` |
| Trascrizioni "inventate" su tratti di silenzio/rumore | Allucinazioni tipiche di Whisper quando riceve segmenti senza parlato reale | Verificare che `silence_gate_enabled = true` e che la soglia sia calibrata correttamente |
| Audio distorto o con click | Overshoot del filtro FIR non clippato, oppure guadagno di ingresso troppo alto | Verificare la presenza dei clip in `transcriber.py`/`utils.py` (dovrebbero già esserci in v3); controllare il livello di ingresso della sorgente audio |
| Import error su `webrtcvad` / `pkg_resources` (Windows) | `setuptools` aggiornato a versione ≥82 che rimuove `pkg_resources` | Reinstallare `setuptools==81.0.0` nell'ambiente virtuale |
| `ModuleNotFoundError: soundfile` con `use_flac: true` | `soundfile` non installato | Il codice fa fallback automatico a WAV con un warning di log; installare `soundfile` per ripristinare FLAC |
| Qualità di trascrizione bassa quando l'audio viene riprodotto via altoparlante e ricatturato da microfono ("recapture acustico") | La riproduzione/ricattura acustica introduce rumore ambientale, riverbero e perdita di banda rispetto a un collegamento digitale/linea diretta | Preferire un collegamento diretto (cavo linea, interfaccia audio USB) invece del percorso altoparlante→microfono, quando possibile |
| Ripetizioni di parole ai bordi dei segmenti (modalità radio) | Effetto collaterale noto dell'`overlap_s`: il contesto ripetuto tra segmenti consecutivi non viene "cucito" a livello testuale | Comportamento noto e documentato nel codice; ridurre `overlap_s` attenua il fenomeno a scapito di un rischio leggermente maggiore di perdita di parole al bordo |
| `archive_log_file()` solleva `NameError: name 'datetime' is not defined` | Import mancante in `logger.py` | Aggiungere `from datetime import datetime` in testa al file |

---

## 13. Possibili sviluppi futuri

Non risultano decisioni esplicite prese nel progetto su questo punto, ma dall'analisi del codice emergono alcune aree di miglioramento naturale:

- **Cucitura testuale (text stitching)** dei segmenti in overlap, per eliminare le ripetizioni di parole ai bordi invece di limitarsi a ridurre `overlap_s`
- **Retry con backoff esponenziale** sulle chiamate Groq fallite per timeout/errore HTTP (attualmente il segmento viene semplicemente perso al primo fallimento)
- **Calibrazione automatica/assistita** della soglia di silenzio (`silence_rms_threshold`), ad esempio con una fase di calibrazione iniziale che misura il rumore di fondo reale del setup
- **Persistenza della configurazione da GUI**: attualmente la sezione "Configurazione rapida" della GUI mostra valori in gran parte statici/hardcoded (es. "VAD Sensibilità: 0.4", "Worker Groq: 5") invece di leggerli dinamicamente da `config.json`
- **Test automatizzati** sulla pipeline (attualmente il workflow è basato su test live con audio reale e ispezione manuale dei log)
- Correzione del piccolo bug di visualizzazione in `_toggle_debug` (messaggio di conferma salvataggio log sovrascritto immediatamente, vedi §8.5)
- Import mancante `datetime` in `logger.py` (vedi §12)

---

*Fine documento.*
