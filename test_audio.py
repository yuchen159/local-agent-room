import base64
import tempfile
import unittest
from pathlib import Path

from media import MAX_TOTAL, MediaStore
from server import Room
from test_room import FakeAgent, wait_for

FIXTURE = Path(__file__).with_name("audio-fixture.b64")
REAL_MP3 = base64.b64decode(FIXTURE.read_text(encoding="ascii").strip())


def wav_bytes(seconds=0.05):
    data = b"\x00\x00" * int(44100 * seconds)
    fmt = (b"fmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
           + (1).to_bytes(2, "little") + (44100).to_bytes(4, "little")
           + (88200).to_bytes(4, "little") + (2).to_bytes(2, "little")
           + (16).to_bytes(2, "little"))
    body = b"WAVE" + fmt + b"data" + len(data).to_bytes(4, "little") + data
    return b"RIFF" + len(body).to_bytes(4, "little") + body


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MediaStore(self.root / "attachments")

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_mp3_is_accepted_and_stored_playably(self):
        meta, raw = self.store.prepare_audio(REAL_MP3, "tone.mp3")
        self.assertEqual(meta["kind"], "audio")
        self.assertEqual(meta["mime"], "audio/mpeg")
        self.assertEqual(raw, REAL_MP3)
        self.store.save([(meta, raw)])
        stored = self.store.path(meta["url"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.read_bytes(), REAL_MP3)
        self.assertEqual(stored.read_bytes()[:3], b"ID3")

    def test_other_containers_and_rejections(self):
        samples = {
            "a.wav": wav_bytes(),
            "a.ogg": b"OggS\x00" + b"\x00" * 24,
            "a.m4a": b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 16 + b"moov" + b"\x00" * 16,
        }
        for name, raw in samples.items():
            meta, _ = self.store.prepare_audio(raw, name)
            self.assertEqual(meta["kind"], "audio")
            self.assertRegex(meta["url"], r"^/media/[a-f0-9]{64}\.(wav|m4a|ogg)$")
        with self.assertRaises(ValueError):
            self.store.prepare_audio(b"<html>not audio</html>", "x.mp3")
        with self.assertRaises(ValueError):
            self.store.prepare_audio(b"", "x.mp3")

    def test_header_only_fakes_are_rejected(self):
        fakes = [
            b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64,
            b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40,
            b"OggS\x00" + b"\x00" * 8,
            b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 16,
            b"\xff\xfb" + b"\x00" * 64,
        ]
        for raw in fakes:
            with self.assertRaises(ValueError):
                self.store.prepare_audio(raw, "fake.mp3")

    def test_upload_limits_and_deduplication(self):
        payload = [{"name": "tone.mp3", "data": base64.b64encode(REAL_MP3).decode()}]
        prepared = self.store.uploads_audio(payload)
        self.store.save(prepared)
        self.store.save(prepared)
        self.assertEqual(len(list((self.root / "attachments").glob("*.mp3"))), 1)
        with self.assertRaises(ValueError):
            self.store.uploads_audio(payload * 3)

    def test_mixed_image_and_audio_markers_both_attach(self):
        voice = self.root / "voice.mp3"
        voice.write_bytes(REAL_MP3)
        picture = self.root / "shot.png"
        picture.write_bytes(
            base64.b64decode(
                b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            )
        )
        text, attachments = self.store.from_reply(
            f"听\n[[ROOM_AUDIO:{voice}]]\n看\n[[ROOM_IMAGE:{picture}]]", [self.root]
        )
        kinds = sorted(item["kind"] for item in attachments)
        self.assertEqual(kinds, ["audio", "image"])
        self.assertNotIn("[[ROOM", text)
        self.assertIsNotNone(self.store.path(attachments[0]["url"]))

    def test_oversized_mixed_attachment_is_not_written(self):
        class Sized(MediaStore):
            def prepare(self, raw, name="图片"):
                return (dict(kind="image", url="/media/" + "a" * 64 + ".png", name=name,
                             mime="image/png", bytes=len(raw)), raw)

            def prepare_audio(self, raw, name="音频"):
                return (dict(kind="audio", url="/media/" + "b" * 64 + ".mp3", name=name,
                             mime="audio/mpeg", bytes=len(raw)), raw)

        store = Sized(self.root / "attachments")
        picture = self.root / "big.png"
        with open(picture, "wb") as handle:
            handle.truncate(11 * 1024 * 1024)
        voice = self.root / "voice.mp3"
        with open(voice, "wb") as handle:
            handle.truncate(10 * 1024 * 1024)
        text, attachments = store.from_reply(
            f"[[ROOM_IMAGE:{picture}]]\n[[ROOM_AUDIO:{voice}]]", [self.root]
        )
        # The audio fits; the image would push the pair past MAX_TOTAL and must not be kept.
        self.assertEqual([item["kind"] for item in attachments], ["audio"])
        self.assertIn("未发送", text)
        self.assertNotIn("[[ROOM", text)

    def test_audio_outside_allowed_roots_is_refused(self):
        allowed = self.root / "allowed"
        allowed.mkdir()
        outside = self.root / "outside-audio.mp3"
        outside.write_bytes(REAL_MP3)
        text, attachments = self.store.from_reply(f"[[ROOM_AUDIO:{outside}]]", [allowed])
        self.assertEqual(attachments, [])
        self.assertIn("未发送", text)
        self.assertNotIn("[[ROOM_AUDIO:", text)


class AudioPauseTests(unittest.TestCase):
    """A held publication must not publish or store the audio attachment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "voice.mp3").write_bytes(REAL_MP3)
        FakeAgent.calls = []
        self.room = None

    def tearDown(self):
        if self.room:
            self.room.close()
        self.tmp.cleanup()

    def test_holding_publication_keeps_audio_out_of_the_room(self):
        voice = self.folder / "voice.mp3"

        class Scripted(FakeAgent):
            def prompt(inner, text, cancel_event=None, on_text=None):
                inner.calls.append((inner.name, text))
                owner.room.command("typing", {"clientId": "tab", "revision": 1, "hasText": True})
                return {"status": "completed", "text": f"听\n[[ROOM_AUDIO:{voice}]]"}

        owner = self
        self.room = Room(self.folder / "room.sqlite3", Scripted)
        self.room.interval = 0
        self.room.command("send", {"text": "GPT聊聊"})
        wait_for(lambda: self.room.paused and self.room.active is None and len(FakeAgent.calls) == 1)
        snapshot = self.room.snapshot()
        self.assertEqual([m["role"] for m in snapshot["messages"]], ["user"])
        self.assertFalse(any((self.folder / "attachments").glob("*.mp3")))
        self.assertEqual(self.room.error, "")


if __name__ == "__main__":
    unittest.main()
