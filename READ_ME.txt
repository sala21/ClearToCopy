-----------------------------
FLUSSO LOGICO
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