"""Download destination flow and thin-footer content/geometry regressions."""
from pathlib import Path
import tempfile,json,threading,unittest,sys
import os,shutil
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import layout,downloads

ROOT=Path(__file__).resolve().parents[1]

class RefinementTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.local/test-tmp/layout';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_custom_folder_names_never_overwrite_existing_files(self):
        a=downloads.reserve_download_folder(self.root/'自选位置','我的演讲 100%')
        (a/'原文件.txt').write_text('keep',encoding='utf-8')
        b=downloads.reserve_download_folder(self.root/'自选位置','我的演讲 100%')
        self.assertEqual(a.name,'我的演讲 100%');self.assertEqual(b.name,'我的演讲 100%_02')
        self.assertEqual((a/'原文件.txt').read_text(encoding='utf-8'),'keep')
        self.assertEqual(a.parent,self.root/'自选位置')

    def test_folder_traversal_and_windows_reserved_names_are_rejected(self):
        for value in ['','..','../outside','a/b',r'a\b','CON','NUL.mp4','COM1','x:y','a*','bad.']:
            with self.assertRaises(ValueError,msg=value):downloads.reserve_download_folder(self.root,value)
        self.assertEqual(downloads.download_name('我想看的讲座 [完整] 100%'),'我想看的讲座 [完整] 100%')

    def test_download_template_keeps_percent_literal_in_directory_and_name(self):
        fake_ff=self.root/'ffmpeg.exe';fake_ff.touch();folder=self.root/'位置 100%';folder.mkdir()
        captured={}
        class FakeYDL:
            def __init__(self,options):captured.update(options)
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def extract_info(self,url,download=True):
                (folder/'讲座 100%.mp4').write_bytes(b'fake fixture')
                return {'title':'fixture','id':'test','width':1280,'height':720}
        with patch('yt_dlp.YoutubeDL',FakeYDL),patch('engine._worker_emit') as emit:
            downloads.download_worker({'url':'https://youtu.be/example','folder':str(folder),'filename':'讲座 100%','ffmpeg':str(fake_ff)})
            self.assertEqual(captured['outtmpl'],str(folder/'讲座 100%').replace('%','%%')+'.%(ext)s')
            self.assertEqual(emit.call_args.args[0]['path'],str(folder/'讲座 100%.mp4'))

    def test_portable_download_uses_bundled_node_without_system_install(self):
        ffmpeg=self.root/'ffmpeg.exe';ffmpeg.touch()
        node=self.root/'node.exe';node.touch()
        captured={}
        class LocalYDL:
            def __init__(self,options):captured.update(options)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def extract_info(self,*args,**kwargs):
                (self_root/'fixture.mp4').write_bytes(b'fixture')
                return {'title':'fixture','id':'fixture'}
        self_root=self.root
        with patch('yt_dlp.YoutubeDL',LocalYDL),patch('engine._worker_emit'),patch('downloads.shutil.which',return_value=None):
            downloads.download_worker({'url':'https://youtu.be/example','folder':str(self.root),'filename':'fixture','ffmpeg':str(ffmpeg)})
        self.assertEqual(captured['js_runtimes']['node']['path'],str(node))

    def test_portable_font_fallback_without_system_font_installation(self):
        fixture=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts/arial.ttf'
        if not fixture.is_file():self.skipTest('Windows fixture font is unavailable')
        fonts=self.root/'fonts';fonts.mkdir()
        for name in ('NotoSansCJKsc-Regular.otf','NotoSansCJKjp-Regular.otf'):shutil.copy2(fixture,fonts/name)
        with patch.dict(os.environ,{'WINDIR':str(self.root/'no-system-fonts')}),patch('layout.bundled_font_folder',return_value=fonts):
            self.assertTrue(layout.font_at(18).getlength('fixture')>0)
            self.assertEqual(Path(layout.japanese_font('fixture')['path']).parent,fonts)
            header='\n'.join(layout.ass_header(640,418,'Microsoft YaHei'))
            self.assertIn('Arial',header)

    def test_slim_footer_keeps_font_sizes_and_all_long_text(self):
        en='A conditional statement remains valid only if '+('the channel stays constant and the observations remain independent. '*10)
        zh='这个结论成立的条件是'+('信道保持不变，而且不同观测之间相互独立。'*18)
        cue={'start':0,'end':40,'text':en}
        for w,h,expected in [(640,360,58),(1280,720,76),(1920,1080,104)]:
            path=self.root/f'{w}.ass'
            self.assertEqual(layout.compact_ass(path,[cue],[zh],w,h),expected)
            plan=json.loads((self.root/'subtitle-layout.json').read_text(encoding='utf-8'))
            self.assertEqual(plan['maximum_language_lines'],[1,1])
            self.assertEqual(plan['subtitle_sizes'],[max(18,round(w*.021)),max(15,round(w*.0165))])
            self.assertEqual(plan['original_frame_rect'],[0,0,w,h])
            lines=[x for x in path.read_text(encoding='utf-8-sig').splitlines() if x.startswith('Dialogue:')]
            self.assertTrue(all(r'\N' not in x for x in lines))
            texts=[x.rsplit('}',1)[-1] for x in lines]
            self.assertEqual(''.join(''.join(texts[::2]).split()),''.join(zh.split()))
            self.assertEqual(''.join(''.join(texts[1::2]).split()),''.join(en.split()))

    def test_ppt_uses_thinner_footer_without_shifting_or_scaling_original(self):
        from engine import parse_srt
        source=ROOT/'tests/fixtures'
        cues=parse_srt((source/'sample.en.srt').read_text(encoding='utf-8-sig'))
        zh=[x['text'] for x in parse_srt((source/'sample.zh.srt').read_text(encoding='utf-8-sig'))]
        data=json.loads((source/'slides.json').read_text(encoding='utf-8'))
        (self.root/'ppt').mkdir()
        plan=layout.presentation(self.root/'bilingual.ass',cues,zh,data,self.root/'ppt')
        self.assertEqual(plan['original_frame_rect'],[288,0,1280,720])
        self.assertEqual(plan['canvas_height'],800);self.assertEqual(plan['subtitle_band_height'],80)
        self.assertEqual(plan['maximum_language_lines'],[1,1]);self.assertFalse(plan['layout_warnings'])

    def test_download_dialog_passes_selected_parent_and_name_to_worker(self):
        from gui import BilingualApp
        app=BilingualApp(app_root=self.root);received=[];errors=[]
        def descendants(w):
            return [w]+[q for child in w.winfo_children() for q in descendants(child)]
        def fake_worker(_self,kind,payload,callback):
            received.append((kind,payload));p=Path(payload['folder'])/(payload['filename']+'.mp4');p.write_bytes(b'test')
            callback({'type':'download_done','path':str(p),'width':1280,'height':720})
        try:
            app._download_dialog();dialog=app.download_window;app.update()
            widgets=descendants(dialog)
            for widget_name,text in [('download_url','https://youtu.be/example'),('download_name','我的讲座')]:
                widget=next(x for x in widgets if x.winfo_name()==widget_name);widget.delete(0,'end');widget.insert(0,text)
            parent=self.root/'自己选的位置'
            with patch('tkinter.filedialog.askdirectory',return_value=str(parent)),patch('engine.Engine._worker',fake_worker),patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)):
                next(w for w in widgets if w.winfo_class()=='TButton' and w.cget('text')=='选择文件夹').invoke()
                next(w for w in widgets if w.winfo_class()=='TButton' and w.cget('text')=='下载').invoke()
                def check():
                    if received and app.download_cancel is None:app.quit()
                    else:app.after(25,check)
                app.after(50,check);app.after(4000,app.quit);app.mainloop()
            self.assertFalse(errors);self.assertEqual(received[0][0],'download')
            self.assertEqual(Path(received[0][1]['folder']),parent/'我的讲座')
            self.assertEqual(received[0][1]['filename'],'我的讲座')
            self.assertTrue((parent/'我的讲座/我的讲座.mp4').is_file());self.assertIsNone(app.download_cancel)
        finally:
            for timer in app.tk.call('after','info'):app.after_cancel(timer)
            app.destroy()

if __name__=='__main__':unittest.main(verbosity=2)
