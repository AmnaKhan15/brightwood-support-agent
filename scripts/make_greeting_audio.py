"""Record the site's spoken welcome once, with a natural Gemini voice.

The greeting never changes, so it is generated ahead of time and shipped as a static file:
every visitor hears the same human-sounding voice, with no API call and no cost per visit.

    python scripts/make_greeting_audio.py              # default voice
    python scripts/make_greeting_audio.py --voice Kore # try another prebuilt voice

Reads GEMINI_API_KEY from .env. The text comes from web/src/lib/greeting.json, the same file the
greeting card displays, so the words on screen always match the recording.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request
import wave
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
GREETING = ROOT / "web" / "src" / "lib" / "greeting.json"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def synthesize(text: str, voice: str, model: str, key: str) -> bytes:
    body = {
        # Only the words to say: a style instruction in the prompt gets read out loud as well.
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        data = json.load(res)
    part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
    return base64.b64decode(part["data"])  # 16-bit mono PCM at 24 kHz


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice", default="Sulafat", help="Gemini prebuilt voice, e.g. Sulafat (warm), Kore, Aoede, Achird")
    parser.add_argument("--model", default="gemini-3.8-flash-tts")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("Set GEMINI_API_KEY in .env first.")

    greeting = json.loads(GREETING.read_text(encoding="utf-8"))
    pcm = synthesize(greeting["text"], args.voice, args.model, key)
    out = ROOT / "web" / "public" / greeting["audio"].lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    print(f"Wrote {out.relative_to(ROOT)}: {len(pcm) / 48000:.1f} s, voice {args.voice}")


if __name__ == "__main__":
    main()
