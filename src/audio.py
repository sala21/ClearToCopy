import queue
import numpy as np
import pyaudio

class AudioCapture:

    def __init__(self, rate=16000, channels=1, chunk=480, max_queue_size=200, input_gain=1.0):
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self.audio_queue = queue.Queue(maxsize=max_queue_size)
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.is_running = False
        self.dropped_frames = 0
        # Moltiplicatore applicato ai campioni catturati, PRIMA che finiscano
        # in coda (quindi prima di VAD/Radio e prima della trascrizione).
        # Utile per segnali deboli (es. audio radio con livello basso) senza
        # dover dipendere dalle impostazioni del mixer di sistema. Letto e
        # scritto da thread diversi (thread audio di PyAudio in scrittura
        # nel callback, thread GUI in aggiornamento a caldo): è un singolo
        # float, la scrittura è atomica in CPython, non serve un lock per
        # un caso d'uso "ultimo valore vince".
        self.input_gain = input_gain

    def _callback(self, in_data, frame_count, time_info, status):
        """Callback per PyAudio."""
        if self.input_gain != 1.0:
            samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
            samples *= self.input_gain
            np.clip(samples, -32768, 32767, out=samples)
            in_data = samples.astype(np.int16).tobytes()

        if self.audio_queue.qsize() < self.audio_queue.maxsize:
            self.audio_queue.put(in_data)
        else:
            self.dropped_frames += 1
        return (None, pyaudio.paContinue)

    def start(self):
        """Avvia lo stream audio."""
        if self.stream is None:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk,
                stream_callback=self._callback
            )
        self.stream.start_stream()
        self.is_running = True
        print("[Audio] Stream avviato.")

    def stop(self):
        """Ferma e chiude lo stream."""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.p.terminate()
        self.is_running = False
        print("[Audio] Stream fermato.")

    def get_frame(self, timeout=0.5):
        """Preleva un frame dalla coda audio."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None