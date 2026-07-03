import io
import wave
import numpy as np

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False


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


def audio_to_flac_bytes(audio_np, rate=16000):
    """
    Converte un array float32 [-1,1] in un file FLAC (lossless, compresso) in memoria.

    A parita' di contenuto vocale il payload FLAC e' tipicamente il 40-60%
    piu' piccolo di un WAV PCM16 equivalente, quindi l'upload verso l'API
    Groq e' piu' veloce a parita' di connessione, senza alcuna perdita di
    qualita' audio (e' compressione lossless, non lossy come mp3).

    Richiede il pacchetto opzionale 'soundfile' (pip install soundfile).
    Solleva RuntimeError se il pacchetto non e' disponibile: il chiamante
    e' responsabile di fare fallback a audio_to_wav_bytes in quel caso.
    """
    if not SOUNDFILE_AVAILABLE:
        raise RuntimeError(
            "Il pacchetto 'soundfile' non e' installato. "
            "Installalo con: pip install soundfile"
        )
    audio_int16 = (audio_np * 32767).astype(np.int16)
    with io.BytesIO() as flac_io:
        sf.write(flac_io, audio_int16, rate, format='FLAC', subtype='PCM_16')
        return flac_io.getvalue()


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