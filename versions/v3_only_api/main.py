import sys
import threading
import time
import numpy as np
from config import load_config
from audio import AudioCapture
from vad import VADProcessor
from transcriber import Transcriber
from logger import get_logger

logger = get_logger()


def _soft_limiter(audio_float, threshold=0.3, ratio=0.5):
    """
    Limita dolcemente i picchi sopra 'threshold' invece di un hard clip
    secco. Un clip netto (np.clip diretto sul segnale intero) introduce
    distorsione armonica udibile su ogni campione che supera la soglia;
    qui invece l'eccesso oltre 'threshold' viene compresso di 'ratio'
    (0-1: più basso = compressione più aggressiva), quindi il segnale
    resta continuo e la transizione è meno brusca.
    """
    out = audio_float.copy()
    over = np.abs(out) > threshold
    sign = np.sign(out[over])
    excess = np.abs(out[over]) - threshold
    out[over] = sign * (threshold + excess * ratio)
    return np.clip(out, -1.0, 1.0)


def preprocess_radio_audio(audio_int16, rate=16000):
    """
    Preprocessing per audio radiofonico:
    1. Normalizzazione del picco (AGC)
    2. Limitatore soft sui picchi (compressione leggera reale, non un hard clip)
    3. Normalizzazione finale

    NOTA: il filtro passa-banda non viene più applicato qui. È applicato in
    modo centralizzato da Transcriber (config filter.*) per evitare due
    filtri passa-banda in cascata, che restringerebbero la banda più del
    previsto e aggiungerebbero distorsione di fase non necessaria.
    """
    audio_float = audio_int16.astype(np.float32) / 32768.0

    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val

    audio_float = _soft_limiter(audio_float, threshold=0.3, ratio=0.5)

    max_val = np.max(np.abs(audio_float))
    if max_val > 0:
        audio_float = audio_float / max_val * 0.9

    audio_float = np.clip(audio_float, -1.0, 1.0)
    return (audio_float * 32767).astype(np.int16)


def _run_radio_mode(audio, transcriber, rate, frame_samples, radio_cfg):
    """
    Modalità radio: bypassa il VAD e segmenta a durata fissa.

    Il buffer è un array numpy pre-allocato con scrittura via slicing,
    non una lista con np.append ripetuto: np.append ricopia l'intero
    array ad ogni chiamata, quindi con un frame ogni 30ms si ricopiava
    l'intero buffer (fino a ~48000 campioni per segmenti da 3s) decine
    di volte al secondo per tutta la sessione.
    """
    segment_duration_s = radio_cfg.get("segment_duration_s", 3.0)
    overlap_s = radio_cfg.get("overlap_s", 0.0)
    silence_gate_enabled = radio_cfg.get("silence_gate_enabled", False)
    silence_rms_threshold = radio_cfg.get("silence_rms_threshold", 300)

    segment_samples = int(rate * segment_duration_s)
    overlap_samples = int(rate * overlap_s)
    # Margine di sicurezza pari a un frame extra, per non dover troncare
    # se l'ultimo frame scritto supera esattamente segment_samples.
    buffer_capacity = segment_samples + overlap_samples + frame_samples

    radio_buffer = np.empty(buffer_capacity, dtype=np.int16)
    write_pos = 0

    logger.info(
        "📻 Modalità RADIO attivata: bypass VAD, segmenti di %.1fs, overlap %.1fs, gate silenzio %s",
        segment_duration_s, overlap_s, "ON" if silence_gate_enabled else "OFF"
    )
    print("\n=== ASCOLTO RADIO (con preprocessing) ===")
    print(f"API: Groq ({transcriber.groq_model})")
    print("Premi Ctrl+C per terminare.\n")

    try:
        while audio.is_running:
            frame = audio.get_frame(timeout=0.5)
            if frame is None:
                continue

            frame_np = np.frombuffer(frame, dtype=np.int16)
            n = len(frame_np)
            if write_pos + n > buffer_capacity:
                # Non dovrebbe succedere con il dimensionamento sopra,
                # ma tronchiamo per sicurezza invece di sollevare un errore.
                n = buffer_capacity - write_pos
                if n <= 0:
                    continue
                frame_np = frame_np[:n]

            radio_buffer[write_pos:write_pos + n] = frame_np
            write_pos += n

            while write_pos >= segment_samples:
                segment = radio_buffer[:segment_samples].copy()
                logger.debug("Buffer radio pieno: segmento da %d campioni pronto per il gate.", segment_samples)

                # Gate energetico: salta segmenti praticamente silenziosi.
                # Evita chiamate Groq sprecate su dead air e riduce le
                # "allucinazioni" di Whisper (testo plausibile inventato
                # quando riceve solo rumore/silenzio).
                send_segment = True
                if silence_gate_enabled:
                    rms = float(np.sqrt(np.mean(segment.astype(np.float64) ** 2)))
                    if rms < silence_rms_threshold:
                        send_segment = False
                        logger.debug(
                            "Segmento radio SCARTATO: RMS %.1f sotto soglia %.1f (silenzio).",
                            rms, silence_rms_threshold
                        )
                    else:
                        logger.debug(
                            "Segmento radio ACCETTATO: RMS %.1f sopra soglia %.1f.",
                            rms, silence_rms_threshold
                        )

                if send_segment:
                    processed = preprocess_radio_audio(segment, rate=rate)
                    transcriber.enqueue(processed)

                # Gestione overlap: sposta indietro gli ultimi overlap_samples
                # campioni così il prossimo segmento inizia con un po' di
                # contesto dal precedente, riducendo il taglio di parole
                # esattamente al confine tra un segmento e l'altro.
                # NOTA: questo può causare piccole ripetizioni di parole ai
                # bordi nella trascrizione finale; una cucitura testuale
                # completa sarebbe più corretta ma è fuori scopo qui.
                remaining = write_pos - segment_samples
                if overlap_samples > 0:
                    tail_start = segment_samples - overlap_samples
                    tail = radio_buffer[tail_start:segment_samples].copy()
                    radio_buffer[:overlap_samples] = tail
                    if remaining > 0:
                        radio_buffer[overlap_samples:overlap_samples + remaining] = \
                            radio_buffer[segment_samples:segment_samples + remaining]
                    write_pos = overlap_samples + remaining
                else:
                    if remaining > 0:
                        radio_buffer[:remaining] = radio_buffer[segment_samples:segment_samples + remaining]
                    write_pos = remaining

    except KeyboardInterrupt:
        print("\nChiusura in corso...")
        logger.info("Interruzione da tastiera ricevuta.")
    finally:
        audio.stop()
        transcriber.stop()
        logger.info("Programma terminato.")


def _run_vad_mode(audio, transcriber, rate, frame_duration_ms, vad_cfg):
    """Modalità normale: segmentazione tramite VAD (rispetta i confini del parlato)."""
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


def main():
    logger.info("🚀 Avvio Audio Transcriber v3.0")
    config = load_config()

    rate = config.get("audio", {}).get("rate", 16000)
    channels = config.get("audio", {}).get("channels", 1)
    frame_duration_ms = config.get("audio", {}).get("frame_duration_ms", 30)
    chunk = int(rate * frame_duration_ms / 1000)
    frame_samples = chunk  # un frame audio contiene 'chunk' campioni

    radio_cfg = config.get("radio", {})
    radio_enabled = radio_cfg.get("enabled", False)
    bypass_vad = radio_cfg.get("bypass_vad", False)

    audio = AudioCapture(rate=rate, channels=channels, chunk=chunk)
    transcriber = Transcriber(config)
    audio.start()

    if radio_enabled and bypass_vad:
        _run_radio_mode(audio, transcriber, rate, frame_samples, radio_cfg)
    else:
        vad_cfg = config.get("vad", {})
        _run_vad_mode(audio, transcriber, rate, frame_duration_ms, vad_cfg)


if __name__ == "__main__":
    main()