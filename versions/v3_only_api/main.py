import sys
import threading
import time
import numpy as np
from config import load_config
from audio import AudioCapture
from vad import VADProcessor
from transcriber import Transcriber
from logger import get_logger

# Importa scipy per i filtri
try:
    from scipy import signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

logger = get_logger()

def preprocess_radio_audio(audio_int16, rate=16000):
    """
    Preprocessing per audio radiofonico:
    1. Normalizzazione del picco (AGC)
    2. Filtro passa-banda stretto (300-3000 Hz) per enfatizzare la voce
    3. Compressore leggero (riduce i picchi e alza le parti basse)
    """
    # Converte in float per il processing
    audio_float = audio_int16.astype(np.float32) / 32768.0

    # 1. Normalizzazione (già fatta, ma la rifacciamo per sicurezza)
    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val

    # 2. Filtro passa-banda per enfatizzare la voce (300-3000 Hz)
    if SCIPY_AVAILABLE:
        # Coefficienti del filtro pre-calcolati (una volta sola per efficienza)
        # Li calcoliamo solo se non esistono già
        if not hasattr(preprocess_radio_audio, "_filter_b"):
            b = signal.firwin(65, [300, 3000], fs=rate, pass_zero=False)
            a = [1.0]
            preprocess_radio_audio._filter_b = b
            preprocess_radio_audio._filter_a = a
        audio_float = signal.lfilter(
            preprocess_radio_audio._filter_b,
            preprocess_radio_audio._filter_a,
            audio_float
        )

    # 3. Compressione leggera (riduce i picchi e alza le parti basse)
    threshold = 0.3
    gain = 2.0
    audio_float = np.clip(audio_float * gain, -1.0, 1.0)

    # 4. Normalizzazione finale e riconversione in int16
    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val * 0.9
    audio_int16 = (audio_float * 32767).astype(np.int16)

    return audio_int16


def main():
    logger.info("🚀 Avvio Audio Transcriber v3.0")
    config = load_config()

    rate = config.get("audio", {}).get("rate", 16000)
    channels = config.get("audio", {}).get("channels", 1)
    frame_duration_ms = config.get("audio", {}).get("frame_duration_ms", 30)
    chunk = int(rate * frame_duration_ms / 1000)

    radio_cfg = config.get("radio", {})
    radio_enabled = radio_cfg.get("enabled", False)
    segment_duration_s = radio_cfg.get("segment_duration_s", 3.0)
    bypass_vad = radio_cfg.get("bypass_vad", False)

    audio = AudioCapture(rate=rate, channels=channels, chunk=chunk)
    transcriber = Transcriber(config)

    if radio_enabled and bypass_vad:
        logger.info("📻 Modalità RADIO attivata: bypass VAD, segmenti di %.1fs", segment_duration_s)
        audio.start()
        print("\n=== ASCOLTO RADIO (con preprocessing) ===")
        print(f"API: Groq ({transcriber.groq_model})")
        print("Premi Ctrl+C per terminare.\n")

        segment_samples = int(rate * segment_duration_s)
        audio_buffer = np.array([], dtype=np.int16)

        try:
            while audio.is_running:
                frame = audio.get_frame(timeout=0.5)
                if frame is None:
                    continue
                frame_np = np.frombuffer(frame, dtype=np.int16)
                audio_buffer = np.append(audio_buffer, frame_np)

                while len(audio_buffer) >= segment_samples:
                    segment = audio_buffer[:segment_samples]
                    audio_buffer = audio_buffer[segment_samples:]

                    # APPLICA IL PREPROCESSING (la novità!)
                    segment = preprocess_radio_audio(segment, rate=rate)

                    transcriber.enqueue(segment)
        except KeyboardInterrupt:
            print("\nChiusura in corso...")
            logger.info("Interruzione da tastiera ricevuta.")
        finally:
            audio.stop()
            transcriber.stop()
            logger.info("Programma terminato.")
    else:
        # Modalità normale (con VAD)...
        vad_cfg = config.get("vad", {})
        aggressiveness = vad_cfg.get("aggressiveness", 2)
        silence_timeout_s = vad_cfg.get("silence_timeout_s", 1.2)
        max_utterance_s = vad_cfg.get("max_utterance_s", 20.0)
        min_segment_duration_s = vad_cfg.get("min_segment_duration_s", 0.6)
        activation_ratio = vad_cfg.get("activation_ratio", 0.6)

        vad = VADProcessor(
            rate=rate,
            frame_duration_ms=frame_duration_ms,
            aggressiveness=aggressiveness,
            silence_timeout_s=silence_timeout_s,
            max_utterance_s=max_utterance_s,
            min_segment_duration_s=min_segment_duration_s,
            activation_ratio=activation_ratio
        )

        def on_segment_ready(audio_np):
            transcriber.enqueue(audio_np)
        vad.set_callback(on_segment_ready)

        audio.start()

        print("\n=== ASCOLTO ATTIVO (con VAD) ===")
        print(f"API: Groq ({transcriber.groq_model})")
        print("Premi Ctrl+C per terminare.\n")
        logger.info("Audio capture avviato. In ascolto...")

        try:
            while audio.is_running:
                frame = audio.get_frame(timeout=0.5)
                if frame is None:
                    continue
                vad.process_frame(frame)
        except KeyboardInterrupt:
            print("\nChiusura in corso...")
            logger.info("Interruzione da tastiera ricevuta.")
        finally:
            audio.stop()
            transcriber.stop()
            logger.info("Programma terminato.")

if __name__ == "__main__":
    main()