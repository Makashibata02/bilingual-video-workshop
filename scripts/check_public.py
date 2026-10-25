"""Audit an explicit source allowlist; never print matched secrets."""
from pathlib import Path,PurePosixPath
import argparse,json,os,re,shutil,subprocess,tempfile

ROOT=Path(__file__).resolve().parents[1]
FAKE_VALUES={'fake','fake-key','fake-secret','first-fake-secret','second-fake-secret','second-key','sensitive-test-key-never-write'}
PRIVATE_PARTS={'.local','.venv','outputs','runs','work','settings','exports','downloads','models','bin','_internal','validation','__pycache__'}
PRIVATE_SUFFIXES={'.pem','.crt','.key','.pfx','.p12','.exe','.dll','.pyd','.mp4','.mkv','.webm','.wav','.mp3','.zip','.onnx','.bin','.pt','.log','.pyc'}
RULES={
    'credential_token':re.compile(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b'),
    'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'personal_absolute_path':re.compile(r'(?i)\b[A-Z]:[\\/](?!Windows\b)[^\s\"\x27]+|/(?:Users|home)/[^/\s]+'),
}
ASSIGNMENT=re.compile(r'''(?im)\b(?:api[_-]?key|password|secret|access[_-]?token)["']?\s*[:=]\s*["']([^"'\n]+)["']''')

def private_path(name):
    p=PurePosixPath(name)
    return p.is_absolute() or '..' in p.parts or any(x in PRIVATE_PARTS for x in p.parts) or p.suffix.lower() in PRIVATE_SUFFIXES or p.name in ('profiles.json','profiles.tmp','.env') or p.name.startswith('.env.')

def scan_text(name,text):
    findings=[]
    for label,pattern in RULES.items():
        for match in pattern.finditer(text):findings.append({'file':name,'line':text.count('\n',0,match.start())+1,'rule':label})
    for match in ASSIGNMENT.finditer(text):
        value=match.group(1)
        if len(value)>=8 and value not in FAKE_VALUES and not any(c in value for c in '{}[]'):
            findings.append({'file':name,'line':text.count('\n',0,match.start())+1,'rule':'literal_credential_assignment'})
    return findings

def allowed_files():
    files=json.loads((ROOT/'scripts/public-files.json').read_text(encoding='utf-8'))['files']
    if len(files)!=len(set(files)):raise ValueError('Duplicate public manifest entries')
    return files

def audit(git_mode=None,gitleaks=False):
    allowed=allowed_files();findings=[]
    selected=allowed
    if git_mode:
        args=['git','-C',str(ROOT),'diff','--cached','--name-only','--diff-filter=ACMR','-z'] if git_mode=='staged' else ['git','-C',str(ROOT),'ls-files','-z']
        p=subprocess.run(args,capture_output=True)
        if p.returncode:raise RuntimeError('This check requires a Git repository.')
        selected=[x for x in p.stdout.decode('utf-8').split('\0') if x]
        findings.extend({'file':name,'rule':'not_in_public_allowlist'} for name in selected if name not in allowed)
    for name in selected:
        if private_path(name):findings.append({'file':name,'rule':'private_file_type'});continue
        p=ROOT/name
        if not p.is_file():findings.append({'file':name,'rule':'missing_file'});continue
        if p.is_symlink() or os.path.isjunction(p) or not p.resolve().is_relative_to(ROOT):
            findings.append({'file':name,'rule':'external_or_linked_file'});continue
        data=p.read_bytes()
        if len(data)>2_000_000:findings.append({'file':name,'rule':'unexpected_large_file'});continue
        try:findings.extend(scan_text(name,data.decode('utf-8-sig')))
        except UnicodeDecodeError:findings.append({'file':name,'rule':'non_text_public_file'})
        if git_mode=='staged':
            staged=subprocess.run(['git','-C',str(ROOT),'show',':'+name],capture_output=True)
            # Compare through Git's clean filters so CRLF on Windows does not
            # reject an otherwise identical staged file.
            reviewed=subprocess.run(['git','-C',str(ROOT),'hash-object','--path='+name,'--',name],capture_output=True)
            indexed=subprocess.run(['git','-C',str(ROOT),'rev-parse',':'+name],capture_output=True)
            if staged.returncode or reviewed.returncode or indexed.returncode or reviewed.stdout.strip()!=indexed.stdout.strip():
                findings.append({'file':name,'rule':'staged_bytes_differ_from_reviewed_file'})
            elif staged.stdout!=data:
                try:findings.extend(scan_text(name,staged.stdout.decode('utf-8-sig')))
                except UnicodeDecodeError:findings.append({'file':name,'rule':'non_text_staged_file'})
    reports=ROOT/'.local/reports';reports.mkdir(parents=True,exist_ok=True)
    result={'passed':not findings,'checked_files':len(selected),'findings':findings,'gitleaks':'not requested'}
    if not findings and gitleaks:
        name='gitleaks.exe' if os.name=='nt' else 'gitleaks'
        scanner=shutil.which('gitleaks') or str(ROOT/'.local/tools/gitleaks'/name)
        if not Path(scanner).is_file():raise RuntimeError('Install Gitleaks first: python scripts/install_gitleaks.py')
        with tempfile.TemporaryDirectory(dir=ROOT/'.local',prefix='audit-') as temp:
            stage=Path(temp)
            for relative in selected:
                target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
            p=subprocess.run([scanner,'dir',str(stage),'--config',str(ROOT/'.gitleaks.toml'),'--redact=100','--no-banner',
                              '--report-format','json','--report-path',str(reports/'gitleaks.json')],capture_output=True,text=True)
            result['gitleaks']='passed' if p.returncode==0 else 'failed'
            result['passed']=p.returncode==0
            # Gitleaks output/report stays local and redacted, never in public artifacts.
            (reports/'gitleaks-output.txt').write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
    (reports/'source-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group()
    group.add_argument('--staged',action='store_true');group.add_argument('--tracked',action='store_true')
    parser.add_argument('--gitleaks',action='store_true');args=parser.parse_args()
    result=audit('staged' if args.staged else 'tracked' if args.tracked else None,args.gitleaks)
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['passed'] else 1)
