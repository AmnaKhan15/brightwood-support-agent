import unittest
from unittest import mock

from fastapi.testclient import TestClient

from brightwood_support import speech
from brightwood_support.server import create_app
from brightwood_support.service import RateLimited, Service

DEMO = {"DEMO_STAFF_LOGIN": "true"}
WITH_KEY = {**DEMO, "GEMINI_API_KEY": "test-key"}
PCM = b"\x00\x01" * 2400  # a tenth of a second of audio


class SpokenTextTests(unittest.TestCase):
    def test_markdown_and_citations_are_not_read_out(self):
        said = speech.spoken_text("Your orders:\n\n* **Order O1002**: `Processing` [shipping#tracking]\n- Refund of $189.00 waits.")
        for junk in ("*", "`", "[", "#", "tracking]"):
            self.assertNotIn(junk, said)
        self.assertIn("Refund of $189.00 waits.", said)

    def test_codes_are_spelled_out_and_bullets_become_sentences(self):
        said = speech.spoken_text("* Shipped with TRK1003\n* Order O2001 delivered")
        self.assertEqual(said, "Shipped with T R K 1 0 0 3. Order O 2 0 0 1 delivered.")

    def test_no_space_is_left_before_punctuation(self):
        self.assertEqual(speech.spoken_text("Done [refunds#limits]."), "Done.")


class SpeakServiceTests(unittest.TestCase):
    def test_without_a_key_the_browser_voice_is_used(self):
        svc = Service(env=DEMO)
        with self.assertRaises(speech.SpeechUnavailable):
            svc.speak(svc.create_session(), "Hello")

    def test_audio_is_cached_and_repeats_cost_nothing(self):
        svc = Service(env=WITH_KEY, daily_ai_calls=1)
        sid = svc.create_session()
        with mock.patch.object(speech, "synthesize", return_value=PCM) as synth:
            first = svc.speak(sid, "Hello there")
            again = svc.speak(sid, "Hello there")
        self.assertTrue(first.startswith(b"RIFF"))
        self.assertEqual(first, again)
        synth.assert_called_once()
        # The single daily call is spent, so new text is refused rather than billed.
        with mock.patch.object(speech, "synthesize", return_value=PCM), self.assertRaises(speech.SpeechUnavailable):
            svc.speak(sid, "Something new")

    def test_new_audio_is_rate_limited(self):
        svc = Service(env=WITH_KEY, per_minute=1)
        sid = svc.create_session()
        with mock.patch.object(speech, "synthesize", return_value=PCM):
            for n in range(4):  # an answer is voiced in a few short pieces
                svc.speak(sid, f"Piece {n}")
            with self.assertRaises(RateLimited):
                svc.speak(sid, "One too many")

    def test_a_model_failure_means_fall_back(self):
        svc = Service(env=WITH_KEY)
        with mock.patch.object(speech, "synthesize", side_effect=TimeoutError("slow")), self.assertRaises(speech.SpeechUnavailable):
            svc.speak(svc.create_session(), "Hello")


class SpeakApiTests(unittest.TestCase):
    def test_tts_returns_wav_and_503_when_unavailable(self):
        svc = Service(env=WITH_KEY)
        client = TestClient(create_app(svc))
        sid = client.post("/api/session").json()["session"]
        with mock.patch.object(speech, "synthesize", return_value=PCM):
            r = client.post("/api/tts", json={"text": "Hello"}, headers={"X-Session": sid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "audio/wav")
        with mock.patch.object(speech, "synthesize", side_effect=OSError("down")):
            r = client.post("/api/tts", json={"text": "Something else"}, headers={"X-Session": sid})
        self.assertEqual((r.status_code, r.json()["error"]), (503, "speech_unavailable"))

    def test_opening_the_api_server_lands_on_the_docs(self):
        client = TestClient(create_app(Service(env=DEMO)))
        r = client.get("/", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (307, "/api/docs"))
        self.assertEqual(client.get("/api/docs").status_code, 200)


if __name__ == "__main__":
    unittest.main()
