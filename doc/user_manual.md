# ClearToCopy — Manuale Utente

**ClearToCopy** è un'applicazione desktop per la trascrizione in tempo reale di comunicazioni radio ATC (Air Traffic Control). Cattura l'audio da microfono o linea audio, isola automaticamente le singole trasmissioni con un rilevatore di attività vocale (VAD), e le trascrive con un modello Whisper specializzato in fraseologia aeronautica — **eseguito interamente in locale sulla GPU del computer**, senza inviare alcun dato audio a servizi esterni.

---

## Indice

1. [Panoramica](#-panoramica)
2. [Requisiti di sistema](#-requisiti-di-sistema)
3. [Avvio dell'applicazione](#-avvio-dellapplicazione)
4. [Interfaccia principale](#-interfaccia-principale)
5. [Comandi e controlli](#-comandi-e-controlli)
6. [Menu laterale](#-menu-laterale)
7. [Finestra di configurazione](#-finestra-di-configurazione)
8. [Finestra di debug](#-finestra-di-debug)
9. [Stati e indicatori](#-stati-e-indicatori)
10. [Salvataggio delle trascrizioni](#-salvataggio-delle-trascrizioni)
11. [Salvataggio dei log di debug](#-salvataggio-dei-log-di-debug)
12. [Risoluzione dei problemi](#-risoluzione-dei-problemi)

---

## Panoramica

ClearToCopy è pensato per:

- **Trascrivere in tempo reale** le comunicazioni radio ATC catturate dal microfono o da una linea audio collegata al computer.
- **Rilevare automaticamente** l'inizio e la fine di ogni trasmissione, grazie al rilevatore di attività vocale (VAD).
- **Filtrare l'audio** con un filtro passa-banda (300–3400 Hz) per isolare la voce umana dal rumore di fondo.
- **Mostrare in tempo reale** il livello del segnale audio, lo stato del sistema e le metriche di elaborazione.
- **Salvare** le trascrizioni su file `.txt` e, se necessario, i log tecnici su file separati.

L'intera trascrizione avviene **sul tuo computer**: non è richiesta una connessione internet durante il funzionamento (serve solo la prima volta, per scaricare il modello, e per l'avvio di ogni sessione dell'applicazione).

---

## Requisiti di sistema

- **Sistema operativo**: Windows 10/11 (ambiente di riferimento)
- **Python** 3.10 o superiore, con le dipendenze del progetto già installate (vedi [`README.md`](../README.md))
- **GPU NVIDIA** con almeno 8 GB di VRAM, driver aggiornato — fortemente consigliata. In assenza di GPU compatibile, l'applicazione può girare su CPU, ma con tempi di trascrizione molto più lunghi.
- **Microfono o linea audio** configurata correttamente nel sistema operativo.
- Circa **3 GB di spazio libero su disco** per il modello di trascrizione (scaricato automaticamente al primo avvio).
- **Pillow** (opzionale): se presente, mostra una piccola illustrazione decorativa nel menu laterale. Se assente, l'applicazione funziona comunque normalmente, semplicemente senza quel dettaglio grafico.

---

## Avvio dell'applicazione

Da terminale, nella cartella del progetto (con l'ambiente virtuale attivo):

```bash
python gui_main.py
```

Si apre la finestra principale. **Il modello di trascrizione viene caricato automaticamente e subito**, non appena la finestra compare — non serve alcuna azione da parte tua. Durante questa fase:

- Il pulsante **▶ AVVIA** resta disabilitato.
- La barra inferiore mostra `⏳ Caricamento modello in corso...`.
- L'indicatore **🧠 Modello Locale** nel pannello di stato resta rosso.

Il caricamento può richiedere fino a circa un minuto (dipende dalla velocità del disco e se il modello è già in cache da un avvio precedente). Al termine, il pulsante **▶ AVVIA** si attiva e la barra mostra `✅ Modello caricato. Premi 'Avvia' per iniziare.`

> 💡 **Il modello resta in memoria per tutta la durata della sessione dell'applicazione**, anche se premi più volte STOP e poi AVVIA: solo la prima volta, all'apertura del programma, c'è da attendere. Il modello viene scaricato dalla memoria video (VRAM) solo quando chiudi completamente la finestra.

---

## Interfaccia principale

La finestra è divisa in tre aree:

### Intestazione (in alto)

- **☰ Menu**: mostra/nasconde il menu laterale.
- **Indicatore di stato**: pallino colorato + etichetta testuale (`FERMO`, `IN ASCOLTO`) che riassume lo stato generale dell'applicazione.

### Colonna centrale (dashboard)

- **Livello Segnale (RMS)**: un misuratore orizzontale che mostra in tempo reale il livello del segnale audio in ingresso, con una linea verticale che indica la soglia oltre la quale l'audio viene considerato "parlato" e non silenzio. Sotto al misuratore, un'etichetta numerica riporta RMS, soglia, ed esito (`● ACCETTATO` o `○ SILENZIO (scartato)`).
- **Trascrizione**: il pannello principale, dove compare il testo trascritto, riga per riga, ciascuna preceduta dall'orario in cui è stata riconosciuta. Se un segmento audio non produce testo riconoscibile, compare la dicitura `(nessun testo riconosciuto)`.

### Colonna laterale destra

- **Dettagli Configurazione**: riepilogo rapido e in sola lettura di modello in uso, lingua, sensibilità VAD e device (`cuda`/`cpu`).
- **Stato Sistema**: tre indicatori — Microfono, Modello Locale, Filtro — ciascuno con pallino colorato (verde = attivo/ok, rosso = non attivo) e testo di stato. Include anche il tempo trascorso dall'avvio della trascrizione (**Uptime**).
- **Metriche**: contatori aggiornati in tempo reale — segmenti audio inviati, completati, falliti, tempo medio di elaborazione, dimensione della coda in attesa.

### Barra inferiore

Una riga di testo colorato che mostra l'ultimo messaggio di stato o errore dell'applicazione (es. conferme di salvataggio, avvisi, errori).

---

## Comandi e controlli

| Comando | Funzione |
|---|---|
| **▶ AVVIA** | Avvia la cattura audio e la trascrizione. Disponibile solo dopo che il modello è stato caricato (vedi [Avvio dell'applicazione](#-avvio-dellapplicazione)). Ogni volta che viene premuto, i contatori delle metriche vengono azzerati, ma il modello resta caricato in memoria — l'avvio è quindi rapido. |
| **■ STOP** | Ferma la cattura audio e la trascrizione (il modello resta comunque caricato in memoria, pronto per un nuovo Avvia). Prima di fermarsi, l'applicazione chiede se vuoi salvare la trascrizione accumulata e, se la modalità debug è attiva, anche il log tecnico. |
| **DEBUG ON/OFF** | Attiva/disattiva la registrazione dettagliata dei log tecnici su file, utile in caso di comportamenti anomali da segnalare. Non influisce sulla trascrizione stessa. |
| **☰ Menu** | Mostra/nasconde il menu laterale. |

---

## Menu laterale

Accessibile tramite il pulsante **☰ Menu** in alto a sinistra, contiene tre pulsanti:

- **Debug**: apre la [finestra di debug](#-finestra-di-debug), che mostra in tempo reale il contenuto del file di log.
- **Config**: apre la [finestra di configurazione](#-finestra-di-configurazione).
- **Ric CFG Live**: ricarica `config.json` da disco e applica a caldo le modifiche a VAD, filtro e (in parte) ai parametri del modello, **senza dover fermare e riavviare la trascrizione**. Funziona solo se la trascrizione è già in corso (dopo aver premuto AVVIA).

---

## Finestra di configurazione

Apribile dal menu laterale (**⚙️ Config**), permette di modificare `config.json` senza editarlo manualmente a mano. È divisa in quattro sezioni:

### Voice Activity Detection (VAD)

| Campo | Significato |
|---|---|
| Aggressiveness (0-3) | Quanto il rilevatore è selettivo nel distinguere parlato da rumore. Valori più alti = più selettivo, rischio di perdere parlato debole. |
| Silence timeout (s) | Quanto silenzio continuo serve per considerare conclusa una trasmissione. |
| Max utterance (s) | Durata massima di un singolo segmento, oltre la quale viene tagliato forzatamente. |
| Min segment duration (s) | Durata minima sotto la quale un segmento viene scartato come probabile rumore. |
| Activation ratio (0-1) | Quanto "convintamente" deve essere rilevato del parlato prima di iniziare a registrare un segmento. |

### Filtro Passa-Banda

| Campo | Significato |
|---|---|
| Abilitato | Attiva/disattiva il filtro. |
| Band min / Band max (Hz) | Intervallo di frequenze lasciato passare — di default tarato sulla voce umana su radio VHF. |

### Modello Locale

| Campo | Significato |
|---|---|
| Nome modello | Identificativo del modello Whisper da usare (repository Hugging Face). |
| Device (cpu/cuda) | Dove eseguire l'inferenza. |
| Lingua | Lingua forzata per la trascrizione. |

> ⚠️ Modificare **Nome modello** o **Device** richiede di fermare e riavviare l'intera applicazione (chiudere e riaprire la finestra) per avere effetto — non basta STOP/AVVIA, perché il modello viene caricato una sola volta all'apertura del programma.

### Impostazioni Radio

| Campo | Significato |
|---|---|
| Bypass VAD (true/false) | Riservato a una modalità di segmentazione alternativa al VAD, **non ancora disponibile** in questa versione. Se impostato su `true`, l'applicazione lo segnala nella barra "Modalità" ma continua comunque a usare il VAD classico. |

**Pulsanti:**
- **🔄 APPLICA**: salva su `config.json` e applica subito le modifiche, senza chiudere la finestra.
- **✅ OK**: chiude la finestra. **Importante:** se non hai mai premuto "Applica" durante quella sessione della finestra, "OK" chiude senza salvare le modifiche — premi sempre prima **APPLICA** se vuoi che le modifiche abbiano effetto, poi eventualmente "OK" per chiudere.

---

## Finestra di debug

Mostra in tempo reale (aggiornamento ogni mezzo secondo) il contenuto del file di log tecnico dell'applicazione (`transcriber.log`, nella cartella del progetto). Utile per capire cosa sta succedendo "dietro le quinte" in caso di comportamenti inattesi, o da allegare a una segnalazione di problema.

---

## Stati e indicatori

| Indicatore | Significato |
|---|---|
| 🟢 pallino verde | Componente attivo / funzionante |
| 🔴 pallino rosso | Componente non attivo / in errore |
| Stato generale `FERMO` | Trascrizione non in corso (il modello può comunque essere già caricato) |
| Stato generale `IN ASCOLTO` | Trascrizione in corso |
| Modello Locale `NON CARICATO` | Caricamento non ancora avviato o fallito |
| Modello Locale `CARICATO` | Modello pronto in VRAM |

**Colori del misuratore di livello (RMS):**
- Grigio: al di sotto della soglia (silenzio)
- Verde: livello normale
- Ambra: livello alto
- Rosso: livello molto alto, possibile saturazione del segnale

---

## Salvataggio delle trascrizioni

Premendo **■ STOP**, se sono state raccolte righe di trascrizione, l'applicazione chiede se salvarle in un file di testo. Confermando, viene creato un file nella cartella del progetto con nome nel formato:

```
transcript_AAAAMMGG_HHMMSS.txt
```

Se scegli di non salvare, la trascrizione accumulata viene scartata definitivamente — assicurati di rispondere "Sì" se ti serve conservarla. Ricomincia da zero a ogni nuovo **▶ AVVIA**.

---

## Salvataggio dei log di debug

Se la modalità **DEBUG** è stata attivata durante la sessione, disattivandola (o premendo **■ STOP**) viene chiesto se salvare o eliminare il file di log tecnico (`transcriber.log`):

- **Salva**: il file viene rinominato con un timestamp (es. `debug_20260710_143200.log`) e conservato.
- **Elimina**: il contenuto del file viene cancellato.

---

## Risoluzione dei problemi

**L'avvio dell'applicazione impiega quasi un minuto**
Normale: è il tempo di caricamento del modello Whisper in memoria/VRAM, che avviene automaticamente all'apertura della finestra. Non serve fare nulla, basta attendere che "▶ AVVIA" si attivi.

**Il pulsante "▶ AVVIA" resta disabilitato a lungo o non si attiva mai**
Consulta la barra inferiore o la finestra di **Debug**: se compare un messaggio di errore relativo al caricamento del modello, la causa più comune è la GPU non disponibile o senza spazio sufficiente in VRAM. Verifica anche la connessione internet se è il primo avvio in assoluto (serve per scaricare il modello).

**Nessuna trascrizione compare nonostante si stia parlando alla radio**
Controlla il misuratore RMS: se il livello resta sempre sotto la soglia (barra grigia), il microfono potrebbe non essere quello giusto nelle impostazioni di sistema, oppure il volume è troppo basso. In alternativa, prova a ridurre `Aggressiveness` o `Activation ratio` nella finestra di configurazione.

**La trascrizione produce parole ripetute senza senso**
Sintomo tipico quando un segmento audio contiene una pausa lunga di silenzio al suo interno. Prova a ridurre `Silence timeout (s)` nella sezione VAD, in modo che i segmenti vengano tagliati più frequentemente sulle pause.

**Ho modificato la configurazione nella finestra "⚙️ Config" ma non è cambiato nulla**
Assicurati di aver premuto **🔄 APPLICA** (non solo "OK"): "OK" da solo non salva le modifiche se non è stata premuta almeno una volta "Applica" durante quella sessione della finestra.

**Il pulsante "Ric CFG Live" non sembra avere effetto**
Funziona solo mentre la trascrizione è **in corso** (dopo aver premuto AVVIA). Inoltre, modifiche al nome del modello o al device non vengono applicate da questo pulsante: richiedono di chiudere e riaprire l'intera applicazione.

**Per problemi non risolti da questa guida**, consulta il [Manuale Tecnico](technical_manual.md) o apri la finestra di Debug per raccogliere informazioni utili prima di segnalare il problema.
