from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root=Path(SPECPATH).resolve().parent
app=root/'app'
datas=[];binaries=[];hidden=[]
for package in ['faster_whisper','ctranslate2','sentencepiece','av','onnxruntime','tokenizers',
                'rapidocr_onnxruntime','PIL','fontTools','cv2','pyclipper','shapely','yt_dlp','yt_dlp_ejs']:
    d,b,h=collect_all(package)
    datas.extend(d);binaries.extend(b);hidden.extend(h)

# No machine-specific certificates, credentials, models or user files are collected.
a=Analysis([str(app/'main.py')],pathex=[str(app)],binaries=binaries,datas=datas,
           hiddenimports=hidden,excludes=['pytest','IPython','matplotlib','torch','tensorflow','imageio_ffmpeg'],
           noarchive=False)
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='BilingualVideo',console=False)
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='engine-worker',console=True)
coll=COLLECT(gui,worker,a.binaries,a.datas,name='BilingualVideo')
