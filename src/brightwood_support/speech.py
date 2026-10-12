"""Natural-sounding speech for the assistant's answers, with Gemini's text-to-speech models.

Browsers' built-in voices are often robotic, spell codes out oddly, and Chrome cuts long speech short.
So answers are turned into audio here and played by the page; the browser voice is only a fallback.

    spoken_text()  rewrites an answer the way a person would say it (no markdown, no citation ids)
    Speech.wav()   returns a WAV file for that text, from a small in-memory cache when it can
"""

from __future__ import annotations

import array
import base64
import hashlib
import io
import json
import math
import re
import threading
import urllib.request
import wave
from collections import OrderedDict

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RATE = 24_000  # Gemini returns 16-bit mono PCM at 24 kHz
MAX_CHARS = 1500
QUIET = 300  # loudness below this counts as silence (16-bit samples)

_CITATION = re.compile(r"\[[a-z_]+#[a-z0-9-]+\]")
_BULLET = re.compile(r"^\s*(?:[*-]|\d+\.)\s+", re.M)
# Codes like TRK1003 or O2001 are read character by character, which is how a person says them.
_CODE = re.compile(r"\b([A-Z]{1,4})(\d{3,})\b")


def spoken_text(text: str) -> str:
    """The answer as it should be said aloud: no markdown, no citation ids, codes spelled out."""
    text = _CITATION.sub("", text)
    text = text.replace("**", "").replace("`", "").replace("#", "")
    # Each bullet becomes its own sentence, so the voice pauses between them.
    lines = [_BULLET.sub("", line).strip() for line in text.splitlines()]
    text = " ".join(line if line.endswith((".", "!", "?", ":")) else f"{line}." for line in lines if line)
    text = _CODE.sub(lambda m: " ".join(m.group(1)) + " " + " ".join(m.group(2)), text)
    text = re.sub(r"\s+([.,!?:;])", r"\1", re.sub(r"\s+", " ", text))
    return text.strip()[:MAX_CHARS]


def clean_pcm(pcm: bytes) -> bytes:
    """Remove the speech model's stray noise and clicks.

    Gemini's speech audio sometimes ends with a short, very loud burst after the last word (heard as a radio-like
    glitch), and can start or stop mid-wave (a click). So: if the clip ends with under a second of audio, after a
    pause, that is far louder than the speech itself, cut it at the pause. Then fade the edges in and out.
    """
    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    frame = RATE // 50  # 20 ms
    rms = [math.sqrt(sum(x * x for x in samples[i:i + frame]) / max(1, len(samples[i:i + frame])))
           for i in range(0, len(samples), frame)]
    voiced = sorted(r for r in rms if r > QUIET)
    if voiced:
        typical = voiced[len(voiced) // 2]
        # Walk back from the end to the last pause (100 ms of quiet) within the final second.
        end, quiet_run = len(rms), 0
        for i in range(len(rms) - 1, max(-1, len(rms) - 1 - 50), -1):
            if rms[i] < QUIET:
                quiet_run += 1
                if quiet_run >= 5:
                    tail = rms[i + quiet_run:]
                    if tail and max(tail) > 2.5 * typical:
                        start = i
                        while start > 0 and rms[start - 1] < QUIET:
                            start -= 1
                        end = start + 2  # keep 40 ms of the pause
                    break
            else:
                quiet_run = 0
        samples = samples[: end * frame]
    fade = min(len(samples) // 2, RATE // 100)  # 10 ms
    for i in range(fade):
        samples[i] = int(samples[i] * i / fade)
        samples[-1 - i] = int(samples[-1 - i] * i / fade)
    return samples.tobytes()


def pcm_to_wav(pcm: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def synthesize(text: str, *, key: str, model: str, voice: str, timeout: float = 30) -> bytes:
    """Raw PCM for the text. Only the words go in the prompt: a style instruction would be read out too."""
    body = {
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
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.load(res)
    return base64.b64decode(data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])


class SpeechUnavailable(Exception):
    """No key configured, or the speech model failed: the page falls back to the browser's voice."""


class Speech:
    def __init__(self, env, cache_size: int = 64) -> None:
        self.key = env.get("GEMINI_API_KEY", "")
        self.model = env.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
        self.voice = env.get("GEMINI_TTS_VOICE", "Sulafat")
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.key)

    def cached(self, text: str) -> bytes | None:
        with self._lock:
            wav = self._cache.get(self._id(text))
            if wav is not None:
                self._cache.move_to_end(self._id(text))
            return wav

    def wav(self, text: str) -> bytes:
        if not self.available:
            raise SpeechUnavailable("no speech model configured")
        hit = self.cached(text)
        if hit is not None:
            return hit
        try:
            wav = pcm_to_wav(clean_pcm(synthesize(text, key=self.key, model=self.model, voice=self.voice)))
        except Exception as e:  # noqa: BLE001 - any failure means "use the browser voice"
            raise SpeechUnavailable(str(e)) from e
        with self._lock:
            self._cache[self._id(text)] = wav
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)
        return wav

    def _id(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}|{self.voice}|{text}".encode()).hexdigest()
