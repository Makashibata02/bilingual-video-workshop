"""Regression tests for saved profiles, real HTTP test calls and optional range UI."""
from pathlib import Path
import json,os,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import engine
from profiles import ProfileStore
from range_picker import time_text,time_value,RangePicker


class FeatureTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/'.local/test-tmp/features';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_named_profiles_survive_restart_with_encrypted_distinct_keys(self):
        store=ProfileStore(self.root)
        a=store.save('DS Flash','https://example.com/v1','ds-flash','first-fake-secret')
        b=store.save('DS Pro','https://example.com/v1','ds-pro','second-fake-secret')
        self.assertNotEqual(a,b)
        raw=store.path.read_text(encoding='utf-8')
        for secret in ('first-fake-secret','second-fake-secret'):self.assertNotIn(secret,raw)
        reopened=ProfileStore(self.root)
        self.assertEqual(reopened.load('DS Flash')['api_key'],'first-fake-secret')
        self.assertEqual(reopened.load('DS Pro')['api_key'],'second-fake-secret')
        self.assertEqual(reopened.code_for('https://example.com/v1','ds-pro'),b)
        reopened.delete('DS Flash');self.assertEqual(reopened.list()[0]['name'],'DS Pro')

    def test_actual_http_translation_test_checks_auth_model_and_reply(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append({'path':self.path,'auth':self.headers.get('Authorization'),'payload':payload})
                if payload['model']=='bad-model':
                    self.send_response(404);self.end_headers();return
                response=json.dumps({'choices':[{'message':{'content':'["信号很清晰。"]'}}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        base=f'http://127.0.0.1:{server.server_port}/v1'
        runner=engine.Engine(self.root,None,threading.Event())
        try:
            for model in ('ds-flash','ds-pro'):
                self.assertEqual(runner.test_translation({'translator':'deepseek','api_base':base,'model_name':model,'api_key':'fake-secret'}),'信号很清晰。')
            with self.assertRaisesRegex(RuntimeError,'404'):
                runner.test_translation({'translator':'deepseek','api_base':base,'model_name':'bad-model','api_key':'fake-secret'})
        finally:server.shutdown();server.server_close();t.join()
        self.assertEqual([r['payload']['model'] for r in received],['ds-flash','ds-pro','bad-model'])
        self.assertTrue(all(r['auth']=='Bearer fake-secret' and r['path']=='/v1/chat/completions' for r in received))

    def test_range_dialog_handles_dragging_and_exact_entry(self):
        import tkinter as tk
        root=tk.Tk();root.geometry('220x80');root.update()
        try:
            p=RangePicker(root,Path('test.mp4'),{'duration':3600,'width':1920,'height':1080})
            p.update();p.a.set('00:10:00.125');p.b.set('00:15:00.250')
            self.assertTrue(p.apply_entries());self.assertEqual(p.start,600.125);self.assertEqual(p.end,900.25)
            event=type('Event',(),{'x':p.left+int((p.right-p.left)*.2)})()
            p.active='start';p.drag(event);self.assertAlmostEqual(p.start,720,delta=8)
            p.accept();self.assertIsNotNone(p.result)
            self.assertEqual(time_value(time_text(900.25)),900.25)
        finally:root.destroy()

    def test_gui_defaults_range_off_and_saved_profiles_load(self):
        from gui import BilingualApp,TRANSLATORS
        store=ProfileStore(self.root/'settings');store.save('DS Flash','https://example.com/v1','ds-flash','fake-key')
        with patch('tkinter.messagebox.showinfo'):
            app=BilingualApp(app_root=self.root)
            try:
                app.update();self.assertFalse(app.clip_enabled.get());self.assertFalse(app.ppt_annotations.get())
                app.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'));app._translator_changed()
                app.profile_name.set('DS Flash');app._load_profile();app.update()
                self.assertEqual(app.model_name.get(),'ds-flash');self.assertEqual(app.api_key.get(),'fake-key')
                self.assertEqual(app._snapshot_options()['profile_code'],store.list()[0]['profile_code'])
                app.profile_name.set('DS Pro');app.model_name.set('ds-pro');app.api_key.set('second-key');app._save_profile()
                self.assertEqual(len(app.profile_store.list()),2)
                self.assertTrue(app.test_button.winfo_exists())
            finally:
                for timer in app.tk.call('after','info'):app.after_cancel(timer)
                app.destroy()

    def test_gui_test_button_returns_result_without_freezing_window(self):
        from gui import BilingualApp,TRANSLATORS
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body=b'{"choices":[{"message":{"content":"[\\\"OK-test-reply\\\"]"}}]}'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        successes=[];errors=[]
        with patch('tkinter.messagebox.showinfo',side_effect=lambda *a,**k:successes.append(a)),patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)):
            app=BilingualApp(app_root=self.root)
            try:
                app.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'));app._translator_changed()
                app.api_base.set(f'http://127.0.0.1:{server.server_port}/v1');app.api_key.set('fake-key');app.model_name.set('ds-pro-test')
                app.after(100,app.test_button.invoke)
                def check():
                    if successes or errors:app.quit()
                    else:app.after(50,check)
                app.after(150,check);app.after(8000,app.quit);app.mainloop()
                self.assertFalse(errors);self.assertTrue(successes);self.assertIn('OK-test-reply',successes[0][1])
                self.assertIsNone(app.test_cancel)
            finally:
                for timer in app.tk.call('after','info'):app.after_cancel(timer)
                app.destroy();server.shutdown();server.server_close();t.join()


if __name__=='__main__':unittest.main(verbosity=2)
