-----------------------------
SET-UP AMBIENTE
-----------------------------
1. Crea un nuovo ambiente virtuale:     python -m venv venv

2. Attivalo:    venv\Scripts\activate

3. Installa le dipendenze:      pip install -r requirements.txt


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