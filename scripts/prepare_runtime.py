"""Explicit, hash-checked model preparation; never runs when importing the app."""
from pathlib import Path
import argparse,hashlib,json,shutil,sys,tempfile,zipfile

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def verified(path,entry):
    return path.is_file() and path.stat().st_size==entry['bytes'] and digest(path)==entry['sha256']

def prepare(runtime,download=False,groups=None):
    manifest=json.loads((ROOT/'scripts/assets.json').read_text(encoding='utf-8'))
    groups=set(groups or ['asr','argos','ocr']);entries=[e for e in manifest['files'] if e['group'] in groups]
    missing=[e for e in entries if not verified(runtime/e['path'],e)]
    if missing and not download:
        print(json.dumps({'ready':False,'missing':[e['path'] for e in missing]},ensure_ascii=False))
        return 1
    runtime.mkdir(parents=True,exist_ok=True)
    if missing:
        import requests
        cache=ROOT/'.local/asset-cache';cache.mkdir(parents=True,exist_ok=True)
        archive=None
        def fetch(url,target):
            temp=target.with_suffix(target.suffix+'.part')
            with requests.get(url,stream=True,timeout=(15,120)) as response:
                response.raise_for_status()
                with temp.open('wb') as output:
                    for data in response.iter_content(1024*1024):output.write(data)
            temp.replace(target)
        if any(e['group']=='argos' for e in missing):
            package=cache/'translate-en_zh-1_9.argosmodel'
            if not package.exists():fetch(manifest['argos_archive'],package)
            archive=zipfile.ZipFile(package)
        try:
            for entry in missing:
                target=(runtime/entry['path']).resolve()
                if not target.is_relative_to(runtime.resolve()):raise ValueError('Unsafe asset path')
                target.parent.mkdir(parents=True,exist_ok=True)
                candidate=target.with_suffix(target.suffix+'.download')
                if entry['group']=='argos':
                    # Read only manifest-listed archive members; never extract arbitrary paths.
                    with archive.open(entry['archive_member']) as source,candidate.open('wb') as out:shutil.copyfileobj(source,out)
                else:fetch(entry['url'],candidate)
                if not verified(candidate,entry):
                    candidate.unlink(missing_ok=True)
                    raise RuntimeError('Asset hash mismatch: '+entry['path'])
                candidate.replace(target)
                print('Verified '+entry['path'],flush=True)
        finally:
            if archive:archive.close()
    import imageio_ffmpeg
    executable=runtime/'bin/ffmpeg.exe';executable.parent.mkdir(parents=True,exist_ok=True)
    if not executable.exists():shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),executable)
    print(json.dumps({'ready':True,'verified_model_files':len(entries),'ffmpeg':executable.is_file()}))
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Explicitly download and verify local video runtime assets.')
    parser.add_argument('--download',action='store_true',help='Allow downloads from the official sources recorded in assets.json.')
    parser.add_argument('--runtime',type=Path,default=ROOT/'.local/runtime')
    parser.add_argument('--groups',nargs='+',choices=['asr','asr-small','argos','ocr'])
    args=parser.parse_args()
    raise SystemExit(prepare(args.runtime.resolve(),args.download,args.groups))
