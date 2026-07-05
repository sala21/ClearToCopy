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


def _find_best_cut_point(buffer, tentative_cut, search_samples, analysis_samples, min_cut):
    """
    Invece di tagliare esattamente a 'tentative_cut' (durata fissa), cerca
    il punto di minima energia in una finestra [min_cut, tentative_cut],
    così il taglio cade con più probabilità in una pausa reale del parlato
    invece che a metà di una parola.

    Il segnale viene diviso in sotto-finestre da 'analysis_samples' campioni
    e si sceglie l'inizio della sotto-finestra con energia RMS minima.
    'min_cut' impedisce di accorciare troppo il segmento (evita segmenti
    troppo corti se il parlato è continuo per tutta la finestra di ricerca).
    """
    search_start = max(min_cut, tentative_cut - search_samples)
    region = buffer[search_start:tentative_cut]
    if len(region) < analysis_samples:
        return tentative_cut

    n_windows = len(region) // analysis_samples
    if n_windows == 0:
        return tentative_cut

    best_offset = 0
    best_energy = None
    for i in range(n_windows):
        w = region[i * analysis_samples:(i + 1) * analysis_samples]
        energy = float(np.mean(w.astype(np.float64) ** 2))
        if best_energy is None or energy < best_energy:
            best_energy = energy
            best_offset = i * analysis_samples

    return search_start + best_offset


def _run_radio_mode(audio, transcriber, rate, frame_samples, radio_cfg, event_bus=None, stop_event=None):
    """
    Modalità radio: bypassa il VAD e segmenta a durata quasi fissa.

    Il buffer è un array numpy pre-allocato con scrittura via slicing,
    non una lista con np.append ripetuto: np.append ricopia l'intero
    array ad ogni chiamata, quindi con un frame ogni 30ms si ricopiava
    l'intero buffer (fino a ~48000 campioni per segmenti da 3s) decine
    di volte al secondo per tutta la sessione.

    Il punto di taglio non è più esattamente 'segment_samples': viene
    cercato il punto di minima energia negli ultimi 'boundary_search_s'
    secondi del segmento (vedi _find_best_cut_point), per evitare di
    tagliare a metà parola quando la pausa naturale tra le parole cade
    vicino al bordo del segmento.
    """
    segment_duration_s = radio_cfg.get("segment_duration_s", 3.0)
    overlap_s = radio_cfg.get("overlap_s", 0.0)
    silence_gate_enabled = radio_cfg.get("silence_gate_enabled", False)
    silence_rms_threshold = radio_cfg.get("silence_rms_threshold", 300)
    boundary_search_s = radio_cfg.get("boundary_search_s", 0.4)
    boundary_analysis_ms = radio_cfg.get("boundary_analysis_ms", 20)

    segment_samples = int(rate * segment_duration_s)
    overlap_samples = int(rate * overlap_s)
    search_samples = min(int(rate * boundary_search_s), segment_samples // 2)
    analysis_samples = max(1, int(rate * boundary_analysis_ms / 1000))
    # Non accorciare il segmento sotto il 60% della durata target, per
    # evitare segmenti troppo brevi quando il parlato copre tutta la
    # finestra di ricerca senza pause rilevabili.
    min_cut_samples = int(segment_samples * 0.6)
    # Margine di sicurezza pari a un frame extra, per non dover troncare
    # se l'ultimo frame scritto supera esattamente segment_samples.
    buffer_capacity = segment_samples + overlap_samples + frame_samples

    radio_buffer = np.empty(buffer_capacity, dtype=np.int16)
    write_pos = 0

    logger.info(
        "Modalità RADIO attivata: bypass VAD, segmenti di %.1fs (taglio dinamico su pausa, "
        "ricerca %.2fs, min %.1fs), overlap %.1fs, gate silenzio %s",
        segment_duration_s, boundary_search_s, min_cut_samples / rate, overlap_s,
        "ON" if silence_gate_enabled else "OFF"
    )
    print("\n=== ASCOLTO RADIO (con preprocessing) ===")
    print(f"API: Groq ({transcriber.groq_model})")
    print("Premi Ctrl+C per terminare.\n")

    try:
        while audio.is_running and not (stop_event and stop_event.is_set()):
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
                cut = _find_best_cut_point(
                    radio_buffer[:write_pos],
                    segment_samples,
                    search_samples,
                    analysis_samples,
                    min_cut_samples
                )
                if cut != segment_samples:
                    logger.debug(
                        "Taglio spostato su pausa rilevata: %d campioni (target %d, -%.2fs).",
                        cut, segment_samples, (segment_samples - cut) / rate
                    )
                segment = radio_buffer[:cut].copy()
                logger.debug("Buffer radio pieno: segmento da %d campioni pronto per il gate.", cut)

                # Gate energetico: salta segmenti praticamente silenziosi.
                # Evita chiamate Groq sprecate su dead air e riduce le
                # "allucinazioni" di Whisper (testo plausibile inventato
                # quando riceve solo rumore/silenzio).
                send_segment = True
                rms = None
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
                if event_bus:
                    event_bus.emit(
                        "rms",
                        value=rms if rms is not None else 0.0,
                        threshold=silence_rms_threshold,
                        accepted=send_segment
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
                remaining = write_pos - cut
                if overlap_samples > 0:
                    tail_start = max(0, cut - overlap_samples)
                    tail = radio_buffer[tail_start:cut].copy()
                    tail_len = len(tail)
                    radio_buffer[:tail_len] = tail
                    if remaining > 0:
                        radio_buffer[tail_len:tail_len + remaining] = \
                            radio_buffer[cut:cut + remaining]
                    write_pos = tail_len + remaining
                else:
                    if remaining > 0:
                        radio_buffer[:remaining] = radio_buffer[cut:cut + remaining]
                    write_pos = remaining

    except KeyboardInterrupt:
        print("\nChiusura in corso...")
        logger.info("Interruzione da tastiera ricevuta.")
    finally:
        audio.stop()
        transcriber.stop()
        logger.info("Programma terminato.")


def _run_vad_mode(audio, transcriber, rate, frame_duration_ms, vad_cfg, event_bus=None, stop_event=None):
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
        while audio.is_running and not (stop_event and stop_event.is_set()):
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


def run_pipeline(config, event_bus=None, stop_event=None):
    """
    Avvia cattura audio + trascrizione e li lascia girare finché lo stream
    è attivo o finché 'stop_event' non viene settato dall'esterno.

    Punto di ingresso condiviso da main() (uso da riga di comando) e da
    gui.py (che lo esegue in un thread di background e usa 'event_bus' per
    aggiornare i widget e 'stop_event' per il bottone Stop). La logica di
    cattura/segmentazione/trascrizione resta identica in entrambi i casi.
    """
    rate = config.get("audio", {}).get("rate", 16000)
    channels = config.get("audio", {}).get("channels", 1)
    frame_duration_ms = config.get("audio", {}).get("frame_duration_ms", 30)
    chunk = int(rate * frame_duration_ms / 1000)
    frame_samples = chunk  # un frame audio contiene 'chunk' campioni

    radio_cfg = config.get("radio", {})
    radio_enabled = radio_cfg.get("enabled", False)
    bypass_vad = radio_cfg.get("bypass_vad", False)

    audio = AudioCapture(rate=rate, channels=channels, chunk=chunk)
    transcriber = Transcriber(config, event_bus=event_bus)
    audio.start()

    if radio_enabled and bypass_vad:
        _run_radio_mode(audio, transcriber, rate, frame_samples, radio_cfg,
                         event_bus=event_bus, stop_event=stop_event)
    else:
        vad_cfg = config.get("vad", {})
        _run_vad_mode(audio, transcriber, rate, frame_duration_ms, vad_cfg,
                       event_bus=event_bus, stop_event=stop_event)


def main():
    logger.info(" Avvio Audio Transcriber v3.0")
    config = load_config()
    run_pipeline(config)


if __name__ == "__main__":
    main()