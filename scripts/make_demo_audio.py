"""Has a synthetic voice read the demonstration person's prepared words, saves the sound for the page, and
checks that the project's own speech recogniser hears every word her records need.

    uv run python scripts/make_demo_audio.py

For every demonstration person in src/khutlisa/demonstration.json whose `audio` is set, this reads the prepared
words aloud with the macOS voice Paulina (Spanish, Mexico) through the `say` program and writes an AAC file into
web/public/demo/, with the length of each file in lengths.json. It then puts each file it wrote through
`khutlisa.speech.transcribe`, the same recogniser the microphone uses, prints what was heard, and writes the
prepared text and the heard text side by side into heard.json. It stops with an error if a name, the city, a
year, the street, the postcode or a holder is missing from what was heard (`demo.spoken_requirements`).

The page plays the file and sends the same file to the server, which transcribes it again there, so the words on
screen are what the recogniser heard and never this file's copy. It needs macOS, ffmpeg and the speech engine
(README, section 2a). No recording of a real person is used: the voice is synthetic.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import demo, speech  # noqa: E402

OUT = ROOT / "web" / "public" / "demo"
VOICE = "Paulina"
RATE = "172"       # words a minute; a little slower than the voice's default, so every name is clear


def seconds_of(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out.strip()), 2)


def speak(text: str, target: Path) -> float:
    with tempfile.TemporaryDirectory(prefix="khutlisa-say-") as tmp:
        raw = Path(tmp) / "speech.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(raw), text], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-c:a", "aac", "-b:a", "96k",
                        str(target)], check=True)
    return seconds_of(target)


def main() -> None:
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        sys.exit("This script needs the macOS `say` program and ffmpeg.")
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if VOICE not in voices:
        sys.exit(f"The voice {VOICE} is not installed on this Mac. Add it in System Settings, Accessibility, Spoken Content.")
    if speech.engine() is None:
        sys.exit("The speech engine is not set up, so the sound cannot be checked. See the README, section 2a.")
    OUT.mkdir(parents=True, exist_ok=True)
    lengths, heard_all, failed = {}, {}, []
    for person in demo.people():
        required = demo.spoken_requirements(person)
        for words_key, file_key in (("words", "audio"), ("answer", "answer_audio")):
            if not person.get(file_key):
                continue
            target = OUT / Path(person[file_key]).name
            lengths[target.name] = speak(person[words_key], target)
            print(f"wrote {target} ({lengths[target.name]} seconds)")
            heard = speech.transcribe(target)
            missing = demo.missing_words(heard["text"], required[words_key])
            heard_all[target.name] = {"voice": VOICE, "seconds": lengths[target.name], "prepared": person[words_key],
                                      "heard": heard["text"], "heard_language": heard["language"]}
            print(f"  prepared: {person[words_key]}")
            print(f"  heard:    {heard['text']}")
            print(f"  required: {' '.join(required[words_key])}")
            if missing:
                failed.append(f"{target.name}: the recogniser did not hear {', '.join(missing)}")
                print(f"  MISSING:  {' '.join(missing)}")
    (OUT / "lengths.json").write_text(json.dumps(lengths, indent=1) + "\n")
    (OUT / "heard.json").write_text(json.dumps(heard_all, indent=1, ensure_ascii=False) + "\n")
    if failed:
        sys.exit("\n".join(failed))


if __name__ == "__main__":
    main()
