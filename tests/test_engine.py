"""Focused offline tests; no real paid requests are made.

python app/engine_tests.py
python app/engine_tests.py --integration VIDEO OUTPUT_ROOT
The optional integration mode uses local ASR + bundled Argos + FFmpeg.
"""
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import engine


SAMPLE_SRT = "1\n00:00:00,200 --> 00:00:01,700\nThe signal is weak.\n\n2\n00:00:02,000 --> 00:00:03,800\nDo not assume that training loss is enough.\n"


class FakeEngine(engine.Engine):
    """Exercise orchestration with deterministic local workers, not HTTP mocks."""
    def __init__(self, root, callback=None, cancel_event=None):
        super().__init__(root, callback, cancel_event)
        self.translation_calls = []
        self.partial_failure = False

    def _probe(self, path):
        return {"width": 640, "height": 360, "duration": 4.0, "audio": True}

    def _worker(self, kind, payload, callback):
        if kind=='understand':
            callback({'type':'understanding','context':{'summary':'测试名称整理','entities':[],'relationships':[],'terms':[],'uncertainties':[],'names':[]}})
            return
        if kind != "translate":
            raise AssertionError("Same-name SRT should skip ASR entirely")
        self.translation_calls.append(json.loads(json.dumps(payload)))
        for index, _ in enumerate(payload["cues"]):
            if str(index) not in payload["cached"]:
                callback({"type": "translated", "index": index, "text": f"第{index + 1}条中文译文"})
                if self.partial_failure:
                    raise RuntimeError("Simulated service interruption")

    def _process(self, command, cwd=None, payload=None, on_line=None):
        self._check_cancel()
        if str(command[-1]).endswith("bilingual.partial.mp4"):
            Path(command[-1]).write_bytes(b"verified-by-fake-probe")
        else:
            raise AssertionError(f"Unexpected subprocess: {command}")
        return ""


class EngineTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("BILINGUAL_TEST_ROOT") or Path(__file__).resolve().parents[1] / '.local' / 'test-tmp' / 'engine')
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.directory.name)
        (self.root / "bin").mkdir()
        (self.root / "bin" / "ffmpeg.exe").write_bytes(b"test")
        self.video = self.root / "Sample with space.mp4"
        self.video.write_bytes(b"do not alter original")
        self.video.with_suffix(".srt").write_text(SAMPLE_SRT, encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def test_sidecar_pipeline_and_original_preservation(self):
        events = []
        runner = FakeEngine(self.root, events.append)
        output = runner.run(self.video, {"translator": "bing"})
        self.assertEqual(self.video.read_bytes(), b"do not alter original")
        for name in ("en.srt", "zh.srt", "bilingual.ass", "bilingual.mp4"):
            self.assertTrue((output / name).is_file())
        ass = (output / "bilingual.ass").read_text(encoding="utf-8-sig")
        self.assertLess(ass.index("第1条中文译文"), ass.index("The signal is weak."))
        self.assertEqual(events[-1]["stage"], "complete")
        self.assertEqual(events[-1]["progress"], 100)

    def test_translation_resume_and_settings_invalidation(self):
        runner = FakeEngine(self.root)
        first = runner.run(self.video, {"translator": "bing"})
        second = runner.run(self.video, {"translator": "bing", "render_mode": "overlay"})
        self.assertNotEqual(first, second)
        self.assertEqual(len(runner.translation_calls), 1)
        runner.run(self.video, {"translator": "google"})
        self.assertEqual(len(runner.translation_calls), 2)

    def test_subtitles_only_then_video_reuses_translation_and_records_time(self):
        runner=FakeEngine(self.root)
        subtitles=runner.run(self.video,{'translator':'bing','subtitles_only':True})
        self.assertFalse((subtitles/'bilingual.mp4').exists())
        self.assertTrue((subtitles/'bilingual.ass').exists())
        result=runner.run(self.video,{'translator':'bing','render_mode':'overlay'})
        self.assertTrue((result/'bilingual.mp4').exists())
        self.assertEqual(len(runner.translation_calls),1)
        self.assertGreaterEqual(json.loads((result/'timings.json').read_text())['total_seconds'],0)
        runner.run(self.video,{'translator':'deepseek','api_key':'fake','model_name':'different'})
        self.assertEqual(len(runner.translation_calls),2)

    def test_shared_cache_reuses_partial_result_in_new_export(self):
        runner=FakeEngine(self.root);runner.partial_failure=True
        with self.assertRaises(RuntimeError):runner.run(self.video,{'translator':'bing'})
        runner.partial_failure=False
        runner.run(self.video,{'translator':'bing','render_mode':'overlay'})
        self.assertEqual(runner.translation_calls[-1]['cached'],{'0':'第1条中文译文'})

    def test_changed_source_creates_new_project(self):
        runner = FakeEngine(self.root)
        first = runner.run(self.video, {"translator": "bing"})
        self.video.with_suffix(".srt").write_text(SAMPLE_SRT.replace("weak", "strong"), encoding="utf-8")
        second = runner.run(self.video, {"translator": "bing"})
        self.assertNotEqual(first, second)
        self.assertTrue((first / "bilingual.mp4").is_file())

    def test_failure_is_not_success_and_completed_translation_resumes(self):
        events = []
        runner = FakeEngine(self.root, events.append)
        runner.partial_failure = True
        with self.assertRaisesRegex(RuntimeError, "Simulated"):
            runner.run(self.video, {"translator": "bing"})
        project = next((self.root / "projects").iterdir())
        self.assertEqual(json.loads((project / "project.json").read_text(encoding="utf-8"))["status"], "failed")
        self.assertFalse((project / "bilingual.mp4").exists())
        self.assertNotIn("complete", [event["stage"] for event in events])
        runner.partial_failure = False
        runner.run(self.video, {"translator": "bing",'resume_from':str(project)})
        self.assertEqual(runner.translation_calls[-1]["cached"], {"0": "第1条中文译文"})
        self.assertTrue((project / "bilingual.mp4").exists())

    def test_api_secret_is_not_persisted(self):
        runner = FakeEngine(self.root)
        key = "sensitive-test-key-never-write"
        project = runner.run(self.video, {"translator": "deepseek", "api_key": key, "model_name": "test-only-no-call"})
        for path in project.iterdir():
            self.assertNotIn(key.encode(), path.read_bytes(), path.name)
        self.assertEqual(runner.translation_calls[0]["api_key"], key)

    def test_srt_malformed_block_is_not_silently_discarded(self):
        with self.assertRaises(ValueError):
            engine.parse_srt(SAMPLE_SRT + "\n3\nthis time is invalid\nmissing text\n")

    def test_overlapping_srt_is_rejected_with_explanation(self):
        with self.assertRaisesRegex(ValueError, "重叠字幕"):
            engine.parse_srt(SAMPLE_SRT.replace("00:00:02,000", "00:00:01,500"))

    def test_incomplete_sentence_merge_preserves_condition(self):
        cues = [{"start": 0, "end": 5, "text": "Noise decreases if the channel"},
                {"start": 5, "end": 7, "text": "remains constant."},
                {"start": 7, "end": 11, "text": "This is another sentence."}]
        merged = engine.merge_incomplete_cues(cues)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0], {"start": 0, "end": 7, "text": "Noise decreases if the channel remains constant."})
        self.assertEqual(len(engine.merge_incomplete_cues(cues, max_seconds=6)), 3)

    def test_wireless_glossary_requires_matching_english_source(self):
        self.assertEqual(engine.apply_wireless_terms("A pilot estimates the channel.", "飞行员估计频道。"), "导频估计信道。")
        self.assertEqual(engine.apply_wireless_terms("A plane flies above us.", "飞行员负责飞机。"), "飞行员负责飞机。")

    def test_srt_timestamp_carry_and_multiline(self):
        cue = engine.parse_srt("1\n00:00:00,000 --> 00:00:59,999\n<i>Hello</i>\nworld\n")[0]
        self.assertEqual(cue["text"], "Hello world")
        self.assertEqual(engine._timestamp(59.999, True), "0:01:00.00")

    def test_ass_injection_and_untranslated_cue_rejected(self):
        path = self.root / "safe.ass"
        cues = [{"start": 0, "end": 1, "text": r"{\pos(0,0)} hello"}]
        engine.build_ass(path, cues, ["安全中文"], 640, 360)
        result = path.read_text(encoding="utf-8-sig")
        self.assertNotIn(r"{\pos(0,0)}", result)
        with self.assertRaises(ValueError):
            engine.build_ass(path, cues, [""], 640, 360)

    def test_remote_http_and_credential_urls_are_rejected(self):
        for url in ("http://api.example.com", "https://key@api.example.com", "https://api.example.com?k=secret"):
            with self.assertRaises(ValueError):
                engine._validate_api_base(url)
        self.assertEqual(engine._validate_api_base("http://127.0.0.1:8000/v1/"), "http://127.0.0.1:8000/v1")

    def test_cancel_terminates_child_promptly(self):
        cancel = threading.Event()
        runner = engine.Engine(self.root, None, cancel)
        timer = threading.Timer(.25, cancel.set)
        start = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(engine.Cancelled):
                runner._process([sys.executable, "-c", "import time; time.sleep(30)"])
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - start, 3.5)

    def test_matching_lock_marker_does_not_prevent_resume(self):
        runner = FakeEngine(self.root)
        project = runner.run(self.video, {"translator": "bing"})
        self.assertTrue((project / ".project.lock").is_file())
        manifest=json.loads((project/'project.json').read_text(encoding='utf-8'))
        manifest['status']='failed';engine._atomic_json(project/'project.json',manifest)
        runner.run(self.video, {"translator": "bing",'resume_from':str(project)})

    def test_repeated_exports_never_overwrite_same_source_and_model(self):
        runner=FakeEngine(self.root)
        first=runner.run(self.video,{'translator':'bing'})
        original=(first/'bilingual.mp4').read_bytes()
        second=runner.run(self.video,{'translator':'bing'})
        self.assertNotEqual(first,second)
        self.assertEqual((first/'bilingual.mp4').read_bytes(),original)
        self.assertRegex(first.name,r'_001_01_\d{12}_\d{2,}$')

    def test_api_models_and_position_codes_differ(self):
        runner=FakeEngine(self.root)
        first=runner.run(self.video,{'translator':'deepseek','model_name':'flash','api_key':'fake','profile_code':10})
        second=runner.run(self.video,{'translator':'deepseek','model_name':'pro','api_key':'fake','profile_code':11,'render_mode':'overlay'})
        self.assertIn('_010_01_',first.name);self.assertIn('_011_02_',second.name)
        self.assertEqual(json.loads((second/'project.json').read_text(encoding='utf-8'))['model_name'],'pro')

    def test_range_intersection_rebases_crossing_cues_and_ignores_disabled_range(self):
        cues=engine.parse_srt(SAMPLE_SRT)
        clipped=engine.clip_cues(cues,1,3)
        self.assertEqual(clipped,[{'start':0,'end':.7,'text':'The signal is weak.'},{'start':1,'end':2,'text':'Do not assume that training loss is enough.'}])
        self.assertEqual(engine.selected_range({'clip_enabled':False,'clip_start':500,'clip_end':1000},4),(0,4))
        for start,end in [(3,2),(-1,2),(0,5),(0,float('nan'))]:
            with self.assertRaises(ValueError):engine.selected_range({'clip_enabled':True,'clip_start':start,'clip_end':end},4)

    def test_fixed_translation_test_uses_selected_api_parameters(self):
        runner=FakeEngine(self.root)
        text=runner.test_translation({'translator':'deepseek','api_key':'fake','api_base':'https://example.com/v1','model_name':'pro'})
        self.assertTrue(text)
        self.assertEqual(runner.translation_calls[0]['model_name'],'pro')


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--integration":
        from paths import app_root
        root = app_root()
        started = time.monotonic()
        runner = engine.Engine(root, lambda event: print(json.dumps(event, ensure_ascii=False), flush=True), threading.Event())
        result = runner.run(sys.argv[2], {"translator": "argos", "model": "base", "output_root": sys.argv[3],
                                        "domain": sys.argv[4] if len(sys.argv) > 4 else "general"})
        print(json.dumps({"result": str(result), "elapsed_seconds": round(time.monotonic() - started, 3)}, ensure_ascii=False))
    else:
        unittest.main(verbosity=2)
