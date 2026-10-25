"""Local, selective slide OCR and a non-destructive Chinese annotation rail."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import re
from difflib import SequenceMatcher

PPT_SCHEMA = 2
SAMPLE_SECONDS = 3.0
SCAN_FPS = 2


def normalize(text):
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def select_blocks(results, width, height):
    """Group aligned OCR lines before selecting prose, large headings and notes.

    Deliberately omit small ticks, model/version labels, logos and formulas.
    All raw OCR remains in the project, including excluded text.
    """
    lines = []
    for box, text, score in results or []:
        x1, y1 = min(p[0] for p in box), min(p[1] for p in box)
        x2, y2 = max(p[0] for p in box), max(p[1] for p in box)
        text = ' '.join(str(text).split())
        if normalize(text) in {'ar','xiv','arxiv','imf','anthropic','anthrop'}:continue
        line_words=re.findall(r"[A-Za-z][A-Za-z'-]*",text)
        if text.count(',')>=2 and sum(w[:1].isupper() for w in line_words)/max(1,len(line_words))>.65 and not re.search(r'\b(?:is|are|was|were|can|will|has|have|should)\b',text,re.I):
            continue
        if score < .86 or y2-y1 < max(14, height*.026) or not re.search('[A-Za-z]', text):
            continue
        if y1 < height*.025 or y2 > height*.94 or abs(box[1][1]-box[0][1]) > (y2-y1)*.4:
            continue
        lines.append({'box':[round(x1),round(y1),round(x2),round(y2)], 'text':text, 'score':float(score), 'height':y2-y1})
    lines.sort(key=lambda x:(x['box'][1],x['box'][0]))
    groups=[]
    for line in lines:
        x1,y1,x2,y2=line['box']; candidates=[]
        for group in groups:
            last=group[-1]; a,b,c,d=last['box']; h=max(last['height'],line['height'])
            aligned=abs(x1-a)<=max(12,h*.8) or abs((x1+x2-a-c)/2)<=h*.45
            if (aligned and -.25*h<=y1-d<=h*.85
                    and max(last['height'],line['height'])/min(last['height'],line['height'])<1.6):
                candidates.append((abs(y1-d),group))
        if candidates:
            min(candidates,key=lambda x:x[0])[1].append(line)
        else:
            groups.append([line])
    blocks=[]
    for group in groups:
        text=''
        for line in group:
            text += ('' if not text or text.endswith('-') else ' ')+line['text']
        original=text
        # English OCR regularly confuses capital I with lowercase l in 'AI'.
        text=re.sub(r'\bAl (?=(?:is|can|systems|models)\b)', 'AI ', text)
        words=re.findall(r"[A-Za-z][A-Za-z'-]*",text)
        tallest=max(l['height'] for l in group)
        lower=sum(c.islower() for c in text)/max(1,sum(c.isalpha() for c in text))
        brand=bool(re.search(r'\b(?:Claude|GPT|Gemini|Sonnet|Opus|Mythos|ANTHROPIC)\b',text,re.I))
        formula=bool(re.search(r'[=∑∫√∂≤≥]',text))
        # Long, comma-separated author lists are names, not explanatory prose.
        name_words=[w for w in words if w[:1].isupper()]
        if text.count(',')>=4 and len(name_words)/max(1,len(words))>.65 and not re.search(r'\b(?:is|are|was|were|can|will|has|have|should)\b',text,re.I):continue
        prose=len(words)>=5 and lower>.45
        heading=tallest>=height*.029 and 1<=len(words)<=8 and len(text)>=4 and not brand
        short_note=len(words)>=3 and lower>.5 and tallest>=height*.021
        if formula or (brand and len(words)<7) or not (prose or heading or short_note):continue
        if re.match(r'^(?:Sources?|Copyright)',text,re.I):continue
        if re.fullmatch(r'[A-Z0-9 .,%()/-]+',text) or not words:continue
        box=[min(l['box'][0] for l in group),min(l['box'][1] for l in group),max(l['box'][2] for l in group),max(l['box'][3] for l in group)]
        blocks.append({'text':text,'ocr_text':original,'box':box,'confidence':round(sum(l['score'] for l in group)/len(group),4),'kind':'explanation' if prose else 'heading' if heading else 'note'})
    # A left-hand row label belongs to its explanatory paragraph (e.g. Math,
    # Biology, Robotics). Keep that relation instead of creating six loose notes.
    consumed=set()
    for i,heading in enumerate(blocks):
        if heading['kind']!='heading' or len(heading['text'].split())>3:continue
        x1,y1,x2,y2=heading['box'];matches=[]
        for j,body in enumerate(blocks):
            if body['kind']!='explanation':continue
            a,b,c,d=body['box']
            overlap=max(0,min(y2,d)-max(y1,b))
            if x2<a-8 and overlap>=min(y2-y1,d-b)*.5:
                matches.append((a-x2,j,body))
        if matches:
            _,j,body=min(matches,key=lambda x:x[0])
            body['text']=heading['text']+': '+body['text']
            body['ocr_text']=heading['ocr_text']+': '+body['ocr_text']
            body['box']=[min(x1,body['box'][0]),min(y1,body['box'][1]),max(x2,body['box'][2]),max(y2,body['box'][3])]
            body['confidence']=min(body['confidence'],heading['confidence'])
            consumed.add(i)
    return sorted((b for i,b in enumerate(blocks) if i not in consumed),key=lambda b:(b['box'][1],b['box'][0]))


def scan_worker(payload):
    import av
    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from engine import _atomic_json, _read_json, _worker_emit
    cv2.setNumThreads(1)
    video=Path(payload['video']);folder=Path(payload['folder']);folder.mkdir(parents=True,exist_ok=True)
    width,height,duration=payload['width'],payload['height'],payload['duration']
    offset=float(payload.get('clip_offset',0))
    model=Path(payload['model'])
    if not model.is_file():raise RuntimeError('缺少本地英语 OCR 模型，请保留完整的应用文件夹。')
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1,rec_model_path=str(model))
    fingerprint=payload['fingerprint'];cachepath=folder/'ocr-samples.json'
    cache=_read_json(cachepath,{})
    samples=cache.get('samples',{}) if cache.get('fingerprint')==fingerprint else {}
    times=[round(.5+i*SAMPLE_SECONDS,3) for i in range(max(1,math.ceil((duration-.5)/SAMPLE_SECONDS))) if .5+i*SAMPLE_SECONDS<duration]
    with av.open(str(video)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=2
        for i,t in enumerate(times):
            key=str(t)
            if key not in samples:
                container.seek(int((t+offset)/float(stream.time_base)),stream=stream,backward=True)
                frame=next((f for f in container.decode(stream) if float(f.time or 0)>=t+offset),None)
                if frame is None:continue
                image=frame.to_ndarray(format='bgr24')
                if image.shape[:2]!=(height,width):
                    raise RuntimeError('PPT 翻译暂不支持带旋转标记的视频；请先导出为正向画面。')
                raw,_=ocr(image,use_cls=False)
                samples[key]={'time':t,'raw':raw or [],'blocks':select_blocks(raw,width,height)}
                _atomic_json(cachepath,{'fingerprint':fingerprint,'samples':samples})
            _worker_emit({'type':'ppt_progress','done':i+1,'total':len(times)})
    # Stable pages must recur; one-frame OCR and dissolves never become pages.
    pages=[]
    for sample in sorted(samples.values(),key=lambda s:s['time']):
        blocks=select_blocks(sample['raw'],width,height)
        if not blocks:continue
        signature=normalize(' '.join(b['text'] for b in blocks))
        match=None
        for page in pages:
            if len(page['blocks'])!=len(blocks):continue
            if max(abs(a-b) for old,new in zip(page['blocks'],blocks) for a,b in zip(old['box'],new['box']))>max(10,width*.008):continue
            if SequenceMatcher(None,page['_signature'],signature).ratio()>.92:
                match=page;break
        if match is None:
            match={'id':f'p{len(pages)+1:03}','blocks':blocks,'sample_times':[],'_signature':signature,'anchor_time':sample['time']}
            pages.append(match)
        match['sample_times'].append(sample['time'])
        if sum(b['confidence'] for b in blocks)>sum(b['confidence'] for b in match['blocks']):
            match.update(blocks=blocks,anchor_time=sample['time'],_signature=signature)
    pages=[p for p in pages if any(b-a<=SAMPLE_SECONDS*1.05 for a,b in zip(p['sample_times'],p['sample_times'][1:]))]
    for page in pages:
        page.pop('_signature',None)
        for block in page['blocks']:
            block['id']=hashlib.sha256((normalize(block['text'])+str([round(v/8) for v in block['box']])).encode()).hexdigest()[:16]
    with av.open(str(video)) as container:
        stream=container.streams.video[0];stream.codec_context.thread_count=2
        for page in pages:
            t=page['anchor_time']+offset;container.seek(int(t/float(stream.time_base)),stream=stream,backward=True)
            frame=next((f for f in container.decode(stream) if float(f.time or 0)>=t),None)
            if frame is not None:frame.to_image().save(folder/(page['id']+'-original.png'))
    # Match only the chosen text patches against a twice-per-second image scan.
    # Speaker motion outside these patches does not change page timing.
    scan_width=payload['scan_width'];scan_height=payload['scan_height']
    pixels=np.fromfile(folder/'scan.gray',np.uint8)
    n=len(pixels)//(scan_width*scan_height)
    images=pixels[:n*scan_width*scan_height].reshape(n,scan_height,scan_width)
    templates=[]
    for page in pages:
        anchor=images[min(n-1,round(page['anchor_time']*SCAN_FPS))]
        patches=[]
        for block in page['blocks']:
            x1,y1,x2,y2=block['box']
            a=max(0,round(x1/width*scan_width)-1);b=max(0,round(y1/height*scan_height)-1)
            c=min(scan_width,round(x2/width*scan_width)+1);d=min(scan_height,round(y2/height*scan_height)+1)
            if c>a and d>b:patches.append((a,b,c,d,anchor[b:d,a:c].astype(np.float32)))
        templates.append(patches)
    labels=[]
    for image in images:
        candidates=[]
        for j,patches in enumerate(templates):
            errors=[float(np.abs(image[b:d,a:c].astype(np.float32)-ref).mean()) for a,b,c,d,ref in patches]
            # Every chosen paragraph must remain visibly present; blanks and fades are gaps.
            if errors and max(errors)<=7 and sum(errors)/len(errors)<=4.5:
                candidates.append((sum(errors)/len(errors),j))
        labels.append(min(candidates)[1] if candidates else -1)
    intervals=[];a=0
    while a<len(labels):
        b=a+1
        while b<len(labels) and labels[b]==labels[a]:b+=1
        if labels[a]>=0 and (b-a)/SCAN_FPS>=2:
            start=max(0,a/SCAN_FPS+.15);end=min(duration,b/SCAN_FPS-.15)
            if end>start:intervals.append({'start':round(start,3),'end':round(end,3),'page':pages[labels[a]]['id']})
        a=b
    output={'schema':PPT_SCHEMA,'fingerprint':fingerprint,'width':width,'height':height,'duration':duration,'sample_seconds':SAMPLE_SECONDS,'boundary_resolution_seconds':1/SCAN_FPS,'pages':pages,'intervals':intervals,'selection':'Prose, large headings and explanatory notes; omit formulas, numerical ticks, model/version labels, logos and tiny source lines','manual_edits':False}
    _atomic_json(folder/'recognition.json',output)
    _worker_emit({'type':'ppt_ready','pages':len(pages),'blocks':sum(len(p['blocks']) for p in pages),'intervals':len(intervals)})


def prepare(engine, video, job, info, source, settings, options):
    from engine import _atomic_json, _read_json, _json_hash
    folder=job/'ppt';folder.mkdir(exist_ok=True)
    model=engine.root/'models/ocr/en_PP-OCRv3_rec_infer.onnx'
    if not model.is_file():raise RuntimeError('缺少 models/ocr 英语 OCR 模型，请使用含 PPT 翻译的完整版本。')
    offset=float(source.get('clip_seconds',[0])[0])
    fingerprint=_json_hash({'source':source['video_sha256'],'clip_seconds':source.get('clip_seconds'),'schema':PPT_SCHEMA,'sample_seconds':SAMPLE_SECONDS,'ocr_model':engine._sha(model)})
    scan=_read_json(folder/'recognition.json',{})
    if scan.get('fingerprint')!=fingerprint:
        sw=320;sh=round(info['height']/info['width']*sw/2)*2
        engine._emit('ppt_scan',72,'本地扫描稳定 PPT 页面；原视频画面不会上传…')
        raw=folder/'scan.gray'
        if not raw.exists() or _read_json(folder/'scan-source.json',{}).get('fingerprint')!=fingerprint:
            temp=folder/'scan.partial.gray'
            engine._process([engine.root/'bin/ffmpeg.exe','-hide_banner','-loglevel','error','-nostdin','-y','-threads','2','-ss',str(offset),'-i',video,'-t',str(info['duration']),'-an','-vf',f'fps={SCAN_FPS},scale={sw}:{sh}','-filter_threads','1','-pix_fmt','gray','-f','rawvideo',temp])
            temp.replace(raw);_atomic_json(folder/'scan-source.json',{'fingerprint':fingerprint})
        def progress(event):
            if event.get('type')=='ppt_progress':
                engine._emit('ppt_scan',72+9*event['done']/max(1,event['total']),f"识别 PPT 画面 {event['done']} / {event['total']}")
        engine._worker('ppt_scan',{'video':str(video),'folder':str(folder),'model':str(model),'fingerprint':fingerprint,**info,'clip_offset':offset,'scan_width':sw,'scan_height':sh},progress)
        scan=_read_json(folder/'recognition.json',{})
        if scan.get('fingerprint')!=fingerprint:raise RuntimeError('PPT 本地识别未完成，已保留进度供下次继续。')
    blocks={}
    for page in scan['pages']:
        for block in page['blocks']:blocks.setdefault(block['id'],block)
    ids=list(blocks)
    cues=[{'start':i,'end':i+1,'text':blocks[key]['text']} for i,key in enumerate(ids)]
    translation_id=_json_hash({'cues':cues,'settings':settings,'schema':PPT_SCHEMA})
    saved=_read_json(folder/'translations.json',{})
    cached=saved.get('translations',{}) if saved.get('fingerprint')==translation_id else {}
    cached={str(i):cached[str(i)] for i in range(len(cues)) if isinstance(cached.get(str(i)),str) and cached[str(i)].strip()}
    def translated(event):
        if event.get('type')!='translated':return
        index=int(event['index']);text=str(event['text']).strip()
        if index not in range(len(cues)) or not text:raise RuntimeError('PPT 翻译服务返回空白或无效结果。')
        cached[str(index)]=text
        _atomic_json(folder/'translations.json',{'fingerprint':translation_id,'settings':settings,'translations':cached})
        engine._emit('ppt_translate',81+5*len(cached)/max(1,len(cues)),f'PPT 解释文字翻译 {len(cached)} / {len(cues)}')
    if len(cached)<len(cues):
        engine._emit('ppt_translate',81,f'翻译 {len(cues)} 块 PPT 解释文字；只发送识别出的文字…')
        engine._worker('translate',{'cues':cues,'cached':cached,**settings,'api_key':str(options.get('api_key','')) if settings['translator']=='deepseek' else ''},translated)
    if len(cached)!=len(cues):raise RuntimeError('PPT 译文不完整，未导出假完成结果。重试会继续已保存进度。')
    overrides=_read_json(folder/'overrides.json',{})
    if not isinstance(overrides,dict):raise ValueError('PPT 校对文件格式不正确。')
    mapping={key:cached[str(i)] for i,key in enumerate(ids)}
    for page in scan['pages']:
        for block in page['blocks']:
            override=overrides.get(block['id'],{})
            text=override.get('translation',mapping[block['id']])
            if not isinstance(text,str) or not text.strip():raise ValueError('PPT 中文注释不能为空；不需要显示的文字可取消勾选。')
            block.update(translation=text.strip(),enabled=bool(override.get('enabled',True)))
    scan.update(translator=settings['translator'],translation_fingerprint=translation_id,manual_edits=bool(overrides),status='ready' if scan['intervals'] else 'no_stable_slides')
    _atomic_json(folder/'annotations.json',scan)
    export_review(folder,scan)
    return scan


def export_review(folder, data):
    import html
    rows=[]
    for page in data['pages']:
        times=', '.join(f"{s['start']:.1f}–{s['end']:.1f}s" for s in data['intervals'] if s['page']==page['id']) or '未确认稳定显示区间'
        rows.append(f'<h2>{page["id"]} · {times}</h2><details><summary>英文原画与实际导出画面</summary><p>英文原画</p><img src="{page["id"]}-original.png" alt="英文原画"><p>成片中的中文注释排版</p><img src="{page["id"]}-annotated.png" alt="实际导出画面"></details>')
        for b in page['blocks']:
            rows.append('<section><p class="source">'+html.escape(b['text'])+'</p><p>'+html.escape(b['translation'])+'</p><small>'+('显示' if b['enabled'] else '已隐藏')+' · OCR '+str(b['confidence'])+' · '+b['id']+'</small></section>')
    (folder/'PPT中英对照.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>PPT 中英对照</title><style>body{font:17px/1.8 "Microsoft YaHei",sans-serif;max-width:1000px;margin:30px auto;padding:0 20px;color:#21374b}section{background:#edf3f6;padding:15px 22px;margin:14px 0;border-radius:8px}p{margin:7px 0}.source,small{color:#65768a}img{max-width:100%;height:auto}</style><h1>PPT 解释性英文 · 中英对照</h1><p>英文原画保留。中文为识别后翻译的页面注释，可能有识别和翻译错误；在 App 中可用“校对 PPT 注释”修改或隐藏，再重新导出。坐标、数字、公式、模型名等默认保留。</p>'+''.join(rows)+'</html>',encoding='utf-8')


def append_ass(path, data, video_width, video_height, band, font='Microsoft YaHei'):
    """Append a measured side rail to the existing subtitle ASS, never cover slides."""
    from engine import _wrap_text, _timestamp
    rail=max(320,round(video_width*.32/2)*2);canvas=video_width+rail
    margin=round(rail*.065);inner=rail-2*margin
    h1=max(20,round(video_width*.019));zh=max(18,round(video_width*.017));en=max(12,round(video_width*.011))
    def wrap(text,size):return _wrap_text(text,max(12,int(inner/(size*.56))))
    page_cards={}
    for page in data['pages']:
        groups=[];cards=[];used=0
        for block in page['blocks']:
            if not block['enabled']:continue
            source=block['text'];source=(source[:62].rsplit(' ',1)[0]+'…') if len(source)>65 else source
            source_lines=wrap(source,en)
            lines=wrap(block['translation'],zh)
            max_lines=max(3,int((video_height-150-len(source_lines)*en*1.35)/(zh*1.4))-1)
            for offset in range(0,len(lines),max_lines):
                part=lines[offset:offset+max_lines]
                card={'source':source_lines,'zh':part,'continuation':offset>0,'height':math.ceil(len(source_lines)*en*1.35+len(part)*zh*1.4+26)}
                if cards and used+card['height']>video_height-145:
                    groups.append(cards);cards=[];used=0
                cards.append(card);used+=card['height']
        if cards:groups.append(cards)
        page_cards[page['id']]=groups
    ass=Path(path).read_text(encoding='utf-8-sig').replace(f'PlayResX: {video_width}',f'PlayResX: {canvas}')
    styles=f'Style: PPT,{font},{zh},&H00F3F6F8,&H00FFFFFF,&H001B2534,&H001B2534,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n'
    ass=ass.replace('[Events]',styles+'\n[Events]')
    events=[]
    def event(a,b,text,layer=2):
        events.append(f'Dialogue: {layer},{_timestamp(a,True)},{_timestamp(b,True)},PPT,,0,0,0,,{text}')
    duration=data['duration'];x=video_width+margin
    event(0,duration,r'{\an7\pos(0,0)\p1\1c&H34251B&}'+f'm {video_width} 0 l {canvas} 0 {canvas} {video_height} {video_width} {video_height}',0)
    event(0,duration,r'{\an7\pos('+str(x)+','+str(margin)+r')\fs'+str(h1)+r'\b1\1c&HC6E5A0&}PPT 中文注释',1)
    event(0,duration,r'{\an7\pos('+str(x)+','+str(margin+h1+12)+r')\fs'+str(en)+r'\1c&HB5A899&}保留英文原画 · 只译解释性文字',1)
    visible=[];warnings=[]
    for interval in data['intervals']:
        groups=page_cards.get(interval['page'],[])
        if not groups:continue
        n=len(groups);span=(interval['end']-interval['start'])/n
        if span<4:warnings.append({'page':interval['page'],'reason':'注释分页显示时间较短，建议人工检查','seconds_per_panel':round(span,2)})
        for i,cards in enumerate(groups):
            a=interval['start']+span*i;b=interval['start']+span*(i+1);y=100
            for j,card in enumerate(cards):
                title=f'{j+1:02d} · '+r'\N'.join(card['source'])+('（续）' if card['continuation'] else '')
                event(a,b,r'{\an7\pos('+str(x)+','+str(y)+r')\fs'+str(en)+r'\1c&HB5A899&}'+title)
                y+=math.ceil(len(card['source'])*en*1.35)+9
                event(a,b,r'{\an7\pos('+str(x)+','+str(y)+r')\fs'+str(zh)+r'\1c&HF3F6F8&}'+r'\N'.join(card['zh']))
                y+=math.ceil(len(card['zh'])*zh*1.4)+17
                if y>video_height-10:raise RuntimeError('PPT 中文注释超出画面，已停止导出以避免裁切文字。')
            if n>1:event(a,b,r'{\an7\pos('+str(x)+','+str(video_height-34)+r')\fs'+str(en)+r'}注释 '+f'{i+1}/{n}')
            visible.append([round(a,3),round(b,3),interval['page']])
    Path(path).write_text(ass+'\n'+'\n'.join(events)+'\n',encoding='utf-8-sig')
    return {'canvas_width':canvas,'rail_width':rail,'page_count':len(data['pages']),'text_blocks':sum(len(p['blocks']) for p in data['pages']),'visible_intervals':visible,'layout_warnings':warnings,'original_picture_unchanged':True}
