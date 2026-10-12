"""Natural-sounding speech for the assistant's answers, with Gemini's text-to-speech models.

Browsers' built-in voices are often robotic, spell codes out oddly, and Chrome cuts long speech short.
So answers are turned into audio here and played by the page; the browser voice is only a fallback.

    spoken_text()  rewrites an answer the way a person would say it (no markdown, no citation ids)
    Speech.wav()   returns a WAV file for that text, from a small in-memory cache when it can
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import urllib.request
import wave
from collections import OrderedDict

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RATE = 24_000  # Gemini returns 16-bit mono PCM at 24 kHz
MAX_CHARS = 1500

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
            wav = pcm_to_wav(synthesize(text, key=self.key, model=self.model, voice=self.voice))
        except Exception as e:  # noqa: BLE001 - any failure means "use the browser voice"
            raise SpeechUnavailable(str(e)) from e
        with self._lock:
            self._cache[self._id(text)] = wav
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)
        return wav

    def _id(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}|{self.voice}|{text}".encode()).hexdigest()
