# ClearToCopy

**Trascrizione in tempo reale di comunicazioni radio ATC (Air Traffic Control)**, tramite rilevamento vocale (VAD), filtro passa-banda dedicato al parlato radio, e un modello Whisper specializzato in fraseologia aeronautica **eseguito interamente in locale su GPU** — nessun dato audio lascia il dispositivo, nessuna dipendenza da servizi cloud a runtime.

---

## Indice

- [Caratteristiche](#caratteristiche)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Avvio rapido](#avvio-rapido)
- [Configurazione](#configurazione)
- [Documentazione](#documentazione)
- [Struttura del progetto](#struttura-del-progetto)
- [Limitazioni note](#limitazioni-note)
- [Crediti](#crediti)
- [Licenza](#licenza)

---

## Caratteristiche

- **Cattura audio in tempo reale** da microfono/linea audio (PyAudio)
- **Voice Activity Detection** (WebRTC VAD) con parametri configurabili, per isolare le singole trasmissioni
- **Filtro passa-banda** (300–3400 Hz) ottimizzato per audio radio VHF
- **Trascrizione 100% locale**: il modello resta caricato in VRAM per l'intera sessione dell'applicazione, riavvii della trascrizione (Stop/Avvia) non richiedono di ricaricarlo
- **Interfaccia grafica** (Tkinter) con pannello di trascrizione live, metriche runtime e configurazione modificabile a caldo
- **Metriche**: segmenti inviati/completati/falliti, tempo medio di inferenza, frame audio scartati

---

## Requisiti

### Hardware

- GPU NVIDIA con almeno **8 GB di VRAM** (testato su RTX 5050 Laptop GPU)
- Se la GPU è di architettura **Blackwell (serie RTX 50)**: driver NVIDIA aggiornato (serie R570+) e PyTorch **2.7.0+** con build CUDA **12.8+**
- In assenza di GPU compatibile, il modello può girare su CPU, con tempi di inferenza significativamente più alti — sconsigliato per l'uso in tempo reale

### Software

- Python 3.10+
- Windows 10/11 (ambiente di riferimento)

---

## Installazione

### 1. Clona il repository

```bash
git clone https://github.com/sala21/Real-Time-Speech-To-Text-AirBand-tool.git
cd Real-Time-Speech-To-Text-AirBand-tool
```

> **Windows + OneDrive:** evita di lavorare da una cartella sincronizzata con OneDrive. I percorsi generati da alcune dipendenze (in particolare `torch`) possono superare il limite di lunghezza di Windows. Clona in un percorso breve, es. `C:\dev\ClearToCopy`.

### 2. Crea un ambiente virtuale

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/macOS
```

### 3. Installa PyTorch con supporto CUDA

**Da fare per primo e separatamente**, con la build corretta per la propria GPU — consulta [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/). Esempio per CUDA 12.8:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

Verifica:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Deve stampare `True` seguito dal nome della GPU.

### 4. Installa le dipendenze rimanenti

```bash
pip install -r requirements.txt
```

Include `transformers` e `accelerate` per l'inferenza locale, `PyAudio` e `webrtcvad` per cattura/VAD, `scipy` per il filtro passa-banda. `Pillow` è opzionale: se assente, l'applicazione funziona comunque, semplicemente senza l'illustrazione decorativa nel menu laterale della GUI.

### 5. (Windows) Abilita i percorsi lunghi

Consigliato per evitare errori di installazione. In PowerShell come amministratore:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

Riavvia il PC dopo la modifica.

---

## Avvio rapido

```bash
python gui_main.py
```

Il modello viene caricato automaticamente all'apertura della finestra (fino a ~1 minuto la prima volta); il pulsante **▶ AVVIA** si attiva al termine del caricamento. Per i dettagli completi sull'uso dell'interfaccia, vedi il [Manuale Utente](docs/user_manual.md).

Per l'uso da riga di comando, senza interfaccia grafica:

```bash
python main.py
```

---

## Configurazione

Tutte le impostazioni si trovano in `config.json`, modificabile a mano o dalla finestra di configurazione della GUI. Riferimento rapido:

| Sezione | Contenuto |
|---|---|
| `local_model` | Modello Whisper, device, lingua, parametri di generazione |
| `audio` | Frequenza di campionamento, canali, durata frame |
| `vad` | Sensibilità e timing del rilevatore di attività vocale |
| `filter` | Filtro passa-banda pre-trascrizione |
| `debug` | Livello di logging |
| `radio` | Riservato a una modalità di segmentazione alternativa, **non ancora implementata** — vedi [Manuale Tecnico](docs/technical_manual.md#-schema-di-configjson) |

Documentazione completa di ogni campo nel [Manuale Tecnico](docs/technical_manual.md#-schema-di-configjson).

---

## Documentazione

| Documento | A chi è rivolto |
|---|---|
| [`docs/user_manual.md`](docs/user_manual.md) | Utenti finali: come installare, avviare e usare ogni funzione dell'interfaccia |
| [`docs/technical_manual.md`](docs/technical_manual.md) | Sviluppatori: architettura, modello di concorrenza, schema di configurazione, problemi noti |

---

## Struttura del progetto

```
.
├── main.py                # Orchestrazione pipeline (CLI + riusabile da GUI)
├── gui_main.py             # Entry point GUI
├── config.py / paths.py    # Caricamento config.json, gestione percorsi
├── config.json             # Configurazione runtime
├── audio.py                # Cattura audio (PyAudio)
├── vad.py                  # Voice Activity Detection e segmentazione
├── transcriber.py          # Trascrizione con modello Whisper locale
├── logger.py                # Logging (console + file)
├── events.py                # EventBus thread-safe pipeline → GUI
├── gui/
│   ├── app.py               # Finestra principale
│   ├── config_window.py     # Finestra di configurazione
│   ├── debug_window.py      # Finestra log di debug
│   └── theme.py              # Palette colori e font
├── requirements.txt
└── docs/
    ├── user_manual.md
    └── technical_manual.md
```

---

## Limitazioni note

- **Modalità "radio" non implementata**: i parametri sono presenti in `config.json` e nella finestra di configurazione, ma non collegati alla pipeline di trascrizione.
- **Hot-reload parziale**: VAD, filtro e alcuni parametri di generazione si aggiornano a caldo; cambiare modello o device richiede la chiusura e riapertura dell'applicazione.
- **Inferenza seriale**: un segmento alla volta, per compatibilità con GPU a VRAM limitata.

Elenco completo, incluse alcune incongruenze minori del codice da tenere presenti in manutenzione, nel [Manuale Tecnico](docs/technical_manual.md#-note-di-manutenzione-e-problemi-noti).

---

## Crediti

- Modello di trascrizione: [`jlvdoorn/whisper-large-v3-atco2-asr-atcosim`](https://huggingface.co/jlvdoorn/whisper-large-v3-atco2-asr-atcosim), fine-tuning di Whisper large-v3 sui dataset [ATCO2](https://www.atco2.org/) e ATCOSIM — progetto [WhisperATC](https://github.com/jlvdoorn/WhisperATC)
- Voice Activity Detection: [WebRTC VAD](https://github.com/wiseman/py-webrtcvad)
- Modello base: [OpenAI Whisper](https://github.com/openai/whisper) via [Transformers](https://github.com/huggingface/transformers)

---

## Licenza

ClearToCopy è un progetto free-license open-source
