from pathlib import Path
import json,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_public import scan_text,private_path,allowed_files
import check_public

class PublicationTests(unittest.TestCase):
    def test_private_files_are_blocked_even_if_force_added(self):
        for name in ['.local/runtime/settings/profiles.json','app/settings/profiles.json','tests/secret.pem','app/example.mp4','../escape.py','outputs/app/main.py']:
            self.assertTrue(private_path(name),name)
        self.assertFalse(private_path('tests/fixtures/sample.en.srt'))
    def test_secret_reports_contain_only_file_and_rule_not_the_value(self):
        token='sk-'+'q9Xr4H7j0M2n8P3z6V5w1T0y9U8k7L6c5B4a'
        findings=scan_text('example.py','api_key = '+repr(token))
        self.assertTrue(findings);self.assertNotIn(token,repr(findings))
    def test_personal_paths_are_blocked_but_system_font_path_is_allowed(self):
        text='E:'+chr(92)+'private'+chr(92)+'project'
        self.assertTrue(scan_text('example.py',text))
        self.assertFalse(scan_text('example.py','C:'+chr(92)+'Windows'))
    def test_manifest_contains_only_existing_public_text_files(self):
        for name in allowed_files():
            self.assertFalse(private_path(name),name)
            self.assertTrue((ROOT/name).is_file(),name)

    @unittest.skipUnless(shutil.which('git'),'Git is needed to exercise the commit guard')
    def test_staged_guard_handles_crlf_and_rejects_unreviewed_and_private_files(self):
        base=ROOT/'.local/test-tmp/publication';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temp:
            repo=Path(temp);(repo/'scripts').mkdir()
            (repo/'scripts/public-files.json').write_text(json.dumps({'files':['sample.py']}),encoding='utf-8')
            (repo/'.gitattributes').write_text('*.py text eol=lf\n',encoding='utf-8')
            sample=repo/'sample.py';sample.write_bytes(b'print("example")\r\n')
            def git(*args):
                subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
            git('init','--quiet');git('add','sample.py')
            with patch.object(check_public,'ROOT',repo):
                self.assertTrue(check_public.audit('staged')['passed'])
                sample.write_bytes(b'print("changed after staging")\r\n')
                self.assertIn('staged_bytes_differ_from_reviewed_file',
                              [x['rule'] for x in check_public.audit('staged')['findings']])
                git('add','sample.py')
                (repo/'settings').mkdir();(repo/'settings/profiles.json').write_text('{}',encoding='utf-8')
                git('add','--force','settings/profiles.json')
                self.assertIn('private_file_type',
                              [x['rule'] for x in check_public.audit('staged')['findings']])

if __name__=='__main__':unittest.main()
