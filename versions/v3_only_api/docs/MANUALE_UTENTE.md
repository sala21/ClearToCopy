# Manuale Utente: ATC Radio Transcriber v3.0

## 1. Installazione

```bash
# Clona o estrai il progetto in una cartella
cd C:\ATC-Transcriber

# Crea ambiente virtuale
python -m venv venv

# Attiva l'ambiente (Windows - Prompt dei comandi)
venv\Scripts\activate.bat

# Attiva l'ambiente (Windows - PowerShell)
venv\Scripts\Activate.ps1

# Attiva l'ambiente (macOS/Linux)
source venv/bin/activate

# Installa le dipendenze
pip install -r requirements.txt

# Se non hai requirements.txt, installa manualmente
pip install pyaudio webrtcvad numpy requests scipy soundfile
```

## 2. Configurazione API Groq

1. Vai su https://console.groq.com
2. Crea un account e genera una API key.
3. Imposta la variabile d'ambiente:

```bash
# Windows (Prompt dei comandi)
set GROQ_API_KEY=la_tua_chiave

# Windows (PowerShell)
$env:GROQ_API_KEY="la_tua_chiave"

# macOS/Linux
export GROQ_API_KEY="la_tua_chiave"
```

## 3. Avvio del programma

```bash
# Con interfaccia grafica
python gui.py

# Senza interfaccia grafica (solo console)
python main.py
```

## 4. Utilizzo base

1. Premi **AVVIA** per iniziare l'ascolto.
2. Parla nel microfono o trasmetti dalla radio.
3. Le trascrizioni appaiono in tempo reale.
4. Premi **STOP** per fermare.
5. Scegli se salvare la trascrizione (Sì/No).
6. Se il debug era attivo, scegli se salvare anche i log.
7. Puoi modificare i parametri principali dell'applicazione in qualsiasi momento premendo il pulsante **Configura** (si apre una finestra dedicata).

## 5. Modalità Debug

- Premi **DEBUG OFF** → diventa **DEBUG ON**.
- Si apre una finestra con i log in tempo reale.
- I log vengono accumulati in `transcriber.log`.
- Allo STOP, puoi salvarli (rinomino in `debug_YYYYMMDD_HHMMSS.log`) o cancellarli.

## 6. Configurazione avanzata

Modifica il file `config.json` nella cartella del progetto.

Parametri principali:
- `vad.aggressiveness`: 0-3 (1 = più sensibile)
- `vad.silence_timeout_s`: secondi di silenzio per fine frase
- `vad.min_segment_duration_s`: durata minima segmento
- `filter.enabled`: true/false (attiva filtro 300-3400 Hz)
- `api.groq.max_concurrent_requests`: richieste parallele a Groq (default 5)

## 7. Risoluzione problemi

**Errore "API key mancante"**:
- Imposta GROQ_API_KEY come variabile d'ambiente
- Oppure inseriscila in `config.json` (sezione `api.groq.api_key`)

**Il microfono non funziona**:
- Controlla Impostazioni Audio → Input → seleziona il dispositivo corretto
- Se usi la radio con cavo AUX, abbassa il volume al 20-30%

**Trascrizione lenta**:
- Verifica la connessione Internet
- Aumenta `max_concurrent_requests` in config.json

## 8. Specifiche tecniche

- Linguaggio: Python 3.11+
- Librerie: PyAudio, WebRTC VAD, NumPy, Requests, SciPy
- Modello AI: Groq Cloud (Whisper-large-v3)
- Audio: PCM 16kHz, mono, 16-bit
- Concorrenza: ThreadPoolExecutor (configurabile)
- Output: GUI Tkinter, file .txt, console, log
- Sistemi: Windows, macOS, Linux

---

## 9. Finestra di Configurazione

L'applicazione include una finestra grafica che ti permette di modificare i parametri principali di `config.json` senza dover aprire manualmente il file.

### Come aprirla

Nella finestra principale, premi il pulsante **Configura** (o simile). Si aprirà una nuova finestra con tutte le impostazioni.

### Cosa puoi modificare

La finestra è organizzata in tre sezioni:

- **Voice Activity Detection (VAD)**:
  - **Aggressiveness**: sensibilità del rilevatore vocale (0 = meno sensibile, 3 = più aggressivo).
  - **Silence timeout**: secondi di silenzio necessari per chiudere una frase.
  - **Max utterance**: durata massima di un singolo segmento prima del taglio forzato.
  - **Min segment duration**: durata minima per considerare un segmento valido (segmenti più brevi vengono scartati).
  - **Activation ratio**: rapporto minimo di frame vocali per attivare un segmento.

- **Filtro Passa-Banda**:
  - **Abilitato**: attiva o disattiva il filtro passa-banda (300-3400 Hz tipico per voce).
  - **Band min/max**: frequenze di taglio in Hertz.

- **API Groq**:
  - **Modello**: il modello Whisper da utilizzare (`whisper-large-v3-turbo` per velocità, `whisper-large-v3` per maggiore accuratezza).
  - **Timeout**: tempo massimo di attesa per una risposta dall'API.
  - **Max concurrent requests**: numero di richieste parallele a Groq (aumentare può velocizzare la trascrizione su connessioni veloci).
  - **Usa FLAC**: abilita la compressione FLAC per ridurre i dati inviati (consigliato).

### Come usarla

1.  Modifica i valori che ti interessano.
2.  Premi **APPLICA** per salvare le modifiche su disco e applicarle all'applicazione senza chiudere la finestra. Puoi usare questo pulsante per testare le nuove impostazioni in tempo reale.
3.  Premi **OK** per salvare le modifiche e chiudere la finestra.

**Importante**: alcune modifiche, come quelle relative al VAD o al filtro, richiedono l'arresto e il riavvio del trascrittore per avere effetto. Puoi farlo premendo **STOP** e poi **AVVIA** di nuovo.

Le modifiche vengono salvate in `config.json`. La finestra è progettata per aggiornare solo i valori modificati, preservando il resto della configurazione.

---

**Nota per l'utente finale**: se non sei sicuro di cosa modificare, è consigliabile lasciare i valori predefiniti. La finestra di configurazione è pensata per utenti esperti che vogliono ottimizzare il comportamento del sistema.

---

**Versione manuale:** 1.0 (06/07/2026)