"""Explicit model installation shared by source and frozen desktop builds."""
from pathlib import Path
import hashlib
import json
import sys


def manifest():
    p = (Path(sys.executable).resolve().parent/'app/assets.json' if getattr(sys, 'frozen', False)
         else Path(__file__).resolve().parents[1]/'scripts/assets.json')
    return json.loads(p.read_text(encoding='utf-8'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def install_model(runtime, model, callback=None, cancel=None):
    if model not in ('base', 'small'):
        raise ValueError('请选择 base 或 small 识别模型。')
    import requests
    runtime = Path(runtime).resolve()
    entries = [e for e in manifest()['files'] if e['path'].startswith('models/'+model+'/')]
    if not entries:
        raise RuntimeError('模型清单缺少此模型。')
    for entry in entries:
        path = (runtime/entry['path']).resolve()
        if not path.is_relative_to(runtime):
            raise ValueError('模型路径无效。')
        if path.is_file() and path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256']:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix+'.download')
        count = 0
        try:
            with requests.get(entry['url'], stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                with partial.open('wb') as output:
                    for block in response.iter_content(1024*1024):
                        if cancel and cancel.is_set():
                            raise RuntimeError('已取消模型下载。')
                        count += len(block)
                        if count > entry['bytes']:
                            raise RuntimeError('模型下载大小超过清单，已停止。')
                        output.write(block)
                        if callback:
                            callback(f"{model} · {path.name} · {count/1024/1024:.1f}/{entry['bytes']/1024/1024:.1f} MB")
            if count != entry['bytes'] or digest(partial) != entry['sha256']:
                raise RuntimeError('模型校验失败，请稍后重新下载。')
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return runtime/'models'/model
