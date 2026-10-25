"""Measured typography, a compact footer, and notes beside the full original frame."""
from pathlib import Path
import math,re,os



def font_at(size):
    from PIL import ImageFont
    for name in ('msyh.ttc','msyhbd.ttc','simhei.ttf'):
        p=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/name
        if p.is_file():return ImageFont.truetype(str(p),size)
    raise RuntimeError('未找到可用于中文排版的系统字体。请安装微软雅黑或黑体后重试。')


def safe(text):
    return str(text).replace('\\','＼').replace('{','｛').replace('}','｝').replace('\x00','')


def japanese_font(text):
    """Use the actual font cmap so unsupported glyphs cannot become squares."""
    from fontTools.ttLib import TTFont
    required={ord(c) for c in text if not c.isspace() and ord(c)>=32}
    folder=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
    candidates=['YuGothM.ttc','YuGothR.ttc','meiryo.ttc','msgothic.ttc','msyh.ttc','simhei.ttf',
                'NotoSansCJK-Regular.ttc','NotoSansJP-Regular.ttf']
    for name in candidates:
        path=folder/name
        if not path.is_file():continue
        try:
            with TTFont(path,fontNumber=0,lazy=True) as font:
                if not required.issubset(font.getBestCmap() or {}):continue
                family=font['name'].getDebugName(1)
                if family:return {'path':str(path),'family':family}
        except (OSError,KeyError):continue
    raise RuntimeError('未找到能完整显示本片日文的字体。请安装日文字体（如 Noto Sans JP）后重新导出；未输出缺字方框成片。')


def wrap(text,size,width,font_path=None):
    if font_path:
        from PIL import ImageFont
        font=ImageFont.truetype(str(font_path),size)
    else:font=font_at(size)
    lines=[];line=''
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_’'./%-]*|[^A-Za-z0-9]",' '.join(str(text).split())):
        if font.getlength(line+token)>width and line.strip():
            if token[:1] in '、。，．！？：；）」』】》〉' and len(line)>1:
                lines.append(line[:-1].strip());line=line[-1]
            else:lines.append(line.strip());line=''
        if font.getlength(token)>width:
            for c in token:
                if font.getlength(line+c)>width and line:lines.append(line.strip());line=''
                line+=c
        else:line+=token
    if line.strip():lines.append(line.strip())
    return lines or ['']


def ass_header(width,height,font):
    if any(c in font for c in ',\r\n'):raise ValueError('字体名称包含不支持的字符。')
    return ['[Script Info]','ScriptType: v4.00+',f'PlayResX: {width}',f'PlayResY: {height}','WrapStyle: 2','ScaledBorderAndShadow: yes','',
      '[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
      f'Style: Bilingual,{font},34,&H00FFFFFF,&H00FFFFFF,&H00141414,&H00000000,0,0,0,0,100,100,0,0,1,0.5,0,8,0,0,0,1',
      f'Style: PPT,{font},26,&H00F4F6FA,&H00FFFFFF,&H00141414,&H0034251B,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1','',
      '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']


def event(a,b,payload,style='Bilingual',layer=3):
    from engine import _timestamp
    return f'Dialogue: {layer},{_timestamp(a,True)},{_timestamp(b,True)},{style},,0,0,0,,{payload}'


def chunks(text,n):
    text=' '.join(str(text).split());cuts=[0]
    latin=not re.search('[\u3040-\u30ff\u3400-\u9fff]',text)
    for i in range(1,n):
        target=round(len(text)*i/n)
        choices=[j+1 for j in range(max(cuts[-1]+1,target-15),min(len(text)-1,target+16)) if text[j] in (' ,;.!?' if latin else '，。；！？、 ')]
        cut=min(choices,key=lambda j:abs(j-target)) if choices else target
        cuts.append(max(cuts[-1]+1,cut))
    cuts.append(len(text))
    return [text[a:b].strip() for a,b in zip(cuts,cuts[1:])]


def subtitles(cues,translations,width,top,band,zh_size,en_size,*,line_limit=2,gap=8,source_font=None):
    if len(cues)!=len(translations) or not all(str(t).strip() for t in translations):raise ValueError('字幕中存在缺失译文，不能生成完成结果。')
    events=[];pages_added=0;warnings=[];max_rows=[0,0]
    for cue,zh in zip(cues,translations):
        z=wrap(zh,zh_size,width-64);e=wrap(cue['text'],en_size,width-64,(source_font or {}).get('path'))
        n=max(1,math.ceil(len(z)/line_limit),math.ceil(len(e)/line_limit))
        while True:
            zs=chunks(zh,n);es=chunks(cue['text'],n)
            pairs=[(wrap(a,zh_size,width-64),wrap(b,en_size,width-64,(source_font or {}).get('path'))) for a,b in zip(zs,es)]
            if all(len(a)<=line_limit and len(b)<=line_limit for a,b in pairs):break
            n+=1
            if n>128:raise RuntimeError('字幕块过长，无法在紧凑字幕带中完整显示。请先整理英文断句。')
        pages_added+=n-1;span=(cue['end']-cue['start'])/n
        if n>1 and span<1.5:warnings.append({'start':cue['start'],'reason':'长字幕分页后显示时间较短','seconds':round(span,2)})
        for i,(z,e) in enumerate(pairs):
            a=cue['start']+span*i;b=cue['start']+span*(i+1)
            zheight=len(z)*zh_size*1.22;eheight=len(e)*en_size*1.22;total=zheight+eheight+gap
            y=top+(band-total)/2
            if y<top+4 or y+total>top+band-4:raise RuntimeError('字幕超出紧凑字幕带，已停止导出避免裁切。')
            events.append(event(a,b,r'{\an8\pos('+str(width//2)+','+str(round(y))+r')\fs'+str(zh_size)+r'\1c&HF8F8F8&}'+r'\N'.join(safe(t) for t in z)))
            face=r'\fn'+source_font['family'] if source_font else ''
            events.append(event(a,b,r'{\an8\pos('+str(width//2)+','+str(round(y+zheight+gap))+r')\fs'+str(en_size)+face+r'\1c&HE0E0E0&}'+r'\N'.join(safe(t) for t in e)))
            max_rows=[max(max_rows[0],len(z)),max(max_rows[1],len(e))]
    return events,{'subtitle_band_height':band,'subtitle_sizes':[zh_size,en_size],'maximum_language_lines':max_rows,'subtitle_pages_added':pages_added,'subtitle_layout_warnings':warnings}


def slim_band(zh_size,en_size):
    # One line in each language, 4px between languages, and ~6px outer margins.
    return math.ceil(((zh_size+en_size)*1.22+4+12)/2)*2


def compact_ass(path,cues,translations,width,height,font='Microsoft YaHei',mode='band',source_language='en'):
    if mode not in ('band','overlay'):raise ValueError('字幕位置选项无效。')
    zh=max(18,round(width*.021));en=max(15,round(width*.0165))
    band=slim_band(zh,en) if mode=='band' else math.ceil((2*(zh+en)*1.22+24)/2)*2
    output_height=height+band if mode=='band' else height
    lines=ass_header(width,output_height,font)
    source_font=japanese_font(''.join(c['text'] for c in cues)) if source_language=='ja' else None
    captions,plan=subtitles(cues,translations,width,height if mode=='band' else height-band,band,zh,en,line_limit=1 if mode=='band' else 2,gap=4 if mode=='band' else 8,source_font=source_font)
    if source_font:plan['source_font']=source_font['family']
    Path(path).write_text('\n'.join(lines+captions)+'\n',encoding='utf-8-sig')
    from engine import _atomic_json
    _atomic_json(Path(path).with_name('subtitle-layout.json'),dict(plan,mode=mode,original_frame_rect=[0,0,width,height],canvas_width=width,canvas_height=output_height))
    return band if mode=='band' else 0


def presentation(path,cues,translations,data,folder,font='Microsoft YaHei'):
    from engine import _atomic_json
    original_w,original_h=data['width'],data['height']
    rail=max(240,round(original_w*.225/2)*2)
    zh_size=max(20,round(original_w*.0234));en_size=max(16,round(original_w*.0172))
    band=slim_band(zh_size,en_size)
    width,height=original_w+rail,original_h+band
    main_h=original_h
    lines=ass_header(width,height,font);duration=data['duration']
    reserve=24
    # The panel occupies its own pixels; neither text nor the presenter covers slides.
    lines.append(event(0,duration,r'{\an7\pos(0,0)\p1\1c&H000000&}'+f'm 0 {main_h} l {width} {main_h} {width} {height} 0 {height}','PPT',1))
    lines.append(event(0,duration,r'{\an7\pos(22,22)\fs24\b1\1c&HC6E5A0&}PPT 中文注释','PPT',2))
    lines.append(event(0,duration,r'{\an7\pos(24,60)\fs15\1c&HB5A899&}英文原画保留','PPT',2))
    available=main_h-reserve-100;page_cards={};warnings=[]
    for page in data['pages']:
        groups=[];cards=[];used=0
        for block in page['blocks']:
            if not block['enabled']:continue
            wrapped=wrap(block['translation'],22,rail-44);max_lines=max(3,int((available-30)/(22*1.24)))
            for offset in range(0,len(wrapped),max_lines):
                rows=wrapped[offset:offset+max_lines];cost=math.ceil(len(rows)*22*1.24+34)
                if cards and used+cost>available:groups.append(cards);cards=[];used=0
                cards.append(rows);used+=cost
        if cards:groups.append(cards)
        page_cards[page['id']]=groups
    visible=[]
    for interval in data['intervals']:
        groups=page_cards[interval['page']];n=len(groups)
        if not n:continue
        span=(interval['end']-interval['start'])/n
        if span<4:warnings.append({'page':interval['page'],'reason':'注释分页显示时间较短','seconds_per_panel':round(span,2)})
        for i,cards in enumerate(groups):
            a=interval['start']+i*span;b=a+span;y=100
            for j,rows in enumerate(cards):
                lines.append(event(a,b,r'{\an7\pos(24,'+str(y)+r')\fs14\1c&HC6E5A0&}'+f'{j+1:02d}','PPT',2));y+=22
                lines.append(event(a,b,r'{\an7\pos(24,'+str(y)+r')\fs22\1c&HF4F6FA&}'+r'\N'.join(safe(t) for t in rows),'PPT',2));y+=math.ceil(len(rows)*22*1.24)+12
                if y>main_h-reserve+4:raise RuntimeError('左侧中文注释超出区域，已停止导出避免裁切。')
            if n>1:lines.append(event(a,b,r'{\an7\pos(24,'+str(main_h-reserve+4)+r')\fs14}'+f'注释 {i+1}/{n}','PPT',2))
            visible.append([round(a,3),round(b,3),interval['page']])
    captions,subtitle_layout=subtitles(cues,translations,width,main_h,band,zh_size,en_size,line_limit=1,gap=4);lines.extend(captions)
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    # Preserve every pixel's position and the complete original framing.
    # No crop, zoom, split-screen inset, or video scaling is applied.
    script=Path(folder).parent/'layout-filter.txt'
    script.write_text(f'[0:v]pad={width}:{height}:{rail}:0:color=0x1B2534,setsar=1,ass=filename=bilingual.ass[vout]',encoding='utf-8')
    result={'canvas_width':width,'canvas_height':height,'rail_side':'left','rail_width':rail,'main_height':main_h,
            'original_frame_rect':[rail,0,original_w,original_h],'original_frame_scale':1.0,
            'page_count':len(data['pages']),'text_blocks':sum(len(p['blocks']) for p in data['pages']),
            'visible_intervals':visible,'layout_warnings':warnings,**subtitle_layout,'filter_script':str(script),
            'original_ppt_text_preserved':True,'original_picture_unchanged':True}
    _atomic_json(Path(folder)/'layout.json',result)
    return result
