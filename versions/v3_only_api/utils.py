import io
import wave
import numpy as np

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False


def _ensure_int16(audio):
    """
    Converte l'input in un array int16 se necessario.
    - Se è già int16, lo restituisce tale e quale.
    - Se è float32, lo normalizza in int16.
    - Se è altro, tenta di convertire.
    """
    if audio.dtype == np.int16:
        return audio
    elif audio.dtype == np.float32:
        return (audio * 32767).astype(np.int16)
    else:
        # Fallback generico
        return (audio.astype(np.float32) * 32767).astype(np.int16)


def audio_to_wav_bytes(audio, rate=16000):
    """
    Converte un array audio (int16 o float32) in un file WAV in memoria.
    """
    audio_int16 = _ensure_int16(audio)
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(audio_int16.tobytes())
        return wav_io.getvalue()


def audio_to_flac_bytes(audio, rate=16000):
    """
    Converte un array audio (int16 o float32) in un file FLAC in memoria.
    Richiede 'soundfile' installato.
    """
    if not SOUNDFILE_AVAILABLE:
        raise RuntimeError(
            "Il pacchetto 'soundfile' non è installato. "
            "Installalo con: pip install soundfile"
        )
    audio_int16 = _ensure_int16(audio)
    with io.BytesIO() as flac_io:
        sf.write(flac_io, audio_int16, rate, format='FLAC', subtype='PCM_16')
        return flac_io.getvalue()