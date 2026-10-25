"""Export only audited allowlisted text; private files cannot enter the ZIP."""
from pathlib import Path
import hashlib,json,zipfile
from check_public import ROOT,allowed_files,audit,scan_text,private_path

def export():
    result=audit(gitleaks=True)
    if not result['passed']:raise RuntimeError('Source privacy audit failed; see .local/reports.')
    destination=ROOT/'.local/publish';destination.mkdir(parents=True,exist_ok=True)
    target=destination/'BilingualVideo-1.9.4-source.zip'
    hashes={}
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in allowed_files():
            data=(ROOT/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
            info=zipfile.ZipInfo('BilingualVideo-1.9.4/'+name,date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            if name.startswith('.githooks/'):info.external_attr=0o755<<16
            archive.writestr(info,data)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(hashes)
        for member in archive.namelist():
            name=member.split('/',1)[1];data=archive.read(member)
            assert name in hashes and not private_path(name)
            assert hashlib.sha256(data).hexdigest()==hashes[name]
            assert not scan_text(name,data.decode('utf-8-sig'))
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (destination/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    report={'passed':True,'files':len(hashes),'zip_bytes':target.stat().st_size,'sha256':digest,'file_sha256':hashes,
            'scope':'Source ZIP only. Local applications, settings, media, models, logs and Git history are excluded.'}
    (ROOT/'.local/reports/source-package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'archive':target.name,'files':len(hashes),'bytes':target.stat().st_size,'sha256':digest}))

if __name__=='__main__':export()
