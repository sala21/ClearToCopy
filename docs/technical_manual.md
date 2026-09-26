# ClearToCopy — Technical Manual

Documentation for developers: architecture, code structure, concurrency model, configuration schema, and maintenance notes.

> For day-to-day use of the application, see the [User Manual](user_manual_en.md). For installation, see the [`README.md`](../README.md).

---

## Table of Contents

1. [General Architecture](#-general-architecture)
2. [Repository Structure](#-repository-structure)
3. [Module by Module](#-module-by-module)
4. [Concurrency Model](#-concurrency-model)
5. [Model Lifecycle](#-model-lifecycle)
6. [EventBus and Event Contract](#-eventbus-and-event-contract)
7. [Application Configuration](#application-configuration)
8. [Hot Reload of Configuration](#-hot-reload-of-configuration)
9. [Considerations](#considerations)
10. [Extending the Project](#-extending-the-project)

---

## General Architecture

```
                     ┌─────────────────────────┐
                     │      gui_main.py        │  GUI entry point
                     └────────────┬────────────┘
                                  │
                     ┌────────────▼────────────────┐
                     │   gui/app.py                │
                     │   TranscriberGUI            │
                     │                             │
                     │  __init__:                  │
                     │   1. builds the UI          │
                     │   2. starts _load_model_async│──── loads Transcriber
                     │      (separate thread)      │      (weights into VRAM)
                     └────────────┬────────────────┘
                                  │ ▶ START
                     ┌────────────▼─────────────┐
                     │  main.run_pipeline()     │  dedicated pipeline thread
                     │  (reuses the already     │
                     │   loaded Transcriber)    │
                     └──┬──────────────┬────────┘
                        │              │
              ┌─────────▼──┐     ┌──────▼─────────┐
              │ AudioCapture│──▶│ VADProcessor   │
              │  (audio.py) │    │  (vad.py)      │
              └─────────────┘    └─────┬──────────┘
                                       │ segment ready
                                ┌──────▼───────────┐
                                │ Transcriber      │
                                │ (transcriber.py) │
                                │ filter + Whisper │
                                └──────┬───────────┘
                                       │ EventBus.emit(...)
                                ┌──────▼───────────┐
                                │  EventBus        │
                                │  (events.py)     │
                                └──────┬───────────┘
                                       │ poll every 100ms (Tk thread)
                                ┌──────▼──────────────┐
                                │  TranscriberGUI     │
                                │  (updates widgets)  │
                                └─────────────────────┘
```

**Key architectural decision**: the Whisper model is loaded **only once**, when the GUI starts, and is **reused** across Start/Stop cycles via `Transcriber.reset()` (clears queues and counters without touching the weights in VRAM). It is released (`Transcriber.stop()`) only when the window is closed. This avoids the reload cost (tens of seconds) on every Start.

---

## Repository Structure

```
.
├── main.py                 # Pipeline orchestration (CLI + reusable from GUI)
├── gui_main.py              # GUI entry point
├── config.py                 # config.json loading
├── paths.py                   # BASE_DIR, CONFIG_PATH, LOG_FILE (independent of config/logger)
├── config.json                 # Runtime configuration
├── audio.py                     # Audio capture (PyAudio)
├── vad.py                        # Voice Activity Detection and segmentation
├── transcriber.py                 # Local Whisper inference
├── utils.py                        # Audio → WAV/FLAC conversion (no longer used by transcriber.py)
├── logger.py                        # Logging (console + file)
├── events.py                         # Thread-safe EventBus pipeline → GUI
└── gui/
    ├── __init__.py
    ├── app.py                # Main window, GUI-side orchestration
    ├── config_window.py       # config.json editor
    ├── debug_window.py         # Live tail of the log file
    └── theme.py                 # Color palette and fonts
```

---

## Module by Module

### `paths.py`

The single source of truth for paths, with no dependency on `config.py` or `logger.py` (avoids circular imports, since both of them import it).

```python
BASE_DIR    # folder of the executable (if packaged with PyInstaller) or of the script
CONFIG_PATH # BASE_DIR/config.json
LOG_FILE    # "transcriber.log" — NB: relative to the CWD, not to BASE_DIR
```

> ⚠️ `LOG_FILE` is not anchored to `BASE_DIR` like the other two. If the application is launched from a working directory different from the one containing the source files (e.g. a desktop shortcut with "Start in" set elsewhere), the log file ends up in an unexpected place. See [Maintenance Notes](#-maintenance-notes-and-known-issues).

### `config.py`

`load_config()` reads `CONFIG_PATH`, and terminates the process (`sys.exit(1)`) if the file does not exist.

### `audio.py` — `AudioCapture`

A wrapper around PyAudio in callback mode (non-blocking). It writes captured frames to a `queue.Queue` with a maximum size (`max_queue_size=200`); if the consumer (the main loop) can't keep up, the excess frames are dropped and counted in `self.dropped_frames` (later exposed in the metrics sent to the GUI).

### `vad.py` — `VADProcessor`

A voice-activity detector based on [`webrtcvad`](https://github.com/wiseman/py-webrtcvad), with **O(1) sliding-window** segmentation (no repeated scanning of the buffer on every frame).

Key concepts:
- **`ring_buffer`** (pre-roll, ~300ms): keeps the last frames before activation, so the start of the utterance isn't lost.
- **`activation_ratio`**: the percentage of "voiced" frames in the pre-roll needed to consider a transmission as having started.
- **`ring_buffer_silence`**: counts consecutive silent frames once activated, to decide when the transmission has ended (`silence_timeout_s`).
- **`max_utterance_s`**: a forced safety cutoff, independent of silence detection.
- **`_state_lock`** (`threading.Lock`): protects all internal state, because `process_frame()` runs on the pipeline thread while `update_params()` can be called from the Tkinter thread (hot reload) — see [Concurrency Model](#-concurrency-model).

`update_params()` closes any in-progress segment before recreating the buffers, so audio isn't lost mid-utterance during a reload.

### `transcriber.py` — `Transcriber`

The heart of the pipeline. It exposes:

```python
Transcriber(config, event_bus=None)
.enqueue(audio_np: np.ndarray)              # queues a segment (int16 or float32)
.set_audio_reference(audio: AudioCapture)   # to read dropped_frames in the metrics
.update_local_model_settings(language=None, max_new_tokens=None,
                              no_repeat_ngram_size=None, repetition_penalty=None)
.reset()                                     # clears queues/counters, does NOT touch the model
.stop()                                       # stops the threads and frees VRAM
```

##

- **`dispatch_thread`**: pulls from the FIFO queue and submits the work to the executor.
- **`ThreadPoolExecutor(max_workers=1)`**: **deliberately limited to a single worker**. Inference runs on a single GPU; concurrent calls to `model.generate()` on the same model bring no benefit and risk memory contention. With a single worker, reordering is effectively always "already in order," but the mechanism remains as a low-cost safety net.
- **`printer_thread`**: pulls results from the min-heap in sequence order, with a reordering timeout (`reorder_timeout_s`) to avoid blocking indefinitely on a segment that never arrives.
- **`metrics_thread`**: publishes a `"metrics"` event roughly every 10s.

**Band-pass filter**: computed once with `scipy.signal.firwin` in `_recompute_filter()`, callable again at runtime (hot reload) without needing to be recreated from scratch by the calling code.

**Inference** (`_transcribe_locally`): normalizes the audio array to float32 `[-1, 1]`, passes it to `WhisperProcessor`, and runs `model.generate()` with:
- `forced_decoder_ids` — enforces the language and task (`transcribe`)
- `no_repeat_ngram_size`, `repetition_penalty`, `condition_on_prev_tokens=False` — mitigate the repetition loops typical of Whisper on segments with internal silences
- `prompt_ids` (optional, `use_initial_prompt`) — injects a fixed prompt with ATC vocabulary (callsigns, phraseology, phonetic alphabet) to steer the decoder


### `main.py` — `run_pipeline()`

```python
def run_pipeline(config, event_bus=None, stop_event=None,
                  components_ref=None, transcriber=None):
```

- If `transcriber` is `None`, it creates a new one (used by `python main.py` in standalone CLI mode).
- If `transcriber` is already provided (the GUI case), it reuses it and reassigns its `event_bus`.
- `components_ref`, if passed (a dictionary), is populated with the real references to `audio`, `vad`, `transcriber` **before** entering the blocking loop — this lets the caller (the GUI) act on the actually-running instances for hot reload.
- The `finally` block only calls `audio.stop()`, **not `transcriber.stop()`**: consistent with the choice to keep the model loaded across cycles. Whoever owns the `Transcriber`'s lifecycle (the GUI, or the caller of `run_pipeline` in general) is responsible for calling `.stop()` when it's genuinely no longer needed.

### `gui/app.py` — `TranscriberGUI`

The largest file in the project. Key points beyond widget construction:

- **`_load_model_async()`**: a separate thread that creates `Transcriber(config, event_bus=None)` when the window opens (`event_bus` is assigned only on the first Start). Updates `self.model_loaded` and re-enables **▶ START** when done.
- **`_pipeline_thread(config, transcriber)`**: a dedicated thread for each Start/Stop session, calling `main.run_pipeline(...)` and passing in the already-loaded transcriber.
- **`_poll_events()`**: runs every 100ms on the main Tkinter thread via `root.after`, consumes events from the `EventBus`, and updates the widgets. It is the **only point of contact** between the background threads and Tkinter — no other part of the code should touch widgets from a thread other than the main one.
- **`on_close()`**: the only place where `transcriber.stop()` is called, and therefore the only moment when VRAM is actually freed during the life of the GUI process.

### `gui/config_window.py` — `ConfigWindow`

A generic editor based on lists of `(key, label, default_value)` tuples for each section (VAD, Filter, Local Model, Radio) — adding a new configurable field is just one row added to the corresponding list plus the constant in the patch dictionary; no further boilerplate is needed.

`_apply_config()` writes to `config.json` and immediately calls `self.app._reload_config()`. `_save_and_close()` does the same **only if `self.apply_pressed` is `True`** (set inside `_apply_config`) — if the user never pressed "Apply" and presses "OK" directly, the window closes without writing anything. See [Maintenance Notes](#-maintenance-notes-and-known-issues).

### `gui/debug_window.py` — `DebugWindow`

A "poor man's" tail of the log file: re-reads from `self.last_pos` every 500ms. The file (`"transcriber.log"`, a relative path) is independent of the application logger — it opens/closes the file on every poll instead of keeping it open, a simple choice but with repeated I/O overhead (acceptable at the current polling frequency).

---

## Concurrency Model

| Thread | Origin | Responsibility |
|---|---|---|
| Main Tkinter thread | `gui_main.py` | UI, `_poll_events()` every 100ms |
| Model-loading thread | `_load_model_async` | Instantiates `Transcriber` (once, at startup) |
| Pipeline thread | `_pipeline_thread` (one per Start/Stop session) | Runs `run_pipeline`: frame-capture loop + `vad.process_frame()` |
| `dispatch_thread` (Transcriber) | `Transcriber.__init__` | Pulls from the queue, submits to the executor |
| `LocalModelWorker` (executor, 1 worker) | `Transcriber.__init__` | Runs `_process_segment` → GPU inference |
| `printer_thread` (Transcriber) | `Transcriber.__init__` | Reorders and publishes results on the `EventBus` |
| `metrics_thread` (Transcriber) | `Transcriber.__init__` | Publishes periodic metrics |

**Golden rule**: no thread other than the main Tkinter thread touches widgets directly. All communication toward the GUI goes through `EventBus.emit(...)` (thread-safe, based on `queue.Queue`) and is consumed only by `_poll_events()`.

**Synchronization points between hot reload and an active pipeline**:
- `VADProcessor._state_lock`: protects `process_frame()` (pipeline thread) from `update_params()` (Tkinter thread, called from `_reload_config`).
- `Transcriber` has no equivalent explicit lock on the generation parameters (`language`, `max_new_tokens`, etc.) — they are plain Python attributes re-read on every call to `_transcribe_locally`. Since the worker is single and sequential, the practical risk of a race condition is low, but it is not a formal guarantee like the VAD's.

---

## Model Lifecycle

```
                    GUI opens
                      │
                      ▼
                    _load_model_async() ──► Transcriber(config)  [loads weights into VRAM, ~30-60s]
                      │
                      ▼
              _____ ▶ START ──► transcriber.reset() ──► run_pipeline(..., transcriber=<existing>)
              |       │                                        │
              |       ▼                                        ▼
              |       |                             capture + VAD + transcription
 no           |       │
reload        |       ■ STOP ──► stop_event.set() ──► audio.stop()  [the model STAYS in VRAM]
              |       |
              |       ▼
              |_______|
                      │
                      ▼
                    Window closes (on_close) ──► transcriber.stop()  [VRAM freed]
```

This design is deliberate: reloading a large Whisper model every time the user stops and restarts transcription would cost tens of unnecessary seconds. The cost is paid only once, when the application opens.

---

## EventBus and Event Contract

`EventBus` (`events.py`) is a thread-safe FIFO queue with no logic of its own: `emit(kind, **data)` enqueues a `(kind, data)` tuple, `poll_all()` drains it. No filtering, no persistence.

Events currently emitted and consumed by `gui/app.py::_poll_events`:

| `kind` | Emitted by | Payload | Effect in the GUI |
|---|---|---|---|
| `"rms"` | VAD (not shown in the files read in this session, presumably from `vad.py` or `audio.py` in a future revision) | `value`, `threshold`, `accepted` | Updates the RMS meter |
| `"transcript"` | `Transcriber._print_result` | `text` | Adds a line to the transcription panel |
| `"metrics"` | `Transcriber._metrics_loop` | `submitted`, `completed`, `failed`, `queue_size`, `avg_time`, `dropped_frames` | Updates the metrics panel |
| `"status"` | `Transcriber._load_model`, `main.run_pipeline` | `message` | Shows the message in the bottom bar |
| `"error"` | `TranscriberGUI._pipeline_thread` (unhandled exceptions) | `message` | Shows the error in red |
| `"stopped"` | `TranscriberGUI._pipeline_thread` (`finally` block) | — | Restores the "STOPPED" state |
| `"model_loaded"` | `main.run_pipeline` | — | Visual confirmation that the model is ready |
| `"audio_started"` | `main.run_pipeline` | — | Sets the "LISTENING" state |

> Note: the `"rms"` event is not emitted by any of the modules included in this revision of the code (`audio.py`, `vad.py`); the level meter in the dashboard, as things stand, receives no runtime updates until this event is actually published somewhere in the capture/VAD pipeline. Check whether this is a feature still in development or code removed by mistake.

---


## Application Configuration

Below is the full documentation of **all** parameters available in the `config.json` file.

---

## Voice Activity Detection (VAD)

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `aggressiveness` | integer | 0–3 | How selective the VAD is. **0** = less selective (also captures weak speech, but more false positives). **3** = maximum selectivity (reduces false positives but risks excluding quiet speech). Recommended value: `1` for general use. |
| `silence_timeout_s` | float | ≥ 0.1 | Seconds of continuous silence needed to consider a segment concluded. Lower values cut sooner, higher values keep the segment open longer. Typical: `1.0` s. |
| `max_utterance_s` | float | ≥ 1.0 | Maximum duration of a single segment. Beyond this limit the segment is forced to end. Prevents excessively long transcriptions. Default: `7.0` s. |
| `min_segment_duration_s` | float | ≥ 0.1 | Minimum acceptable duration for a segment. Shorter segments are discarded as likely noise. Typical: `0.6` s. |
| `activation_ratio` | float | 0.0–1.0 | Minimum ratio of "active" (voiced) frames to total needed to start a segment. Higher values require more continuous speech before activating. Typical: `0.4`. |
| `rms_gate_enabled` | boolean | `true`/`false` | If `true`, enables an additional filter based on the signal's RMS (Root Mean Square) energy. Excludes low-energy but persistent noise (e.g. background hum). Improves selectivity in moderately noisy environments. |

---

## Band-Pass Filter

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `enabled` | boolean | `true`/`false` | Enables or disables the band-pass filter. If `false`, audio is processed without filtering. |
| `band_min` | integer | 20–20000 (Hz) | Minimum frequency (Hz) of the filter. Everything below is attenuated. Tuned by default for human speech over VHF: `300` Hz. |
| `band_max` | integer | 20–20000 (Hz) | Maximum frequency (Hz) of the filter. Everything above is attenuated. Default: `3400` Hz (telephone band). |

---

## Local Model (Whisper)

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `model_name` | string | Hugging Face identifier | Name of the Whisper model to load (e.g. `"jlvdoorn/whisper-large-v3-atco2-asr-atcosim"`). **Requires an app restart** to take effect. |
| `device` | string | `"cpu"` / `"cuda"` | Device for inference. `"cuda"` uses the GPU (faster), `"cpu"` uses the processor. **Requires a restart**. |
| `language` | string | ISO 639-1 code | Forced language for transcription. E.g. `"en"` for English, `"it"` for Italian. If not specified, Whisper attempts to auto-detect it. |
| `max_new_tokens` | integer | ≥ 1 | Maximum number of tokens generated per segment. Higher values allow longer transcriptions, but increase inference time and memory use. Typical: `256`. |
| `no_repeat_ngram_size` | integer | ≥ 1 | Size of the n-gram to avoid repeating. Setting `3` means the model will never generate a sequence of 3 identical consecutive tokens. Reduces loops and hallucinations. Typical: `3`. |
| `repetition_penalty` | float | ≥ 1.0 | Penalty factor for repeating already-generated tokens. Values > `1.0` discourage repetition. `1.3` is a good compromise for radio speech. Too-high values can hurt naturalness. |
| `use_initial_prompt` | boolean | `true`/`false` | If `true`, the model receives an initial prompt (e.g. "Transcribe the following audio") to improve contextual coherence and transcription quality. |
| `reorder_timeout_s` | float | ≥ 0.1 | Maximum wait time (in seconds) for reordering segments when using fine-grained detection mechanisms (e.g. to handle overlaps). Higher values improve accuracy at the cost of latency. Typical: `3.0` s. |

> ⚠️ **Important:** `model_name` and `device` require a full restart of the application (closing and reopening the window). Changing them on the fly has no effect.

---

## Audio

Parameters for acquisition and pre-processing of the audio signal.

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `rate` | integer | 8000, 16000, 44100, etc. | Sample rate (Hz) for acquisition. Whisper is optimized for `16000` Hz; using other values may degrade performance. |
| `channels` | integer | 1 (mono) / 2 (stereo) | Number of audio channels. The system is designed for a mono (`1`) stream to reduce computational load and simplify processing. |
| `frame_duration_ms` | integer | 10–100 (ms) | Duration in milliseconds of each audio frame processed by the VAD and the filter. `30` ms is the standard value for voice detection (a balance between precision and responsiveness). |
| `input_gain` | float | ≥ 0.1 | Multiplicative gain applied to the incoming signal. Values > `1.0` amplify the audio (useful for low-sensitivity microphones or distant sources). Be careful not to cause clipping. Typical: `1.0`. |

---

## Debug

Controls for logging and diagnostics.

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `enabled` | boolean | `true`/`false` | Enables debug mode. If `true`, detailed logs of every phase are produced (VAD, transcription, filters, etc.), useful for troubleshooting. |
| `log_to_file` | boolean | `true`/`false` | If `true`, logs are also written to a file (in addition to the console). The file path is defined at the application level. |
| `console_level` | string | `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"` | Minimum severity level for messages shown in the console. `"DEBUG"` shows everything, `"ERROR"` only critical errors. `"INFO"` is recommended for normal use. |

---

## Radio Settings

Parameters specific to handling radio audio streams (e.g. VHF communications), with segmentation and silence control.

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `enabled` | boolean | `true`/`false` | Enables/disables "radio" mode. If `false`, the system uses the standard VAD and segmentation settings. |
| `bypass_vad` | boolean | `true`/`false` | If `true`, the system attempts to use fixed-time segmentation instead of the VAD. |
| `segment_duration_s` | float | ≥ 0.5 | Fixed duration of each segment when using time-based segmentation (non-VAD). Default value: `3.0` s. Used only if the VAD is bypassed (not yet implemented). |
| `overlap_s` | float | 0.0 – `segment_duration_s` | Overlap in seconds between consecutive segments. Reduces the risk of cutting off words at boundaries. Typical values: `0.3`–`0.5` s. |
| `silence_gate_enabled` | boolean | `true`/`false` | If `true`, enables a silence gate based on the RMS threshold. When the level drops below the threshold, recording of the segment is stopped (useful for intermittent background noise). |
| `silence_rms_threshold` | integer | 0–32767 | Linear RMS threshold for the silence gate. Recommended values: `50` for very quiet environments, `100–200` for moderately noisy environments. Higher values make the gate less sensitive. |
| `boundary_search_s` | float | 0.1–1.0 | Width of the time window (in seconds) within which to search for the optimal cut point around a segment boundary. Avoids truncating words mid-way. Typical: `0.4` s. |
| `boundary_analysis_ms` | integer | 5–50 | Time resolution (in milliseconds) of the analysis for boundary search. Smaller values give more precise cuts but increase computational load. Typical: `20` ms. |

---

## General Notes

- **Order of application**: The captured audio is first amplified (`input_gain`), then band-pass filtered, then processed by the VAD (and/or the radio controls), and finally sent to the Whisper model for transcription.
- **Performance tips**:
  - To reduce latency, decrease `max_new_tokens` and `reorder_timeout_s`.
  - To improve accuracy in noisy environments, increase `aggressiveness` and enable `rms_gate_enabled`.
  - For smoother transcriptions, increase `overlap_s` and `boundary_search_s` (at the cost of a slight increase in load).

---

## Hot Reload of Configuration

`TranscriberGUI._reload_config()` (triggered by the "🔄 Live Reload CFG" button or by the configuration window after "Apply") applies changes to the already-active components without stopping the pipeline:

| Parameter | Applied on the fly? | Notes |
|---|---|---|
| `vad.*` | ✅ Yes | Via `VADProcessor.update_params()`, thread-safe |
| `filter.*` | ✅ Yes | Via `transcriber._recompute_filter()` |
| `local_model.language` | ✅ Yes | Via `transcriber.update_local_model_settings()` |
| `local_model.max_new_tokens` | ✅ Yes | same |
| `local_model.no_repeat_ngram_size` | ✅ Yes | same |
| `local_model.repetition_penalty` | ✅ Yes | same |
| `local_model.model_name` | ❌ No | Requires a full application restart (the model is loaded only once, at startup) |
| `local_model.device` | ❌ No | Same |
| `radio.*` | ❌ No | Section not wired into the pipeline |

The reload requires the pipeline to already be active (`self.running`); if the components are not yet ready, `_reload_config` reschedules itself after 300ms instead of failing silently.

---

## Considerations

An honest list of areas to revisit, for whoever picks the code back up:


1. **`Transcriber.__init__` no longer has an automatic fallback to CPU.** In the current revision:
   ```python
   if requested_device == "cuda" and not torch.cuda.is_available():
       logger.warning("device='cuda' requested but CUDA is not available.")
       return
   ```
   The `return` here exits `__init__` **before** setting `self.device` and before creating queues/threads or loading the model. The resulting `Transcriber` object is in a partially-initialized, unusable state (attributes such as `self.device`, `self.model`, `self.transcribe_queue` are missing). Any subsequent call (e.g. `enqueue()`) will raise `AttributeError`. To fix: either restore the automatic CPU fallback (`self.device = "cpu"` with explicit logging) or raise an explicit exception (`raise RuntimeError(...)`) instead of a silent `return`, so that the caller (`_load_model_async` in `app.py`, which already catches `Exception`) can handle it properly instead of ending up with a broken but apparently-created object.

---

## Extending the Project

**Adding a new hot-reloadable configuration parameter (e.g. a new Whisper generation parameter):**
1. Add it with a sensible default in `config.json`.
2. Read it in `Transcriber.__init__` (or the dedicated reload method) and add the corresponding parameter to `update_local_model_settings()`.
3. Add the entry to the `local_model_params` list in `gui/config_window.py::_build_ui`, and the corresponding field in `_get_patch_from_entries` / `_save_config_with_patch` / `_update_entries_from_config`.
4. If it needs to be applied on the fly, add the corresponding call in `TranscriberGUI._reload_config`.

**Changing the base Whisper model:** simply change `local_model.model_name` in `config.json` (or from the configuration window) and restart the application — no code changes required, as long as the new checkpoint is compatible with the Transformers `WhisperForConditionalGeneration`/`WhisperProcessor` API.
