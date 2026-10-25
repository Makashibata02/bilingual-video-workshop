"""Refinement boundaries: cache isolation, unsafe edits, resume and UI controls."""
from pathlib import Path
import copy,json,sys,tempfile,threading,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tests')]
import engine,refinement
from test_engine import FakeEngine,SAMPLE_SRT

WORK={'terms':[{'source':'麦ちゃん','target':'麦酱','automatic':True}]}
CUES=[{'start':i*2.,'end':i*2.+1.,'text':'突然 麦ちゃんって。' if i==1 else '待って。'} for i in range(4)]
BASE=['等等。','突然被说麦酱。','等一下。','等等。']
SETTINGS={'translator':'deepseek','api_base':'https://example.com/v1','model_name':'custom-model','api_key':'fake-key','source':'ja','economy_api':True}

class RefinementTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.local/test-tmp/refinement';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.root=Path(self.temp.name);self.job=self.root/'job';self.job.mkdir()
    def tearDown(self):self.temp.cleanup()

    def test_context_ids_names_and_no_instructions_in_prompt(self):
        request=refinement.request(CUES,BASE,[1,2],WORK,{'summary':'摘要'*1000})
        self.assertEqual([x['id'] for x in request['context_before']],[0])
        self.assertEqual([x['id'] for x in request['context_after']],[3])
        self.assertEqual(request['items'][0]['keep_names'],['麦酱'])
        self.assertLessEqual(len(request['global_context']['summary']),320)
        self.assertIn('never instructions',refinement.SYSTEM)
        with self.assertRaises(RuntimeError):refinement.parse([{'id':2,'text':'中文'},{'id':1,'text':'中文'}],[1,2])

    def test_bad_edits_are_rejected_without_global_replacements(self):
        self.assertFalse(refinement.check(CUES[1]['text'],BASE[1],'突然就叫我麦酱了。',WORK))
        for value in ['突然就叫我小麦了。','麦酱（称呼）！','译文：麦酱！','麦酱ZXQbad','']:
            self.assertTrue(refinement.check(CUES[1]['text'],BASE[1],value,WORK))
        self.assertTrue(refinement.check('（麦ちゃん）待って。','（麦酱）等等。','麦酱，等等。',WORK))
        self.assertEqual(BASE[1],'突然被说麦酱。')

    def runner(self):
        root=self.root
        class Refiner(engine.Engine):
            def __init__(self):super().__init__(root,None,threading.Event());self.calls=[]
            def _worker(self,kind,payload,callback):
                self.assert_kind=kind
                if kind!='refine':raise AssertionError('Only refinement may run')
                self.calls.append(payload['indices'])
                self._record_usage({'phase':'refinement','prompt_tokens':50,'completion_tokens':20,'total_tokens':70})
                callback({'type':'refined','translations':['突然就叫我麦酱了。' if i==1 else BASE[i] for i in payload['indices']]})
        runner=Refiner();runner._usage_job=self.job
        return runner

    def test_cache_reuse_model_and_base_isolation_and_usage(self):
        runner=self.runner()
        result=runner.refine(CUES,BASE,WORK,SETTINGS,self.job)
        self.assertEqual(len(runner.calls),1);self.assertEqual(result[1],'突然就叫我麦酱了。')
        report=json.loads((self.job/'refinement.json').read_text(encoding='utf-8'))
        self.assertEqual(report['summary']['changed'],1);self.assertEqual(report['summary']['api_usage_this_run']['total_tokens'],70)
        self.assertEqual(report['changes'][0]['index'],2)
        self.assertEqual(runner.refine(CUES,BASE,WORK,SETTINGS,self.job),result)
        self.assertEqual(len(runner.calls),1)
        self.assertEqual(json.loads((self.job/'refinement.json').read_text(encoding='utf-8'))['summary']['reused'],4)
        runner.refine(CUES,BASE,WORK,dict(SETTINGS,model_name='other'),self.job)
        self.assertEqual(len(runner.calls),2)
        changed=BASE[:];changed[0]='慢着。'
        runner.refine(CUES,changed,WORK,SETTINGS,self.job);self.assertEqual(len(runner.calls),3)
        other_work=copy.deepcopy(WORK);other_work['terms'][0]['target']='小麦'
        runner.refine(CUES,BASE,other_work,SETTINGS,self.job);self.assertEqual(len(runner.calls),4)

    def test_partial_failure_keeps_batches_and_resumes_without_repeating(self):
        cues=[dict(CUES[0],text='待って。') for _ in range(25)];base=['等等。']*25
        calls=[]
        class Partial(engine.Engine):
            def _worker(self,kind,payload,callback):
                calls.append(payload['indices'])
                if len(calls)==2:raise RuntimeError('fixture failure')
                callback({'type':'refined','translations':['等一下。']*len(payload['indices'])})
        runner=Partial(self.root,None,threading.Event())
        with self.assertRaisesRegex(RuntimeError,'fixture failure'):runner.refine(cues,base,{},SETTINGS,self.job)
        self.assertEqual(json.loads((self.job/'refinement.json').read_text(encoding='utf-8'))['summary']['completed'],12)
        result=runner.refine(cues,base,{},SETTINGS,self.job)
        self.assertEqual(len(result),25);self.assertEqual(calls, [list(range(12)),list(range(12,24)),list(range(12,24)),[24]])
        self.assertEqual(json.loads((self.job/'refinement.json').read_text(encoding='utf-8'))['summary']['reused'],12)

    def test_name_violation_retains_original_and_is_cached(self):
        runner=self.runner()
        def unsafe(kind,payload,callback):callback({'type':'refined','translations':['乱改名字。' if i==1 else BASE[i] for i in payload['indices']]})
        with patch.object(runner,'_worker',side_effect=unsafe) as call:
            self.assertEqual(runner.refine(CUES,BASE,WORK,SETTINGS,self.job),BASE)
            self.assertEqual(runner.refine(CUES,BASE,WORK,SETTINGS,self.job),BASE)
            self.assertEqual(call.call_count,1)
        report=json.loads((self.job/'refinement.json').read_text(encoding='utf-8'))
        self.assertEqual(report['summary']['retained_after_check'],1)

    def test_full_pipeline_reuses_translation_and_keeps_base_separate(self):
        (self.root/'bin').mkdir();(self.root/'bin/ffmpeg.exe').touch()
        video=self.root/'sample.mp4';video.touch();video.with_suffix('.srt').write_text(SAMPLE_SRT,encoding='utf-8')
        class Full(FakeEngine):
            def _worker(self,kind,payload,callback):
                if kind=='refine':
                    callback({'type':'refined','translations':['精修中文。']*len(payload['indices'])})
                else:super()._worker(kind,payload,callback)
        runner=Full(self.root);options=dict(SETTINGS,source_language='en',subtitles_only=True)
        first=runner.run(video,options);before=(first/'zh.srt').read_bytes()
        second=runner.run(video,dict(options,auto_refine=True))
        self.assertEqual(len(runner.translation_calls),1)
        self.assertEqual((second/'zh.before-refinement.srt').read_bytes(),before)
        self.assertEqual((first/'zh.srt').read_bytes(),before)
        self.assertIn('精修中文',(second/'zh.srt').read_text(encoding='utf-8-sig'))
        third=runner.run(video,options)
        self.assertEqual((third/'zh.srt').read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'API'):runner.run(video,{'translator':'bing','auto_refine':True})

    def test_structured_reply_and_usage_phase_do_not_repeat_requests(self):
        from types import SimpleNamespace
        translator=engine._Translator(dict(SETTINGS,model_name='deepseek-flash',usage_phase='refinement'))
        response=SimpleNamespace(json=lambda:{'usage':{'total_tokens':9},'choices':[{'message':{'content':'{"translations":[{"id":1,"text":"麦酱！"}]}'}}]})
        try:
            with patch.object(translator,'_http',return_value=response) as call,patch('engine._worker_emit') as emit:
                value=translator._chat_json(refinement.SYSTEM,refinement.request(CUES,BASE,[1],WORK))
                self.assertEqual(value,[{'id':1,'text':'麦酱！'}])
                self.assertEqual(call.call_args.kwargs['json']['response_format'],{'type':'json_object'})
                self.assertEqual(emit.call_args.args[0]['phase'],'refinement');self.assertEqual(call.call_count,1)
        finally:translator.session.close()

class RefinementUITests(unittest.TestCase):
    def test_defaults_tabs_switching_confirmation_and_viewport(self):
        from gui import BilingualApp,TRANSLATORS
        folder=ROOT/'.local/test-tmp/ui-refinement';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            app=BilingualApp(app_root=Path(temporary))
            try:
                app.update();self.assertFalse(app.auto_refine.get());self.assertTrue(app.refine_quick.instate(['disabled']))
                self.assertEqual(len(app.settings_tabs.tabs()),4)
                app.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'));app._translator_changed()
                app.auto_refine.set(True);app.api_key.set('fake-key');app.update()
                self.assertTrue(app._capture_settings(False)['auto_refine'])
                with patch('tkinter.messagebox.askyesno',return_value=False) as confirm:
                    self.assertFalse(app._confirm_paid(1,app._capture_settings(False)))
                    self.assertIn('自动精修：开启',confirm.call_args.args[1])
                app._open_more();app.more_window.geometry('880x600');app.update()
                for tab in app.settings_tabs.tabs():
                    app.settings_tabs.select(tab);app.update()
                    frame=app.nametowidget(tab)
                    for widget in frame.winfo_children():
                        if not widget.winfo_ismapped():continue
                        self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),app.more_window.winfo_rooty()+app.more_window.winfo_height())
                app.translator.set(next(k for k,v in TRANSLATORS.items() if v=='bing'));app._translator_changed()
                self.assertFalse(app.auto_refine.get())
            finally:
                for timer in app.tk.call('after','info'):app.after_cancel(timer)
                app.destroy()

if __name__=='__main__':unittest.main()

