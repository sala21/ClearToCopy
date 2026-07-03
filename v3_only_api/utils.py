import io
import wave
import numpy as np

def audio_to_wav_bytes(audio_np, rate=16000):
    """
    Converte un array float32 [-1,1] in un file WAV (16kHz mono, 16-bit PCM) in memoria.
    Restituisce i bytes del file WAV completo.
    """
    audio_int16 = (audio_np * 32767).astype(np.int16)
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(audio_int16.tobytes())
        return wav_io.getvalue()

def apply_bandpass_filter(audio_np, rate=16000, band_min=300, band_max=3400):
    """
    Filtro FIR leggero 300-3400 Hz (opzionale).
    Restituisce l'array filtrato.
    """
    try:
        from scipy import signal
        b = signal.firwin(65, [band_min, band_max], fs=rate, pass_zero=False)
        return signal.lfilter(b, [1.0], audio_np)
    except Exception:
        # Se scipy non è disponibile, restituisce l'originale
        return audio_np