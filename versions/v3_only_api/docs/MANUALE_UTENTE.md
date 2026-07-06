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

**Versione manuale:** 1.0 (06/07/2026)