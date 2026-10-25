"""Small yt-dlp adapter; reuse bundled FFmpeg and keep downloads as local inputs."""
from pathlib import Path
from urllib.parse import urlsplit
import shutil
import sys
import re


def download_name(value):
    """One Windows path component, also usable literally in yt-dlp's template."""
    name=str(value).strip()
    if not name or name in ('.','..') or len(name)>100 or name.endswith(('.', ' ')) or re.search(r'[<>:"/\\|?*\x00-\x1f]',name):
        raise ValueError('请输入不超过100字的名称，不能包含路径分隔符或 Windows 文件名禁用字符。')
    reserved={'CON','PRN','AUX','NUL','CONIN$','CONOUT$',*[f'{kind}{i}' for kind in ('COM','LPT') for i in range(1,10)]}
    if name.split('.')[0].upper() in reserved:raise ValueError('该名称是 Windows 保留名称，请换一个。')
    return name


def reserve_download_folder(parent,name):
    parent=Path(parent).expanduser().resolve();name=download_name(name)
    parent.mkdir(parents=True,exist_ok=True)
    for i in range(1,100000):
        folder=parent/(name if i==1 else f'{name}_{i:02d}')
        try:folder.mkdir();return folder
        except FileExistsError:continue
    raise RuntimeError('无法创建新的下载文件夹。')


def validate_url(value):
    url=value.strip();p=urlsplit(url)
    hosts={'youtube.com','www.youtube.com','m.youtube.com','youtu.be','x.com','www.x.com','twitter.com','www.twitter.com','mobile.twitter.com'}
    if p.scheme not in ('https','http') or p.hostname not in hosts or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('请粘贴 YouTube 或 X/Twitter 的视频链接。')
    if not p.path.strip('/'):raise ValueError('请粘贴具体视频链接，不能只填写网站首页。')
    return url


def download_worker(payload):
    import yt_dlp
    from engine import _worker_emit,_atomic_json
    url=validate_url(payload['url']);folder=Path(payload['folder']).resolve();folder.mkdir(parents=True,exist_ok=True)
    name=download_name(payload.get('filename') or 'video')
    ffmpeg=Path(payload['ffmpeg']).resolve()
    if not ffmpeg.is_file():raise RuntimeError('缺少 FFmpeg，无法合并视频和音频。')
    limit=payload.get('height','best')
    if limit not in ('best','1080','720'):raise ValueError('无效的下载清晰度。')
    condition='' if limit=='best' else f'[height<={limit}]'
    class QuietLogger:
        def debug(self,msg):pass
        def warning(self,msg):pass
        def error(self,msg):pass
    def progress(d):
        total=d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        _worker_emit({'type':'download_progress','percent':round(min(100,100*d.get('downloaded_bytes',0)/total),1) if total else None,
                      'message':'正在下载视频或音频…' if d.get('status')=='downloading' else '下载完成，正在合并音视频…'})
    options={'format':f'bv*{condition}+ba/b{condition}', 'noplaylist':True,'playlist_items':'1',
             'outtmpl':str(folder/name).replace('%','%%')+'.%(ext)s','merge_output_format':'mkv','ffmpeg_location':str(ffmpeg),
             'quiet':True,'no_warnings':True,'logger':QuietLogger(),'progress_hooks':[progress],
             'socket_timeout':25,'retries':1,'fragment_retries':1,'concurrent_fragment_downloads':2,
             'overwrites':False,'windowsfilenames':True}
    bundled_node=ffmpeg.parent/'node.exe'
    node=str(bundled_node) if bundled_node.is_file() else shutil.which('node')
    # Portable releases prefer their verified runtime; source users may use PATH.
    if node:options['js_runtimes']={'node':{'path':node}}
    if payload.get('test_seconds'):
        from yt_dlp.utils import download_range_func
        options['download_ranges']=download_range_func(None,[(0,float(payload['test_seconds']))])
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info=ydl.extract_info(url,download=True)
            if info.get('_type')=='playlist':info=next(e for e in info['entries'] if e)
    except Exception:
        raise RuntimeError('下载未完成。请检查网络、链接是否公开以及网站是否要求登录；也可先用浏览器下载，再添加本地视频。') from None
    videos=sorted([p for p in folder.iterdir() if p.is_file() and p.stem==name and p.suffix in ('.mp4','.mkv','.webm','.mov')],key=lambda p:p.stat().st_size,reverse=True)
    if not videos:raise RuntimeError('网站未返回可用视频文件。')
    metadata={k:info.get(k) for k in ('id','title','webpage_url','uploader','duration','width','height','format_id')}
    _atomic_json(folder/'下载信息.json',metadata)
    _worker_emit({'type':'download_done','path':str(videos[0]),'title':metadata['title'],'width':metadata['width'],'height':metadata['height']})
