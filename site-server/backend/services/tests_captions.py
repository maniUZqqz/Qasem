"""Auto-captions: the ASR-answer parser, grouping into screen lines, caption clips, audio extraction (real ffmpeg) and
the node/local/offline decision (fake compute — Metis and the real node are never called)."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from services.editing import captions, titles
from services.editing.errors import TimelineError
from services.video.ffmpeg import FFMPEG, probe

HAVE_FFMPEG = bool(shutil.which(FFMPEG) or shutil.which("ffmpeg"))

VOSK = {"text": "سلام دنیا", "result": [
    {"word": "سلام", "start": 0.5, "end": 0.9, "conf": 0.98}, {"word": "دنیا", "start": 1.0, "end": 1.6, "conf": 0.9}]}


def words(texts, step=0.4, dur=0.3, t0=0.0):
    return [{"w": w, "s": round(t0 + i * step, 3), "e": round(t0 + i * step + dur, 3)} for i, w in enumerate(texts)]


class ParserTests(SimpleTestCase):
    def test_vosk_shape(self):
        out = captions.words_from_asr(VOSK)
        self.assertEqual([w["w"] for w in out], ["سلام", "دنیا"])
        self.assertEqual((out[0]["s"], out[1]["e"]), (0.5, 1.6))

    def test_whisper_segments_flat_words_and_lists(self):
        seg = {"segments": [{"text": "a b", "start": 0, "end": 2, "words": [{"word": " a", "start": 0.1, "end": 0.5},
                                                                                {"word": "b", "start": 0.6, "end": 1.0}]},
                            {"text": "c", "start": 3, "end": 4, "words": [{"word": "c", "start": 3.1, "end": 3.5}]}]}
        self.assertEqual([w["w"] for w in captions.words_from_asr(seg)], ["a", "b", "c"])
        flat = {"words": [{"text": "x", "s": 1, "e": 2}, {"text": "y", "s": 2.5, "e": 3}]}
        self.assertEqual([w["w"] for w in captions.words_from_asr(flat)], ["x", "y"])
        parts = [VOSK, {"result": [{"word": "سوم", "start": 2.0, "end": 2.4}]}]
        self.assertEqual([w["w"] for w in captions.words_from_asr(parts)], ["سلام", "دنیا", "سوم"])

    def test_a_json_string_milliseconds_and_unsorted_input(self):
        raw = json.dumps({"words": [{"word": "دوم", "start_ms": 1500, "end_ms": 2000}, {"word": "اول", "start_ms": 500, "end_ms": 900}]})
        out = captions.words_from_asr(raw)
        self.assertEqual([w["w"] for w in out], ["اول", "دوم"])
        self.assertEqual(out[1]["s"], 1.5)

    def test_segment_text_without_words_is_spread_evenly_and_levels_are_not_double_counted(self):
        out = captions.words_from_asr({"segments": [{"text": "یک دو سه چهار", "start": 0, "end": 4}]})
        self.assertEqual(len(out), 4)
        self.assertAlmostEqual(out[0]["s"], 0.0)
        self.assertAlmostEqual(out[-1]["e"], 4.0, delta=0.01)
        self.assertTrue(all(a["e"] <= b["s"] + 1e-6 for a, b in zip(out, out[1:])))
        both = {"text": "سلام دنیا", "words": VOSK["result"], "result": VOSK["result"]}
        self.assertEqual(len(captions.words_from_asr(both)), 2)

    def test_junk_gives_no_words(self):
        for junk in (None, "", "not json", {}, [], {"text": "hello"}, {"words": [{"word": "x"}]}, 42):
            self.assertEqual(captions.words_from_asr(junk), [])


class GroupingTests(SimpleTestCase):
    def test_a_long_gap_a_sentence_end_and_the_limits_start_new_lines(self):
        ws = words(["a", "b", "c"]) + words(["d", "e"], t0=5.0)
        self.assertEqual([g["text"] for g in captions.group_words(ws)], ["a b c", "d e"])
        ws = words(["سلام.", "دنیا", "خوبی؟", "من"])
        self.assertEqual([g["text"] for g in captions.group_words(ws)], ["سلام.", "دنیا خوبی؟", "من"])
        many = words([f"w{i}" for i in range(15)], step=0.2, dur=0.15)
        groups = captions.group_words(many, max_words=5)
        self.assertEqual([len(g["words"]) for g in groups], [5, 5, 5])
        long_words = words(["قهوهٔ", "تازه", "با", "تخفیفِ", "ویژهٔ", "امروز", "برای", "شما"], step=0.3, dur=0.25)
        for g in captions.group_words(long_words, max_chars=20):
            self.assertLessEqual(len(g["text"]), 20)
        slow = words(["a", "b", "c", "d", "e", "f"], step=1.2, dur=1.0)
        self.assertGreater(len(captions.group_words(slow, max_dur=3.0, max_gap=2)), 1)

    def test_groups_keep_every_word_with_absolute_times(self):
        ws = words([f"w{i}" for i in range(12)], step=0.35, dur=0.3, t0=2.0)
        groups = captions.group_words(ws)
        self.assertEqual([w["w"] for g in groups for w in g["words"]], [w["w"] for w in ws])
        self.assertEqual(groups[0]["s"], 2.0)
        self.assertEqual(groups[-1]["e"], ws[-1]["e"])


class CaptionClipTests(SimpleTestCase):
    def clips(self, **kw):
        ws = words(["قهوه", "تازه", "امروز"], t0=1.0) + words(["تخفیف", "ویژه"], t0=6.0)
        return captions.caption_clips(captions.group_words(ws), **kw)

    def test_clips_are_timeline_text_clips_with_word_timing_relative_to_the_clip(self):
        clips = self.clips(offset=10.0)
        self.assertEqual(len(clips), 2)
        first = clips[0]
        self.assertEqual(first["at"], 11.0)
        self.assertTrue(first["caption"])
        self.assertEqual(first["text"], "قهوه تازه امروز")
        self.assertEqual(first["words"][0]["s"], 0.0)
        self.assertAlmostEqual(first["words"][2]["s"], 0.8, delta=0.001)
        self.assertGreaterEqual(first["duration"], first["words"][-1]["e"])
        self.assertEqual(titles.clean(first)["text"], first["text"], "already cleaned")

    def test_default_caption_style_and_overrides(self):
        first = self.clips()[0]
        self.assertEqual((first["font"], first["stroke"], first["hl_color"], first["box"], first["position"], first["y"]),
                         ("vazir", 12.0, "#ffd400", False, "bottom", 0.86))
        custom = self.clips(style={"hl_color": "#00ff00", "size": 8, "box": True, "hl_mode": "scale"})[0]
        self.assertEqual((custom["hl_color"], custom["size"], custom["box"], custom["hl_mode"]), ("#00ff00", 8.0, True, "scale"))

    def test_clips_never_overlap_and_are_at_least_a_third_of_a_second(self):
        ws = words(["a", "b"], step=0.12, dur=0.1)
        tight = captions.caption_clips([{"text": "a", "s": 0.0, "e": 0.1, "words": [ws[0]]},
                                        {"text": "b", "s": 0.12, "e": 0.22, "words": [ws[1]]}])
        self.assertLessEqual(tight[0]["at"] + tight[0]["duration"], tight[1]["at"] + 0.2)
        for c in self.clips():
            self.assertGreaterEqual(c["duration"], 0.3)
        clips = self.clips()
        self.assertLessEqual(clips[0]["at"] + clips[0]["duration"], clips[1]["at"] + 1e-6)


def make_media(path, *, audio=True, seconds=3):
    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True, stdin=subprocess.DEVNULL)


class ExtractAudioTests(SimpleTestCase):
    def setUp(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg نیست")
        self.dir = Path(tempfile.mkdtemp(prefix="nm-cap-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_range_becomes_a_16k_mono_wav(self):
        src = self.dir / "a.mp4"
        make_media(src)
        out = captions.extract_audio(src, 0.5, 2.0, self.dir / "x" / "out.wav")
        info = probe(out)
        stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
        self.assertEqual((int(stream["sample_rate"]), int(stream["channels"])), (16000, 1))
        self.assertAlmostEqual(float(info["format"]["duration"]), 1.5, delta=0.1)

    def test_silent_video_too_short_and_too_long_ranges_are_refused_in_persian(self):
        silent = self.dir / "s.mp4"
        make_media(silent, audio=False)
        with self.assertRaises(TimelineError) as ctx:
            captions.extract_audio(silent, 0, 2, self.dir / "o.wav")
        self.assertIn("صدا", str(ctx.exception))
        with self.assertRaises(TimelineError):
            captions.extract_audio(silent, 1, 1.1, self.dir / "o.wav")
        with self.assertRaises(TimelineError) as ctx:
            captions.extract_audio(silent, 0, captions.MAX_SECONDS + 5, self.dir / "o.wav")
        self.assertIn("دقیقه", str(ctx.exception))


class FakeJob(SimpleNamespace):
    def outputs(self):
        return self.outs


class TranscribeTests(SimpleTestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="nm-cap-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.wav = self.dir / "a.wav"
        self.wav.write_bytes(b"RIFF" + b"\0" * 100)

    def test_node_online_runs_voice_asr_and_parses_its_json(self):
        (self.dir / "asr.json").write_text(json.dumps(VOSK), encoding="utf-8")
        job = FakeJob(outs=[{"name": "asr.json"}])
        with patch("apps.compute.services.online_nodes", return_value=[object()]) as online, \
                patch("apps.compute.services.enqueue", return_value=job) as enqueue, \
                patch("apps.compute.services.wait", return_value=job) as wait, \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            ticks = []
            out = captions.transcribe_wav(self.wav, store=None, on_tick=ticks.append)
        online.assert_called_with("voice")
        args, kwargs = enqueue.call_args
        self.assertEqual(args[0], "voice.asr")
        self.assertEqual(args[1], {"audio": "audio.wav"})
        self.assertEqual(kwargs["files"], {"audio.wav": self.wav})
        self.assertEqual(wait.call_args.kwargs["on_tick"], ticks.append)
        self.assertEqual(out["engine"], "node")
        self.assertEqual([w["w"] for w in out["words"]], ["سلام", "دنیا"])
        self.assertEqual(out["text"], "سلام دنیا")

    def test_node_json_under_another_output_name_is_found(self):
        (self.dir / "result.json").write_text(json.dumps({"words": [{"word": "x", "start": 0, "end": 1}]}), encoding="utf-8")
        job = FakeJob(outs=[{"name": "result.json"}])
        with patch("apps.compute.services.online_nodes", return_value=[object()]), \
                patch("apps.compute.services.enqueue", return_value=job), patch("apps.compute.services.wait", return_value=job), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            self.assertEqual(captions.transcribe_wav(self.wav)["words"][0]["w"], "x")

    def test_silence_and_node_errors_become_persian_messages(self):
        from apps.compute import services as compute

        (self.dir / "asr.json").write_text(json.dumps({"text": "", "result": []}), encoding="utf-8")
        job = FakeJob(outs=[{"name": "asr.json"}])
        with patch("apps.compute.services.online_nodes", return_value=[object()]), \
                patch("apps.compute.services.enqueue", return_value=job), patch("apps.compute.services.wait", return_value=job), \
                patch("apps.compute.services.output_path", side_effect=lambda j, name: self.dir / name):
            with self.assertRaises(captions.CaptionsUnavailable) as ctx:
                captions.transcribe_wav(self.wav)
            self.assertIn("گفتاری شنیده نشد", str(ctx.exception))
        for exc, word in ((compute.ComputeFailed("boom"), "نتوانست"), (compute.ComputeTimeout("slow"), "تمام نکرد"),
                          (compute.ComputeCancelled("x"), "لغو")):
            with patch("apps.compute.services.online_nodes", return_value=[object()]), \
                    patch("apps.compute.services.enqueue", return_value=job), patch("apps.compute.services.wait", side_effect=exc):
                with self.assertRaises(captions.CaptionsUnavailable) as ctx:
                    captions.transcribe_wav(self.wav)
                self.assertIn(word, str(ctx.exception))

    def test_node_offline_and_no_local_model_says_what_to_do(self):
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("services.editing.captions._local_ready", return_value=False):
            with self.assertRaises(captions.CaptionsUnavailable) as ctx:
                captions.transcribe_wav(self.wav)
        message = str(ctx.exception)
        self.assertIn("سرور پردازش", message)
        self.assertIn("«زیرنویس»", message)
        # a caption job must never enqueue when no node is online
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("apps.compute.services.enqueue") as enqueue, \
                patch("services.editing.captions._local_ready", return_value=False):
            with self.assertRaises(captions.CaptionsUnavailable):
                captions.transcribe_wav(self.wav)
            enqueue.assert_not_called()

    def test_node_vanishing_between_check_and_enqueue_falls_back(self):
        from apps.compute import services as compute

        with patch("apps.compute.services.online_nodes", return_value=[object()]), \
                patch("apps.compute.services.enqueue", side_effect=compute.ComputeUnavailable("offline")), \
                patch("services.editing.captions._local_ready", return_value=False):
            with self.assertRaises(captions.CaptionsUnavailable) as ctx:
                captions.transcribe_wav(self.wav)
        self.assertIn("«زیرنویس»", str(ctx.exception))

    def test_local_whisper_is_used_only_when_its_model_is_on_disk(self):
        seg = SimpleNamespace(words=[SimpleNamespace(text="سلام", start=0.1, end=0.5), SimpleNamespace(text="دنیا", start=0.6, end=1.0)])
        heard = SimpleNamespace(segments=[seg])
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("services.editing.captions._local_ready", return_value=True), \
                patch("services.audio.transcribe.transcribe", return_value=heard) as run:
            out = captions.transcribe_wav(self.wav)
        self.assertEqual(out["engine"], "local")
        self.assertEqual([w["w"] for w in out["words"]], ["سلام", "دنیا"])
        self.assertEqual(run.call_args.kwargs["language"], "fa")
        with patch("services.audio.transcribe.available", return_value=(True, "")), patch("services.editing.captions._local_model_cached", return_value=False):
            self.assertFalse(captions._local_ready())

    def test_status_reports_both_paths_before_the_button_is_pressed(self):
        with patch("apps.compute.services.online_nodes", return_value=[]), patch("services.editing.captions._local_ready", return_value=False):
            st = captions.status()
        self.assertEqual((st["node"], st["local"], st["ok"]), (False, False, False))
        self.assertIn("«زیرنویس»", st["message"])
        with patch("apps.compute.services.online_nodes", return_value=[object()]), patch("services.editing.captions._local_ready", return_value=False):
            st = captions.status()
        self.assertEqual((st["node"], st["ok"], st["message"]), (True, True, ""))
