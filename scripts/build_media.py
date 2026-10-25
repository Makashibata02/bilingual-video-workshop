"""Rebuild the release media executable; see docs/PORTABLE.md."""
from pathlib import Path
import urllib.request,hashlib,json,tarfile,zipfile,subprocess,os,time,sys
import argparse,ctypes
parser=argparse.ArgumentParser(description='Build the portable FFmpeg from preserved, hash-pinned sources.')
parser.add_argument('--work',type=Path,required=True)
parser.add_argument('--toolchain',type=Path,required=True,help='MinGW-w64 bin directory, including gcc, gmake, nasm, cmake and ninja')
parser.add_argument('--git',type=Path,required=True,help='Git for Windows installation directory')
parser.add_argument('--pkg-config',type=Path,required=True)
parser.add_argument('--perl',type=Path,help='Required only for the Perl pkg-config implementation')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1];base=args.work.resolve()
if not str(base).isascii() or ' ' in str(base):raise ValueError('Use an ASCII work path without spaces for the native build tools.')
def posix(path):return '/'+str(path.resolve()).replace(chr(92),'/').replace(':','',1)
short=ctypes.create_unicode_buffer(32768)
if not ctypes.windll.kernel32.GetShortPathNameW(str(args.git/'usr/bin/sh.exe'),short,len(short)):raise RuntimeError('Cannot determine a space-free shell path.')
make_shell=short.value.replace(chr(92),'/')
sources=base/'sources';sources.mkdir(parents=True,exist_ok=True)

records=[]
def fetch(name,url,expected=None):
 path=sources/name
 if not path.exists():
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'BilingualVideo release source preparation'}),timeout=90) as response,path.open('wb') as output:
   while block:=response.read(1024*1024):output.write(block)
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 if expected:assert digest==expected,(name,digest)
 records.append({'name':name,'url':url,'sha256':digest,'bytes':path.stat().st_size})
 return path
items=[
 ('ffmpeg','ffmpeg-n9.0.2.tar.gz','https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n9.0.2',None),
 ('x264','x264-31e19f9.tar.gz','https://codeload.github.com/mirror/x264/tar.gz/31e19f92f00c7003fa115047ce50978bc98c3a0d',None),
 ('freetype','freetype-2.13.3.tar.gz','https://codeload.github.com/freetype/freetype/tar.gz/refs/tags/VER-2-13-3',None),
 ('fribidi','fribidi-1.0.16.tar.xz','https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz',None),
 ('harfbuzz','harfbuzz-10.4.0.tar.xz','https://github.com/harfbuzz/harfbuzz/releases/download/10.4.0/harfbuzz-10.4.0.tar.xz',None),
 ('libass','libass-0.17.3.tar.xz','https://github.com/libass/libass/releases/download/0.17.3/libass-0.17.3.tar.xz',None),
 ('dav1d','dav1d-1.5.4-git.tar.gz','https://codeload.github.com/videolan/dav1d/tar.gz/refs/tags/1.5.4',None),
 ('zlib','zlib-1.3.1.tar.gz','https://codeload.github.com/madler/zlib/tar.gz/refs/tags/v1.3.1',None)]
SOURCE_HASHES={'ffmpeg-n9.0.2.tar.gz': '6e374ed621e48faa40639307dff48ba6fe574a509977956d2cce9669b7cc27e9', 'x264-31e19f9.tar.gz': 'd053c9d86988d6bc78237ca5205865c5ddf99c98ef4cd9927eec8f6d388f6dd9', 'freetype-2.13.3.tar.gz': 'bc5c898e4756d373e0d991bab053036c5eb2aa7c0d5c67e8662ddc6da40c4103', 'fribidi-1.0.16.tar.xz': '1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c', 'harfbuzz-10.4.0.tar.xz': '480b6d25014169300669aa1fc39fb356c142d5028324ea52b3a27648b9beaad8', 'libass-0.17.3.tar.xz': 'eae425da50f0015c21f7b3a9c7262a910f0218af469e22e2931462fed3c50959', 'dav1d-1.5.4-git.tar.gz': 'a1d5b63d2d38ec9bd03acf643caa51fa22edd1e89c5a109c4807717216bbec07', 'zlib-1.3.1.tar.gz': '17e88863f3600672ab49182f217281b6fc4d3c762bde361935e436a95214d05c'}
for name,filename,url,expected in items:
 expected=expected or SOURCE_HASHES[filename]
 archive=fetch(filename,url,expected);dest=base/'src'/name;dest.mkdir(parents=True,exist_ok=True)
 if not list(dest.iterdir()):
  temp=base/'unpack'/name;temp.mkdir(parents=True,exist_ok=True)
  with tarfile.open(archive) as tar:tar.extractall(temp,filter='data')
  children=list(temp.iterdir());assert len(children)==1 and children[0].is_dir()
  for file in children[0].iterdir():file.rename(dest/file.name)
 print('Source ready: '+name,flush=True)
(base/'sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
env=dict(os.environ);env['PATH']=str(args.toolchain)+';'+str(args.git/'usr/bin')+';'+env['PATH']
env['CMAKE_BUILD_PARALLEL_LEVEL']='8';env['LC_ALL']='C'
prefix=base/'prefix';prefix.mkdir(exist_ok=True)
flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
def run(args,cwd=None):
 print('Building '+str(cwd or args[0]),flush=True)
 with (base/'compiler-output.log').open('a',encoding='utf-8') as output:
  subprocess.run([str(a) for a in args],cwd=cwd,env=env,check=True,creationflags=flags,stdout=output,stderr=subprocess.STDOUT)
cmake=str(args.toolchain/'cmake.exe')
for name,options in [
 ('freetype',['-DFT_DISABLE_ZLIB=ON','-DFT_DISABLE_BZIP2=ON','-DFT_DISABLE_PNG=ON','-DFT_DISABLE_HARFBUZZ=ON','-DFT_DISABLE_BROTLI=ON']),
 ('harfbuzz',['-DHB_BUILD_UTILS=OFF','-DHB_BUILD_TESTS=OFF','-DHB_HAVE_FREETYPE=OFF','-DHB_HAVE_GLIB=OFF','-DHB_HAVE_ICU=OFF']),('zlib',[])]:
 src=base/'src'/name;build=base/'build'/name
 if (prefix/'lib'/{'freetype':'libfreetype.a','harfbuzz':'libharfbuzz.a','zlib':'libzlibstatic.a'}[name]).is_file():continue
 run([cmake,'-S',src,'-B',build,'-G','Ninja','-DCMAKE_C_COMPILER='+str(args.toolchain/'gcc.exe'),'-DCMAKE_CXX_COMPILER='+str(args.toolchain/'g++.exe'),'-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=OFF','-DCMAKE_INSTALL_PREFIX='+str(prefix),*options])
 run([cmake,'--build',build,'--parallel','8']);run([cmake,'--install',build])
shutil=__import__('shutil')
shutil.copy2(prefix/'lib/libzlibstatic.a',prefix/'lib/libz.a')
dav1d=base/'build/dav1d'
if not dav1d.exists():
 run([sys.executable,'-m','mesonbuild.mesonmain','setup',dav1d,base/'src/dav1d','--prefix='+str(prefix),'--libdir=lib','--default-library=static','--buildtype=release','-Denable_tests=false','-Denable_tools=false'])
run([sys.executable,'-m','mesonbuild.mesonmain','compile','-C',dav1d,'-j','8'])
run([sys.executable,'-m','mesonbuild.mesonmain','install','-C',dav1d])
tools=base/'tools';tools.mkdir(exist_ok=True)
(tools/'make').write_text('#!/bin/sh\nexec '+posix(args.toolchain/'gmake.exe')+' "$@"\n',encoding='utf-8',newline='\n')
(tools/'pkg-config').write_text('#!/bin/sh\nexec '+((posix(args.perl)+' ') if args.perl else '')+posix(args.pkg_config)+' "$@"\n',encoding='utf-8',newline='\n')
# Source scripts are trusted upstream build systems; no commands come from media.
sh=base/'compile-native.sh'
sh.write_text('''#!/bin/bash
set -eu
export PATH="'''+posix(tools)+':'+posix(args.toolchain)+''':/usr/bin:$PATH"
export PKG_CONFIG_LIBDIR="'''+posix(prefix)+'''/lib/pkgconfig"
export LC_ALL=C
export SHELL=sh
export CONFIG_SHELL=/usr/bin/bash
cd "'''+posix(base)+'''"
PREFIX="$(cygpath -m "$(pwd)/prefix")"
cd src/x264
bash configure --prefix="$PREFIX" --enable-static --disable-cli --disable-opencl --disable-lavf --disable-swscale
make SHELL="'''+make_shell+'''" -j8
make SHELL="'''+make_shell+'''" install
cd ../fribidi
bash configure --prefix="$PREFIX" --disable-shared --enable-static --disable-docs
make SHELL="'''+make_shell+'''" -j8
make SHELL="'''+make_shell+'''" install
cd ../libass
ac_cv_header_iconv_h=no bash configure --prefix="$PREFIX" --disable-shared --enable-static --disable-fontconfig --enable-directwrite
make SHELL="'''+make_shell+'''" -j8
make SHELL="'''+make_shell+'''" install
cd ../ffmpeg
# Keep public configure options free of the private absolute build location.
PKG_CONFIG_PATH="$PKG_CONFIG_LIBDIR" bash configure --prefix=/bilingual-video --pkg-config=pkg-config --pkg-config-flags=--static --disable-autodetect --enable-gpl --enable-version3 --enable-libx264 --enable-libass --enable-libdav1d --enable-zlib --disable-iconv --enable-schannel --disable-doc --disable-debug --disable-ffplay --disable-ffprobe --extra-ldflags=-static
make SHELL="'''+make_shell+'''" -j8
mkdir -p ../../bin
cp ffmpeg.exe ../../bin/ffmpeg.exe
''',encoding='utf-8',newline='\n')
run([args.git/'bin/bash.exe',str(sh)])
print('FFmpeg built from preserved sources',flush=True)
