import heapq
import itertools
import queue
import threading
import time
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor

from utils import audio_to_wav_bytes, audio_to_flac_bytes, SOUNDFILE_AVAILABLE
from logger import get_logger

logger = get_logger()

try:
    from scipy import signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

INITIAL_PROMPT = "Transcription of aviation radio communication."


class Transcriber:
    def __init__(self, config):
        logger.debug("Inizializzazione Transcriber...")
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
        self.reorder_timeout_s = groq_cfg.get("reorder_timeout_s", 3.0)

        self.use_flac = groq_cfg.get("use_flac", True) and SOUNDFILE_AVAILABLE
        if groq_cfg.get("use_flac", True) and not SOUNDFILE_AVAILABLE:
            logger.warning("'soundfile' non installato: uso WAV invece di FLAC (pip install soundfile per upload più veloci).")

        self.apply_filter = config.get("filter", {}).get("enabled", False)
        self.band_min = config.get("filter", {}).get("band_min", 300)
        self.band_max = config.get("filter", {}).get("band_max", 3400)
        self.rate = config.get("audio", {}).get("rate", 16000)

        if self.apply_filter:
            if not SCIPY_AVAILABLE:
                logger.warning("scipy non installato: filtro disabilitato. Installa con: pip install scipy")
                self.apply_filter = False
            else:
                self._filter_b = signal.firwin(65, [self.band_min, self.band_max], fs=self.rate, pass_zero=False)
                self._filter_a = [1.0]
                logger.info("Filtro passa-banda pre-calcolato (%d-%d Hz).", self.band_min, self.band_max)

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

        self._seq_counter = itertools.count()
        self._next_seq_to_print = 0
        self._result_heap = []
        self._result_lock = threading.Condition()

        self.executor = ThreadPoolExecutor(
            max_workers=max_concurrent_requests,
            thread_name_prefix="GroqWorker",
        )

        # Metriche
        self.metrics = {
            "segments_submitted": 0,
            "segments_completed": 0,
            "segments_failed": 0,
            "total_response_time": 0.0,
            "last_log_time": time.time()
        }
        self.metrics_lock = threading.Lock()

        self.dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self.dispatch_thread.start()

        self.printer_thread = threading.Thread(target=self._printer_loop, daemon=True)
        self.printer_thread.start()

        self.metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        self.metrics_thread.start()

        logger.info("Pronto. Modello Groq: %s (max %d richieste in parallelo, formato: %s)",
                    self.groq_model, max_concurrent_requests, 'FLAC' if self.use_flac else 'WAV')

    def enqueue(self, audio):
        seq = next(self._seq_counter)
        self.transcribe_queue.put((seq, audio))
        with self.metrics_lock:
            self.metrics["segments_submitted"] += 1
        logger.debug("Segmento accodato: seq=%d, dimensione=%d", seq, len(audio))

    def _dispatch_loop(self):
        while not self.stop_event.is_set():
            try:
                item = self.transcribe_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            seq, audio = item
            logger.debug("Dispatcher: invio segmento seq=%d al worker.", seq)
            self.executor.submit(self._process_segment, seq, audio)
        logger.debug("Dispatcher terminato.")

    def _process_segment(self, seq, audio):
        start_time = time.time()
        logger.debug("Processamento segmento seq=%d iniziato.", seq)

        if self.apply_filter:
            if audio.dtype == np.int16:
                audio_float = audio.astype(np.float32) / 32768.0
            else:
                audio_float = audio.astype(np.float32)
            audio_filtered = signal.lfilter(self._filter_b, self._filter_a, audio_float)
            text = self._transcribe_with_groq(audio_filtered)
        else:
            text = self._transcribe_with_groq(audio)

        elapsed = time.time() - start_time
        with self.metrics_lock:
            if text is not None:
                self.metrics["segments_completed"] += 1
                self.metrics["total_response_time"] += elapsed
                logger.debug("Segmento seq=%d completato in %.2fs.", seq, elapsed)
            else:
                self.metrics["segments_failed"] += 1
                logger.warning("Segmento seq=%d fallito (timeout o errore Groq).", seq)

        if text:
            with self._last_text_lock:
                if text == self.last_text and len(text) < 15:
                    text = None
                    logger.debug("Segmento seq=%d scartato (ripetizione breve).", seq)
                else:
                    self.last_text = text
                    self.last_text_time = time.time()

        self._submit_result(seq, text)

    def _submit_result(self, seq, text):
        with self._result_lock:
            heapq.heappush(self._result_heap, (seq, text, time.time()))
            self._result_lock.notify_all()

    def _printer_loop(self):
        while not self.stop_event.is_set():
            with self._result_lock:
                if not self._result_heap:
                    self._result_lock.wait(timeout=0.5)
                    continue
                seq, text, arrived_at = self._result_heap[0]
                if seq == self._next_seq_to_print:
                    heapq.heappop(self._result_heap)
                    self._next_seq_to_print += 1
                    logger.debug("Printer: stampato segmento seq=%d", seq)
                elif (time.time() - arrived_at) > self.reorder_timeout_s:
                    heapq.heappop(self._result_heap)
                    self._next_seq_to_print = seq + 1
                    logger.warning("Printer: timeout per seq=%d, salto avanti.", seq)
                else:
                    self._result_lock.wait(timeout=self.reorder_timeout_s)
                    continue
            self._print_result(text)

        self._flush_remaining_results()

    def _flush_remaining_results(self):
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

    def _metrics_loop(self):
        """
        Stampa metriche di riepilogo ogni 10 secondi.
        Inoltre, se il debug è attivo, stampa la dimensione della coda ogni 2 secondi.
        """
        last_queue_log = time.time()
        while not self.stop_event.is_set():
            time.sleep(1)  # Controllo ogni secondo per maggiore precisione

            # === METRICHE COMPLETE OGNI 10 SECONDI ===
            if time.time() - self.metrics["last_log_time"] >= 10:
                with self.metrics_lock:
                    submitted = self.metrics["segments_submitted"]
                    completed = self.metrics["segments_completed"]
                    failed = self.metrics["segments_failed"]
                    avg_time = (self.metrics["total_response_time"] / completed) if completed > 0 else 0.0
                    queue_size = self.transcribe_queue.qsize()
                    self.metrics["last_log_time"] = time.time()
                logger.info("📊 Metriche: inviati=%d, completati=%d, falliti=%d, coda=%d, tempo_medio=%.2fs",
                            submitted, completed, failed, queue_size, avg_time)

            # === MONITORAGGIO VELOCE DELLA CODA (ogni 2 secondi, solo in DEBUG) ===
            if time.time() - last_queue_log >= 2:
                last_queue_log = time.time()
                queue_size = self.transcribe_queue.qsize()
                # Usa logger.debug per mostrarlo solo se il debug è attivo
                logger.debug("📋 Coda attuale: %d segmenti in attesa.", queue_size)

    def _transcribe_with_groq(self, audio):
        if self.use_flac:
            try:
                audio_bytes = audio_to_flac_bytes(audio, rate=self.rate)
                filename, content_type = "audio.flac", "audio/flac"
            except Exception as e:
                logger.error("Encoding FLAC fallito (%s), uso WAV per questo segmento.", e)
                audio_bytes = audio_to_wav_bytes(audio, rate=self.rate)
                filename, content_type = "audio.wav", "audio/wav"
        else:
            audio_bytes = audio_to_wav_bytes(audio, rate=self.rate)
            filename, content_type = "audio.wav", "audio/wav"

        files = {"file": (filename, audio_bytes, content_type)}
        data = {
            "model": self.groq_model,
            "language": "en",
            "response_format": "json",
            "prompt": INITIAL_PROMPT,
        }

        try:
            logger.debug("Invio richiesta a Groq: %s", filename)
            resp = self.session.post(
                self.groq_url,
                files=files,
                data=data,
                timeout=self.groq_timeout_s,
            )
            if resp.status_code != 200:
                logger.error("Errore HTTP %d: %s", resp.status_code, resp.text[:200])
                return None
            text = resp.json().get("text", "").strip()
            logger.debug("Risposta Groq ricevuta: %d caratteri", len(text) if text else 0)
            return text if text else None
        except requests.exceptions.Timeout:
            logger.error("Timeout dopo %ds - segmento perso.", self.groq_timeout_s)
            return None
        except Exception as e:
            logger.error("Errore: %s", e)
            return None

    def stop(self):
        logger.info("Arresto Transcriber in corso...")
        self.stop_event.set()
        self.transcribe_queue.put(None)
        self.dispatch_thread.join(timeout=3.0)
        self.executor.shutdown(wait=True)
        with self._result_lock:
            self._result_lock.notify_all()
        self.printer_thread.join(timeout=self.reorder_timeout_s + 1.0)
        self.metrics_thread.join(timeout=1.0)
        self.session.close()
        logger.info("Transcriber fermato.")