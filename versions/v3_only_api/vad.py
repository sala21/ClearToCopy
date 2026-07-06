import collections
import numpy as np
import webrtcvad
from logger import get_logger

logger = get_logger()

class VADProcessor:
    """Voice Activity Detection e segmentazione con sliding window O(1)"""

    def __init__(
        self,
        rate=16000,
        frame_duration_ms=30,
        aggressiveness=2,
        silence_timeout_s=1.2,
        max_utterance_s=20.0,
        min_segment_duration_s=1.2,
        activation_ratio=0.6
    ):
        self.rate = rate
        self.frame_duration_ms = frame_duration_ms
        self.vad = webrtcvad.Vad(aggressiveness)
        self.silence_timeout_s = silence_timeout_s
        self.max_utterance_s = max_utterance_s
        self.min_segment_duration_s = min_segment_duration_s
        self.activation_ratio = activation_ratio

        self.triggered = False

        self.ring_buffer = None
        self.ring_buffer_maxlen = 0
        self._voiced_count = 0
        self.ring_buffer_silence = None
        self.silence_ring_maxlen = 0
        self._unvoiced_count = 0
        self.max_voiced_frames = 0
        self.frame_samples = int(rate * frame_duration_ms / 1000)
        self._voiced_capacity = 0
        self._voiced_buffer = None
        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        self.on_transcription_ready = None

        self._update_buffers()

        logger.debug("VAD inizializzato: rate=%d, aggressiveness=%d, activation_ratio=%.2f",
                     rate, aggressiveness, activation_ratio)

    def _update_buffers(self):
        num_padding_frames = int(300 / self.frame_duration_ms)
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
                self._flush_segment()
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
            return

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
            return

        logger.debug("Segmento VAD pronto: durata=%.2fs, campioni=%d", duration, len(audio_int16))
        if self.on_transcription_ready:
            self.on_transcription_ready(audio_int16)

        self.ring_buffer_silence.clear()
        self._unvoiced_count = 0