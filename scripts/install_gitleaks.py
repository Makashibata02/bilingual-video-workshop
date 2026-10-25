"""Install a checksum-pinned scanner into ignored local tools, never system PATH."""
from pathlib import Path
import hashlib,io,os,platform,tarfile,urllib.request,zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='8.30.1'
ASSETS={
    'Windows':('windows_x64.zip','d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e','gitleaks.exe'),
    'Linux':('linux_x64.tar.gz','551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb','gitleaks'),
}

def install():
    system=platform.system()
    if system not in ASSETS or platform.machine().lower() not in ('amd64','x86_64'):raise RuntimeError('Use an official Gitleaks binary for your platform.')
    suffix,expected,name=ASSETS[system]
    url=f'https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_{suffix}'
    request=urllib.request.Request(url,headers={'User-Agent':'BilingualVideo source audit'})
    with urllib.request.urlopen(request,timeout=60) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Gitleaks checksum mismatch')
    target=ROOT/'.local/tools/gitleaks'/name;target.parent.mkdir(parents=True,exist_ok=True)
    if suffix.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:contents=archive.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:contents=archive.extractfile(name).read()
    target.write_bytes(contents)
    if os.name!='nt':target.chmod(0o755)
    print('Installed pinned Gitleaks in .local/tools/gitleaks')
    return target

if __name__=='__main__':install()
