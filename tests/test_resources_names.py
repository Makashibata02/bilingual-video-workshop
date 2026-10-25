"""Automatic naming, small context budgets, and graceful resource fallbacks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import anime,engine,resources


class ResourceNameTests(unittest.TestCase):
    def test_automatic_target_notes_are_moved_and_human_aliases_are_preserved(self):
        rows=[{'source':'お姉さん','target':'姐姐（称呼）','automatic':True},
              {'source':'ルリ','target':'译名：露莉【暂译，非官方】','automatic':True},
              {'source':'ハル','target':'小春 - 音译候选','automatic':True},
              {'source':'リリ','target':'莉莉（Lily）','automatic':True},
              {'source':'先生','target':'老师（尊称）','confirmed':True}]
        original=copy.deepcopy(rows);clean=anime.validate_terms(rows)
        self.assertEqual([r['target'] for r in clean],['姐姐','露莉','小春','莉莉（Lily）','老师（尊称）'])
        self.assertIn('称呼',clean[0]['notes']);self.assertEqual(clean,anime.validate_terms(clean))
        self.assertEqual(rows,original)
        work=anime.automatic_work([{'text':'ルリ、お姉さん！'}],{},rows[:2])
        self.assertEqual([x['target'] for x in work['terms']],['姐姐','露莉'])

    def test_cache_note_cleanup_is_source_grounded_and_model_isolated(self):
        cues=[{'text':'お姉さん！'},{'text':'この表記を説明する。'}]
        raw={'terms':[{'source':'お姉さん','target':'姐姐（称呼）','automatic':True}]}
        old={'translator':'deepseek','source':'ja','model_name':'fixture','work_snapshot':raw,'name_protection':'protected-names-4-address-boundaries'}
        prior={'settings':old,'fingerprint':engine._json_hash({'texts':[c['text'] for c in cues],'settings':old}),
               'translations':{'0':'姐姐（称呼）！','1':'这里写的是“姐姐（称呼）”。'}}
        settings=dict(old,work_snapshot=anime.snapshot(raw),name_protection=anime.NAME_RECIPE)
        result=engine.migrate_clean_name_cache(cues,prior,settings)
        self.assertEqual(result['translations'],{'0':'姐姐！'});self.assertEqual(result['repaired_cues'],[1])
        self.assertIsNone(engine.migrate_clean_name_cache(cues,prior,dict(settings,model_name='other')))
        self.assertIsNone(engine.migrate_clean_name_cache(cues,dict(prior,fingerprint='invalid'),settings))
        self.assertEqual(prior['translations']['0'],'姐姐（称呼）！')

    def test_pipeline_reuses_dirty_name_cache_without_any_translation_worker(self):
        from test_engine import FakeEngine
        base=ROOT/'.local/test-tmp/note-cleanup';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            root=Path(folder);(root/'bin').mkdir();(root/'bin/ffmpeg.exe').touch()
            video=root/'fixture.mp4';video.write_bytes(b'fixture')
            video.with_suffix('.ja.srt').write_text('1\n00:00:00,200 --> 00:00:01,700\nお姉さん！\n',encoding='utf-8')
            options={'translator':'bing','source_language':'ja','content_mode':'anime','subtitles_only':True,
                     'work_snapshot':{'terms':[{'source':'お姉さん','target':'姐姐（称呼）','automatic':True}]}}
            class Seed(FakeEngine):
                def _worker(self,kind,payload,callback):callback({'type':'translated','index':0,'text':'姐姐！'})
            first=Seed(root).run(video,options);cache=json.loads((first/'translations.json').read_text(encoding='utf-8'))
            new_shared=root/'cache/translations'/(cache['fingerprint']+'.json');new_shared.unlink()
            cache['settings']['name_protection']='protected-names-4-address-boundaries'
            cache['settings']['work_snapshot']['terms'][0].update(target='姐姐（称呼）',notes='')
            cache['fingerprint']=engine._json_hash({'texts':['お姉さん！'],'settings':cache['settings']});cache['translations']['0']='姐姐（称呼）！'
            (first/'translations.json').write_text(json.dumps(cache,ensure_ascii=False),encoding='utf-8')
            (root/'cache/translations'/(cache['fingerprint']+'.json')).write_text(json.dumps(cache,ensure_ascii=False),encoding='utf-8')
            direct=engine.migrate_clean_name_cache([{'text':'お姉さん！'}],cache,dict(cache['settings'],work_snapshot=anime.snapshot(cache['settings']['work_snapshot']),name_protection=anime.NAME_RECIPE))
            self.assertEqual(direct['repaired_cues'],[1])
            class NoNetwork(FakeEngine):
                def _worker(self,*args,**kwargs):raise AssertionError('A paid or free translator must not run for this cache cleanup')
            output=NoNetwork(root).run(video,options)
            self.assertIn('姐姐！',(output/'zh.srt').read_text(encoding='utf-8-sig'))
            self.assertNotIn('称呼',(output/'zh.srt').read_text(encoding='utf-8-sig'))
            self.assertEqual(json.loads((output/'translation-cache-migration.json').read_text(encoding='utf-8'))['sources'][0]['cleaned_cues'],[1])

    def test_auto_names_are_grounded_fixed_and_not_human_confirmed(self):
        cues=[{'text':'（ルリ）まめさん、麦ちゃん。こまめに麦芽を混ぜる。'}]
        candidates=[{'source':'まめ','target':'小豆'},{'source':'麦','target':'小麦'},
                    {'source':'存在しない人','target':'虚构姓名'}]
        work=anime.automatic_work(cues,{},candidates)
        names={t['source']:t for t in work['terms']}
        self.assertEqual(names['まめさん']['target'],'小豆')
        self.assertEqual(names['麦ちゃん']['target'],'小麦酱')
        self.assertEqual(names['ルリ']['target'],'ルリ')
        self.assertNotIn('存在しない人',names)
        self.assertTrue(all(t['automatic'] and not t['confirmed'] for t in names.values()))
        protected,mapping=anime.protect_names(cues[0]['text'],work,stable=True)
        self.assertIn('こまめに麦芽',protected)
        self.assertEqual(anime.protect_names(cues[0]['text'],work,stable=True)[0],protected)
        self.assertIn('小豆',anime.restore_names(protected,mapping))

    def test_saved_human_and_prior_auto_choices_override_new_model_preferences(self):
        cues=[{'text':'ルリ、まめちゃん。'}]
        human={'terms':[{'source':'ルリ','target':'露莉','confirmed':True}]}
        prior=[{'source':'まめ','target':'小豆','automatic':True}]
        work=anime.automatic_work(cues,human,[{'source':'ルリ','target':'琉璃'},{'source':'まめ','target':'豆豆'}],prior)
        names={t['source']:t['target'] for t in work['terms']}
        self.assertEqual(names['ルリ'],'露莉');self.assertEqual(names['まめちゃん'],'小豆酱')
        frozen=copy.deepcopy(work);human['terms'][0]['target']='新名称'
        self.assertEqual(work,frozen)

    def test_unspaced_connectives_lock_names_without_matching_ordinary_words(self):
        cues=[{'text':'うん。けどルリちゃん、でもまめ。こまめに麦芽を混ぜる。（鼻歌）（笑い声）'}]
        work=anime.automatic_work(cues,{},[{'source':'ルリ','target':'露莉'},{'source':'まめ','target':'小豆'},{'source':'麦','target':'麦'}])
        text,mapping=anime.protect_names(cues[0]['text'],work)
        self.assertEqual(list(mapping.values()),['露莉酱','小豆'])
        self.assertIn('こまめに麦芽',text)
        self.assertFalse(any(t['source'] in ('鼻歌','笑い声') for t in work['terms']))
        with self.assertRaises(RuntimeError):anime.restore_names(next(iter(mapping)),{})

    def test_explicit_speaker_label_is_preserved_outside_api_generation(self):
        work={'terms':[{'source':'ハル','target':'小春','automatic':True},{'source':'ルリ','target':'露莉','automatic':True}]}
        cues=[{'text':'（ハル）ルリ、行こう。'}]
        translator=engine._Translator({'translator':'deepseek','source':'ja','work_snapshot':work})
        try:
            def reply(system,data):
                self.assertEqual(data['items'][0]['speaker'],'小春')
                self.assertNotIn('（',data['items'][0]['text'])
                return [{'id':0,'text':data['items'][0]['text']}]
            with patch.object(translator,'_chat_json',side_effect=reply):
                self.assertEqual(translator.translate_anime(cues,[0]),['（小春）露莉、行こう。'])
        finally:translator.session.close()

    def test_address_continuations_are_protected_without_context_marker_leaks(self):
        cues=[{'text':'ハルちゃんって呼んで。'},{'text':'ちょっと待って。'},{'text':'ハルさんみたいなのはいいね。'}]
        work=anime.automatic_work(cues,{},[{'source':'ハル','target':'小春'}])
        translator=engine._Translator({'translator':'deepseek','source':'ja','work_snapshot':work})
        try:
            def reply(system,data):
                self.assertEqual(data['items'][0]['keep_names'],[])
                for key in ('context_before','context_after'):
                    self.assertFalse(any('ZXQ' in row['text'] for row in data[key]))
                return [{'id':1,'text':'稍等一下。'}]
            with patch.object(translator,'_chat_json',side_effect=reply):
                self.assertEqual(translator.translate_anime(cues,[1]),['稍等一下。'])
            self.assertEqual(list(anime.protect_names(cues[0]['text'],work)[1].values()),['小春酱'])
            self.assertEqual(list(anime.protect_names(cues[2]['text'],work)[1].values()),['小春'])
        finally:translator.session.close()
        self.assertEqual(list(anime.translation_batches([1,4,5,6,12])),[[1],[4,5,6],[12]])

    def test_deepseek_compute_parameters_do_not_leak_to_other_providers(self):
        from types import SimpleNamespace
        response=SimpleNamespace(json=lambda:{'choices':[{'message':{'content':'[]'}}]})
        for model,economy,expected in [('deepseek-flash',True,'disabled'),('deepseek-flash',False,None),('custom-model',True,None)]:
            translator=engine._Translator({'translator':'deepseek','source':'ja','api_base':'https://example.com/v1','model_name':model,'api_key':'fake-key','economy_api':economy})
            try:
                with patch.object(translator,'_http',return_value=response) as call:
                    translator._chat_json('fixture',[])
                    body=call.call_args.kwargs['json']
                    self.assertEqual(body.get('thinking',{}).get('type'),expected)
                    self.assertNotIn('reasoning_effort',body)
                    translator._chat_json('fixture',[],analysis=True)
                    body=call.call_args.kwargs['json']
                    if expected:self.assertEqual(body['reasoning_effort'],'low')
            finally:translator.session.close()

    def test_deepseek_structured_object_is_unwrapped_without_repeating_paid_calls(self):
        from types import SimpleNamespace
        translator=engine._Translator({'translator':'deepseek','source':'ja','api_base':'https://example.com/v1','model_name':'deepseek-flash','api_key':'fake-key'})
        response=SimpleNamespace(json=lambda:{'choices':[{'message':{'content':'{"translations":[{"id":0,"text":"好。"}]}'}}]})
        data={'response_schema':'anime-translations-object-v1','items':[{'id':0,'text':'はい。'}]}
        try:
            with patch.object(translator,'_http',return_value=response) as call:
                self.assertEqual(translator._chat_json('json fixture',data),[{'id':0,'text':'好。'}])
                self.assertEqual(call.call_args.kwargs['json']['response_format'],{'type':'json_object'})
                self.assertEqual(call.call_count,1)
            bad=SimpleNamespace(json=lambda:{'choices':[{'message':{'content':'{"translations":['}}]})
            with patch.object(translator,'_http',return_value=bad) as call,patch('engine._worker_emit') as emit:
                with self.assertRaisesRegex(RuntimeError,'未自动重发'):translator._chat_json('json fixture',data)
                self.assertEqual(call.call_count,1)
                self.assertEqual(emit.call_args.args[0]['type'],'invalid_api_content')
        finally:translator.session.close()

    def test_compact_request_omits_full_entity_lists_and_unrelated_notes(self):
        cues=[{'text':'ルリ、行こう。'} for _ in range(8)]
        work=anime.automatic_work(cues,{},[{'source':'ルリ','target':'露莉'}])
        context={'summary':'摘要。'*1000,'entities':['长人物资料'*80]*30,'relationships':['甲乙无关说明'*30]*30,'terms':[]}
        translator=engine._Translator({'translator':'deepseek','source':'ja','work_snapshot':work,'global_context':context,'related_context':context})
        sent=[]
        def reply(system,data):
            sent.append(data)
            return [{'id':x['id'],'text':x['text']} for x in data['items']]
        try:
            with patch.object(translator,'_chat_json',side_effect=reply):
                values=translator.translate_anime(cues,[0,1])
                translator.translate_anime(cues,[2,3])
            self.assertTrue(all('露莉' in x and 'ZXQ' not in x for x in values))
            self.assertLessEqual(len(sent[0]['global_context']['summary']),320)
            self.assertNotIn('entities',json.dumps(sent[0]))
            self.assertEqual(sent[0]['global_context'],sent[1]['global_context'])
            with patch.object(translator,'_chat_json',return_value=[{'id':0,'text':'琉璃，走吧。'}]):
                with self.assertRaisesRegex(RuntimeError,'未自动重发'):translator.translate_anime(cues,[0])
        finally:translator.session.close()

    def test_balanced_policy_handles_small_large_unknown_and_uma_memory(self):
        for logical,physical,ram in [(2,2,4),(8,4,8),(32,24,64),(128,64,256)]:
            hardware={'logical_cores':logical,'physical_cores':physical,'memory':{'total':ram*resources.GIB,'available':ram*resources.GIB//2}}
            plan=resources.balanced_plan(hardware)
            self.assertLessEqual(plan['encode_threads'],12)
            self.assertLessEqual(plan['asr_threads'],4)
            self.assertLessEqual(plan['memory_budget_bytes'],ram*resources.GIB//2)
            self.assertEqual(plan['asr_device'],'cpu')
        plan=resources.balanced_plan({})
        self.assertEqual(plan['encode_threads'],1)
        self.assertEqual(resources.balanced_plan({'memory':{'total':64*resources.GIB,'available':resources.GIB}})['memory_budget_bytes'],0)
        hardware={'cpu_name':'fixture','logical_cores':8,'gpus':[{'name':'UMA','dedicated_vram':128*1024**2,'shared_ram_limit':16*resources.GIB}]}
        self.assertIn('共享上限 16.0 GB',resources.describe(hardware,plan))

    def test_low_memory_gate_can_be_cancelled_without_starting_work(self):
        runner=engine.Engine(ROOT,None,threading.Event())
        runner.resource_plan={'memory_reserve_bytes':2*resources.GIB}
        with patch('resources.memory_status',return_value={'available':512*1024**2}):
            runner.cancel.set()
            with self.assertRaises(engine.Cancelled):runner._memory_gate()
        runner.cancel.clear()
        with patch('resources.memory_status',side_effect=[{'available':512*1024**2},{'available':4*resources.GIB}]):
            runner._memory_gate()


if __name__=='__main__':unittest.main()
