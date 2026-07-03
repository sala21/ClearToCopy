import queue
import threading
import time
import requests
import numpy as np
from faster_whisper import WhisperModel

from utils import audio_to_wav_bytes, apply_bandpass_filter

"""API Groq + fallback locale"""

INITIAL_PROMPT = (
    "ATC radio transmission, aviation phraseology, pilot and tower control. "
    "Aircraft callsigns, runway numbers, headings, flight levels, and altitudes. "
    "Keywords: cleared to land, line up and wait, hold short, taxi via, squawk, "
    "maintain, radar contact, wind, knots, QNH, altimeter, ILS approach, flight level. "
    "Phonetic alphabet: Alfa, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, "
    "Juliett, Kilo, Lima, Mike, November, Oscar, Papa, Quebec, Romeo, Sierra, Tango, "
    "Uniform, Victor, Whiskey, X-ray, Yankee, Zulu. "
    "Numbers and digits: zero, one, two, tree, four, fife, six, seven, eight, niner, hundred, thousand."
)

class Transcriber:
    def __init__(self, config):
        self.api_key = config.get("api", {}).get("groq", {}).get("api_key", "")
        self.groq_model = config.get("api", {}).get("groq", {}).get("model", "whisper-large-v3")
        self.groq_url = config.get("api", {}).get("groq", {}).get(
            "url", "https://api.groq.com/openai/v1/audio/transcriptions"
        )

        self.local_model_name = config.get("local", {}).get("model", "base")
        self.local_device = config.get("local", {}).get("device", "cpu")
        self.local_compute_type = config.get("local", {}).get("compute_type", "int8")

        self.apply_filter = config.get("filter", {}).get("enabled", False)
        self.band_min = config.get("filter", {}).get("band_min", 300)
        self.band_max = config.get("filter", {}).get("band_max", 3400)
        self.rate = config.get("audio", {}).get("rate", 16000)

        self.transcribe_queue = queue.Queue(maxsize=2)
        self.stop_event = threading.Event()
        self.last_text = ""
        self.last_text_time = 0

        # Carica modello locale (fallback)
        print("Caricamento modello locale (fallback)...")
        self.local_model = WhisperModel(
            self.local_model_name,
            device=self.local_device,
            compute_type=self.local_compute_type
        )
        print("Modello locale pronto.")

        # Avvia il thread worker
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def enqueue(self, audio_np):
        """Aggiunge un segmento audio alla coda di trascrizione."""
        try:
            self.transcribe_queue.put(audio_np, timeout=1.0)
        except queue.Full:
            print("[Transcriber] Coda piena, segmento perso.")

    def _worker_loop(self):
        """Thread worker per la trascrizione."""
        while not self.stop_event.is_set():
            try:
                audio_np = self.transcribe_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if audio_np is None:
                break

            # Pre-processing
            if self.apply_filter:
                audio_np = apply_bandpass_filter(
                    audio_np,
                    rate=self.rate,
                    band_min=self.band_min,
                    band_max=self.band_max
                )

            # Prova API Groq
            text = self._transcribe_with_groq(audio_np)

            # Fallback locale
            if text is None:
                print("[Transcriber] Fallback a modello locale...")
                text = self._transcribe_local(audio_np)

            # Anti-loop
            if text and text == self.last_text and len(text) < 15:
                print(f"[Transcriber] Testo identico e breve ('{text}') – ignorato.")
                continue

            if text:
                print(text)
                self.last_text = text
                self.last_text_time = time.time()
            else:
                print("[Transcriber] Nessun testo riconosciuto.")
            print("-" * 40)

        print("[Transcriber] Worker terminato.")

    def _transcribe_with_groq(self, audio_np):
        """Invia l'audio all'API Groq."""
        if not self.api_key:
            return None

        wav_bytes = audio_to_wav_bytes(audio_np, rate=self.rate)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {
            "model": self.groq_model,
            "language": "en",
            "response_format": "json",
            "prompt": INITIAL_PROMPT
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            resp = requests.post(self.groq_url, headers=headers, files=files, data=data, timeout=30)
            if resp.status_code != 200:
                print(f"[Groq] Errore HTTP {resp.status_code}")
                return None
            text = resp.json().get("text", "").strip()
            return text if text else None
        except Exception as e:
            print(f"[Groq] Errore: {e}")
            return None

    def _transcribe_local(self, audio_np):
        """Trascrizione con modello locale."""
        try:
            segments, _ = self.local_model.transcribe(
                audio_np,
                beam_size=1,
                language="en",
                initial_prompt=INITIAL_PROMPT,
            )
            full_text = " ".join(seg.text for seg in segments).strip()
            return full_text if full_text else None
        except Exception as e:
            print(f"[Locale] Errore: {e}")
            return None

    def stop(self):
        """Termina il worker."""
        self.stop_event.set()
        self.transcribe_queue.put(None)
        self.worker_thread.join(timeout=3.0)