import sys
import threading
import time

from config import load_config
from audio import AudioCapture
from vad import VADProcessor
from transcriber import Transcriber

def main():
    # 1. Carica configurazione
    config = load_config()

    # 2. Estrai parametri
    rate = config.get("audio", {}).get("rate", 16000)
    channels = config.get("audio", {}).get("channels", 1)
    frame_duration_ms = config.get("audio", {}).get("frame_duration_ms", 30)
    chunk = int(rate * frame_duration_ms / 1000)

    vad_cfg = config.get("vad", {})
    aggressiveness = vad_cfg.get("aggressiveness", 2)
    silence_timeout_s = vad_cfg.get("silence_timeout_s", 1.2)
    max_utterance_s = vad_cfg.get("max_utterance_s", 20.0)
    min_segment_duration_s = vad_cfg.get("min_segment_duration_s", 0.6)

    # 3. Inizializza componenti
    audio = AudioCapture(rate=rate, channels=channels, chunk=chunk)
    transcriber = Transcriber(config)
    vad = VADProcessor(
        rate=rate,
        frame_duration_ms=frame_duration_ms,
        aggressiveness=aggressiveness,
        silence_timeout_s=silence_timeout_s,
        max_utterance_s=max_utterance_s,
        min_segment_duration_s=min_segment_duration_s
    )

    # 4. Collega VAD al transcriber
    def on_segment_ready(audio_np):
        transcriber.enqueue(audio_np)
    vad.set_callback(on_segment_ready)

    # 5. Avvia audio
    audio.start()

    print("\n=== ASCOLTO ATTIVO ===")
    print(f"API: Groq ({transcriber.groq_model})")
    print("Premi Ctrl+C per terminare.\n")

    # 6. Loop principale
    try:
        while audio.is_running:
            frame = audio.get_frame(timeout=0.5)
            if frame is None:
                continue
            vad.process_frame(frame)
    except KeyboardInterrupt:
        print("\nChiusura in corso...")
    finally:
        audio.stop()
        transcriber.stop()
        print("Programma terminato.")

if __name__ == "__main__":
    main()
