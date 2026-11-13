"""Speech to text on this machine, free. `transcribe(path)` is the one door; swap its insides to change engine.

Engine order:
1. whisper.cpp (`whisper-cli`, from `brew install whisper-cpp`) with a multilingual model file. The default file
   is data/models/ggml-small.bin (the multilingual "small" model, 488 MB); KHUTLISA_WHISPER_MODEL points elsewhere.
2. The `faster-whisper` Python package, if it is installed (`uv add faster-whisper`), with its "small" model.

The language is detected by the model. Audio in any format ffmpeg reads (the browser sends WebM or MP4) is first
turned into 16 kHz mono WAV.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "data" / "models" / "ggml-small.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
MAX_SECONDS = 300          # anything longer is cut; an intake is a minute or two of speech
MAX_BYTES = 30 * 1024 * 1024

# Whisper's language codes for the languages this product is most likely to hear. Others are shown as the code.
LANGUAGES = {"en": "English", "tl": "Tagalog", "es": "Spanish", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
             "vi": "Vietnamese", "hi": "Hindi", "pa": "Punjabi", "ar": "Arabic", "fr": "French", "pt": "Portuguese",
             "ru": "Russian", "de": "German", "it": "Italian", "id": "Indonesian", "ms": "Malay", "th": "Thai",
             "st": "Sesotho", "sn": "Shona", "sw": "Swahili", "ur": "Urdu", "bn": "Bengali", "ta": "Tamil"}


class SpeechUnavailable(RuntimeError):
    """Nothing on this machine can transcribe, or the audio could not be read. The message is fit to show."""


def _find(program: str) -> str | None:
    return shutil.which(program) or next(
        (p for p in (f"/opt/homebrew/bin/{program}", f"/usr/local/bin/{program}") if os.path.exists(p)), None)


def model_path() -> Path:
    return Path(os.environ.get("KHUTLISA_WHISPER_MODEL") or MODEL_PATH)


def engine() -> str | None:
    """Which engine `transcribe` will use here: "whisper.cpp", "faster-whisper" or None."""
    if _find("whisper-cli") and model_path().is_file():
        return "whisper.cpp"
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        return None


def to_wav(source: str | Path, target: str | Path) -> None:
    """Any audio ffmpeg can read, as 16 kHz mono 16-bit WAV, which is what whisper wants."""
    ffmpeg = _find("ffmpeg")
    if not ffmpeg:
        raise SpeechUnavailable("ffmpeg is not installed, so the recording cannot be converted.")
    done = subprocess.run([ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", str(source), "-t", str(MAX_SECONDS),
                           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
                          capture_output=True, text=True, timeout=120)
    if done.returncode != 0 or not Path(target).is_file() or Path(target).stat().st_size < 1000:
        raise SpeechUnavailable("The recording could not be read as audio.")


def _whisper_cpp(wav: Path, folder: Path) -> dict:
    out = folder / "heard"
    cmd = [_find("whisper-cli"), "-m", str(model_path()), "-f", str(wav), "-l", "auto", "-oj", "-of", str(out),
           "-np", "-nt", "-t", str(min(8, os.cpu_count() or 4))]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    result = out.with_suffix(".json")
    if done.returncode != 0 or not result.is_file():
        raise SpeechUnavailable("The speech model stopped before it finished.")
    data = json.loads(result.read_text(errors="replace"))
    text = " ".join(seg.get("text", "").strip() for seg in data.get("transcription", []))
    return {"text": " ".join(text.split()), "language": (data.get("result") or {}).get("language") or ""}


_faster_model = None


def _faster_whisper(wav: Path) -> dict:
    global _faster_model
    from faster_whisper import WhisperModel
    if _faster_model is None:
        _faster_model = WhisperModel(os.environ.get("KHUTLISA_FASTER_WHISPER_MODEL", "small"), compute_type="int8")
    segments, info = _faster_model.transcribe(str(wav), beam_size=5)
    return {"text": " ".join(" ".join(s.text.strip() for s in segments).split()), "language": info.language or ""}


def transcribe(path: str | Path) -> dict:
    """{"text": what was said, "language": the detected language code such as "tl"}. Raises SpeechUnavailable."""
    which = engine()
    if which is None:
        raise SpeechUnavailable(
            "Speech to text is not set up on this machine. Install whisper.cpp and put a multilingual model at "
            f"{model_path()}, or add the faster-whisper package. The README has the two commands. "
            "You can type your history instead.")
    with tempfile.TemporaryDirectory(prefix="khutlisa-speech-") as tmp:
        wav = Path(tmp) / "audio.wav"
        to_wav(path, wav)
        heard = _whisper_cpp(wav, Path(tmp)) if which == "whisper.cpp" else _faster_whisper(wav)
    heard["text"] = heard["text"].replace("[BLANK_AUDIO]", "").strip()
    return heard


def language_name(code: str) -> str:
    return LANGUAGES.get((code or "").lower(), code or "")
