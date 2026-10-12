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
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.speech import RATE, pcm_to_wav, synthesize  # noqa: E402

GREETING = ROOT / "web" / "src" / "lib" / "greeting.json"


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
    pcm = synthesize(greeting["text"], key=key, model=args.model, voice=args.voice, timeout=120)
    out = ROOT / "web" / "public" / greeting["audio"].lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pcm_to_wav(pcm))
    print(f"Wrote {out.relative_to(ROOT)}: {len(pcm) / (RATE * 2):.1f} s, voice {args.voice}")


if __name__ == "__main__":
    main()
