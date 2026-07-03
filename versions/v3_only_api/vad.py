import collections
import numpy as np
import webrtcvad

class VADProcessor:
    """Voice Activity Detection e segmentazione"""
    def __init__(
        self,
        rate=16000,
        frame_duration_ms=30,
        aggressiveness=2,
        silence_timeout_s=1.2,
        max_utterance_s=20.0,
        min_segment_duration_s=1.2
    ):

        self.rate = rate
        self.frame_duration_ms = frame_duration_ms
        self.vad = webrtcvad.Vad(aggressiveness)
        self.silence_timeout_s = silence_timeout_s
        self.max_utterance_s = max_utterance_s
        self.min_segment_duration_s = min_segment_duration_s

        # Buffer e stati interni
        self.triggered = False
        num_padding_frames = int(300 / frame_duration_ms)
        self.ring_buffer = collections.deque(maxlen=num_padding_frames)
        num_silence_frames = int(silence_timeout_s * 1000 / frame_duration_ms)
        self.ring_buffer_silence = collections.deque(maxlen=num_silence_frames)
        self.max_voiced_frames = int(max_utterance_s * 1000 / frame_duration_ms)

        # Buffer numpy pre-allocato per i campioni vocali, riutilizzato ad
        # ogni segmento invece di accumulare in una lista Python con append
        # ripetuti (che genera migliaia di micro-allocazioni su trasmissioni
        # lunghe). Dimensionato sul caso peggiore: max_voiced_frames frame
        # da frame_samples campioni ciascuno.
        self.frame_samples = int(rate * frame_duration_ms / 1000)
        self._voiced_capacity = self.max_voiced_frames * self.frame_samples
        self._voiced_buffer = np.empty(self._voiced_capacity, dtype=np.int16)
        self._voiced_write_pos = 0   # prossima posizione libera, in campioni
        self._voiced_frame_count = 0  # frame accumulati nel segmento corrente

        self.on_transcription_ready = None  # Callback per quando un segmento è pronto

    def set_callback(self, callback):
        """Imposta una funzione da chiamare quando un segmento audio è pronto."""
        self.on_transcription_ready = callback

    def _append_voiced_frame(self, frame_bytes):
        """Scrive un frame nel buffer pre-allocato via slicing, senza allocare."""
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        n = len(samples)
        start = self._voiced_write_pos
        end = start + n

        if end > self._voiced_capacity:
            # Non dovrebbe accadere perché max_voiced_frames limita già
            # l'accumulo altrove, ma tronchiamo per sicurezza invece di
            # sollevare un errore o corrompere la memoria.
            n = self._voiced_capacity - start
            if n <= 0:
                return
            samples = samples[:n]
            end = start + n

        self._voiced_buffer[start:end] = samples
        self._voiced_write_pos = end
        self._voiced_frame_count += 1

    def process_frame(self, frame):
        """
        Processa un singolo frame audio.
        Restituisce True se è stato completato un segmento (da inviare alla trascrizione).
        """
        is_speech = self.vad.is_speech(frame, self.rate)
        segment_completed = False

        if not self.triggered:
            self.ring_buffer.append((frame, is_speech))
            num_voiced = sum(1 for _, speech in self.ring_buffer if speech)
            if num_voiced > 0.6 * self.ring_buffer.maxlen:
                self.triggered = True
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
                    self.triggered = True
                else:
                    self.triggered = False

        return segment_completed

    def _flush_segment(self):
        """Svuota i campioni vocali accumulati e li invia al callback."""
        if self._voiced_frame_count == 0:
            return

        # Copia solo la parte effettivamente scritta del buffer; astype()
        # crea gia' un nuovo array, quindi il buffer pre-allocato puo'
        # essere riutilizzato in sicurezza dal prossimo segmento.
        audio_np = self._voiced_buffer[:self._voiced_write_pos].astype(np.float32) / 32768.0

        self._voiced_write_pos = 0
        self._voiced_frame_count = 0

        # Calcola durata e scarta se troppo breve
        duration = len(audio_np) / self.rate
        if duration < self.min_segment_duration_s:
            print(f"[VAD] Segmento troppo breve ({duration:.2f}s) – scartato.")
            self.ring_buffer_silence.clear()
            return

        # Invoca il callback
        if self.on_transcription_ready:
            self.on_transcription_ready(audio_np)

        self.ring_buffer_silence.clear()