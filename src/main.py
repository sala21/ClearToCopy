import threading
from config import load_config
from audio import AudioCapture
from vad import VADProcessor
from transcriber import Transcriber
from logger import get_logger

logger = get_logger()

def run_pipeline(config, event_bus=None, stop_event=None, components_ref=None, transcriber=None):
    
    if stop_event is None:
        stop_event = threading.Event()

    rate = config.get("audio", {}).get("rate", 16000)
    channels = config.get("audio", {}).get("channels", 1)
    frame_duration_ms = config.get("audio", {}).get("frame_duration_ms", 30)
    chunk = int(rate * frame_duration_ms / 1000)

    vad_cfg = config.get("vad", {})
    aggressiveness = vad_cfg.get("aggressiveness", 1)
    silence_timeout_s = vad_cfg.get("silence_timeout_s", 1.0)
    max_utterance_s = vad_cfg.get("max_utterance_s", 15.0)
    min_segment_duration_s = vad_cfg.get("min_segment_duration_s", 0.6)
    activation_ratio = vad_cfg.get("activation_ratio", 0.4)

    audio = AudioCapture(rate=rate, channels=channels, chunk=chunk)

    # Tiene traccia di chi possiede il ciclo di vita del Transcriber: se è stato
    # creato qui dentro (caso CLI, transcriber=None in ingresso), questa funzione
    # è responsabile di fermarlo all'uscita. Se invece è stato passato dall'esterno
    # già pronto (caso GUI, dove il modello resta caricato tra un Avvia/Stop e
    # l'altro), il rilascio resta responsabilità del chiamante (TranscriberGUI.on_close).
    owns_transcriber = transcriber is None

    if transcriber is None:
        try:
            transcriber = Transcriber(config, event_bus=event_bus)
            if event_bus:
                event_bus.emit("model_loaded")
        except Exception:
            audio.stop()
            raise

    else:
        if event_bus is not None:
            if hasattr(transcriber, 'event_bus'):
                transcriber.event_bus = event_bus
            # Se ha un metodo setter, usalo
            elif hasattr(transcriber, 'set_event_bus'):
                transcriber.set_event_bus(event_bus)

    transcriber.set_audio_reference(audio)

    vad = VADProcessor(
        rate=rate,
        frame_duration_ms=frame_duration_ms,
        aggressiveness=aggressiveness,
        silence_timeout_s=silence_timeout_s,
        max_utterance_s=max_utterance_s,
        min_segment_duration_s=min_segment_duration_s,
        activation_ratio=activation_ratio,
        event_bus=event_bus,
        rms_threshold=config.get("radio", {}).get("silence_rms_threshold", 50.0)
    )

    if components_ref is not None:
        components_ref["audio"] = audio
        components_ref["vad"] = vad
        components_ref["transcriber"] = transcriber

    def on_segment_ready(audio_np):
        transcriber.enqueue(audio_np)

    vad.set_callback(on_segment_ready)

    audio.start()
    if event_bus:
        event_bus.emit("audio_started")

    logger.info("Audio capture avviato. In ascolto...")
    if event_bus:
        event_bus.emit("status", message="Ascolto attivo")

    try:
        while audio.is_running and not stop_event.is_set():
            frame = audio.get_frame(timeout=0.5)
            if frame is None:
                continue
            vad.process_frame(frame)
    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera ricevuta.")
    finally:
        audio.stop()
        if owns_transcriber:
            # Solo se il Transcriber è stato creato qui dentro (modalità CLI):
            # libera la VRAM e ferma i thread interni prima di uscire. Se invece
            # è stato passato dall'esterno (GUI), resta caricato — lo ferma
            # esplicitamente TranscriberGUI.on_close() alla chiusura della finestra.
            transcriber.stop()
        logger.info("Pipeline terminato.")


def main():
    config = load_config()
    run_pipeline(config)


if __name__ == "__main__":
    main()