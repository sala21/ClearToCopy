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


def transcribe_file(model, processor, device, audio_path, language="en"):
    print(f"[2/3] Carico audio: {audio_path}")
    audio = load_audio(audio_path)
    duration_s = len(audio) / TARGET_SR
    print(f"      Durata: {duration_s:.1f}s")

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
        )
    elapsed = time.time() - t0

    text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()

    rtf = elapsed / duration_s if duration_s > 0 else float("nan")
    print(f"      Inferenza completata in {elapsed:.2f}s (RTF={rtf:.2f}, "
          f"{'più veloce' if rtf < 1 else 'più lento'} del tempo reale)")

    return text, elapsed, duration_s


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
            text, elapsed, duration = transcribe_file(
                model, processor, device, audio_path, language=args.language
            )
        except Exception as e:
            print(f"❌ Errore su {audio_path}: {e}")
            continue

        print(f"\n📄 File: {audio_path}")
        print(f"⏱️  Tempo inferenza: {elapsed:.2f}s su {duration:.1f}s di audio")
        print(f"📝 Trascrizione:\n   {text}")
        print("=" * 70)

    if device == "cuda":
        peak_mem = torch.cuda.max_memory_allocated() / (1024**3)
        print(f"\nPicco VRAM utilizzata: {peak_mem:.2f} GB")


if __name__ == "__main__":
    main()
