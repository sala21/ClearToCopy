# ClearToCopy — Manuale Tecnico

Documentazione per sviluppatori: architettura, struttura del codice, modello di concorrenza, schema di configurazione e note di manutenzione.

> Per l'uso quotidiano dell'applicazione, vedi il [Manuale Utente](user_manual.md). Per l'installazione, vedi il [`README.md`](../README.md).

---

## Indice


1. [Architettura generale](#-architettura-generale)
2. [Struttura del repository](#-struttura-del-repository)
3. [Modulo per modulo](#-modulo-per-modulo)
4. [Modello di concorrenza](#-modello-di-concorrenza)
5. [Ciclo di vita del modello](#-ciclo-di-vita-del-modello)
6. [EventBus e contratto degli eventi](#-eventbus-e-contratto-degli-eventi)
7. [Configurazione dell'applicazione`](#configurazione-dell'applicazione)
8. [Reload a caldo della configurazione](#-reload-a-caldo-della-configurazione)
9. [Consideazioni](#considerazioni)
10. [Estendere il progetto](#-estendere-il-progetto)

---

## Architettura generale

```
                     ┌─────────────────────────┐
                     │      gui_main.py        │  entry point GUI
                     └────────────┬────────────┘
                                  │
                     ┌────────────▼────────────────┐
                     │   gui/app.py                │
                     │   TranscriberGUI            │ 
                     │                             │
                     │  __init__:                  │
                     │   1. costruisce la UI       │
                     │   2. avvia _load_model_async│──── carica Transcriber
                     │      (thread separato)      │      (pesi in VRAM)
                     └────────────┬────────────────┘
                                  │ ▶ AVVIA
                     ┌────────────▼─────────────┐
                     │  main.run_pipeline()     │  thread pipeline dedicato
                     │  (riusa il Transcriber   │
                     │   già caricato)          │
                     └──┬──────────────┬────────┘
                        │              │
              ┌─────────▼──┐     ┌──────▼─────────┐
              │ AudioCapture│──▶│ VADProcessor   │
              │  (audio.py) │    │  (vad.py)      │
              └─────────────┘    └─────┬──────────┘
                                       │ segmento pronto
                                ┌──────▼───────────┐
                                │ Transcriber      │
                                │ (transcriber.py) │
                                │ filtro + Whisper │
                                └──────┬───────────┘
                                       │ EventBus.emit(...)
                                ┌──────▼───────────┐
                                │  EventBus        │
                                │  (events.py)     │
                                └──────┬───────────┘
                                       │ poll ogni 100ms (thread Tk)
                                ┌──────▼──────────────┐
                                │  TranscriberGUI     │
                                │  (aggiorna i widget)│
                                └─────────────────────┘
```

**Decisione architetturale chiave**: il modello Whisper viene caricato **una sola volta**, all'avvio della GUI, e **riutilizzato** attraverso i cicli Avvia/Stop tramite `Transcriber.reset()` (svuota code e contatori senza toccare i pesi in VRAM). Viene rilasciato (`Transcriber.stop()`) solo alla chiusura della finestra. Questo evita il costo di ricaricamento (decine di secondi) a ogni Avvia.

---

## Struttura del repository

```
.
├── main.py                 # Orchestrazione pipeline (CLI + riusabile da GUI)
├── gui_main.py              # Entry point GUI
├── config.py                 # Caricamento config.json
├── paths.py                   # BASE_DIR, CONFIG_PATH, LOG_FILE (indipendente da config/logger)
├── config.json                 # Configurazione runtime
├── audio.py                     # Cattura audio (PyAudio)
├── vad.py                        # Voice Activity Detection e segmentazione
├── transcriber.py                 # Inferenza Whisper locale
├── utils.py                        # Conversione audio → WAV/FLAC (non più usato da transcriber.py)
├── logger.py                        # Logging (console + file)
├── events.py                         # EventBus thread-safe pipeline → GUI
└── gui/
    ├── __init__.py
    ├── app.py                # Finestra principale, orchestrazione GUI-side
    ├── config_window.py       # Editor di config.json
    ├── debug_window.py         # Tail live del file di log
    └── theme.py                 # Palette colori e font
```

---

## Modulo per modulo

### `paths.py`

Unico punto di verità per i percorsi, senza dipendenze da `config.py` o `logger.py` (evita import circolari, dato che entrambi lo importano).

```python
BASE_DIR    # cartella dell'eseguibile (se pacchettizzato con PyInstaller) o dello script
CONFIG_PATH # BASE_DIR/config.json
LOG_FILE    # "transcriber.log" — NB: percorso relativo alla CWD, non a BASE_DIR
```

> ⚠️ `LOG_FILE` non è ancorato a `BASE_DIR` come gli altri due. Se l'applicazione viene avviata da una directory di lavoro diversa da quella dei file sorgente (es. un collegamento sul desktop con "Esegui in" impostato altrove), il file di log finisce in un posto imprevisto. Vedi [Note di manutenzione](#-note-di-manutenzione-e-problemi-noti).

### `config.py`

`load_config()` legge `CONFIG_PATH`, e termina il processo (`sys.exit(1)`) se il file non esiste.

### `audio.py` — `AudioCapture`

Wrapper su PyAudio in modalità callback (non bloccante). Scrive i frame catturati in una `queue.Queue` con dimensione massima (`max_queue_size=200`); se il consumatore (il loop principale) non riesce a tenere il passo, i frame in eccesso vengono scartati e contati in `self.dropped_frames` (esposto poi nelle metriche verso la GUI).

### `vad.py` — `VADProcessor`

Rilevatore di attività vocale basato su [`webrtcvad`](https://github.com/wiseman/py-webrtcvad), con segmentazione a **sliding window O(1)** (nessuna scansione ripetuta del buffer a ogni frame).

Concetti chiave:
- **`ring_buffer`** (pre-roll, ~300ms): mantiene gli ultimi frame prima dell'attivazione, per non perdere l'inizio della frase.
- **`activation_ratio`**: percentuale di frame "vocali" nel pre-roll necessaria per considerare iniziata una trasmissione.
- **`ring_buffer_silence`**: conta i frame di silenzio consecutivi una volta attivato, per decidere quando la trasmissione è conclusa (`silence_timeout_s`).
- **`max_utterance_s`**: taglio forzato di sicurezza, indipendente dal rilevamento del silenzio.
- **`_state_lock`** (`threading.Lock`): protegge tutto lo stato interno, perché `process_frame()` gira sul thread della pipeline mentre `update_params()` può essere chiamato dal thread Tkinter (reload a caldo) — vedi [Modello di concorrenza](#-modello-di-concorrenza).

`update_params()` chiude un eventuale segmento in corso prima di ricreare i buffer, per non perdere audio a metà frase durante un reload.

### `transcriber.py` — `Transcriber`

Cuore della pipeline. Espone:

```python
Transcriber(config, event_bus=None)
.enqueue(audio_np: np.ndarray)              # accoda un segmento (int16 o float32)
.set_audio_reference(audio: AudioCapture)   # per leggere dropped_frames nelle metriche
.update_local_model_settings(language=None, max_new_tokens=None,
                              no_repeat_ngram_size=None, repetition_penalty=None)
.reset()                                     # svuota code/contatori, NON tocca il modello
.stop()                                       # ferma i thread e libera la VRAM
```

##

- **`dispatch_thread`**: preleva dalla coda FIFO e sottomette il lavoro all'executor.
- **`ThreadPoolExecutor(max_workers=1)`**: **volutamente limitato a un solo worker**. L'inferenza gira su un'unica GPU; chiamate concorrenti a `model.generate()` sullo stesso modello non offrono benefici e rischiano contese sulla memoria. Con un solo worker, il riordino è di fatto sempre "già in ordine", ma il meccanismo resta come rete di sicurezza a basso costo.
- **`printer_thread`**: preleva i risultati dal min-heap in ordine di sequenza, con timeout di riordino (`reorder_timeout_s`) per non bloccarsi indefinitamente su un segmento mai arrivato.
- **`metrics_thread`**: pubblica un evento `"metrics"` ogni ~10s.

**Filtro passa-banda**: calcolato una volta con `scipy.signal.firwin` in `_recompute_filter()`, richiamabile a runtime (reload a caldo) senza doverlo ricreare da zero nel codice chiamante.

**Inferenza** (`_transcribe_locally`): normalizza l'array audio a float32 `[-1, 1]`, lo passa a `WhisperProcessor`, esegue `model.generate()` con:
- `forced_decoder_ids` — impone lingua e task (`transcribe`)
- `no_repeat_ngram_size`, `repetition_penalty`, `condition_on_prev_tokens=False` — mitigano i loop di ripetizione tipici di Whisper su segmenti con silenzi interni
- `prompt_ids` (opzionale, `use_initial_prompt`) — inietta un prompt fisso con vocabolario ATC (callsign, fraseologia, alfabeto fonetico) per orientare il decoder


### `main.py` — `run_pipeline()`

```python
def run_pipeline(config, event_bus=None, stop_event=None,
                  components_ref=None, transcriber=None):
```

- Se `transcriber` è `None`, ne crea uno nuovo (usato da `python main.py` in modalità CLI standalone).
- Se `transcriber` è già fornito (caso GUI), lo riusa e gli riassegna `event_bus`.
- `components_ref`, se passato (un dizionario), viene popolato con i riferimenti reali a `audio`, `vad`, `transcriber` **prima** di entrare nel loop bloccante — permette al chiamante (la GUI) di agire sulle istanze realmente in esecuzione per il reload a caldo.
- Il blocco `finally` chiama solo `audio.stop()`, **non `transcriber.stop()`**: coerente con la scelta di mantenere il modello caricato tra un ciclo e l'altro. Chi possiede il ciclo di vita del `Transcriber` (la GUI, o il chiamante di `run_pipeline` in generale) è responsabile di chiamare `.stop()` quando davvero non serve più.

### `gui/app.py` — `TranscriberGUI`

Il file più corposo del progetto. Punti salienti oltre alla costruzione dei widget:

- **`_load_model_async()`**: thread separato che crea `Transcriber(config, event_bus=None)` all'apertura della finestra (l'`event_bus` viene assegnato solo al primo Avvia). Aggiorna `self.model_loaded` e riattiva `▶ AVVIA` al termine.
- **`_pipeline_thread(config, transcriber)`**: thread dedicato per ogni sessione Avvia/Stop, chiama `main.run_pipeline(...)` passando il transcriber già caricato.
- **`_poll_events()`**: eseguito ogni 100ms sul thread principale Tkinter via `root.after`, consuma gli eventi dall'`EventBus` e aggiorna i widget. È l'**unico punto di contatto** tra i thread di background e Tkinter — nessun altro punto del codice deve toccare i widget da un thread diverso da quello principale.
- **`on_close()`**: unico punto in cui viene chiamato `transcriber.stop()`, quindi l'unico momento in cui la VRAM viene effettivamente liberata durante la vita del processo GUI.

### `gui/config_window.py` — `ConfigWindow`

Editor generico basato su liste di tuple `(chiave, etichetta, valore_default)` per ciascuna sezione (VAD, Filtro, Modello Locale, Radio) — aggiungere un nuovo campo configurabile è un'aggiunta di una riga alla lista corrispondente più la constante nel dizionario del patch, non serve altro boilerplate.

`_apply_config()` scrive su `config.json` e richiama `self.app._reload_config()` immediatamente. `_save_and_close()` fa lo stesso **solo se `self.apply_pressed` è `True`** (impostato dentro `_apply_config`) — se l'utente non ha mai premuto "Applica" e preme direttamente "OK", la finestra si chiude senza scrivere nulla. Vedi [Note di manutenzione](#-note-di-manutenzione-e-problemi-noti).

### `gui/debug_window.py` — `DebugWindow`

Tail "povero" del file di log: rilegge da `self.last_pos` ogni 500ms. Il file (`"transcriber.log"`, percorso relativo) è indipendente dal logger applicativo — apre/chiude il file a ogni poll invece di tenerlo aperto, scelta semplice ma con overhead di I/O ripetuto (accettabile alla frequenza attuale).

---

## Modello di concorrenza

| Thread | Origine | Responsabilità |
|---|---|---|
| Thread principale Tkinter | `gui_main.py` | UI, `_poll_events()` ogni 100ms |
| Thread caricamento modello | `_load_model_async` | Istanzia `Transcriber` (una tantum, all'apertura) |
| Thread pipeline | `_pipeline_thread` (uno per sessione Avvia/Stop) | Esegue `run_pipeline`: loop di cattura frame + `vad.process_frame()` |
| `dispatch_thread` (Transcriber) | `Transcriber.__init__` | Preleva dalla coda, sottomette all'executor |
| `LocalModelWorker` (executor, 1 worker) | `Transcriber.__init__` | Esegue `_process_segment` → inferenza GPU |
| `printer_thread` (Transcriber) | `Transcriber.__init__` | Riordina e pubblica i risultati sull'`EventBus` |
| `metrics_thread` (Transcriber) | `Transcriber.__init__` | Pubblica metriche periodiche |

**Regola d'oro**: nessun thread diverso da quello principale Tkinter tocca direttamente i widget. Tutta la comunicazione verso la GUI passa da `EventBus.emit(...)` (thread-safe, basato su `queue.Queue`) e viene consumata solo da `_poll_events()`.

**Punti di sincronizzazione tra reload a caldo e pipeline attiva**:
- `VADProcessor._state_lock`: protegge `process_frame()` (thread pipeline) da `update_params()` (thread Tkinter, chiamato da `_reload_config`).
- `Transcriber` non ha un lock equivalente esplicito sui parametri di generazione (`language`, `max_new_tokens`, ecc.) — sono semplici attributi Python riletti a ogni chiamata di `_transcribe_locally`. Essendo il worker unico e sequenziale, il rischio pratico di race condition è basso, ma non è una garanzia formale come quella del VAD.

---

## Ciclo di vita del modello

```
                    Apertura GUI
                      │
                      ▼
                    _load_model_async() ──► Transcriber(config)  [carica pesi in VRAM, ~30-60s]
                      │
                      ▼
              _____ ▶ AVVIA ──► transcriber.reset() ──► run_pipeline(..., transcriber=<esistente>)
              |       │                                        │
              |       ▼                                        ▼
              |       |                             cattura + VAD + trascrizione
 nessun       |       │
ricaricamento |       ■ STOP ──► stop_event.set() ──► audio.stop()  [il modello RESTA in VRAM]
              |       |
              |       ▼
              |_______|
                      │
                      ▼
                    Chiusura finestra (on_close) ──► transcriber.stop()  [VRAM liberata]
```

Questo schema è deliberato: ricaricare un modello Whisper large ogni volta che l'utente ferma e riavvia la trascrizione costerebbe decine di secondi non necessari. Il costo si paga una sola volta, all'apertura dell'applicazione.

---

## EventBus e contratto degli eventi

`EventBus` (`events.py`) è una coda FIFO thread-safe senza logica propria: `emit(kind, **data)` accoda una tupla `(kind, data)`, `poll_all()` la svuota. Nessun filtro, nessuna persistenza.

Eventi attualmente emessi e consumati da `gui/app.py::_poll_events`:

| `kind` | Emesso da | Payload | Effetto in GUI |
|---|---|---|---|
| `"rms"` | VAD (non mostrato nei file letti in questa sessione, presumibilmente da `vad.py` o `audio.py` in una revisione futura) | `value`, `threshold`, `accepted` | Aggiorna il misuratore RMS |
| `"transcript"` | `Transcriber._print_result` | `text` | Aggiunge una riga al pannello trascrizione |
| `"metrics"` | `Transcriber._metrics_loop` | `submitted`, `completed`, `failed`, `queue_size`, `avg_time`, `dropped_frames` | Aggiorna il pannello metriche |
| `"status"` | `Transcriber._load_model`, `main.run_pipeline` | `message` | Mostra il messaggio nella barra inferiore |
| `"error"` | `TranscriberGUI._pipeline_thread` (eccezioni non gestite) | `message` | Mostra errore in rosso |
| `"stopped"` | `TranscriberGUI._pipeline_thread` (blocco `finally`) | — | Ripristina lo stato "FERMO" |
| `"model_loaded"` | `main.run_pipeline` | — | Conferma visiva che il modello è pronto |
| `"audio_started"` | `main.run_pipeline` | — | Imposta lo stato "IN ASCOLTO" |

> Nota: l'evento `"rms"` non è emesso da nessuno dei moduli inclusi in questa revisione del codice (`audio.py`, `vad.py`); il misuratore di livello nella dashboard, allo stato attuale, non riceve aggiornamenti a runtime finché questo evento non viene effettivamente pubblicato da qualche parte della pipeline di cattura/VAD. Verificare se si tratta di funzionalità in sviluppo o di codice rimosso per errore.

---


## Configurazione dell'applicazione

Di seguito la documentazione completa di **tutti** i parametri disponibili nel file `config.json`.

---

## Voice Activity Detection (VAD)

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `aggressiveness` | intero | 0–3 | Grado di selettività del VAD. **0** = meno selettivo (cattura anche parlato debole ma più falsi positivi). **3** = massima selettività (riduce i falsi positivi ma rischia di escludere parlato a bassa voce). Valore consigliato: `1` per uso generico. |
| `silence_timeout_s` | float | ≥ 0.1 | Secondi di silenzio continuo necessari per considerare un segmento concluso. Valori più bassi tagliano prima, valori più alti mantengono il segmento aperto più a lungo. Tipico: `1.0` s. |
| `max_utterance_s` | float | ≥ 1.0 | Durata massima di un singolo segmento. Oltre questo limite il segmento viene forzato a concludersi. Previene trascrizioni eccessivamente lunghe. Default: `7.0` s. |
| `min_segment_duration_s` | float | ≥ 0.1 | Durata minima accettabile per un segmento. Segmenti più brevi vengono scartati in quanto probabilmente rumore. Tipico: `0.6` s. |
| `activation_ratio` | float | 0.0–1.0 | Rapporto minimo di frame "attivi" (con voce) rispetto al totale per iniziare un segmento. Valori più alti richiedono un parlato più continuo prima di attivarsi. Tipico: `0.4`. |
| `rms_gate_enabled` | booleano | `true`/`false` | Se `true`, attiva un filtro aggiuntivo basato sull'energia RMS (Root Mean Square) del segnale. Esclude rumori a bassa energia ma persistenti (es. ronzio di fondo). Migliora la selettività in ambienti moderatamente rumorosi. |

---

## Filtro Passa‑Banda

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `enabled` | booleano | `true`/`false` | Attiva o disattiva il filtro passa‑banda. Se `false` l'audio viene processato senza filtraggio. |
| `band_min` | intero | 20–20000 (Hz) | Frequenza minima (Hz) del filtro. Tutto ciò che è al di sotto viene attenuato. Tarato di default per la voce umana su VHF: `300` Hz. |
| `band_max` | intero | 20–20000 (Hz) | Frequenza massima (Hz) del filtro. Tutto ciò che è al di sopra viene attenuato. Default: `3400` Hz (banda telefonica). |

---

## Modello Locale (Whisper)

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `model_name` | stringa | identificatore Hugging Face | Nome del modello Whisper da caricare (es. `"jlvdoorn/whisper-large-v3-atco2-asr-atcosim"`). **Richiede riavvio dell'app** per essere applicato. |
| `device` | stringa | `"cpu"` / `"cuda"` | Dispositivo per l'inferenza. `"cuda"` usa la GPU (più veloce), `"cpu"` usa il processore. **Richiede riavvio**. |
| `language` | stringa | codice ISO 639‑1 | Lingua forzata per la trascrizione. Es. `"en"` per inglese, `"it"` per italiano. Se non specificato, Whisper tenta di rilevarla automaticamente. |
| `max_new_tokens` | intero | ≥ 1 | Numero massimo di token generati per ogni segmento. Valori più alti consentono trascrizioni più lunghe, ma aumentano il tempo di inferenza e il consumo di memoria. Tipico: `256`. |
| `no_repeat_ngram_size` | intero | ≥ 1 | Dimensione del n‑gramma da evitare in ripetizione. Impostando `3`, il modello non genererà mai una sequenza di 3 token identici consecutivi. Riduce loop e allucinazioni. Tipico: `3`. |
| `repetition_penalty` | float | ≥ 1.0 | Fattore di penalità per la ripetizione di token già generati. Valori > `1.0` scoraggiano la ripetizione. `1.3` è un buon compromesso per il parlato radiofonico. Valori troppo alti possono alterare la naturalezza. |
| `use_initial_prompt` | booleano | `true`/`false` | Se `true`, il modello riceve un prompt iniziale (es. "Trascrivi il seguente audio") per migliorare la coerenza contestuale e la qualità della trascrizione. |
| `reorder_timeout_s` | float | ≥ 0.1 | Tempo massimo (in secondi) di attesa per il riordino dei segmenti quando si utilizzano meccanismi di rilevamento fine (es. per gestire sovrapposizioni). Valori più alti migliorano la precisione a scapito della latenza. Tipico: `3.0` s. |

> ⚠️ **Importante:** `model_name` e `device` richiedono il riavvio completo dell'applicazione (chiusura e riapertura della finestra). Modificarli a caldo non ha effetto.

---

## Audio

Parametri di acquisizione e preprocessamento del segnale audio.

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `rate` | intero | 8000, 16000, 44100, ecc. | Frequenza di campionamento (Hz) per l'acquisizione. Whisper è ottimizzato per `16000` Hz; usare altri valori può degradare le prestazioni. |
| `channels` | intero | 1 (mono) / 2 (stereo) | Numero di canali audio. Il sistema è progettato per flusso mono (`1`) per ridurre il carico di calcolo e semplificare il processing. |
| `frame_duration_ms` | intero | 10–100 (ms) | Durata in millisecondi di ciascun frame audio processato dal VAD e dal filtro. `30` ms è il valore standard per il rilevamento vocale (bilanciamento tra precisione e reattività). |
| `input_gain` | float | ≥ 0.1 | Guadagno moltiplicativo applicato al segnale in ingresso. Valori > `1.0` amplificano l'audio (utile per microfoni poco sensibili o sorgenti distanti). Attenzione a non saturare. Tipico: `1.0`. |

---

## Debug

Controlli per il logging e la diagnostica.

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `enabled` | booleano | `true`/`false` | Attiva la modalità debug. Se `true`, vengono prodotti log dettagliati di ogni fase (VAD, trascrizione, filtri, ecc.), utili per il troubleshooting. |
| `log_to_file` | booleano | `true`/`false` | Se `true`, i log vengono scritti anche su un file (oltre che sulla console). Il percorso del file è definito a livello di applicazione. |
| `console_level` | stringa | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` | Livello di severità minimo per i messaggi mostrati nella console. `"DEBUG"` mostra tutto, `"ERROR"` solo gli errori critici. Per uso normale si consiglia `"INFO"`. |

---

## Impostazioni Radio

Parametri specifici per la gestione di flussi audio radiofonici (es. comunicazioni VHF), con segmentazione e controllo del silenzio.

| Campo | Tipo | Valori | Descrizione |
|-------|------|--------|-------------|
| `enabled` | booleano | `true`/`false` | Attiva/disattiva la modalità "radio". Se `false`, il sistema usa le impostazioni standard di VAD e segmentazione. |
| `bypass_vad` | booleano | `true`/`false` | Se `true` il sistema tenta di usare una segmentazione a tempo fisso invece del VAD.  |
| `segment_duration_s` | float | ≥ 0.5 | Durata fissa di ogni segmento quando si usa la segmentazione temporale (non VAD). Valore di default: `3.0` s. Usato solo se il VAD viene bypassato (non ancora implementato). |
| `overlap_s` | float | 0.0 – `segment_duration_s` | Sovrapposizione in secondi tra segmenti consecutivi. Riduce il rischio di tagliare parole a cavallo dei confini. Valori tipici: `0.3`–`0.5` s. |
| `silence_gate_enabled` | booleano | `true`/`false` | Se `true`, abilita un gate di silenzio basato sulla soglia RMS. Quando il livello scende sotto la soglia, la registrazione del segmento viene interrotta (utile per rumori di fondo intermittenti). |
| `silence_rms_threshold` | intero | 0–32767 | Soglia RMS lineare per il gate di silenzio. Valori consigliati: `50` per ambienti molto silenziosi, `100–200` per ambienti con rumore di fondo moderato. Valori più alti rendono il gate meno sensibile. |
| `boundary_search_s` | float | 0.1–1.0 | Ampiezza della finestra temporale (in secondi) entro cui cercare il punto di taglio ottimale intorno a un confine di segmento. Evita di troncare parole a metà. Tipico: `0.4` s. |
| `boundary_analysis_ms` | intero | 5–50 | Risoluzione temporale (in millisecondi) dell'analisi per la ricerca dei confini. Valori più piccoli danno tagli più precisi ma aumentano il carico computazionale. Tipico: `20` ms. |

---

## Note generali

- **Ordine di applicazione**: L'audio acquisito viene prima amplificato (`input_gain`), poi filtrato passa‑banda, quindi processato dal VAD (e/o dai controlli radio), e infine inviato al modello Whisper per la trascrizione.
- **Consigli per prestazioni**:
  - Per ridurre la latenza, diminuire `max_new_tokens` e `reorder_timeout_s`.
  - Per migliorare la precisione in ambienti rumorosi, aumentare `aggressiveness` e abilitare `rms_gate_enabled`.
  - Per trascrizioni più fluide, aumentare `overlap_s` e `boundary_search_s` (a scapito di un lieve aumento del carico).

---

## Reload a caldo della configurazione

`TranscriberGUI._reload_config()` (invocato dal pulsante "🔄 Ric CFG Live" o dalla finestra di configurazione dopo "Applica") applica le modifiche ai componenti già attivi, senza fermare la pipeline:

| Parametro | Applicato a caldo? | Note |
|---|---|---|
| `vad.*` | ✅ Sì | Via `VADProcessor.update_params()`, thread-safe |
| `filter.*` | ✅ Sì | Via `transcriber._recompute_filter()` |
| `local_model.language` | ✅ Sì | Via `transcriber.update_local_model_settings()` |
| `local_model.max_new_tokens` | ✅ Sì | idem |
| `local_model.no_repeat_ngram_size` | ✅ Sì | idem |
| `local_model.repetition_penalty` | ✅ Sì | idem |
| `local_model.model_name` | ❌ No | Richiede riavvio completo dell'applicazione (il modello è caricato una sola volta all'apertura) |
| `local_model.device` | ❌ No | Idem |
| `radio.*` | ❌ No | Sezione non collegata alla pipeline |

Il reload richiede che la pipeline sia già attiva (`self.running`); se i componenti non sono ancora pronti, `_reload_config` si ri-schedula da solo dopo 300ms invece di fallire silenziosamente.

---

## Considerazioni

Elenco onesto di aree da rivedere, per chi riprende in mano il codice:


1. **`Transcriber.__init__` non ha più un fallback automatico a CPU.** Nella revisione attuale:
   ```python
   if requested_device == "cuda" and not torch.cuda.is_available():
       logger.warning("device='cuda' richiesto ma CUDA non disponibile.")
       return
   ```
   Il `return` qui esce da `__init__` **prima** di impostare `self.device` e prima di creare code/thread/eseguire il caricamento del modello. L'oggetto `Transcriber` risultante è in uno stato parzialmente inizializzato e inutilizzabile (mancano attributi come `self.device`, `self.model`, `self.transcribe_queue`). Qualunque chiamata successiva (es. `enqueue()`) solleverà `AttributeError`. Da correggere: o si ripristina il fallback automatico a CPU (`self.device = "cpu"` con logging esplicito) oppure si solleva un'eccezione esplicita (`raise RuntimeError(...)`) invece di un `return` silenzioso, così che il chiamante (`_load_model_async` in `app.py`, che già intercetta `Exception`) possa gestirlo correttamente invece di ritrovarsi un oggetto rotto ma apparentemente creato.

---

## Estendere il progetto

**Aggiungere un nuovo parametro configurabile a caldo (es. un nuovo parametro di generazione Whisper):**
1. Aggiungilo con un default sensato in `config.json`.
2. Leggilo in `Transcriber.__init__` (o nel metodo di reload dedicato) e aggiungi il parametro corrispondente a `update_local_model_settings()`.
3. Aggiungi la entry alla lista `local_model_params` in `gui/config_window.py::_build_ui`, e il campo corrispondente in `_get_patch_from_entries` / `_save_config_with_patch` / `_update_entries_from_config`.
4. Se serve applicarlo a caldo, aggiungi la chiamata corrispondente in `TranscriberGUI._reload_config`.

**Cambiare modello Whisper di base:** basta modificare `local_model.model_name` in `config.json` (o dalla finestra di configurazione) e riavviare l'applicazione — nessuna modifica al codice richiesta, a patto che il nuovo checkpoint sia compatibile con l'API `WhisperForConditionalGeneration`/`WhisperProcessor` di  Transformers.