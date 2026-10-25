"""Audit a pristine portable directory before producing public artifacts."""
from pathlib import Path
import argparse,hashlib,json,re,sys,types

PRIVATE_DIRS={'.local','.git','settings','exports','downloads','cache','runs','work','__pycache__'}
PRIVATE_FILES={'profiles.json','works.json','api-usage.json','project.json','codex-rejected-cas.pem'}
MEDIA_SUFFIXES={'.mp4','.mkv','.webm','.avi','.mov','.wav','.mp3','.srt','.ass','.pdb','.key','.pfx','.p12'}
TEXT_SUFFIXES={'.py','.txt','.md','.rst','.json','.yaml','.yml','.toml','.ini','.html'}
TOKEN=re.compile(rb'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def audit(folder,private_markers=()):
    folder=Path(folder).resolve();findings=[];inventory=[]
    markers=[x.encode(encoding) for x in private_markers for encoding in ('utf-8','utf-16-le')]
    for file in sorted(folder.rglob('*')):
        if file.is_symlink():findings.append({'file':str(file.relative_to(folder)),'rule':'symlink'});continue
        if not file.is_file():continue
        relative=file.relative_to(folder);name=relative.as_posix()
        if PRIVATE_DIRS.intersection(relative.parts) or file.name in PRIVATE_FILES or file.suffix.lower() in MEDIA_SUFFIXES:
            findings.append({'file':name,'rule':'private_or_debug_artifact'})
        if file.suffix.lower()=='.pem' and name!='_internal/certifi/cacert.pem':
            findings.append({'file':name,'rule':'unexpected_certificate'})
        # Scan in bounded blocks, including overlapping bytes at boundaries.
        previous=b''
        with file.open('rb') as stream:
            while block:=stream.read(1024*1024):
                data=previous+block
                if any(marker and marker in data for marker in markers):
                    findings.append({'file':name,'rule':'private_build_path'});break
                if file.suffix.lower() in TEXT_SUFFIXES and TOKEN.search(data):
                    findings.append({'file':name,'rule':'credential_pattern'});break
                previous=data[-512:]
        inventory.append({'path':name,'bytes':file.stat().st_size,'sha256':digest(file)})
    required=['BilingualVideo.exe','engine-worker.exe','bin/ffmpeg.exe','bin/node.exe','LICENSE','THIRD-PARTY-NOTICES.md','licenses/index.json','BUILD-INFO.json']
    for name in required:
        if not (folder/name).is_file():findings.append({'file':name,'rule':'required_file_missing'})
    manifest=json.loads((folder/'app/assets.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path=(folder/entry['path']).resolve()
        if not path.is_relative_to(folder):
            findings.append({'file':entry['path'],'rule':'unsafe_model_path'});continue
        if not path.is_file() or path.stat().st_size!=entry['bytes'] or digest(path)!=entry['sha256']:
            findings.append({'file':entry['path'],'rule':'model_integrity'})
    licenses=json.loads((folder/'licenses/index.json').read_text(encoding='utf-8'))
    for package in licenses['packages']:
        if not package['license_files']:
            findings.append({'file':package['name'],'rule':'missing_license_material'})
    return {'passed':not findings,'files':len(inventory),'bytes':sum(x['bytes'] for x in inventory),
            'findings':findings,'inventory':inventory,
            'scope':'Checks archive inputs, known private build markers, model integrity and license-material presence; not a legal opinion or malware certification.'}

def inspect_python_archives(folder,private_markers):
    """Inspect compressed code objects as well as uncompressed PE contents."""
    from PyInstaller.archive.readers import CArchiveReader
    findings=[];modules=0
    def walk(code,name):
        if not isinstance(code,types.CodeType):return
        if any(marker.casefold() in code.co_filename.casefold() for marker in private_markers):
            findings.append({'file':name,'rule':'private_code_filename'})
        for constant in code.co_consts:
            if isinstance(constant,types.CodeType):walk(constant,name)
            elif isinstance(constant,str) and any(marker in constant for marker in private_markers):
                findings.append({'file':name,'rule':'private_code_constant'})
    import marshal
    import zipfile
    base_library=Path(folder)/'_internal/base_library.zip'
    if base_library.is_file():
        with zipfile.ZipFile(base_library) as archive:
            for name in archive.namelist():
                if name.endswith('.pyc'):
                    walk(marshal.loads(archive.read(name)[16:]),'base_library.zip:'+name);modules+=1
    for executable in ('BilingualVideo.exe','engine-worker.exe'):
        archive=CArchiveReader(str(Path(folder)/executable))
        for name,entry in archive.toc.items():
            if entry[-1]=='s':walk(marshal.loads(archive.extract(name)),executable+':'+name)
            if entry[-1]=='z':
                pyz=archive.open_embedded_archive(name)
                for module,data in pyz.toc.items():
                    value=pyz.extract(module)
                    if isinstance(value,types.CodeType):walk(value,executable+':'+module);modules+=1
    return {'passed':not findings,'modules_checked':modules,'findings':findings}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--private-marker',action='append',default=[])
    args=parser.parse_args();report=audit(args.folder,args.private_marker)
    report['compressed_python']=inspect_python_archives(args.folder,args.private_marker)
    report['passed']=report['passed'] and report['compressed_python']['passed']
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','files','bytes','findings')},ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
