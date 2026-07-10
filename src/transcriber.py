import heapq
import itertools
import queue
import threading
import time
import numpy as np
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor
from concurrent.futures import ThreadPoolExecutor

from logger import get_logger

logger = get_logger()

# Tentativo di importare scipy per il filtro (invariato rispetto a prima)
try:
    from scipy import signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

TARGET_SAMPLE_RATE = 16000  # Whisper vuole sempre audio mono a 16kHz

# Stesso prompt usato con Groq: aiuta a orientare il modello sul
# vocabolario ATC (callsign, fraseologia, alfabeto fonetico). Con Whisper
# locale viene passato tramite processor.get_prompt_ids(), meccanismo
# equivalente al campo "prompt" che si mandava all'API Groq.
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
    """
    Trascrive segmenti audio usando un modello Whisper caricato in locale
    (via 'transformers'), invece di appoggiarsi all'API di Groq.

    L'interfaccia pubblica (enqueue, stop, set_audio_reference,
    update_local_model_settings) e gli eventi emessi sull'event_bus
    ("transcript", "metrics") sono identici a prima: il resto della
    pipeline (main.py, vad.py, la GUI) non deve cambiare nulla.

    NOTA SULLA CONCORRENZA: a differenza delle richieste HTTP a Groq (che
    potevano girare in parallelo su più thread), l'inferenza su una
    singola GPU va eseguita in modo seriale — chiamate concorrenti a
    model.generate() sullo stesso modello possono degradare le
    performance o dare risultati inattesi. Per questo il ThreadPoolExecutor
    qui sotto viene sempre creato con un solo worker, indipendentemente
    da eventuali valori residui di "max_concurrent_requests" in config.
    """

    def __init__(self, config, event_bus=None):
        logger.debug("Inizializzazione Transcriber (modello locale)...")
        self.event_bus = event_bus
        self.SCIPY_AVAILABLE = SCIPY_AVAILABLE
        self._filter_b = None
        self._filter_a = None
        self.audio_ref = None

        local_cfg = config.get("local_model", {})
        self.model_name = local_cfg.get("model_name", "jlvdoorn/whisper-large-v3-atco2-asr-atcosim")
        self.language = local_cfg.get("language", "en")
        self.max_new_tokens = local_cfg.get("max_new_tokens", 256)
        self.no_repeat_ngram_size = local_cfg.get("no_repeat_ngram_size", 3)
        self.repetition_penalty = local_cfg.get("repetition_penalty", 1.3)
        self.use_initial_prompt = local_cfg.get("use_initial_prompt", True)
        self.reorder_timeout_s = local_cfg.get("reorder_timeout_s", 3.0)

        requested_device = local_cfg.get("device", "cuda")
        if requested_device == "cuda" and not torch.cuda.is_available():
            logger.warning("device='cuda' richiesto ma CUDA non disponibile.")
            return
        else:
            self.device = requested_device

        self.filter_cfg_enabled = config.get("filter", {}).get("enabled", False)
        self.apply_filter = self.filter_cfg_enabled
        self.band_min = config.get("filter", {}).get("band_min", 300)
        self.band_max = config.get("filter", {}).get("band_max", 3400)
        self.rate = config.get("audio", {}).get("rate", 16000)
        self._recompute_filter()

        self._load_model()

        self.transcribe_queue = queue.Queue()
        self.stop_event = threading.Event()

        self.last_text = ""
        self.last_text_time = 0
        self._last_text_lock = threading.Lock()

        self._seq_counter = itertools.count()
        self._next_seq_to_print = 0
        self._result_heap = []
        self._result_lock = threading.Condition()

        # Un solo worker: vedi nota sulla concorrenza nel docstring della classe.
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="LocalModelWorker",
        )

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

        logger.info("Pronto. Modello locale: %s (device=%s)", self.model_name, self.device)

    # ------------------------------------------------------------------
    # Caricamento modello
    # ------------------------------------------------------------------
    def _load_model(self):
        t0 = time.time()
        logger.info("Caricamento modello %s su device=%s ...",
                    self.model_name, self.device)
        if self.event_bus:
            self.event_bus.emit("status", message=f"Caricamento modello {self.model_name}...")

        self.processor = WhisperProcessor.from_pretrained(self.model_name)

        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = WhisperForConditionalGeneration.from_pretrained(
            self.model_name,
            torch_dtype=dtype,
            low_cpu_mem_usage=True,
        ).to(self.device)
        self.model.eval()
        self._model_dtype = dtype

        self._forced_decoder_ids = self.processor.get_decoder_prompt_ids(
            language=self.language, task="transcribe"
        )

        self._prompt_ids = None
        if self.use_initial_prompt:
            self._prompt_ids = self.processor.get_prompt_ids(
                INITIAL_PROMPT, return_tensors="pt"
            ).to(self.device)

        elapsed = time.time() - t0
        logger.info("Modello caricato in %.1fs.", elapsed)
        if self.device == "cuda":
            peak = torch.cuda.max_memory_allocated() / (1024 ** 3)
            logger.info("VRAM allocata dopo il caricamento: %.2f GB", peak)

    def set_audio_reference(self, audio):
        """Fornisce un riferimento all'istanza AudioCapture per leggere i frame scartati."""
        self.audio_ref = audio

    def _recompute_filter(self):
        """Ricalcola (o disattiva) il filtro passa-banda in base allo stato corrente."""
        if not self.apply_filter:
            self._filter_b = None
            self._filter_a = None
            return
        if not self.SCIPY_AVAILABLE:
            logger.warning("scipy non installato: filtro disabilitato. Installa con: pip install scipy")
            self.apply_filter = False
            self._filter_b = None
            self._filter_a = None
            return
        self._filter_b = signal.firwin(65, [self.band_min, self.band_max], fs=self.rate, pass_zero=False)
        self._filter_a = [1.0]
        logger.info("Filtro passa-banda (ri)calcolato (%d-%d Hz).", self.band_min, self.band_max)

    # ------------------------------------------------------------------
    # Coda / dispatch
    # ------------------------------------------------------------------
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

        try:
            if self.apply_filter and self._filter_b is not None:
                if audio.dtype == np.int16:
                    audio_float = audio.astype(np.float32) / 32768.0
                else:
                    audio_float = audio.astype(np.float32)
                audio_filtered = signal.lfilter(self._filter_b, self._filter_a, audio_float)
                audio_filtered = np.clip(audio_filtered, -0.99, 0.99).astype(np.float32)
                text = self._transcribe_locally(audio_filtered)
            else:
                text = self._transcribe_locally(audio)
        except Exception as e:
            logger.error("Segmento seq=%d: errore imprevisto durante il processing: %s", seq, e, exc_info=True)
            text = None

        elapsed = time.time() - start_time
        with self.metrics_lock:
            if text is not None:
                self.metrics["segments_completed"] += 1
                self.metrics["total_response_time"] += elapsed
                logger.debug("Segmento seq=%d completato in %.2fs.", seq, elapsed)
            else:
                self.metrics["segments_failed"] += 1
                logger.warning("Segmento seq=%d fallito (errore o testo vuoto).", seq)

        # Anti-loop: scarta ripetizioni brevi identiche (invariato da prima)
        if text:
            with self._last_text_lock:
                if text == self.last_text and len(text) < 15:
                    text = None
                    logger.debug("Segmento seq=%d scartato (ripetizione breve).", seq)
                else:
                    self.last_text = text
                    self.last_text_time = time.time()

        self._submit_result(seq, text)

    def update_local_model_settings(self, language=None, max_new_tokens=None,
                                     no_repeat_ngram_size=None, repetition_penalty=None):
        """
        Aggiorna a caldo i parametri di generazione. NON supporta il cambio
        di 'model_name' o 'device' a caldo: richiedono di ricreare il
        Transcriber (quindi riavviare la trascrizione) perché comportano
        lo scaricamento/caricamento di pesi diversi in memoria/VRAM.
        """
        if language is not None and language != self.language:
            self.language = language
            self._forced_decoder_ids = self.processor.get_decoder_prompt_ids(
                language=self.language, task="transcribe"
            )
        if max_new_tokens is not None:
            self.max_new_tokens = max_new_tokens
        if no_repeat_ngram_size is not None:
            self.no_repeat_ngram_size = no_repeat_ngram_size
        if repetition_penalty is not None:
            self.repetition_penalty = repetition_penalty
        logger.info(
            "Parametri modello locale aggiornati: language=%s, max_new_tokens=%d, "
            "no_repeat_ngram_size=%d, repetition_penalty=%.2f",
            self.language, self.max_new_tokens, self.no_repeat_ngram_size, self.repetition_penalty
        )

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

        if self.event_bus:
            self.event_bus.emit("transcript", text=text)

    def _metrics_loop(self):
        last_queue_log = time.time()
        while not self.stop_event.wait(timeout=1.0):
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

                if self.event_bus:
                    dropped = self.audio_ref.dropped_frames if self.audio_ref else 0
                    self.event_bus.emit(
                        "metrics",
                        submitted=submitted, completed=completed, failed=failed,
                        queue_size=queue_size, avg_time=avg_time,
                        dropped_frames=dropped
                    )

            if time.time() - last_queue_log >= 2:
                last_queue_log = time.time()
                queue_size = self.transcribe_queue.qsize()
                logger.debug("📋 Coda attuale: %d segmenti in attesa.", queue_size)

    # ------------------------------------------------------------------
    # Inferenza locale
    # ------------------------------------------------------------------
    def _transcribe_locally(self, audio):
        """
        Trascrive un array audio numpy (int16 o float32) usando il modello
        Whisper caricato in memoria. Sostituisce la vecchia chiamata HTTP
        a Groq: nessuna rete, nessuna conversione a file WAV/FLAC, si
        lavora direttamente sull'array.
        """
        if audio.dtype == np.int16:
            audio_float = audio.astype(np.float32) / 32768.0
        else:
            audio_float = audio.astype(np.float32)

        inputs = self.processor(
            audio_float, sampling_rate=TARGET_SAMPLE_RATE, return_tensors="pt"
        )
        input_features = inputs.input_features.to(self.device)
        if self.device == "cuda":
            input_features = input_features.to(self._model_dtype)

        generate_kwargs = dict(
            forced_decoder_ids=self._forced_decoder_ids,
            max_new_tokens=self.max_new_tokens,
            no_repeat_ngram_size=self.no_repeat_ngram_size,
            repetition_penalty=self.repetition_penalty,
            condition_on_prev_tokens=False,
        )
        if self._prompt_ids is not None:
            generate_kwargs["prompt_ids"] = self._prompt_ids

        try:
            with torch.no_grad():
                predicted_ids = self.model.generate(input_features, **generate_kwargs)
            text = self.processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
            return text if text else None
        except torch.cuda.OutOfMemoryError:
            logger.error("CUDA out of memory durante l'inferenza. Segmento perso.")
            if self.device == "cuda":
                torch.cuda.empty_cache()
            return None
        except Exception as e:
            logger.error("Errore durante l'inferenza locale: %s", e, exc_info=True)
            return None

    def reset(self):
        """Resetta lo stato interno (coda, contatori, heap) senza fermare i thread."""
        # Svuota la coda
        while not self.transcribe_queue.empty():
            try:
                self.transcribe_queue.get_nowait()
            except queue.Empty:
                break
        # Resetta contatori
        with self.metrics_lock:
            self.metrics = {
                "segments_submitted": 0,
                "segments_completed": 0,
                "segments_failed": 0,
                "total_response_time": 0.0,
                "last_log_time": time.time()
            }
        # Resetta sequenza
        self._seq_counter = itertools.count()
        self._next_seq_to_print = 0
        # Svuota heap
        with self._result_lock:
            self._result_heap.clear()
        # Resetta ultimo testo
        with self._last_text_lock:
            self.last_text = ""
            self.last_text_time = 0
        logger.info("Transcriber resettato (coda svuotata, contatori azzerati).")


    def stop(self):
        logger.info("Arresto Transcriber in corso...")
        self.stop_event.set()
        self.transcribe_queue.put(None)
        self.dispatch_thread.join(timeout=3.0)
        self.executor.shutdown(wait=True)
        with self._result_lock:
            self._result_lock.notify_all()
        self.printer_thread.join(timeout=self.reorder_timeout_s + 1.0)
        self.metrics_thread.join(timeout=1.5)

        # Libera la VRAM: importante se l'app viene riavviata più volte
        # nello stesso processo (es. Stop poi Avvia di nuovo dalla GUI)
        del self.model
        del self.processor
        if self.device == "cuda":
            torch.cuda.empty_cache()

        logger.info("Transcriber fermato.")