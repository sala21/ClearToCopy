import queue
import pyaudio

class AudioCapture:
    def __init__(self, rate=16000, channels=1, chunk=480, max_queue_size=200):
        self.rate = rate
        self.channels = channels
        self.chunk = chunk
        self.audio_queue = queue.Queue(maxsize=max_queue_size)
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.is_running = False

    def _callback(self, in_data, frame_count, time_info, status):
        """Callback per PyAudio."""
        try:
            if self.audio_queue.qsize() < self.audio_queue.maxsize:
                self.audio_queue.put(in_data)
        except queue.Full:
            pass
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