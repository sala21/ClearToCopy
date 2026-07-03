import heapq
import itertools
import queue
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor

from utils import audio_to_wav_bytes, audio_to_flac_bytes, apply_bandpass_filter, SOUNDFILE_AVAILABLE

"""Trascrizione via API Groq (whisper-large-v3). Nessun fallback locale.

I segmenti vengono trascritti in parallelo (ThreadPoolExecutor), ma stampati
in ordine cronologico tramite un min-heap: ogni segmento riceve un numero di
sequenza all'ingresso, e un thread dedicato stampa solo quando il segmento
"atteso" e' pronto, riordinando eventuali risultati arrivati fuori sequenza.
"""

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

        # Se un segmento atteso in ordine non arriva entro questo tempo (perso,
        # errore, timeout Groq), il printer salta avanti invece di bloccarsi
        # per sempre in attesa di un risultato che non arrivera' mai.
        self.reorder_timeout_s = groq_cfg.get("reorder_timeout_s", 3.0)

        # FLAC riduce le dimensioni del payload rispetto al WAV grezzo, quindi
        # upload piu' veloce verso Groq. Se 'soundfile' non e' installato,
        # si fa fallback automatico a WAV con un avviso a schermo (una volta sola).
        self.use_flac = groq_cfg.get("use_flac", True) and SOUNDFILE_AVAILABLE
        if groq_cfg.get("use_flac", True) and not SOUNDFILE_AVAILABLE:
            print("[Transcriber] 'soundfile' non installato: uso WAV invece di FLAC "
                  "(pip install soundfile per upload piu' veloci).")

        self.apply_filter = config.get("filter", {}).get("enabled", False)
        self.band_min = config.get("filter", {}).get("band_min", 300)
        self.band_max = config.get("filter", {}).get("band_max", 3400)
        self.rate = config.get("audio", {}).get("rate", 16000)

        # Session condivisa: riusa le connessioni TCP/TLS gia' aperte verso
        # Groq invece di rifare l'handshake ad ogni singola richiesta. Il
        # pool e' dimensionato sul numero di worker paralleli, cosi' ognuno
        # puo' avere la propria connessione mantenuta viva (keep-alive).
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=max_concurrent_requests,
            pool_maxsize=max_concurrent_requests,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

        self.transcribe_queue = queue.Queue()
        self.stop_event = threading.Event()

        self.last_text = ""
        self.last_text_time = 0
        self._last_text_lock = threading.Lock()

        # Numero di sequenza crescente assegnato a ogni segmento all'ingresso,
        # usato per riordinare i risultati in uscita.
        self._seq_counter = itertools.count()
        self._next_seq_to_print = 0
        self._result_heap = []  # elementi: (seq, text_o_None, timestamp_arrivo)
        self._result_lock = threading.Condition()

        # Pool di worker: piu' richieste Groq possono essere "in volo"
        # contemporaneamente invece di accodarsi una dietro l'altra.
        self.executor = ThreadPoolExecutor(
            max_workers=max_concurrent_requests,
            thread_name_prefix="GroqWorker",
        )

        # Thread leggero che smista i segmenti pronti al pool, senza mai bloccarsi
        # in attesa della risposta di Groq.
        self.dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatch_thread.start()

        # Thread che stampa i risultati nell'ordine cronologico corretto,
        # anche se i worker Groq finiscono fuori sequenza.
        self.printer_thread = threading.Thread(target=self._printer_loop, daemon=True)
        self.printer_thread.start()

        print(f"[Transcriber] Pronto. Modello Groq: {self.groq_model} "
              f"(max {max_concurrent_requests} richieste in parallelo, "
              f"formato: {'FLAC' if self.use_flac else 'WAV'}).")

    def enqueue(self, audio_np):
        """Aggiunge un segmento audio alla coda di trascrizione (non bloccante)."""
        seq = next(self._seq_counter)
        self.transcribe_queue.put((seq, audio_np))

    def _dispatch_loop(self):
        """Preleva i segmenti e li smista al pool di worker Groq."""
        while not self.stop_event.is_set():
            try:
                item = self.transcribe_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            seq, audio_np = item
            self.executor.submit(self._process_segment, seq, audio_np)

        print("[Transcriber] Dispatcher terminato.")

    def _process_segment(self, seq, audio_np):
        """Eseguito nel pool: pre-processing + chiamata Groq + invio al printer."""
        if self.apply_filter:
            audio_np = apply_bandpass_filter(
                audio_np,
                rate=self.rate,
                band_min=self.band_min,
                band_max=self.band_max,
            )

        text = self._transcribe_with_groq(audio_np)

        # Anti-loop: scarta ripetizioni brevi identiche (es. rumore che genera
        # sempre la stessa parola breve). La sequenza mantiene comunque il suo
        # "slot" nell'ordine, altrimenti il printer resterebbe bloccato ad
        # aspettarla.
        if text:
            with self._last_text_lock:
                if text == self.last_text and len(text) < 15:
                    text = None
                else:
                    self.last_text = text
                    self.last_text_time = time.time()

        self._submit_result(seq, text)

    def _submit_result(self, seq, text):
        """Inserisce un risultato nel min-heap e sveglia il thread di stampa."""
        with self._result_lock:
            heapq.heappush(self._result_heap, (seq, text, time.time()))
            self._result_lock.notify_all()

    def _printer_loop(self):
        """Stampa i risultati in ordine di sequenza, riordinando se necessario."""
        while not self.stop_event.is_set():
            with self._result_lock:
                if not self._result_heap:
                    self._result_lock.wait(timeout=0.5)
                    continue

                seq, text, arrived_at = self._result_heap[0]

                if seq == self._next_seq_to_print:
                    heapq.heappop(self._result_heap)
                    self._next_seq_to_print += 1
                elif (time.time() - arrived_at) > self.reorder_timeout_s:
                    # Il segmento atteso non e' mai arrivato: probabilmente
                    # perso o fallito. Salta avanti per non bloccare l'output
                    # all'infinito.
                    heapq.heappop(self._result_heap)
                    self._next_seq_to_print = seq + 1
                else:
                    self._result_lock.wait(timeout=self.reorder_timeout_s)
                    continue

            self._print_result(text)

        self._flush_remaining_results()

    def _flush_remaining_results(self):
        """Stampa in ordine tutto cio' che resta nell'heap allo shutdown."""
        with self._result_lock:
            remaining = sorted(self._result_heap)
            self._result_heap.clear()
        for _, text, _ in remaining:
            self._print_result(text)

    def _print_result(self, text):
        if text:
            print(text)
        else:
            print("[Transcriber] Nessun testo riconosciuto.")
        print("-" * 40)

    def _transcribe_with_groq(self, audio_np):
        """Invia l'audio all'API Groq. Ritorna None in caso di errore o timeout."""
        if self.use_flac:
            try:
                audio_bytes = audio_to_flac_bytes(audio_np, rate=self.rate)
                filename, content_type = "audio.flac", "audio/flac"
            except Exception as e:
                print(f"[Transcriber] Encoding FLAC fallito ({e}), uso WAV per questo segmento.")
                audio_bytes = audio_to_wav_bytes(audio_np, rate=self.rate)
                filename, content_type = "audio.wav", "audio/wav"
        else:
            audio_bytes = audio_to_wav_bytes(audio_np, rate=self.rate)
            filename, content_type = "audio.wav", "audio/wav"

        files = {"file": (filename, audio_bytes, content_type)}
        data = {
            "model": self.groq_model,
            "language": "en",
            "response_format": "json",
            "prompt": INITIAL_PROMPT,
        }
        # L'header Authorization e' gia' impostato una volta sulla session
        # (self.session.headers), non va ricostruito ad ogni chiamata.
        try:
            resp = self.session.post(
                self.groq_url,
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
        """Termina dispatcher, worker pool e printer in modo pulito."""
        self.stop_event.set()
        self.transcribe_queue.put(None)
        self.dispatch_thread.join(timeout=3.0)
        self.executor.shutdown(wait=True)

        with self._result_lock:
            self._result_lock.notify_all()
        self.printer_thread.join(timeout=self.reorder_timeout_s + 1.0)

        self.session.close()