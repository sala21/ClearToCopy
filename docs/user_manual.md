# ClearToCopy — User Manual

**ClearToCopy** is a desktop application for real-time transcription of ATC (Air Traffic Control) radio communications. It captures audio from a microphone or audio line, automatically isolates individual transmissions using a voice activity detector (VAD), and transcribes them with a Whisper model specialized in aviation phraseology — **running entirely locally on the computer's GPU**, without sending any audio data to external services.

---

## Table of Contents

1. [Overview](#-overview)
2. [System Requirements](#-system-requirements)
3. [Starting the Application](#-starting-the-application)
4. [Main Interface](#-main-interface)
5. [Commands and Controls](#-commands-and-controls)
6. [Side Menu](#-side-menu)
7. [Configuration Window](#-configuration-window)
8. [Debug Window](#-debug-window)
9. [States and Indicators](#-states-and-indicators)
10. [Saving Transcriptions](#-saving-transcriptions)
11. [Saving Debug Logs](#-saving-debug-logs)
12. [Troubleshooting](#-troubleshooting)

---

## Overview

ClearToCopy is designed to:

- **Transcribe in real time** the ATC radio communications captured from a microphone or an audio line connected to the computer.
- **Automatically detect** the start and end of each transmission, thanks to the voice activity detector (VAD).
- **Filter the audio** with a band-pass filter (300–3400 Hz) to isolate the human voice from background noise.
- **Show in real time** the audio signal level, system status, and processing metrics.
- **Save** transcriptions to a `.txt` file and, if needed, technical logs to separate files.

The entire transcription happens **on your computer**: no internet connection is required while it's running (it's only needed the first time, to download the model, and at the start of each application session).

---

## System Requirements

- **Operating system**: Windows 10/11 (reference environment)
- **Python** 3.10 or higher, with the project's dependencies already installed (see [`README.md`](../README.md))
- **NVIDIA GPU** with at least 8 GB of VRAM, updated driver — strongly recommended. Without a compatible GPU, the application can run on CPU, but with much longer transcription times.
- **Microphone or audio line** correctly configured in the operating system.
- About **3 GB of free disk space** for the transcription model (downloaded automatically on first launch).
- **Pillow** (optional): if present, shows a small decorative illustration in the side menu. If absent, the application still works normally, simply without that graphical detail.

---

## Starting the Application

From a terminal, in the project folder (with the virtual environment active):

```bash
python gui_main.py
```

The main window opens. **The transcription model is loaded automatically and immediately**, as soon as the window appears — no action is required from you. During this phase:

- The **▶ START** button remains disabled.
- The bottom bar shows `⏳ Loading model...`.
- The **🧠 Local Model** indicator in the status panel stays red.

Loading can take up to about a minute (depending on disk speed and whether the model is already cached from a previous launch). Once done, the **▶ START** button becomes active and the bar shows `✅ Model loaded. Press 'Start' to begin.`

> 💡 **The model stays in memory for the entire duration of the application session**, even if you press STOP and then START multiple times: only the first time, when the program opens, is there a wait. The model is unloaded from video memory (VRAM) only when you fully close the window.

---

## Main Interface

The window is divided into three areas:

### Header (top)

- **☰ Menu**: shows/hides the side menu.
- **Status indicator**: a colored dot + text label (`STOPPED`, `LISTENING`) summarizing the application's overall state.

### Center column (dashboard)

- **Signal Level (RMS)**: a horizontal meter showing the incoming audio signal level in real time, with a vertical line marking the threshold above which the audio is considered "speech" rather than silence. Below the meter, a numeric label reports RMS, threshold, and outcome (`● ACCEPTED` or `○ SILENCE (discarded)`).
- **Transcription**: the main panel, where the transcribed text appears line by line, each preceded by the time it was recognized. If an audio segment produces no recognizable text, the label `(no text recognized)` appears.

### Right side column

- **Configuration Details**: a quick, read-only summary of the model in use, language, VAD sensitivity, and device (`cuda`/`cpu`).
- **System Status**: three indicators — Microphone, Local Model, Filter — each with a colored dot (green = active/ok, red = not active) and a status text. Also includes the elapsed time since transcription started (**Uptime**).
- **Metrics**: counters updated in real time — audio segments sent, completed, failed, average processing time, size of the waiting queue.

### Bottom bar

A line of colored text showing the application's latest status or error message (e.g. save confirmations, warnings, errors).

---

## Commands and Controls

| Command | Function |
|---|---|
| **▶ START** | Starts audio capture and transcription. Available only after the model has been loaded (see [Starting the Application](#-starting-the-application)). Each time it's pressed, the metric counters are reset, but the model stays loaded in memory — so starting is fast. |
| **■ STOP** | Stops audio capture and transcription (the model stays loaded in memory regardless, ready for a new Start). Before stopping, the application asks whether you want to save the accumulated transcription and, if debug mode is active, the technical log as well. |
| **DEBUG ON/OFF** | Enables/disables detailed recording of technical logs to a file, useful in case of unusual behavior that needs to be reported. Does not affect the transcription itself. |
| **☰ Menu** | Shows/hides the side menu. |

---

## Side Menu

Accessible via the **☰ Menu** button at the top left, it contains three buttons:

- **Debug**: opens the [debug window](#-debug-window), which shows the contents of the log file in real time.
- **Config**: opens the [configuration window](#-configuration-window).
- **Live Reload CFG**: reloads `config.json` from disk and applies the changes to VAD, filter, and (partially) the model parameters on the fly, **without needing to stop and restart transcription**. Only works if transcription is already running (after pressing START).

---

## Configuration Window

Opened from the side menu (**⚙️ Config**), it lets you modify `config.json` without editing it by hand. It's divided into four sections:

# Application Configuration

Below is the full documentation of all parameters available in the `config.json` file, including recent additions.

---

## Voice Activity Detection (VAD)

| Field | Meaning |
|-------|---------|
| `aggressiveness` (0-3) | How selective the detector is in distinguishing speech from noise. Higher values = more selective, with a risk of missing weak speech. |
| `silence_timeout_s` | How much continuous silence is needed to consider a transmission concluded. |
| `max_utterance_s` | Maximum duration of a single segment, beyond which it is forcibly cut. |
| `min_segment_duration_s` | Minimum duration below which a segment is discarded as likely noise. |
| `activation_ratio` (0-1) | How "confidently" speech must be detected before starting to record a segment. |
| `rms_gate_enabled` | If `true`, enables an additional filter based on the signal's RMS energy. Useful for excluding low-energy but persistent noise, improving the VAD's selectivity. |

---

## Band-Pass Filter

| Field | Meaning |
|-------|---------|
| `enabled` | Enables/disables the filter. |
| `band_min` / `band_max` (Hz) | Frequency range let through — tuned by default for the human voice over VHF radio. |

---

## Local Model (Whisper)

| Field | Meaning |
|-------|---------|
| `model_name` | Identifier of the Whisper model to use (Hugging Face repository). |
| `device` (`cpu`/`cuda`) | Where to run inference. |
| `language` | Forced language for transcription. |
| `max_new_tokens` | Maximum number of tokens generated per segment. Higher values allow longer transcriptions but increase inference time. |
| `no_repeat_ngram_size` | Prevents repetition of n-gram sequences within the output. With `3`, no consecutive triplets are repeated, reducing loops and hallucinations. |
| `repetition_penalty` | Penalizes generation of tokens that already appeared. Values > 1.0 reduce repetitions; the default (1.3) is a good compromise for radio speech. |
| `use_initial_prompt` | If `true`, the model uses an initial prompt to improve contextual coherence. |
| `reorder_timeout_s` | Maximum wait time (in seconds) for reordering segments in fine-grained detection mechanisms. Higher values can improve accuracy in the presence of overlaps. |

> ⚠️ **Important:** Changing `model_name` or `device` requires stopping and restarting the entire application (closing and reopening the window) — STOP/START alone is not enough, because the model is loaded only once when the program opens.

---

## Audio

Parameters related to capturing and pre-processing the signal:

| Field | Meaning |
|-------|---------|
| `rate` | Sample rate (Hz) at which the audio is acquired. The value 16000 is optimal for Whisper. |
| `channels` | Number of audio channels (1 = mono). The system expects a mono stream to reduce load. |
| `frame_duration_ms` | Duration (in milliseconds) of each frame processed by the VAD and the filter. 30 ms is the standard value for voice detection. |
| `input_gain` | Gain applied to the incoming signal (multiplicative factor). Values > 1.0 amplify the audio, useful for weak sources. |

---

## Debug

Parameters for logging and diagnostics:

| Field | Meaning |
|-------|---------|
| `enabled` | Enables/disables debug mode. If `true`, detailed logs are produced. |
| `log_to_file` | If `true`, logs are written to a file (in addition to the console). |
| `console_level` | Minimum severity level for messages shown on the console (e.g. `"INFO"`, `"DEBUG"`, `"WARNING"`). |

---

## Radio Settings

| Field | Meaning |
|-------|---------|
| `bypass_vad` | *(reserved)* If `true`, attempts to use fixed-time segmentation, but **in this version the VAD always stays active**; only a warning is shown in the "Mode" bar. |
| `segment_duration_s` | Fixed duration (in seconds) of each segment in time-based segmentation (not VAD-based). Default 3.0 s. |
| `overlap_s` | Overlap (in seconds) between consecutive segments, to avoid sharp cuts in the middle of words. |
| `silence_gate_enabled` | If `true`, enables a silence gate based on the RMS threshold to stop recording when the level drops below the threshold. |
| `silence_rms_threshold` | RMS threshold (linear value, 0–32767) for the silence gate. Typical values: 50 for quiet environments, 100–200 for noisy environments. |
| `boundary_search_s` | Width of the window (in seconds) in which to search for the optimal cut point around a segment boundary, to avoid truncating words. |
| `boundary_analysis_ms` | Resolution (in milliseconds) of the analysis for boundary search. Smaller values give more precise cuts but increase computational load. |

---


**Buttons:**
- **🔄 APPLY**: saves to `config.json` and applies the changes immediately, without closing the window.
- **✅ OK**: closes the window. **Important:** if you never pressed "Apply" during that window session, "OK" closes without saving the changes — always press **APPLY** first if you want the changes to take effect, then "OK" if you want to close.

---

## Debug Window

Shows in real time (updated every half second) the contents of the application's technical log file (`transcriber.log`, in the project folder). Useful for understanding what's happening "behind the scenes" in case of unexpected behavior, or to attach to a bug report.

---

## States and Indicators

| Indicator | Meaning |
|---|---|
| 🟢 green dot | Component active / working |
| 🔴 red dot | Component not active / in error |
| Overall state `STOPPED` | Transcription not running (the model may still already be loaded) |
| Overall state `LISTENING` | Transcription in progress |
| Local Model `NOT LOADED` | Loading not yet started or failed |
| Local Model `LOADED` | Model ready in VRAM |

**Level meter (RMS) colors:**
- Gray: below the threshold (silence)
- Green: normal level
- Amber: high level
- Red: very high level, possible signal clipping

---

## Saving Transcriptions

Pressing **■ STOP**, if transcription lines have been collected, the application asks whether to save them to a text file. If confirmed, a file is created in the project folder with a name in the format:

```
transcript_YYYYMMDD_HHMMSS.txt
```

If you choose not to save, the accumulated transcription is permanently discarded — make sure to answer "Yes" if you need to keep it. It starts fresh with every new **▶ START**.

---

## Saving Debug Logs

If **DEBUG** mode was enabled during the session, disabling it (or pressing **■ STOP**) prompts you to save or delete the technical log file (`transcriber.log`):

- **Save**: the file is renamed with a timestamp (e.g. `debug_20260710_143200.log`) and kept.
- **Delete**: the file's contents are erased.

---

## Troubleshooting

**Starting the application takes almost a minute**
Normal: this is the time needed to load the Whisper model into memory/VRAM, which happens automatically when the window opens. There's nothing to do, just wait for "▶ START" to become active.

**The "▶ START" button stays disabled for a long time or never activates**
Check the bottom bar or the **Debug** window: if an error message related to model loading appears, the most common cause is the GPU being unavailable or not having enough VRAM. Also check your internet connection if this is the very first launch (needed to download the model).

**No transcription appears even though someone is speaking on the radio**
Check the RMS meter: if the level always stays below the threshold (gray bar), the microphone might not be the right one in the system settings, or the volume is too low. Alternatively, try lowering `Aggressiveness` or `Activation ratio` in the configuration window.

**The transcription produces repeated, nonsensical words**
A typical symptom when an audio segment contains a long silent pause in the middle. Try lowering `Silence timeout (s)` in the VAD section, so segments get cut more frequently at pauses.

**I changed the configuration in the "⚙️ Config" window but nothing changed**
Make sure you pressed **🔄 APPLY** (not just "OK"): "OK" alone does not save the changes if "Apply" hasn't been pressed at least once during that window session.

**The "Live Reload CFG" button doesn't seem to have any effect**
It only works while transcription is **running** (after pressing START). Also, changes to the model name or device are not applied by this button: they require closing and reopening the entire application.

**For issues not resolved by this guide**, see the [Technical Manual](technical_manual_en.md) or open the Debug window to gather useful information before reporting the problem.
