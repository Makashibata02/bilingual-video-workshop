"""Assemble a new, empty portable app from a fresh build and verified assets."""
from pathlib import Path
import argparse,importlib.metadata as metadata,json,shutil,sys,hashlib,re

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.9.5'
def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def assemble(build,runtime,materials,ffmpeg,destination):
    build=Path(build).resolve();runtime=Path(runtime).resolve();materials=Path(materials).resolve()
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Destination must be a new directory; never package an existing installation.')
    destination.mkdir(parents=True)
    for name in ('BilingualVideo.exe','engine-worker.exe'):
        shutil.copy2(build/name,destination/name)
    shutil.copytree(build/'_internal',destination/'_internal',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo','*.pdb','opencv_videoio_ffmpeg*.dll'))
    shutil.copytree(ROOT/'app',destination/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(ROOT/'scripts/assets.json',destination/'app/assets.json')
    for name in ('LICENSE','NOTICE.md','PRIVACY.md','README.md'):
        shutil.copy2(ROOT/name,destination/name)
    shutil.copytree(ROOT/'docs',destination/'docs')
    manifest=json.loads((ROOT/'scripts/assets.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        source=runtime/entry['path']
        if not source.is_file() or source.stat().st_size!=entry['bytes'] or sha(source)!=entry['sha256']:
            raise ValueError('Missing or altered public model asset: '+entry['path'])
        target=(destination/entry['path']).resolve()
        if not target.is_relative_to(destination) or not Path(entry['path']).parts[0]=='models':raise ValueError('Unsafe model path')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (destination/'bin').mkdir()
    shutil.copy2(ffmpeg,destination/'bin/ffmpeg.exe')
    shutil.copy2(materials/'node/node.exe',destination/'bin/node.exe')
    (destination/'fonts').mkdir()
    for name in ('NotoSansCJKsc-Regular.otf','NotoSansCJKjp-Regular.otf','LICENSE'):
        shutil.copy2(materials/'fonts'/name,destination/'fonts'/name)
    licenses=destination/'licenses';licenses.mkdir()
    packages=[]
    supplemental=materials/'supplemental-licenses'
    for distribution in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=distribution.metadata['Name'];version=distribution.version;files=[]
        target=licenses/re.sub('[^A-Za-z0-9_.-]','_',name);target.mkdir()
        for item in distribution.files or ():
            parts=item.parts
            if '__pycache__' in parts or item.suffix in ('.pyc','.pyo'):continue
            if not any(any(term in p.lower() for term in ('license','copying','notice')) for p in parts):continue
            source=Path(distribution.locate_file(item))
            if not source.is_file() or source.suffix.lower() in ('.dll','.pyd','.exe','.so','.onnx'):continue
            # Preserve nested vendor license names without retaining local paths.
            relative='/'.join(parts);filename=re.sub('[^A-Za-z0-9_.-]','_',relative)
            output=target/filename;shutil.copy2(source,output);files.append(output.relative_to(destination).as_posix())
        if (supplemental/name).is_dir():
            for source in (supplemental/name).rglob('*'):
                if not source.is_file():continue
                output=target/source.name;shutil.copy2(source,output);files.append(output.relative_to(destination).as_posix())
        if not files:raise ValueError('No license material for '+name)
        expression=distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See preserved upstream license files'
        packages.append({'name':name,'version':version,'declared_license':expression[:300],'license_files':sorted(set(files)),'source_project_urls':distribution.metadata.get_all('Project-URL',[])})
    for directory in ('runtime','models','media','node','fonts'):
        (licenses/directory).mkdir(exist_ok=True)
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',licenses/'runtime/PYTHON-LICENSE.txt')
    for source in (materials/'runtime-licenses').glob('*'):shutil.copy2(source,licenses/'runtime'/source.name)
    shutil.copy2(materials/'fonts/WHISPER-LICENSE',licenses/'models/WHISPER-LICENSE.txt')
    shutil.copy2(materials/'fonts/PADDLEOCR-LICENSE',licenses/'models/PADDLEOCR-LICENSE.txt')
    shutil.copy2(materials/'fonts/CC-BY-4.0.txt',licenses/'models/CC-BY-4.0.txt')
    shutil.copy2(runtime/'models/argos/translate-en_zh-1_9/README.md',licenses/'models/ARGOS-ATTRIBUTION.md')
    shutil.copy2(materials/'node/LICENSE',licenses/'node/LICENSE.txt')
    shutil.copy2(materials/'fonts/LICENSE',licenses/'fonts/OFL.txt')
    shutil.copytree(materials/'media-licenses',licenses/'media',dirs_exist_ok=True)
    index={'version':VERSION,'packages':packages,'components':['CPython / Tcl / Tk / OpenSSL','FFmpeg / x264 / libass / FreeType / FriBidi / HarfBuzz','PyAV FFmpeg runtime and linked libraries','Noto Sans CJK SC / JP','Node.js','Whisper base / small','Argos English-Chinese','RapidOCR / PaddleOCR'],
           'corresponding_source_asset':'BilingualVideo-1.9.5-third-party-sources.zip',
           'notice':'Metadata describes the Python wrapper only; linked native libraries retain their own terms. Read the full preserved license files.'}
    (licenses/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
    info={'version':VERSION,'platform':'windows-x64','python':sys.version.split()[0],
          'interpreter':json.loads((materials/'interpreter-provenance.json').read_text(encoding='utf-8')),
          'node':json.loads((materials/'node-provenance.json').read_text(encoding='utf-8')),
          'fonts':json.loads((materials/'fonts/provenance.json').read_text(encoding='utf-8')),
          'application_source':'https://github.com/Makashibata02/bilingual-video-workshop',
          'release':'https://github.com/Makashibata02/bilingual-video-workshop/releases/tag/v1.9.5',
          'code_sha256':{f.name:sha(f) for f in (ROOT/'app').glob('*.py')},
          'models_verified':len(manifest['files']),'personal_data_copied':False,
          'ffmpeg_sha256':sha(destination/'bin/ffmpeg.exe'),'node_sha256':sha(destination/'bin/node.exe')}
    (destination/'BUILD-INFO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(materials/'THIRD-PARTY-NOTICES.md',destination/'THIRD-PARTY-NOTICES.md')
    (destination/'开始使用.txt').write_text('双语视频工坊 1.9.5 · Windows 64位便携版\n\n1. 完整解压，不要只复制exe。\n2. 双击 BilingualVideo.exe，无需安装Python或模型。\n3. 添加视频 → 选择模式/翻译方案 → 可选选择片段 → 开始选中。\n\n免费网页接口需要网络，可能限流。Argos仅支持英中离线翻译。\nAPI方案需自行填写密钥；全局理解和精修可能计费，不会暗中切换付费。\n本包初始不含任何人的密钥、配置、作品资料或视频。\n\nsettings、cache、exports、downloads是使用后生成的本地资料，请勿上传或分享。\n完整来源、依赖和许可见README.md、THIRD-PARTY-NOTICES.md、licenses目录与同一Release的对应源码附件。\n',encoding='utf-8')
    (destination/'启动工坊.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "" "BilingualVideo.exe"\n',encoding='ascii')
    return destination

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--materials',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    args=p.parse_args();output=assemble(args.build,args.runtime,args.materials,args.ffmpeg,args.destination)
    print('Pristine portable directory assembled: '+str(output))
