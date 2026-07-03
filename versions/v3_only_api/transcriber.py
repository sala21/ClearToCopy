import queue
import threading
import time
import requests
from concurrent.futures import ThreadPoolExecutor

from utils import audio_to_wav_bytes, apply_bandpass_filter

"""Trascrizione via API Groq (whisper-large-v3). Nessun fallback locale."""

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
        groq_cfg = config.get("api", {}).get("groq", {})
        self.api_key = groq_cfg.get("api_key", "")
        if not self.api_key:
            raise ValueError(
                "API key Groq mancante. Impostala nella variabile d'ambiente "
                "GROQ_API_KEY (consigliato) oppure nel campo api.groq.api_key "
                "di config.json."
            )

        self.groq_model = groq_cfg.get("model", "whisper-large-v3")
        self.groq_url = groq_cfg.get("url", "https://api.groq.com/openai/v1/audio/transcriptions")
        self.groq_timeout_s = groq_cfg.get("timeout_s", 10)
        max_concurrent_requests = groq_cfg.get("max_concurrent_requests", 3)

        self.apply_filter = config.get("filter", {}).get("enabled", False)
        self.band_min = config.get("filter", {}).get("band_min", 300)
        self.band_max = config.get("filter", {}).get("band_max", 3400)
        self.rate = config.get("audio", {}).get("rate", 16000)

        self.transcribe_queue = queue.Queue()
        self.stop_event = threading.Event()

        self.last_text = ""
        self.last_text_time = 0
        self._last_text_lock = threading.Lock()

        # Pool di worker: più richieste Groq possono essere "in volo"
        # contemporaneamente invece di accodarsi una dietro l'altra.
        self.executor = ThreadPoolExecutor(
            max_workers=max_concurrent_requests,
            thread_name_prefix="GroqWorker",
        )

        # Thread leggero che smista i segmenti pronti al pool, senza mai bloccarsi
        # in attesa della risposta di Groq.
        self.dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatch_thread.start()

        print(f"[Transcriber] Pronto. Modello Groq: {self.groq_model} "
              f"(max {max_concurrent_requests} richieste in parallelo).")

    def enqueue(self, audio_np):
        """Aggiunge un segmento audio alla coda di trascrizione (non bloccante)."""
        self.transcribe_queue.put(audio_np)

    def _dispatch_loop(self):
        """Preleva i segmenti e li smista al pool di worker Groq."""
        while not self.stop_event.is_set():
            try:
                audio_np = self.transcribe_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if audio_np is None:
                break

            self.executor.submit(self._process_segment, audio_np)

        print("[Transcriber] Dispatcher terminato.")

    def _process_segment(self, audio_np):
        """Eseguito nel pool: pre-processing + chiamata Groq + stampa risultato."""
        if self.apply_filter:
            audio_np = apply_bandpass_filter(
                audio_np,
                rate=self.rate,
                band_min=self.band_min,
                band_max=self.band_max,
            )

        text = self._transcribe_with_groq(audio_np)

        if not text:
            print("[Transcriber] Nessun testo riconosciuto.")
            print("-" * 40)
            return

        # Anti-loop: scarta ripetizioni brevi identiche (es. rumore che genera
        # sempre la stessa parola breve). Protetto da lock perché più worker
        # possono finire quasi in contemporanea.
        with self._last_text_lock:
            if text == self.last_text and len(text) < 15:
                print(f"[Transcriber] Testo identico e breve ('{text}') - ignorato.")
                return
            self.last_text = text
            self.last_text_time = time.time()

        print(text)
        print("-" * 40)

    def _transcribe_with_groq(self, audio_np):
        """Invia l'audio all'API Groq. Ritorna None in caso di errore o timeout."""
        wav_bytes = audio_to_wav_bytes(audio_np, rate=self.rate)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {
            "model": self.groq_model,
            "language": "en",
            "response_format": "json",
            "prompt": INITIAL_PROMPT,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            resp = requests.post(
                self.groq_url,
                headers=headers,
                files=files,
                data=data,
                timeout=self.groq_timeout_s,
            )
            if resp.status_code != 200:
                print(f"[Groq] Errore HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            text = resp.json().get("text", "").strip()
            return text if text else None
        except requests.exceptions.Timeout:
            print(f"[Groq] Timeout dopo {self.groq_timeout_s}s - segmento perso.")
            return None
        except Exception as e:
            print(f"[Groq] Errore: {e}")
            return None

    def stop(self):
        """Termina dispatcher e worker pool in modo pulito."""
        self.stop_event.set()
        self.transcribe_queue.put(None)
        self.dispatch_thread.join(timeout=3.0)
        self.executor.shutdown(wait=True)
