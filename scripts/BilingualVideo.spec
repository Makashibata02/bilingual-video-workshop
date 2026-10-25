from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root=Path(SPECPATH).resolve().parent
app=root/'app'
datas=[];binaries=[];hidden=[]
for package in ['faster_whisper','ctranslate2','sentencepiece','av','onnxruntime','tokenizers',
                'rapidocr_onnxruntime','PIL','fontTools','cv2','pyclipper','shapely','yt_dlp','yt_dlp_ejs']:
    d,b,h=collect_all(package)
    def runtime_file(item):
        path=Path(item[0])
        return not {'tests','test','__pycache__'}.intersection(path.parts) and path.suffix.lower() not in ('.pyc','.pyo','.pdb')
    datas.extend(item for item in d if runtime_file(item))
    binaries.extend(item for item in b if runtime_file(item))
    hidden.extend(name for name in h if '.tests' not in name and '.test_' not in name)

# No machine-specific certificates, credentials, models or user files are collected.
a=Analysis([str(app/'main.py')],pathex=[str(app)],binaries=binaries,datas=datas,
           hiddenimports=hidden,excludes=['pytest','IPython','matplotlib','torch','tensorflow','imageio_ffmpeg'],
           noarchive=False)
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='BilingualVideo',console=False)
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='engine-worker',console=True)
coll=COLLECT(gui,worker,a.binaries,a.datas,name='BilingualVideo')
