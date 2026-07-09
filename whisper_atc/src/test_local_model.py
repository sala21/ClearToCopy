"""
Script di test isolato: carica il modello whisper-large-v3-atco2-asr(-atcosim)
di jlvdoorn/WhisperATC e trascrive uno o più file audio locali, misurando
tempo di inferenza e stampando il testo, cosi' puoi confrontarlo "a orecchio"
con quello che oggi ti restituisce Groq sugli stessi file.

NON fa parte della pipeline principale: e' solo per decidere se vale la pena
integrare il modello locale al posto di Groq.

Requisiti (da installare UNA volta sul tuo PC, non qui):
    pip install torch --index-url https://download.pytorch.org/whl/cu124
    pip install transformers accelerate soundfile librosa

NB sulla riga di torch: installa la build CUDA giusta per la tua scheda.
Controlla su https://pytorch.org/get-started/locally/ la combinazione
corretta per la RTX 5050 (driver/CUDA toolkit che hai installato).
"""

import argparse
import time
import sys

import torch
import soundfile as sf
import librosa
import numpy as np
from transformers import WhisperForConditionalGeneration, WhisperProcessor

# Modelli disponibili (scegli quello che preferisci testare)
MODEL_OPTIONS = {
    "atco2": "jlvdoorn/whisper-large-v3-atco2-asr",
    "atcosim": "jlvdoorn/whisper-large-v3-atcosim",
    "combined": "jlvdoorn/whisper-large-v3-atco2-asr-atcosim",
}

TARGET_SR = 16000  # Whisper vuole audio mono a 16kHz


def load_audio(path):
    """
    Carica un file audio qualsiasi (wav, flac, mp3 se ffmpeg e' installato...)
    e lo converte in mono float32 a 16kHz, il formato che si aspetta Whisper.
    """
    audio, sr = librosa.load(path, sr=TARGET_SR, mono=True)
    return audio.astype(np.float32)


def load_model(model_key, device):
    model_name = MODEL_OPTIONS[model_key]
    print(f"[1/3] Scaricamento/caricamento modello: {model_name}")
    print("      (la prima volta scarica ~3GB da Hugging Face, poi resta in cache locale)")

    t0 = time.time()
    processor = WhisperProcessor.from_pretrained(model_name)

    # float16 sulla GPU per risparmiare VRAM e velocizzare; su CPU serve float32
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = WhisperForConditionalGeneration.from_pretrained(
        model_name,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(device)
    model.eval()

    print(f"      Modello caricato in {time.time() - t0:.1f}s su device={device}")
    return model, processor


def split_on_silence(audio, top_db=35, min_silence_s=0.5):
    """
    Spezza l'audio nei punti di silenzio, in modo simile (anche se più
    grezzo) a quello che fa VADProcessor nella pipeline reale. Serve per
    testare il modello su segmenti realistici invece che su un blocco
    grezzo con pause nel mezzo, che causa i loop di ripetizione visti
    nel primo test.
    """
    intervals = librosa.effects.split(
        audio, top_db=top_db, frame_length=2048, hop_length=512
    )
    min_silence_samples = int(min_silence_s * TARGET_SR)

    # Unisce intervalli separati da silenzi troppo brevi per essere una
    # vera pausa tra trasmissioni (evita di spezzare in mezzo a una parola)
    merged = []
    for start, end in intervals:
        if merged and start - merged[-1][1] < min_silence_samples:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    return [audio[s:e] for s, e in merged]


def transcribe_chunk(model, processor, device, audio, language="en"):
    inputs = processor(
        audio, sampling_rate=TARGET_SR, return_tensors="pt"
    )
    input_features = inputs.input_features.to(device)
    if device == "cuda":
        input_features = input_features.to(torch.float16)

    # Forza la lingua/task come fai gia' con Groq (language="en")
    forced_decoder_ids = processor.get_decoder_prompt_ids(
        language=language, task="transcribe"
    )

    print("[3/3] Inferenza in corso...")
    t0 = time.time()
    with torch.no_grad():
        predicted_ids = model.generate(
            input_features,
            forced_decoder_ids=forced_decoder_ids,
            max_new_tokens=256,
            # Anti-loop: senza questi, un silenzio nel mezzo del clip può far
            # entrare il decoder in un ciclo che ripete lo stesso token
            # all'infinito (es. "a a a a a..."). condition_on_prev_tokens=False
            # evita che il rumore/silenzio "avveleni" il contesto delle parole
            # successive nello stesso blocco.
            no_repeat_ngram_size=3,
            repetition_penalty=1.3,
            condition_on_prev_tokens=False,
        )
    elapsed = time.time() - t0

    text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
    return text, elapsed


def transcribe_file(model, processor, device, audio_path, language="en", split=True):
    print(f"[2/3] Carico audio: {audio_path}")
    audio = load_audio(audio_path)
    duration_s = len(audio) / TARGET_SR
    print(f"      Durata totale: {duration_s:.1f}s")

    if not split:
        # Comportamento vecchio: un unico blocco grezzo. Utile solo per
        # capire quanto e' grave il problema dei loop di ripetizione su
        # audio con silenzi nel mezzo; sconsigliato per valutare la
        # qualita' reale del modello.
        text, elapsed = transcribe_chunk(model, processor, device, audio, language)
        rtf = elapsed / duration_s if duration_s > 0 else float("nan")
        print(f"      Inferenza completata in {elapsed:.2f}s (RTF={rtf:.2f})")
        return [(0.0, duration_s, text)], elapsed

    print("[3/3] Segmentazione sui silenzi (come farebbe il VAD nella pipeline reale)...")
    chunks = split_on_silence(audio)
    print(f"      Trovati {len(chunks)} segmenti di parlato")

    results = []
    total_elapsed = 0.0
    cursor = 0
    for i, chunk in enumerate(chunks):
        chunk_duration = len(chunk) / TARGET_SR
        if chunk_duration < 0.3:
            continue  # scarta scampoli troppo corti, come min_segment_duration_s nel VAD
        text, elapsed = transcribe_chunk(model, processor, device, chunk, language)
        total_elapsed += elapsed
        rtf = elapsed / chunk_duration if chunk_duration > 0 else float("nan")
        print(f"      [{i+1}/{len(chunks)}] {chunk_duration:.1f}s -> "
              f"{elapsed:.2f}s (RTF={rtf:.2f}): {text}")
        results.append((cursor / TARGET_SR, (cursor + len(chunk)) / TARGET_SR, text))
        cursor += len(chunk)

    return results, total_elapsed


def main():
    parser = argparse.ArgumentParser(
        description="Test locale WhisperATC vs Groq su file audio esistenti."
    )
    parser.add_argument(
        "audio_files", nargs="+",
        help="Uno o piu' file audio da trascrivere (wav/flac consigliati)."
    )
    parser.add_argument(
        "--model", choices=MODEL_OPTIONS.keys(), default="combined",
        help="Quale checkpoint WhisperATC usare (default: combined)."
    )
    parser.add_argument(
        "--language", default="en",
        help="Lingua forzata per la trascrizione (default: en, come in transcriber.py)."
    )
    parser.add_argument(
        "--no-split", action="store_true",
        help="Trascrivi il file come blocco unico invece di spezzarlo sui silenzi "
             "(sconsigliato: su audio con pause nel mezzo puo' causare loop di "
             "ripetizione, vedi il test iniziale su test.wav)."
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        print("⚠️  CUDA non disponibile: il modello girerà su CPU, sarà MOLTO più lento.")
        print("   Controlla che torch sia installato con supporto CUDA "
              "(vedi commento in cima allo script).")
        device = "cpu"
    else:
        device = "cuda"
        print(f"✅ GPU rilevata: {torch.cuda.get_device_name(0)}")
        total_vram = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"   VRAM totale: {total_vram:.1f} GB")

    model, processor = load_model(args.model, device)

    print("\n" + "=" * 70)
    for audio_path in args.audio_files:
        try:
            results, total_elapsed = transcribe_file(
                model, processor, device, audio_path,
                language=args.language, split=not args.no_split
            )
        except Exception as e:
            print(f"❌ Errore su {audio_path}: {e}")
            continue

        print(f"\n📄 File: {audio_path}")
        print(f"⏱️  Tempo inferenza totale: {total_elapsed:.2f}s")
        print("📝 Trascrizione per segmento:")
        for start_s, end_s, text in results:
            print(f"   [{start_s:5.1f}s - {end_s:5.1f}s] {text}")
        print("=" * 70)

    if device == "cuda":
        peak_mem = torch.cuda.max_memory_allocated() / (1024**3)
        print(f"\nPicco VRAM utilizzata: {peak_mem:.2f} GB")


if __name__ == "__main__":
    main()