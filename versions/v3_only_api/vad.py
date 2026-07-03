import collections
import numpy as np
import webrtcvad
from logger import get_logger

logger = get_logger()

class VADProcessor:
    """Voice Activity Detection e segmentazione"""

    def __init__(
        self,
        rate=16000,
        frame_duration_ms=30,
        aggressiveness=2,
        silence_timeout_s=1.2,
        max_utterance_s=20.0,
        min_segment_duration_s=1.2,
        activation_ratio=0.6  # Nuovo parametro con default 0.6
    ):
        self.rate = rate
        self.frame_duration_ms = frame_duration_ms
        self.vad = webrtcvad.Vad(aggressiveness)
        self.silence_timeout_s = silence_timeout_s
        self.max_utterance_s = max_utterance_s
        self.min_segment_duration_s = min_segment_duration_s
        self.activation_ratio = activation_ratio  # <--- PUNTO 2

        self.triggered = False
        num_padding_frames = int(300 / frame_duration_ms)
        self.ring_buffer = collections.deque(maxlen=num_padding_frames)
        num_silence_frames = int(silence_timeout_s * 1000 / frame_duration_ms)
        self.ring_buffer_silence = collections.deque(maxlen=num_silence_frames)
        self.max_voiced_frames = int(max_utterance_s * 1000 / frame_duration_ms)

        self.frame_samples = int(rate * frame_duration_ms / 1000)
        self._voiced_capacity = self.max_voiced_frames * self.frame_samples
        self._voiced_buffer = np.empty(self._voiced_capacity, dtype=np.int16)
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        self.on_transcription_ready = None
        logger.debug("VAD inizializzato: rate=%d, aggressiveness=%d, activation_ratio=%.2f", 
                     rate, aggressiveness, activation_ratio)

    def set_callback(self, callback):
        self.on_transcription_ready = callback

    def _append_voiced_frame(self, frame_bytes):
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
        is_speech = self.vad.is_speech(frame, self.rate)
        segment_completed = False

        if not self.triggered:
            self.ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in self.ring_buffer if speech)
            # <--- PUNTO 2: usa activation_ratio invece di 0.6 fisso
            if num_voiced > self.activation_ratio * self.ring_buffer.maxlen:
                self.triggered = True
                logger.debug("VAD attivato (inizio parlato).")
                for f, _ in self.ring_buffer:
                    self._append_voiced_frame(f)
                self.ring_buffer.clear()
        else:
            self._append_voiced_frame(frame)
            self.ring_buffer_silence.append(is_speech)
            num_unvoiced = sum(1 for speech in self.ring_buffer_silence if not speech)
            end_of_transmission = num_unvoiced == self.ring_buffer_silence.maxlen
            forced_cutoff = self._voiced_frame_count >= self.max_voiced_frames

            if end_of_transmission or forced_cutoff:
                self._flush_segment()
                segment_completed = True
                if forced_cutoff and not end_of_transmission:
                    logger.debug("VAD: taglio forzato per durata massima.")
                    self.triggered = True
                else:
                    logger.debug("VAD: fine parlato.")
                    self.triggered = False

        return segment_completed

    def _flush_segment(self):
        if self._voiced_frame_count == 0:
            return

        audio_int16 = self._voiced_buffer[:self._voiced_write_pos].copy()
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        # <--- PUNTO 3: NORMALIZZAZIONE DEL PICCO (alza il volume)
        max_val = np.max(np.abs(audio_int16))
        if max_val > 0:
            audio_int16 = (audio_int16 / max_val * 0.9 * 32767).astype(np.int16)

        duration = len(audio_int16) / self.rate
        if duration < self.min_segment_duration_s:
            logger.warning("Segmento troppo breve (%.2fs) – scartato.", duration)
            self.ring_buffer_silence.clear()
            return

        logger.debug("Segmento VAD pronto: durata=%.2fs, campioni=%d", duration, len(audio_int16))
        if self.on_transcription_ready:
            self.on_transcription_ready(audio_int16)

        self.ring_buffer_silence.clear()