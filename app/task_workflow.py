"""Task approval, per-video settings and local anime review dialogs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from anime import WorkStore, snapshot, validate_terms


class WorkflowUI:
    def _init_workflow(self):
        self.content_mode = tk.StringVar(value='英语视频')
        self.work_name = tk.StringVar()
        self.asset_cancel = None
        self.glossary_cancel = None
        self.work_store = None
        try:
            self.work_store = WorkStore(self.app_root/'settings')
        except (OSError, ValueError) as error:
            self.after(300, lambda text=str(error): messagebox.showerror('作品资料无法读取', text, parent=self))

    def _work_labels(self):
        return {w['title']+'【'+w['id'][:6]+'】': w['id'] for w in self.work_store.list()} if self.work_store else {}

    def _selected_work(self):
        label = self.work_name.get()
        if not label:
            return {}
        work_id = self._work_labels().get(label)
        if not work_id:
            raise ValueError('所选作品已不存在，请重新选择或清空作品选择。')
        return self.work_store.get(work_id)

    def _mode_changed(self, _event=None):
        from gui import TRANSLATORS
        anime = self.content_mode.get() == '日本动漫（日→中）'
        self.translator_box.configure(values=[k for k,v in TRANSLATORS.items() if not anime or v!='argos'])
        self.asr_model.set('small' if anime else 'base')
        if anime:
            from gui import TRANSLATORS
            self.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'))
            self.ppt_annotations.set(False)
            self.domain.set('通用内容')
        self._ppt_changed(); self._translator_changed()

    def _capture_settings(self, validate=True):
        from gui import TRANSLATORS
        from engine import _validate_api_base
        try:
            anime = self.content_mode.get() == '日本动漫（日→中）'
            translator = TRANSLATORS[self.translator.get()]
            output = self.output_root.get().strip()
            if validate and not output:
                raise ValueError('请选择导出位置。')
            options = {'global_understanding':self.global_understanding.get() if translator=='deepseek' else False, 'translator':translator, 'model':self.asr_model.get(),
                       'economy_api':self.economy_api.get() if translator=='deepseek' else False,
                       'auto_refine':self.auto_refine.get() if translator=='deepseek' else False,
                       'source_language':'ja' if anime else 'en', 'content_mode':'anime' if anime else 'general',
                       'domain':'wireless' if not anime and self.domain.get()=='无线通信课程' else 'general',
                       'output_root':str(Path(output or self.app_root/'exports').expanduser().resolve()),
                       'api_key':self.api_key.get().strip() if translator=='deepseek' else '',
                       'api_base':self.api_base.get().strip() or 'https://api.deepseek.com',
                       'model_name':self.model_name.get().strip() or 'deepseek-flash',
                       'font':'Microsoft YaHei', 'render_mode':'band' if self.render_mode.get().startswith('独立') else 'overlay',
                       'ppt_annotations':False if anime else self.ppt_annotations.get(),
                       'subtitles_only':self.subtitles_only.get() if hasattr(self,'subtitles_only') else False,
                       'quality':{'高保真 · 推荐':'high','标准 · 文件较小':'balanced','无损编码 · 文件很大':'lossless'}[self.quality.get()],
                       'profile_name':self.profile_name.get().strip() if translator=='deepseek' else self.translator.get(),
                       'work_snapshot':snapshot(self._selected_work()) if anime else {}}
            if validate and anime and translator=='argos':
                raise ValueError('当前 Argos 只有英中模型；动漫请选择 API、必应或 Google。')
            if validate and translator=='deepseek':
                if not options['api_key']:
                    raise ValueError('请先选择保存的 API 方案或填写密钥。')
                options['api_base'] = _validate_api_base(options['api_base'])
                if not self.profile_store:
                    raise ValueError('翻译方案无法读取，不能分配模型编号。')
                options['profile_code'] = self.profile_store.code_for(options['api_base'], options['model_name'])
            return options
        except (ValueError, OSError) as error:
            messagebox.showerror('设置需要调整', str(error), parent=self)
            return None

    def _import_jobs(self, paths):
        from gui import Job, VIDEO_SUFFIXES
        from engine import Engine
        if self.closing:
            return
        options = self._capture_settings(validate=False)
        if options is None:
            return
        seen = set(); first = None
        for raw in paths:
            video = Path(raw).resolve()
            if not video.is_file() or video.suffix.lower() not in VIDEO_SUFFIXES or video in seen:
                continue
            seen.add(video)
            job = Job(video=video, options=copy.deepcopy(options))
            job.logs.append('已导入，尚未开始。可先选片段、载入并修改设置，再应用到此任务。')
            self.jobs[job.id] = job
            self.tree.insert('', 'end', iid=job.id, values=self._row(job))
            first = first or job.id
            def probe(job=job):
                try:
                    info = Engine(self.app_root, None, threading.Event())._probe(job.video)
                    error = ''
                except Exception as exc:
                    info, error = {}, str(exc)
                def done(job=job, info=info, error=error):
                    if job.id in self.jobs:
                        job.info, job.metadata_error = info, error
                        if error: job.logs.append('本地信息读取失败，开始前会重新检查：'+error)
                        self._refresh_job(job)
                self.messages.put(('ui_call', None, done))
            threading.Thread(target=probe, daemon=True).start()
        if first and not self.active_id:
            self.tree.selection_set(first); self._show_selected_log()
        if not first:
            messagebox.showinfo('没有新增视频', '请选择支持的本地视频文件。', parent=self)
        self._update_summary()
        # Import intentionally never calls _start_next or an online confirmation.

    def _editable_jobs(self):
        return [self.jobs[i] for i in self.tree.selection() if self.jobs[i].status=='待开始']

    def _load_selected_settings(self):
        jobs = self._editable_jobs()
        if len(jobs)!=1:
            messagebox.showinfo('选择一个待开始任务', '已排队的任务请先取消排队；再选择一个待开始视频载入设置。', parent=self); return
        self._fill_task_settings(jobs[0])

    def _fill_task_settings(self, job):
        from gui import TRANSLATORS
        o = job.options
        for attr, value in [('content_mode','日本动漫（日→中）' if o.get('source_language')=='ja' else '英语视频'),
                            ('asr_model',o.get('model','base')),('domain','无线通信课程' if o.get('domain')=='wireless' else '通用内容'),
                            ('translator',next(k for k,v in TRANSLATORS.items() if v==o['translator'])),
                            ('output_root',o['output_root']),('api_key',o.get('api_key','')),('api_base',o.get('api_base','')),
                            ('model_name',o.get('model_name','')),('profile_name',o.get('profile_name','')),
                            ('render_mode','独立字幕带 · 保留完整画面' if o.get('render_mode')=='band' else '画面内叠加 · 底部显示'),
                            ('quality',{'high':'高保真 · 推荐','balanced':'标准 · 文件较小','lossless':'无损编码 · 文件很大'}[o.get('quality','high')])]:
            getattr(self,attr).set(value)
        self.ppt_annotations.set(o.get('ppt_annotations',False))
        self.global_understanding.set(o.get('global_understanding',True))
        self.economy_api.set(o.get('economy_api',True))
        self.auto_refine.set(o.get('auto_refine',False))
        self.translator_box.configure(values=[k for k,v in TRANSLATORS.items() if o.get('source_language')!='ja' or v!='argos'])
        self.work_name.set(next((label for label,identifier in self._work_labels().items() if identifier==o.get('work_snapshot',{}).get('id')),''))
        self._ppt_changed(); self._translator_changed()
        self.progress_text.set('选中任务设置已载入。单选修改自动保存，多选请批量应用。')

    def _apply_selected_settings(self):
        jobs = self._editable_jobs(); options = self._capture_settings(validate=False)
        if options is None:return
        if not jobs:
            messagebox.showinfo('选择待开始任务', '先选择待开始视频；已排队的任务需先取消排队。', parent=self); return
        for job in jobs:
            previous = job.options
            per_video = {k:v for k,v in previous.items() if k in ('clip_enabled','clip_start','clip_end','source_srt','srt_encoding','reviewed_srt')}
            if previous.get('source_language','en')!=options['source_language']:
                per_video = {k:v for k,v in per_video.items() if k.startswith('clip_')}
            updated = dict(copy.deepcopy(options), **per_video)
            if updated != previous:job.output = None
            job.options = updated
            self._refresh_job(job)
        self.progress_text.set(f'已应用到 {len(jobs)} 个待开始任务，原有片段范围保留。')

    def _one_draft(self):
        jobs = self._editable_jobs()
        if len(jobs)!=1:
            messagebox.showinfo('选择一个待开始视频', '此操作每次针对一个待开始视频。', parent=self); return None
        return jobs[0]

    def _select_range(self):
        from engine import Engine
        from range_picker import RangePicker
        job = self._one_draft()
        if not job:return
        try:
            info = job.info or Engine(self.app_root,None,threading.Event())._probe(job.video)
            initial = (job.options['clip_start'],job.options['clip_end']) if job.options.get('clip_enabled') else None
            picker = RangePicker(self,job.video,info,initial)
            self.wait_window(picker)
            if picker.result is None:return
            a,b = picker.result
            enabled = not (abs(a)<.001 and abs(b-info['duration'])<.001)
            job.options.update(clip_enabled=enabled,clip_start=a,clip_end=b)
            job.options.pop('reviewed_srt',None);job.output=None
            self._refresh_job(job)
        except Exception as error:messagebox.showerror('无法选择片段',str(error),parent=self)

    def _source_subtitles_dialog(self):
        job = self._one_draft()
        if not job:return
        dialog = tk.Toplevel(self); dialog.title('原文字幕来源'); dialog.transient(self); dialog.grab_set()
        body = ttk.Frame(dialog,padding=18);body.pack(fill='both',expand=True)
        path = tk.StringVar(value=job.options.get('source_srt',''))
        encoding = tk.StringVar(value=job.options.get('srt_encoding','utf-8-sig'))
        ttk.Label(body,text='留空：日语仅自动查找同名 .ja.srt；英语查找同名 .srt；否则识别音频。',wraplength=560).pack(anchor='w')
        row = ttk.Frame(body);row.pack(fill='x',pady=12)
        ttk.Entry(row,textvariable=path,width=64).pack(side='left',fill='x',expand=True)
        def choose():
            selected=filedialog.askopenfilename(parent=dialog,filetypes=[('原文字幕','*.srt')])
            if selected:path.set(selected)
        ttk.Button(row,text='选择 SRT',command=choose).pack(side='left',padx=8)
        ttk.Combobox(body,textvariable=encoding,values=['utf-8-sig','cp932','gb18030'],state='readonly').pack(anchor='w')
        def save():
            job.options.update(source_srt=path.get().strip(),srt_encoding=encoding.get())
            job.options.pop('reviewed_srt',None);job.output=None;dialog.destroy()
        ttk.Button(body,text='保存字幕来源',command=save).pack(anchor='e',pady=(14,0))

    def _begin_jobs(self, all_jobs=False, recognize=False):
        from engine import Engine, _validate_api_base
        selected = list(self.jobs.values()) if all_jobs else [self.jobs[i] for i in self.tree.selection()]
        jobs = [j for j in selected if j.status=='待开始']
        if not jobs:
            messagebox.showinfo('没有待开始任务','先导入视频，或选择待开始任务。待校对任务请从“校对原文 / 继续翻译”进入。',parent=self);return
        self._save_single_settings()
        prepared=[]
        try:
            for job in jobs:
                options=copy.deepcopy(job.options);options['recognize_only']=bool(recognize)
                Engine(self.app_root,None,threading.Event()).preflight(job.video,options)
                if not recognize and options['translator']=='deepseek':
                    options['api_base']=_validate_api_base(options['api_base'])
                    if not self.profile_store:raise ValueError('翻译方案无法读取。')
                    options['profile_code']=self.profile_store.code_for(options['api_base'],options['model_name'])
                prepared.append((job,options))
        except Exception as error:
            messagebox.showerror('开始前检查未通过',f'{job.video.name}\n\n{error}\n\n本批任务均未开始。上方修改设置后，请先“应用设置到选中”。',parent=self);return
        groups={}
        for job,options in prepared:
            if not recognize and options['translator'] in ('bing','google','deepseek'):
                key=(options['translator'],options.get('api_base',''),options.get('model_name',''),options.get('source_language','en'),options.get('global_understanding',False),options.get('economy_api',True),options.get('auto_refine',False))
                groups.setdefault(key,[]).append(options)
        for group in groups.values():
            options=group[0]
            confirm=self._confirm_paid if options['translator']=='deepseek' else self._confirm_online
            if not confirm(len(group),options):return
        for job,options in prepared:
            job.options=options;job.status='待处理';job.stage='等待识别校对' if recognize else '等待处理'
            self._refresh_job(job)
        self.queue_paused=False;self.resume_button.configure(state='disabled')
        self._update_summary();self._start_next()

    def _cancel_queued(self):
        for i in self.tree.selection():
            job=self.jobs[i]
            if job.status=='待处理':
                job.status='待开始';job.stage='已取消排队，可修改设置';self._refresh_job(job)
        self._update_summary()

    def _prepare_model(self):
        if self.asset_cancel:return
        from model_assets import install_model, manifest
        model=self.asr_model.get()
        size=sum(e['bytes'] for e in manifest()['files'] if e['path'].startswith('models/'+model+'/'))
        if not messagebox.askyesno('准备本地识别模型',f'将显式下载并校验 {model} 模型（约 {size/1024/1024:.0f} MB）。\n已校验文件会跳过，视频处理不会自动下载。是否继续？',parent=self,default='no'):return
        cancel=threading.Event();self.asset_cancel=cancel
        def done(error):
            self.asset_cancel=None
            if error:messagebox.showerror('模型准备未完成',error,parent=self)
            else:messagebox.showinfo('模型准备完成',f'{model} 已下载并通过 SHA-256 校验。',parent=self)
        def run():
            try:
                def progress(text):self.messages.put(('ui_call',None,lambda text=text:self.progress_text.set(text)))
                install_model(self.app_root,model,progress,cancel)
                self.messages.put(('ui_call',None,lambda:done('')))
            except Exception as error:self.messages.put(('ui_call',None,lambda text=str(error):done(text)))
        threading.Thread(target=run,daemon=True).start()

    def _edit_source(self):
        from engine import parse_srt, write_srt, _read_json
        selected=self.tree.selection();job=self.jobs.get(selected[0]) if len(selected)==1 else None
        if not job or job.status!='待校对' or not job.output:
            messagebox.showinfo('选择待校对任务','先选择视频并点击“先识别 / 校对”，识别结束后再打开此窗口。',parent=self);return
        self._fill_task_settings(job)
        language=job.options.get('source_language','en')
        source=job.output/(language+'.srt')
        dialog=tk.Toplevel(self);dialog.title('校对原文后继续翻译');dialog.geometry('920x680');dialog.transient(self)
        body=ttk.Frame(dialog,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='时间轴从本次片段 00:00 开始。已载入本任务设置；继续时采用主界面当前 API 方案和作品译名表。').pack(anchor='w')
        text=tk.Text(body,wrap='word',undo=True,font=('Microsoft YaHei UI',11));text.pack(fill='both',expand=True,pady=10)
        text.insert('1.0',source.read_text(encoding='utf-8-sig'))
        def save():
            cues=parse_srt(text.get('1.0','end'))
            manifest=_read_json(job.output/'project.json',{})
            start,end=manifest.get('clip_seconds',[0,job.info.get('duration',0)])
            if cues[-1]['end']>end-start+.001:raise ValueError('校对稿时间超出本次片段。')
            destination=job.output/'reviewed.srt';write_srt(destination,cues)
            job.options['reviewed_srt']=str(destination)
            return cues
        def save_only():
            try:save();messagebox.showinfo('已保存校对稿','原始识别稿仍保留，尚未开始翻译。',parent=dialog)
            except Exception as error:messagebox.showerror('无法保存',str(error),parent=dialog)
        def continue_translation():
            try:
                save()
                # Explicitly adopt the current selected API/work profile now;
                # time range and edited source remain attached to this video.
                options=self._capture_settings(validate=True)
                if options is None:return
                if options['source_language']!=language:raise ValueError('上方处理模式与此校对稿语言不同，请先切回正确模式。')
                job.options.update({k:v for k,v in options.items() if k not in ('model','output_root')})
                job.options['recognize_only']=False;job.status='待开始'
                self.tree.selection_set(job.id);self._begin_jobs()
                if job.status=='待开始':job.status='待校对'
                else:dialog.destroy()
                self._refresh_job(job)
            except Exception as error:messagebox.showerror('无法继续',str(error),parent=dialog)
        buttons=ttk.Frame(body);buttons.pack(fill='x')
        ttk.Button(buttons,text='保存校对稿',command=save_only).pack(side='left')
        if language=='ja':ttk.Button(buttons,text='作品与译名表 / AI 起草',command=lambda:self._edit_work(lambda:parse_srt(text.get('1.0','end')))).pack(side='left',padx=8)
        ttk.Button(buttons,text='继续翻译与导出',command=continue_translation,style='Accent.TButton').pack(side='right')

    def _name_review(self):
        selected=self.tree.selection();job=self.jobs.get(selected[0]) if len(selected)==1 else None
        path=job.output/'name-review.json' if job and job.output else None
        if not path or not path.is_file():messagebox.showinfo('暂无译名检查','请选择已完成的日语任务。',parent=self);return
        rows=json.loads(path.read_text(encoding='utf-8'))['warnings']
        dialog=tk.Toplevel(self);dialog.title('本次固定译名与检查');dialog.geometry('850x540')
        text=tk.Text(dialog,wrap='word',font=('Microsoft YaHei UI',11));text.pack(fill='both',expand=True,padx=15,pady=15)
        effective=job.output/'effective-names.json'
        if effective.is_file():
            names=json.loads(effective.read_text(encoding='utf-8'))['work']['terms']
            text.insert('end','以下译名在本次任务固定；自动约定不代表官方译名，无需逐条人工确认。\n同一作品后续任务自动复用。未选作品时仅在同一视频复用。\n\n')
            for term in names:text.insert('end',f"{term['source']} → {term['target']}  （{'人工指定' if term['confirmed'] else '自动约定'}）\n")
            text.insert('end','\n检查结果：\n')
        for row in rows:text.insert('end',f"{row['start']:.2f} 秒 · 建议核对：{row['expected']}\n原文：{row['source']}\n译文：{row['translation']}\n\n")
        if not rows:text.insert('end','未发现已登记译名缺失。仅对原文中匹配到的名称和称呼保证固定；未识别的人物、代词指代和转写错误仍可能影响结果。')
        text.configure(state='disabled')

    def _edit_work(self, cues_provider=None):
        if not self.work_store:messagebox.showerror('作品资料不可用','请保留原文件并先解决读取错误。',parent=self);return
        try:work=self._selected_work()
        except ValueError:work={}
        terms=copy.deepcopy(work.get('terms',[]));editing=[None]
        dialog=tk.Toplevel(self);dialog.title('作品资料与人物译名表');dialog.geometry('1040x780');dialog.transient(self);dialog.grab_set()
        body=ttk.Frame(dialog,padding=18);body.pack(fill='both',expand=True)
        title=tk.StringVar(value=work.get('title',''))
        ttk.Label(body,text='作品名（同一作品后续集数可复用）').pack(anchor='w')
        ttk.Entry(body,textvariable=title).pack(fill='x',pady=(4,10))
        ttk.Label(body,text='关系和称呼备注：自然中文为默认；这里填写的规则会随确认译名发送给 API。').pack(anchor='w')
        notes=tk.Text(body,height=3,wrap='word');notes.pack(fill='x',pady=5);notes.insert('1.0',work.get('notes',''))
        table=ttk.Frame(body);table.pack(fill='both',expand=True,pady=8)
        tree=ttk.Treeview(table,columns=('source','reading','target','state'),show='headings',height=4)
        for key,label in [('source','日文原名 / 完整称呼'),('reading','假名读音'),('target','中文译名'),('state','状态')]:tree.heading(key,text=label);tree.column(key,width=180)
        tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(table,orient='vertical',command=tree.yview);scroll.pack(side='right',fill='y');tree.configure(yscrollcommand=scroll.set)
        form=ttk.Frame(body);form.pack(fill='x')
        values={k:tk.StringVar() for k in ('source','reading','target','aliases','notes')};confirmed=tk.BooleanVar(value=False)
        for i,(key,label) in enumerate([('source','日文原名 / 完整称呼'),('reading','假名读音'),('target','中文译名'),('aliases','别名（用 | 分隔）'),('notes','条目备注；免费翻译不执行备注提示词')]):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',pady=3)
            ttk.Entry(form,textvariable=values[key]).grid(row=i,column=1,sticky='ew',padx=10)
        form.columnconfigure(1,weight=1)
        ttk.Checkbutton(form,text='我已核对，确认此条目生效（AI 候选默认不生效）',variable=confirmed).grid(row=5,column=0,columnspan=2,sticky='w',pady=6)
        def redraw():
            tree.delete(*tree.get_children())
            for i,t in enumerate(terms):tree.insert('','end',iid=str(i),values=(t['source'],t['reading'],t['target'],'已确认' if t['confirmed'] else '待确认'))
        def load(_event=None):
            selected=tree.selection()
            if not selected:return
            i=int(selected[0]);editing[0]=i;term=terms[i]
            for key,var in values.items():var.set(' | '.join(term['aliases']) if key=='aliases' else term[key])
            confirmed.set(term['confirmed'])
        tree.bind('<<TreeviewSelect>>',load)
        def add():
            try:
                row={k:v.get() for k,v in values.items()};row['aliases']=[v.strip() for v in row['aliases'].split('|') if v.strip()];row['confirmed']=confirmed.get()
                candidate=copy.deepcopy(terms)
                if editing[0] is None:candidate.append(row)
                else:candidate[editing[0]]=row
                terms[:]=validate_terms(candidate);editing[0]=None
                for var in values.values():var.set('')
                confirmed.set(False);redraw()
            except ValueError as error:messagebox.showerror('条目需要调整',str(error),parent=dialog)
        def new():
            editing[0]=None
            for var in values.values():var.set('')
            confirmed.set(False);tree.selection_remove(*tree.selection())
        def remove():
            selected=tree.selection()
            if selected:del terms[int(selected[0])];new();redraw()
        def new_work():
            work.clear();terms.clear();title.set('');notes.delete('1.0','end');new();redraw()
        row=ttk.Frame(body);row.pack(fill='x',pady=6)
        ttk.Button(row,text='写入当前条目',command=add).pack(side='left')
        ttk.Button(row,text='新增空白条目',command=new).pack(side='left',padx=8)
        ttk.Button(row,text='删除选中条目',command=remove).pack(side='left')
        ttk.Button(row,text='新建作品',command=new_work).pack(side='left',padx=8)
        status=tk.StringVar(value='无需逐项确认：正式处理会自动选定并固定译名。这里可选填人工覆盖；完整称呼单独建条目时优先最长匹配。免费接口复用已有固定表或保留识别出的人名原文，不会暗中调用付费 API。')
        ttk.Label(body,textvariable=status,wraplength=970).pack(anchor='w',pady=5)
        def draft():
            if self.glossary_cancel:return
            try:
                if cues_provider:cues=cues_provider()
                else:
                    selected=self.tree.selection();job=self.jobs.get(selected[0]) if len(selected)==1 else None
                    if not job or not job.output or job.options.get('source_language')!='ja':raise ValueError('先对日语视频执行“先识别 / 校对”，再从校对窗口起草名称表。')
                    from engine import read_sidecar
                    cues=read_sidecar(job.output/'ja.srt','ja')
                options=self._capture_settings(validate=True)
                if options is None:return
                if options['translator']!='deepseek':raise ValueError('AI 起草需要 API；请先在主界面选择 API 方案。')
                if not messagebox.askyesno('确认 AI 起草调用',f"将向 {options['api_base']} 的 {options['model_name']} 发送前 100 条、最多 6000 字的日文台词。\n会消耗 API 余额；候选需你确认，不自动生效。是否继续？",parent=dialog,default='no'):return
                self.glossary_cancel=threading.Event();cancel=self.glossary_cancel;draft_button.configure(state='disabled');status.set('正在起草，候选不会自动生效…')
                def finish(result,error):
                    self.glossary_cancel=None
                    if not dialog.winfo_exists():return
                    draft_button.configure(state='normal')
                    if error:status.set('起草未完成：'+self._redact(error));return
                    existing={t['source'] for t in terms}
                    terms.extend(t for t in result if t['source'] not in existing);redraw()
                    status.set('候选已加入为“待确认”。请逐项核对、勾选确认并写入条目，再保存作品。')
                def run():
                    from engine import Engine
                    result=[]
                    try:
                        payload={k:options[k] for k in ('api_base','model_name','api_key')};payload['cues']=cues
                        Engine(self.app_root,None,cancel)._worker('glossary',payload,lambda e:result.extend(e['terms']) if e.get('type')=='glossary_done' else None)
                        self.messages.put(('ui_call',None,lambda:finish(result,'')))
                    except Exception as error:self.messages.put(('ui_call',None,lambda text=str(error):finish([],text)))
                threading.Thread(target=run,daemon=True).start()
            except Exception as error:messagebox.showerror('无法起草',str(error),parent=dialog)
        draft_button=ttk.Button(row,text='AI 起草候选（需确认）',command=draft);draft_button.pack(side='right')
        def save_work():
            try:
                if any(v.get().strip() for v in values.values()):
                    raise ValueError('还有未写入的条目，请先点击“写入当前条目”，或点“新增空白条目”清空编辑区。')
                identifier=self.work_store.save(title.get(),terms,notes.get('1.0','end').strip(),work.get('id'))
                self.work_box.configure(values=['',*self._work_labels()])
                self.work_name.set(next(label for label,value in self._work_labels().items() if value==identifier))
                dialog.destroy()
            except (ValueError,OSError) as error:messagebox.showerror('无法保存作品',str(error),parent=dialog)
        ttk.Button(body,text='保存作品资料',command=save_work,style='Accent.TButton').pack(anchor='e',pady=8)
        redraw()
