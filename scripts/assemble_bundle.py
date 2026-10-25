"""Copy source/license and runtime assets only, never user settings or exports."""
from pathlib import Path
import argparse,shutil,json

ROOT=Path(__file__).resolve().parents[1]

def assemble(include_models=False):
    from prepare_runtime import digest,verified
    bundle=ROOT/'dist/BilingualVideo';runtime=ROOT/'.local/runtime'
    if not (bundle/'BilingualVideo.exe').is_file():raise RuntimeError('Build the executables first.')
    shutil.copytree(ROOT/'app',bundle/'app',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'scripts/assets.json',bundle/'app/assets.json')
    for name in ['LICENSE','NOTICE.md','PRIVACY.md','README.md']:
        shutil.copy2(ROOT/name,bundle/name)
    (bundle/'docs').mkdir(exist_ok=True)
    for name in ['ANIME.md','ARCHITECTURE.md','RELEASE.md','VALIDATION.md']:
        shutil.copy2(ROOT/'docs'/name,bundle/'docs'/name)
    executable=runtime/'bin/ffmpeg.exe'
    if not executable.is_file():raise RuntimeError('Prepare the runtime before assembling the bundle.')
    (bundle/'bin').mkdir(exist_ok=True);shutil.copy2(executable,bundle/'bin/ffmpeg.exe')
    if include_models:
        manifest=json.loads((ROOT/'scripts/assets.json').read_text(encoding='utf-8'))
        small_ready=all(verified(runtime/e['path'],e) for e in manifest['files'] if e['group']=='asr-small')
        for entry in manifest['files']:
            if entry['group']=='asr-small' and not small_ready:continue
            source=runtime/entry['path']
            if not verified(source,entry):raise RuntimeError('Missing or altered model: '+entry['path'])
            target=bundle/entry['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if not small_ready:print('Optional small model omitted; users can explicitly prepare it from the app.')
    # An artifact is not approved for sharing just because compilation succeeded.
    print('Bundle assembled locally. Review dependency licenses and audit the binary bundle separately before sharing.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--include-models',action='store_true')
    assemble(parser.parse_args().include_models)
