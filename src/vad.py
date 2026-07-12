import collections
import numpy as np
import webrtcvad
import threading
from logger import get_logger

logger = get_logger()

class VADProcessor:
    """Voice Activity Detection e segmentazione con sliding window O(1)"""

    def __init__(
        self,
        rate=16000,                    # campioni al secondo (16kHz)
        frame_duration_ms=30,          # durata di ogni frame audio in millisecondi
        aggressiveness=2,              # sensibilità del VAD (0=più permissivo, 3=più aggressivo)
        silence_timeout_s=1.2,         # quanto silenzio serve per chiudere un segmento
        max_utterance_s=20.0,          # durata massima di un segmento (taglio forzato)
        min_segment_duration_s=1.2,    # durata minima per considerare il segmento valido
        activation_ratio=0.6,          # % di frame vocali per attivare il segmento
        event_bus=None,                # se fornito, pubblica l'evento "rms" a ogni frame
        rms_threshold=50.0,            # soglia RMS mostrata/usata per l'indicatore "accettato/scartato"
        rms_gate_enabled=False         # se True, un frame sotto rms_threshold non è mai considerato parlato,
                                        # anche se webrtcvad lo classifica come tale (filtro anti rumore/statica)
    ):
        self._state_lock = threading.Lock()
        self.rate = rate
        self.frame_duration_ms = frame_duration_ms
        self.vad = webrtcvad.Vad(aggressiveness)
        self.silence_timeout_s = silence_timeout_s
        self.max_utterance_s = max_utterance_s
        self.min_segment_duration_s = min_segment_duration_s
        self.activation_ratio = activation_ratio
        self.event_bus = event_bus
        self.rms_threshold = rms_threshold
        self.rms_gate_enabled = rms_gate_enabled

        self.triggered = False

        self.ring_buffer = None          # serve a ricordare gli ultimi ~300ms di audio prima che inizi il parlato per non perdere l'inizio della frase
        self.ring_buffer_maxlen = 0
        self._voiced_count = 0           # tiene traccia di quanti frame con voce ci sono in questo buffer
        self.ring_buffer_silence = None  # serve a decidere quando finisce il parlato
        self.silence_ring_maxlen = 0
        self._unvoiced_count = 0        # tiene traccia di quanti frame senza voce ci sono in questo buffer
        self.max_voiced_frames = 0
        self.frame_samples = int(rate * frame_duration_ms / 1000)    # quanti campioni audio ci sono in un singolo frame   
        self._voiced_capacity = 0
        self._voiced_buffer = None
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        self.on_transcription_ready = None
        self._update_buffers()

        logger.debug("VAD inizializzato: rate=%d, aggressiveness=%d, activation_ratio=%.2f",
                     rate, aggressiveness, activation_ratio)

    def _update_buffers(self):
        """Inizializza i buffer"""
        num_padding_frames = int(300 / self.frame_duration_ms)      #calcola quanti frame audio servono per coprire 300 millisecondi
        self.ring_buffer_maxlen = num_padding_frames
        self.ring_buffer = collections.deque(maxlen=num_padding_frames)
        self._voiced_count = 0

        num_silence_frames = int(self.silence_timeout_s * 1000 / self.frame_duration_ms)
        self.silence_ring_maxlen = num_silence_frames
        self.ring_buffer_silence = collections.deque()
        self._unvoiced_count = 0

        self.max_voiced_frames = int(self.max_utterance_s * 1000 / self.frame_duration_ms)
        self._voiced_capacity = self.max_voiced_frames * self.frame_samples
        self._voiced_buffer = np.empty(self._voiced_capacity, dtype=np.int16)
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

    def set_callback(self, callback):
        self.on_transcription_ready = callback

    def _append_voiced_frame(self, frame_bytes):
        """Scrive un frame audio (un blocco di 30ms) nel buffer principale del parlato"""
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        n = len(samples)
        start = self._voiced_write_pos
        end = start + n
        if end > self._voiced_capacity:
            n = self._voiced_capacity - start
            if n <= 0:
                return
            samples = samples[:n]
            end = start + n
        self._voiced_buffer[start:end] = samples
        self._voiced_write_pos = end
        self._voiced_frame_count += 1

    def process_frame(self, frame):
        with self._state_lock:
            is_speech = self.vad.is_speech(frame, self.rate)
            segment_completed = False

            # Calcola sempre l'RMS del frame: serve sia per l'evento verso la
            # GUI sia (se abilitato) per il gate anti-rumore qui sotto.
            samples = np.frombuffer(frame, dtype=np.int16)
            if len(samples) > 0:
                rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            else:
                rms = 0.0

            # Gate RMS opzionale: un frame sotto soglia non viene MAI considerato
            # parlato, anche se webrtcvad lo classifica come tale. Serve a filtrare
            # rumore/statica che webrtcvad può scambiare per voce su segnali radio
            # degradati. Il gate può solo "declassare" a non-parlato, mai promuovere
            # un frame che webrtcvad ha già scartato.
            if self.rms_gate_enabled and rms < self.rms_threshold:
                is_speech = False

            # Pubblica il livello del segnale (RMS) verso la GUI. "accepted" riflette
            # la decisione finale (dopo l'eventuale gate), cioè se questo frame
            # contribuisce davvero a un segmento da trascrivere.
            if self.event_bus:
                self.event_bus.emit(
                    "rms", value=rms, threshold=self.rms_threshold, accepted=is_speech
                )

            if not self.triggered:
                if len(self.ring_buffer) == self.ring_buffer_maxlen:
                    _, old_is_speech = self.ring_buffer.popleft()
                    if old_is_speech:
                        self._voiced_count -= 1

                self.ring_buffer.append((frame, is_speech))
                if is_speech:
                    self._voiced_count += 1

                if self._voiced_count > self.activation_ratio * self.ring_buffer_maxlen:
                    self.triggered = True
                    logger.debug("VAD attivato (inizio parlato).")
                    for f, _ in self.ring_buffer:
                        self._append_voiced_frame(f)
                    self.ring_buffer.clear()
                    self._voiced_count = 0
            else:
                self._append_voiced_frame(frame)

                if len(self.ring_buffer_silence) == self.silence_ring_maxlen:
                    _, old_is_speech = self.ring_buffer_silence.popleft()
                    if not old_is_speech:
                        self._unvoiced_count -= 1

                self.ring_buffer_silence.append((frame, is_speech))
                if not is_speech:
                    self._unvoiced_count += 1

                end_of_transmission = (self._unvoiced_count == self.silence_ring_maxlen)
                forced_cutoff = self._voiced_frame_count >= self.max_voiced_frames

                if end_of_transmission or forced_cutoff:
                    flushed = self._flush_segment()
                    segment_completed = bool(flushed)
                    segment_completed = True
                    if forced_cutoff and not end_of_transmission:
                        logger.debug("VAD: taglio forzato per durata massima.")
                        self.triggered = True
                        self.ring_buffer_silence.clear()
                        self._unvoiced_count = 0
                    else:
                        logger.debug("VAD: fine parlato.")
                        self.triggered = False

            return segment_completed

    def _flush_segment(self):
        if self._voiced_frame_count == 0:
            return False

        audio_int16 = self._voiced_buffer[:self._voiced_write_pos].copy()
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        max_val = np.max(np.abs(audio_int16))
        if max_val > 0:
            audio_int16 = (audio_int16 / max_val * 0.9 * 32767).astype(np.int16)

        duration = len(audio_int16) / self.rate
        if duration < self.min_segment_duration_s:
            logger.warning("Segmento troppo breve (%.2fs) – scartato.", duration)
            self.ring_buffer_silence.clear()
            self._unvoiced_count = 0
            return False

        logger.debug("Segmento VAD pronto: durata=%.2fs, campioni=%d", duration, len(audio_int16))
        if self.on_transcription_ready:
            self.on_transcription_ready(audio_int16)
            return True

        self.ring_buffer_silence.clear()
        self._unvoiced_count = 0

    def update_params(self, aggressiveness, silence_timeout_s, max_utterance_s,
                       min_segment_duration_s, activation_ratio, rms_threshold=None,
                       rms_gate_enabled=None):
        """Aggiorna i parametri VAD in modo thread-safe."""
        with self._state_lock:
            # Se c'è un segmento in corso, chiudilo prima di ricreare i buffer
            if self.triggered and self._voiced_frame_count > 0:
                self._flush_segment()
                self.triggered = False

            self.aggressiveness = aggressiveness
            self.silence_timeout_s = silence_timeout_s
            self.max_utterance_s = max_utterance_s
            self.min_segment_duration_s = min_segment_duration_s
            self.activation_ratio = activation_ratio
            if rms_threshold is not None:
                self.rms_threshold = rms_threshold
            if rms_gate_enabled is not None:
                self.rms_gate_enabled = rms_gate_enabled
            self.vad.set_mode(aggressiveness)
            self._update_buffers()