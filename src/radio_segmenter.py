import threading
import numpy as np

from logger import get_logger

logger = get_logger()


class RadioSegmenter:
    """
    Segmentazione a finestra (quasi) fissa, alternativa al VAD classico.

    A differenza di VADProcessor (che segmenta sull'inizio/fine di una
    trasmissione rilevata), qui l'audio viene tagliato a intervalli di
    circa 'segment_duration_s', indipendentemente dal fatto che ci sia
    o meno una pausa netta. Pensato per traffico radio continuo dove le
    trasmissioni si susseguono senza silenzi chiari tra loro.

    Per ridurre gli artefatti di un taglio "cieco" a tempo fisso:
    - 'boundary_search_s'/'boundary_analysis_ms': invece di tagliare
      esattamente a 'segment_duration_s', cerca all'indietro (nella
      finestra di 'boundary_search_s') il punto di energia minima, così
      il taglio cade su una pausa reale invece che a metà parola.
    - 'overlap_s': l'ultima porzione del segmento appena tagliato viene
      ripetuta in testa al segmento successivo, per dare al modello un
      po' di contesto ed evitare di perdere parole esattamente sul bordo.
    - 'silence_gate_enabled'/'silence_rms_threshold': i segmenti la cui
      energia media (RMS) è sotto soglia vengono scartati senza essere
      inviati al modello (dead air, niente da trascrivere).

    Interfaccia compatibile con VADProcessor (process_frame, set_callback,
    update_params), cosi' main.py puo' trattare i due segmentatori in modo
    intercambiabile.
    """

    def __init__(
        self,
        rate=16000,
        frame_duration_ms=30,
        segment_duration_s=3.0,
        overlap_s=0.3,
        silence_gate_enabled=True,
        silence_rms_threshold=50,
        boundary_search_s=0.4,
        boundary_analysis_ms=20,
        event_bus=None,
    ):
        self._state_lock = threading.Lock()
        self.rate = rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_samples = int(rate * frame_duration_ms / 1000)

        self.segment_duration_s = segment_duration_s
        self.overlap_s = overlap_s
        self.silence_gate_enabled = silence_gate_enabled
        self.silence_rms_threshold = silence_rms_threshold
        self.boundary_search_s = boundary_search_s
        self.boundary_analysis_ms = boundary_analysis_ms
        self.event_bus = event_bus

        self.on_transcription_ready = None
        self._frames = []  # frame grezzi (bytes) non ancora tagliati in un segmento

        self._recompute_frame_counts()

        logger.debug(
            "RadioSegmenter inizializzato: segment_duration_s=%.2f, overlap_s=%.2f, "
            "silence_gate_enabled=%s, silence_rms_threshold=%.1f",
            segment_duration_s, overlap_s, silence_gate_enabled, silence_rms_threshold
        )

    def _recompute_frame_counts(self):
        self.target_frames = max(1, round(self.segment_duration_s * 1000 / self.frame_duration_ms))

        overlap_frames = max(0, round(self.overlap_s * 1000 / self.frame_duration_ms))
        # Non ha senso un overlap più lungo del segmento stesso: lo limitiamo
        # per evitare che il buffer non si svuoti mai tra un taglio e l'altro.
        self.overlap_frames = min(overlap_frames, self.target_frames - 1) if self.target_frames > 1 else 0

        boundary_search_frames = max(0, round(self.boundary_search_s * 1000 / self.frame_duration_ms))
        self.boundary_search_frames = min(boundary_search_frames, self.target_frames - 1) if self.target_frames > 1 else 0

        self.boundary_analysis_frames = max(1, round(self.boundary_analysis_ms / self.frame_duration_ms))

    def set_callback(self, callback):
        self.on_transcription_ready = callback

    @staticmethod
    def _frame_rms(frame_bytes):
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

    def process_frame(self, frame):
        with self._state_lock:
            segment_completed = False

            if self.event_bus:
                rms = self._frame_rms(frame)
                accepted = (not self.silence_gate_enabled) or (rms >= self.silence_rms_threshold)
                self.event_bus.emit(
                    "rms", value=rms, threshold=self.silence_rms_threshold, accepted=accepted
                )

            self._frames.append(frame)

            if len(self._frames) >= self.target_frames:
                segment_completed = self._cut_segment()

            return segment_completed

    def _find_cut_index(self):
        """
        Cerca, negli ultimi 'boundary_search_frames' frame prima del bordo
        target, la sotto-finestra di energia minima (dimensione
        'boundary_analysis_frames'), per spostare il taglio su una pausa
        reale. Se la ricerca non è configurata/possibile, ripiega sul
        taglio a tempo fisso ('target_frames').
        """
        target = self.target_frames
        if self.boundary_search_frames == 0 or self.boundary_analysis_frames > self.boundary_search_frames:
            return target

        search_start = target - self.boundary_search_frames
        energies = [self._frame_rms(f) for f in self._frames[search_start:target]]

        window = self.boundary_analysis_frames
        best_local_start = 0
        best_energy = None
        for start in range(0, len(energies) - window + 1):
            e = sum(energies[start:start + window]) / window
            if best_energy is None or e < best_energy:
                best_energy = e
                best_local_start = start

        return search_start + best_local_start + window // 2

    def _cut_segment(self):
        cut_index = self._find_cut_index()
        cut_index = max(1, min(cut_index, len(self._frames)))

        segment_frames = self._frames[:cut_index]
        overlap_tail = segment_frames[-self.overlap_frames:] if self.overlap_frames > 0 else []
        remaining_frames = self._frames[cut_index:]

        # Il prossimo segmento riparte dalla coda di overlap + quello che
        # non è ancora stato incluso in nessun segmento.
        self._frames = overlap_tail + remaining_frames

        audio_int16 = np.frombuffer(b"".join(segment_frames), dtype=np.int16).copy()
        if len(audio_int16) == 0:
            return False

        duration = len(audio_int16) / self.rate
        rms = float(np.sqrt(np.mean(audio_int16.astype(np.float64) ** 2)))

        if self.silence_gate_enabled and rms < self.silence_rms_threshold:
            logger.debug(
                "RadioSegmenter: segmento scartato (silenzio, durata=%.2fs, RMS=%.1f < soglia=%.1f).",
                duration, rms, self.silence_rms_threshold
            )
            return False

        # Normalizzazione di ampiezza: stessa logica usata da
        # VADProcessor._flush_segment, per coerenza di volume percepito
        # indipendentemente dalla modalità di segmentazione attiva.
        max_val = np.max(np.abs(audio_int16))
        if max_val > 0:
            audio_int16 = (audio_int16 / max_val * 0.9 * 32767).astype(np.int16)

        logger.debug("RadioSegmenter: segmento pronto (durata=%.2fs, RMS=%.1f).", duration, rms)
        if self.on_transcription_ready:
            self.on_transcription_ready(audio_int16)
            return True
        return False

    def update_params(self, segment_duration_s=None, overlap_s=None,
                       silence_gate_enabled=None, silence_rms_threshold=None,
                       boundary_search_s=None, boundary_analysis_ms=None):
        """Aggiorna i parametri in modo thread-safe. I frame già accumulati
        restano validi: verranno tagliati secondo i nuovi parametri al
        raggiungimento della prossima soglia."""
        with self._state_lock:
            if segment_duration_s is not None:
                self.segment_duration_s = segment_duration_s
            if overlap_s is not None:
                self.overlap_s = overlap_s
            if silence_gate_enabled is not None:
                self.silence_gate_enabled = silence_gate_enabled
            if silence_rms_threshold is not None:
                self.silence_rms_threshold = silence_rms_threshold
            if boundary_search_s is not None:
                self.boundary_search_s = boundary_search_s
            if boundary_analysis_ms is not None:
                self.boundary_analysis_ms = boundary_analysis_ms
            self._recompute_frame_counts()
