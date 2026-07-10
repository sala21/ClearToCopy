# Test locale: WhisperATC vs Groq

Script isolato per capire se il modello `jlvdoorn/whisper-large-v3-atco2-asr(-atcosim)`
funziona bene sulla tua RTX 5050 e se la qualità ti convince, PRIMA di integrarlo
nella pipeline vera (`transcriber.py`).

## 1. Installazione (una volta sola)

Apri un terminale nella cartella del progetto e crea un ambiente virtuale dedicato
(consigliato, per non toccare le dipendenze della pipeline principale):

```bash
python -m venv venv-whisperatc
venv-whisperatc\Scripts\activate      # Windows
# oppure: source venv-whisperatc/bin/activate   # Linux/Mac
```

Installa PyTorch con supporto CUDA. Vai su https://pytorch.org/get-started/locally/,
seleziona la tua combinazione (OS / Pip / CUDA) e copia il comando esatto — di solito
è simile a:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

Poi installa il resto:

```bash
pip install -r requirements.txt
```

## 2. Verifica che la GPU sia visibile

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Deve stampare `True` e il nome della tua scheda. Se stampa `False`, il problema è
nell'installazione di torch/driver CUDA, non nello script — fermati qui e sistema
quello prima di andare avanti.

## 3. Esegui il test

Scegli 2-3 file audio che hai già registrato con la pipeline attuale (idealmente
con audio "difficile": callsign lunghi, rumore di fondo) e per cui hai già visto
cosa ti risponde Groq, così puoi confrontare a occhio.

```bash
python test_local_model.py percorso/file1.wav percorso/file2.wav --model combined
```

`--model` può essere `atco2`, `atcosim` o `combined` (default: `combined`, allenato
su entrambi i dataset — di solito il più robusto come punto di partenza).

La prima esecuzione scarica il modello da Hugging Face (~3GB, ci mette un po');
le successive lo carica dalla cache locale (`~/.cache/huggingface`), molto più veloce.

## 4. Cosa guardare nell'output

- **RTF (real-time factor)**: se è < 1, il modello trascrive più veloce del tempo
  reale dell'audio (buon segno per l'uso in pipeline). Se è vicino o sopra 1,
  con 8GB di VRAM potresti dover accettare qualche secondo di latenza in più
  rispetto a Groq — da valutare se accettabile per il tuo caso d'uso.
- **Picco VRAM utilizzata**: se si avvicina troppo agli 8GB della 5050, in
  produzione (con più cose in memoria: sistema operativo, altre app) potresti
  andare in out-of-memory. Se è già oltre 6-6.5GB qui, ne parliamo per capire
  come ridurlo (quantizzazione a 8 bit, batch più piccoli).
- **Qualità del testo**: confronta a orecchio con l'output Groq sugli stessi
  file, soprattutto su callsign, numeri e squawk — sono i punti dove un modello
  specializzato ATC dovrebbe fare la differenza.

## Se qualcosa va storto

- `CUDA out of memory` → prova prima con `--model atco2` (dataset più piccolo,
  ma il checkpoint ha comunque le stesse dimensioni di large-v3... in realtà
  la dimensione del modello è la stessa per tutte e 3 le varianti, quindi se
  va in OOM con una va in OOM con tutte: fammi sapere e passiamo a caricare
  il modello quantizzato a 8-bit, che dimezza la VRAM necessaria).
- Errori di import/libreria mancante → manda l'errore completo, sistemiamo
  le versioni.
- Trascrizione vuota o piena di rumore → prova ad alzare `max_new_tokens`
  nello script se i tuoi segmenti audio sono più lunghi di ~15-20 secondi.
