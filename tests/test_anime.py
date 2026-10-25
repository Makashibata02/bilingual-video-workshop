"""Japanese pipeline, isolated context and explicit queue-start regressions."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'tests')]
import anime,engine,layout
from test_engine import FakeEngine

JA='1\n00:00:00,200 --> 00:00:01,700\nハル、明日会おう。\n\n2\n00:00:02,000 --> 00:00:03,800\n先生、ありがとう。\n'
WORK={'id':'fixture','title':'合成作品','notes':'人物为虚构测试资料','terms':[
    {'source':'ハル','reading':'はる','aliases':['ハル君'],'target':'小春','notes':'','confirmed':True},
    {'source':'先生','reading':'','aliases':[],'target':'老师','notes':'待核对','confirmed':False}]}


class AnimeTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.local/test-tmp/anime';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_work_store_confirmed_snapshot_and_independent_saved_versions(self):
        store=anime.WorkStore(self.root)
        identifier=store.save(WORK['title'],WORK['terms'],WORK['notes'])
        saved=anime.WorkStore(self.root).get(identifier)
        frozen=anime.snapshot(saved)
        self.assertEqual(len(frozen['terms']),1)
        saved['terms'][0]['target']='春同学';store.save(saved['title'],saved['terms'],work_id=identifier)
        self.assertEqual(frozen['terms'][0]['target'],'小春')
        self.assertNotIn('小春',anime.asr_hint(saved))
        self.assertEqual(anime.asr_hint(frozen),anime.asr_hint(saved))

    def test_conflicting_confirmed_aliases_are_rejected(self):
        other=dict(WORK['terms'][0],source='別名',target='另一个人',aliases=['ハル'])
        with self.assertRaises(ValueError):anime.validate_terms([WORK['terms'][0],other])

    def test_context_only_in_selected_cues_and_reply_rejects_extra_or_reordered_ids(self):
        cues=[{'text':str(i)} for i in range(10)]
        request=anime.request_data(cues,[3,4],WORK)
        self.assertEqual([x['id'] for x in request['context_before']],[1,2])
        self.assertEqual([x['id'] for x in request['context_after']],[5,6])
        self.assertEqual(len(request['work']['terms']),1)
        self.assertEqual(anime.parse_reply([{'id':3,'text':'甲'},{'id':4,'text':'乙'}],[3,4]),['甲','乙'])
        for invalid in [[{'id':4,'text':'甲'},{'id':3,'text':'乙'}],[{'id':3,'text':'甲'}],
                        [{'id':3,'text':'甲'},{'id':4,'text':'乙'},{'id':5,'text':'上下文不应输出'}]]:
            with self.assertRaises(RuntimeError):anime.parse_reply(invalid,[3,4])

    def test_name_check_warns_without_rewriting_or_using_unconfirmed_names(self):
        cues=engine.parse_srt(JA);translations=['明天见。','谢谢。']
        before=translations[:];warnings=anime.name_warnings(cues,translations,WORK)
        self.assertEqual(len(warnings),1);self.assertEqual(warnings[0]['expected'],'小春')
        self.assertEqual(translations,before)

    def test_protected_names_longest_alias_boundaries_and_marker_integrity(self):
        work={'terms':[{'source':'まめ','target':'小豆','confirmed':True},{'source':'麦','target':'麦','confirmed':True},{'source':'麦ちゃん','target':'小麦','confirmed':True}]}
        protected,mapping=anime.protect_names('店長は まめでしょ？ 麦ちゃん、麦さん。こまめに麦芽を混ぜる。',work)
        self.assertEqual(list(mapping.values()),['小豆','小麦','麦'])
        self.assertIn('こまめに麦芽',protected)
        restored=anime.restore_names(protected,mapping)
        self.assertIn('小豆でしょ',restored);self.assertIn('小麦',restored)
        with self.assertRaises(RuntimeError):anime.restore_names('标记丢失',mapping)
        with self.assertRaises(RuntimeError):anime.restore_names(protected+protected,mapping)
        unconfirmed={'terms':[dict(work['terms'][0],confirmed=False)]}
        self.assertFalse(anime.protect_names('まめ',unconfirmed)[1])

    def test_full_source_chunks_cover_last_cue_and_context_is_validated(self):
        cues=[{'text':'原文'+str(i)+'あ'*10000} for i in range(5)]
        chunks=anime.source_chunks(cues)
        self.assertEqual([r['id'] for group in chunks for r in group],list(range(5)))
        self.assertGreater(len(chunks),1)
        context={'summary':'测试概述','entities':[],'relationships':[],'terms':[],'uncertainties':[]}
        self.assertEqual(anime.validate_context(context),context)
        for bad in ({},dict(context,summary=''),dict(context,entities=['x'*601])):
            with self.assertRaises(RuntimeError):anime.validate_context(bad)

    def test_understanding_hierarchy_cache_and_model_isolation(self):
        calls=[]
        class Reader(engine.Engine):
            def _worker(self,kind,payload,callback):
                self.assert_kind=kind;calls.append(payload)
                callback({'type':'understanding','context':{'summary':'已读全部提供资料'+str(len(calls)),'entities':[],'relationships':[],'terms':[],'uncertainties':[]}})
        reader=Reader(self.root,None,None);cues=[{'text':'あ'*10000} for _ in range(3)]
        settings={'api_base':'https://example.com','model_name':'fixture','api_key':'fake-key'}
        first=reader.understand(cues,anime.snapshot(),settings,self.root/'first')
        self.assertEqual(len(calls),5)
        self.assertEqual([x['id'] for p in calls if 'items' in p['data'] for x in p['data']['items']],[0,1,2])
        reader.understand(cues,anime.snapshot(),settings,self.root/'second');self.assertEqual(len(calls),5)
        self.assertNotIn('fake-key',''.join(p.read_text(encoding='utf-8') for p in self.root.rglob('*.json')))
        reader.understand(cues,anime.snapshot(),dict(settings,model_name='other'),self.root/'third');self.assertEqual(len(calls),10)
        self.assertEqual(json.loads((self.root/'second/global-context.json').read_text(encoding='utf-8'))['api_requests_this_run'],0)

    def test_pipeline_understanding_precedes_translation_and_is_in_cache_key(self):
        (self.root/'bin').mkdir();(self.root/'bin/ffmpeg.exe').touch()
        video=self.root/'fixture.mp4';video.write_bytes(b'fixture');video.with_suffix('.ja.srt').write_text(JA,encoding='utf-8')
        calls=[]
        class Reader(FakeEngine):
            def _worker(self,kind,payload,callback):
                calls.append(kind)
                if kind=='understand':callback({'type':'understanding','context':{'summary':'上下文','entities':[],'relationships':[],'terms':[],'uncertainties':[]}})
                else:super()._worker(kind,payload,callback)
        reader=Reader(self.root);options={'translator':'deepseek','api_key':'fake','global_understanding':True,'source_language':'ja','subtitles_only':True}
        output=reader.run(video,options)
        self.assertEqual(calls,['understand','translate'])
        self.assertEqual(reader.translation_calls[0]['global_context']['summary'],'上下文')
        reader.run(video,dict(options,render_mode='overlay'));self.assertEqual(calls,['understand','translate'])
        reader.run(video,dict(options,global_understanding=False));self.assertEqual(calls,['understand','translate','understand','translate'])

    def test_japanese_source_choice_encoding_and_sentence_boundaries(self):
        video=self.root/'example.mkv';video.touch();video.with_suffix('.srt').write_text('English only',encoding='utf-8')
        self.assertFalse(engine.source_sidecar(video,{'source_language':'ja'}).exists())
        subtitle=video.with_suffix('.ja.srt');subtitle.write_bytes(JA.encode('cp932'))
        with self.assertRaisesRegex(ValueError,'CP932'):engine.read_sidecar(subtitle,'ja')
        cues=engine.read_sidecar(subtitle,'ja','cp932')
        self.assertEqual(len(engine.merge_incomplete_cues(cues,language='ja')),2)
        self.assertEqual(engine.source_sidecar(video,{'source_language':'ja','source_srt':str(subtitle)}),subtitle)

    def test_anime_word_timestamps_split_a_long_silence(self):
        words=[SimpleNamespace(start=1,end=1.3,word='ハル、'),SimpleNamespace(start=1.3,end=2,word='行こう。'),
               SimpleNamespace(start=30,end=31,word='ありがとう。')]
        cues=engine.japanese_word_cues(SimpleNamespace(start=1,end=31,text='ハル、行こう。ありがとう。',words=words))
        self.assertEqual(len(cues),2);self.assertEqual(cues[0]['end'],2);self.assertEqual(cues[1]['start'],30)

    def test_anime_api_sends_context_and_validates_before_emitting(self):
        settings={'translator':'deepseek','source':'ja','work_snapshot':WORK,'api_base':'https://example.com/v1','model_name':'fixture','api_key':'fake-key'}
        translator=engine._Translator(settings);payloads=[]
        def reply(system,data):
            payloads.append(data)
            import re
            token=re.search(r'ZXQ\w+QXZ',data['items'][0]['text']).group()
            return [{'id':x['id'],'text':token+'，我们走吧。'} for x in data['items']]
        try:
            with patch.object(translator,'_chat_json',side_effect=reply):
                result=translator.translate_anime(engine.parse_srt(JA),[0])
            self.assertEqual(result,['小春，我们走吧。'])
            self.assertEqual(payloads[0]['context_after'][0]['id'],1)
            self.assertNotIn('fake-key',json.dumps(payloads))
        finally:translator.session.close()

    def test_ai_name_candidates_cannot_confirm_themselves(self):
        translator=engine._Translator({'translator':'deepseek','source':'ja'})
        try:
            with patch.object(translator,'_chat_json',return_value=[dict(WORK['terms'][0],confirmed=True)]):
                result=translator.draft_names(engine.parse_srt(JA))
            self.assertFalse(result[0]['confirmed']);self.assertFalse(anime.snapshot({'terms':result})['terms'])
        finally:translator.session.close()

    def test_free_translators_use_japanese_source_and_argos_is_blocked(self):
        with self.assertRaises(ValueError):engine._Translator({'translator':'argos','source':'ja'})
        translator=engine._Translator({'translator':'google','source':'ja'})
        response=SimpleNamespace(json=lambda:[[['你好','x']]])
        try:
            with patch.object(translator,'_http',return_value=response) as call:
                self.assertEqual(translator.translate(['こんにちは']),['你好'])
                self.assertEqual(call.call_args.kwargs['params']['sl'],'ja')
        finally:translator.session.close()

    def test_review_phase_does_not_translate_and_continues_with_edited_source(self):
        (self.root/'bin').mkdir();(self.root/'bin/ffmpeg.exe').touch()
        video=self.root/'fixture.mp4';video.write_bytes(b'fixture');video.with_suffix('.ja.srt').write_text(JA,encoding='utf-8')
        runner=FakeEngine(self.root);options={'translator':'bing','source_language':'ja','content_mode':'anime','work_snapshot':WORK}
        out=runner.run(video,dict(options,recognize_only=True))
        self.assertFalse(runner.translation_calls);self.assertFalse((out/'bilingual.mp4').exists())
        self.assertEqual(json.loads((out/'project.json').read_text(encoding='utf-8'))['status'],'awaiting_review')
        reviewed=out/'reviewed.srt';reviewed.write_text(JA.replace('明日','今日'),encoding='utf-8')
        with patch('layout.japanese_font',return_value=None):
            completed=runner.run(video,dict(options,resume_from=str(out),reviewed_srt=str(reviewed)))
        self.assertEqual(out,completed);self.assertIn('今日',runner.translation_calls[0]['cues'][0]['text'])
        self.assertTrue((out/'ja.original.srt').is_file());self.assertFalse((out/'en.srt').exists())
        self.assertTrue((out/'bilingual.mp4').exists())

    def test_chinese_name_change_reuses_asr_but_japanese_hint_change_does_not(self):
        (self.root/'bin').mkdir();(self.root/'bin/ffmpeg.exe').touch()
        model=self.root/'models/base';model.mkdir(parents=True)
        for name in ['model.bin','config.json','tokenizer.json']:(model/name).touch()
        video=self.root/'fixture.mp4';video.write_bytes(b'fixture')
        calls=[]
        class Recognizer(FakeEngine):
            def _worker(self,kind,payload,callback):
                if kind=='asr':
                    calls.append(payload)
                    for cue in engine.parse_srt(JA):callback({'type':'segment','cue':cue})
                else:super()._worker(kind,payload,callback)
            def _process(self,command,**kwargs):
                if str(command[-1]).endswith('audio.wav'):Path(command[-1]).touch();return ''
                return super()._process(command,**kwargs)
        options={'translator':'bing','source_language':'ja','content_mode':'anime','model':'base','recognize_only':True,'work_snapshot':copy.deepcopy(WORK)}
        Recognizer(self.root).run(video,options)
        options['work_snapshot']['terms'][0]['target']='春同学';Recognizer(self.root).run(video,options)
        self.assertEqual(len(calls),1)
        options['work_snapshot']['terms'][0]['reading']='ハル';Recognizer(self.root).run(video,options)
        self.assertEqual(len(calls),2)

    def test_review_new_model_gets_new_folder_and_preserves_original(self):
        (self.root/'bin').mkdir();(self.root/'bin/ffmpeg.exe').touch()
        video=self.root/'fixture.mp4';video.write_bytes(b'fixture');video.with_suffix('.ja.srt').write_text(JA,encoding='utf-8')
        options={'translator':'bing','source_language':'ja','content_mode':'anime'}
        runner=FakeEngine(self.root);original=runner.run(video,dict(options,recognize_only=True))
        changed=dict(options,translator='deepseek',api_base='https://example.com/v1',api_key='fake-key',model_name='fixture',
                     profile_code=15,resume_from=str(original),reviewed_srt=str(original/'ja.srt'))
        with patch('layout.japanese_font',return_value=None):result=runner.run(video,changed)
        self.assertNotEqual(original,result);self.assertIn('_015_',result.name)
        self.assertTrue((result/'ja.original.srt').is_file())
        self.assertEqual(json.loads((original/'project.json').read_text(encoding='utf-8'))['status'],'awaiting_review')


class QueueTests(unittest.TestCase):
    def setUp(self):
        from gui import BilingualApp
        base=ROOT/'.local/test-tmp/queue';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
        self.app=BilingualApp(app_root=self.root)
        self.info=patch('tkinter.messagebox.showinfo');self.info.start()
        self.error=patch('tkinter.messagebox.showerror');self.errors=self.error.start()
        self.probe=patch('engine.Engine._probe',return_value={'duration':100.,'width':1280,'height':720,'audio':True});self.probe.start()
        self.preflight=patch('engine.Engine.preflight',return_value={'duration':100.});self.preflight.start()
    def tearDown(self):
        for timer in self.app.tk.call('after','info'):self.app.after_cancel(timer)
        self.app.destroy();self.probe.stop();self.preflight.stop();self.info.stop();self.error.stop();self.temp.cleanup()
        self.assertFalse(self.errors.called,self.errors.call_args)
    def add(self,count=2):
        paths=[]
        for i in range(count):
            p=self.root/f'{len(self.app.jobs)}-{i}.mp4';p.touch();paths.append(p)
        self.app.enqueue(paths);self.app.update()
        return list(self.app.jobs.values())
    def test_import_never_starts_or_confirms_even_when_api_key_is_missing(self):
        from gui import TRANSLATORS
        self.app.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'))
        with patch.object(self.app,'_start_next') as start,patch.object(self.app,'_confirm_paid') as confirm:
            jobs=self.add()
        self.assertTrue(all(j.status=='待开始' for j in jobs));start.assert_not_called();confirm.assert_not_called()
    def test_apply_settings_preserves_individual_ranges_and_new_imports_wait(self):
        jobs=self.add();jobs[0].options.update(clip_enabled=True,clip_start=10,clip_end=20)
        self.app.tree.selection_set(*[j.id for j in jobs]);self.app.asr_model.set('small');self.app._apply_selected_settings()
        self.assertEqual(jobs[0].options['clip_start'],10);self.assertFalse(jobs[1].options.get('clip_enabled',False))
        self.assertTrue(all(j.options['model']=='small' for j in jobs))
        self.app.active_id=jobs[0].id
        with patch.object(self.app,'_start_next') as start:self.add(1)
        start.assert_not_called();self.assertEqual(list(self.app.jobs.values())[-1].status,'待开始')
    def test_cancelled_start_keeps_all_drafts_and_selected_start_freezes_snapshot(self):
        jobs=self.add();self.app.tree.selection_set(jobs[0].id)
        with patch.object(self.app,'_confirm_online',return_value=False),patch.object(self.app,'_start_next') as start:self.app._begin_jobs()
        self.assertTrue(all(j.status=='待开始' for j in jobs));start.assert_not_called()
        with patch.object(self.app,'_confirm_online',return_value=True),patch.object(self.app,'_start_next') as start:self.app._begin_jobs()
        self.assertEqual(jobs[0].status,'待处理');self.assertEqual(jobs[1].status,'待开始');start.assert_called_once()
        original=copy.deepcopy(jobs[0].options);self.app.asr_model.set('small');self.app._apply_selected_settings()
        self.assertEqual(jobs[0].options,original)
    def test_retry_requires_explicit_start_and_review_only_does_not_confirm_api(self):
        jobs=self.add();jobs[0].status='失败';self.app.tree.selection_set(jobs[0].id)
        with patch.object(self.app,'_start_next') as start:self.app._retry_selected()
        self.assertEqual(jobs[0].status,'待开始');start.assert_not_called()
        with patch.object(self.app,'_confirm_online') as confirm,patch.object(self.app,'_start_next'):
            self.app._begin_jobs(recognize=True)
        confirm.assert_not_called();self.assertTrue(jobs[0].options['recognize_only'])

    def test_single_selection_autosaves_and_details_stay_hidden(self):
        jobs=self.add();self.app.tree.selection_set(jobs[0].id);self.app._select_task()
        self.app.render_mode.set('画面内叠加 · 底部显示');self.app.update()
        self.assertEqual(jobs[0].options['render_mode'],'overlay')
        self.assertFalse(self.app.more_window.winfo_ismapped())
        self.assertFalse(self.app.log_frame.winfo_ismapped())
        self.assertEqual(jobs[1].options['render_mode'],'band')
        self.app.tree.selection_set(jobs[1].id);self.app._select_task();self.app.update()
        self.assertTrue(self.app.render_mode.get().startswith('独立'))

    def test_work_editor_has_visible_save_and_can_start_another_work(self):
        import tkinter as tk
        self.app._edit_work();self.app.update()
        dialog=next(w for w in self.app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='作品资料与人物译名表')
        def descendants(w):return [w]+[g for child in w.winfo_children() for g in descendants(child)]
        buttons=[w for w in descendants(dialog) if w.winfo_class()=='TButton']
        save=next(w for w in buttons if w.cget('text')=='保存作品资料')
        self.assertLessEqual(save.winfo_rooty()+save.winfo_height(),dialog.winfo_rooty()+dialog.winfo_height())
        self.assertTrue(any(w.cget('text')=='新建作品' for w in buttons))
        dialog.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
