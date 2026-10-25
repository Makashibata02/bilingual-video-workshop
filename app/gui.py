"""Chinese desktop UI for the local bilingual video workflow (standard library only)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass, field
import uuid
from datetime import datetime


from task_workflow import WorkflowUI
from paths import app_root as runtime_root
APP_ROOT = runtime_root()
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".mpeg", ".mpg"}
TRANSLATORS = {
    "必应在线｜免费 · 推荐": "bing",
    "Google 在线｜可能限流": "google",
    "Argos 离线｜备用": "argos",
    "API 翻译｜DeepSeek / 兼容服务": "deepseek",
}
STAGES = {
    "understand":"全局理解原文",
    "refine":"自动精修字幕",
    "audio": "提取音频", "recognize": "本地识别", "prepare": "准备中", "probe": "检查视频", "extract": "提取音频",
    "transcribe": "本地识别", "asr": "本地识别", "transcription": "本地识别",
    "translate": "翻译字幕", "translation": "翻译字幕",
    "subtitle": "整理字幕", "subtitles": "整理字幕", "render": "合成视频",
    "ppt_scan": "识别 PPT", "ppt_translate": "翻译 PPT", "ppt_layout": "排版注释",
    "synthesize": "合成视频", "done": "已完成", "complete": "已完成",
}


@dataclass
class Job:
    video: Path
    options: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "待开始"
    progress: float = 0.0
    stage: str = "等待开始"
    output: Path | None = None
    logs: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    metadata_error: str = ""


class BilingualApp(WorkflowUI, tk.Tk):
    def __init__(self, *, app_root: Path = APP_ROOT) -> None:
        super().__init__()
        self.app_root = Path(app_root)
        self.title("双语视频工坊 1.9.4")
        self.geometry("1180x760")
        self.minsize(1040, 720)
        self.configure(bg="#f3f6fa")
        self.jobs: dict[str, Job] = {}
        self.messages: queue.Queue = queue.Queue()
        self.active_id: str | None = None
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.closing = False
        self.queue_paused = False
        self.translator = tk.StringVar(value=next(iter(TRANSLATORS)))
        self.asr_model = tk.StringVar(value="base")
        self.domain = tk.StringVar(value="通用内容")
        self.output_root = tk.StringVar(value=str(self.app_root / "exports"))
        self.render_mode = tk.StringVar(value="独立字幕带 · 保留完整画面")
        self.ppt_annotations = tk.BooleanVar(value=False)
        self.api_key = tk.StringVar()
        self.api_base = tk.StringVar(value="https://api.deepseek.com")
        self.model_name = tk.StringVar(value="deepseek-flash")
        self.profile_name = tk.StringVar()
        self.global_understanding=tk.BooleanVar(value=True)
        self.economy_api=tk.BooleanVar(value=True)
        self.auto_refine=tk.BooleanVar(value=False)
        self.subtitles_only=tk.BooleanVar(value=False)
        self.quality = tk.StringVar(value='高保真 · 推荐')
        self.clip_enabled = tk.BooleanVar(value=False)
        self.range_memory = {}
        from profiles import ProfileStore
        self.profile_error = ''
        try:self.profile_store = ProfileStore(self.app_root/'settings')
        except (OSError,ValueError) as error:
            self.profile_store = None;self.profile_error = str(error)
        self.test_cancel = None
        self.download_cancel = None
        self.download_parent = tk.StringVar(value=str(self.app_root/'downloads'))
        self.progress_value = tk.DoubleVar(value=0)
        self.status_text = tk.StringVar(value="准备就绪")
        self.progress_text = tk.StringVar(value="导入后先设置，再点击开始。可逐个选择片段，也可批量应用翻译设置。")
        self.queue_summary = tk.StringVar(value="还没有视频")
        self._init_workflow()
        self._build_style()
        self._build_ui()
        def read_hardware():
            from resources import detect_hardware,balanced_plan,describe
            try:
                hardware=detect_hardware();text=describe(hardware,balanced_plan(hardware))
            except Exception:text='硬件信息暂不可用；处理时仍使用保守线程预算。'
            self.messages.put(('ui_call',None,lambda text=text:self.hardware_text.set(text)))
        threading.Thread(target=read_hardware,daemon=True).start()
        self._translator_changed()
        self._ppt_changed()
        if self.profile_error:self.after(300,lambda:messagebox.showerror('翻译方案无法读取',self.profile_error,parent=self))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_messages)

    def _build_style(self) -> None:
        self.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background="#f3f6fa", foreground="#24354b")
        style.configure("TFrame", background="#f3f6fa")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f3f6fa", foreground="#24354b")
        style.configure("Card.TLabel", background="#ffffff")
        style.configure("Muted.TLabel", foreground="#607187", background="#f3f6fa")
        style.configure("CardMuted.TLabel", foreground="#607187", background="#ffffff")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 23, "bold"), foreground="#173047")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 11, "bold"), background="#ffffff")
        style.configure("TButton", padding=(13, 8), relief="flat", background="#e8edf4", borderwidth=0)
        style.map("TButton", background=[("active", "#dce5ef"), ("disabled", "#edf0f5")], foreground=[("disabled", "#99a3b1")])
        style.configure("Accent.TButton", foreground="white", background="#167b76", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#106763"), ("disabled", "#a5c4c1")], foreground=[("disabled", "#f1f6f5")])
        style.configure("TEntry", padding=7, fieldbackground="#ffffff", bordercolor="#d9e2ee", lightcolor="#d9e2ee", darkcolor="#d9e2ee")
        style.configure("TCombobox", padding=6, fieldbackground="#ffffff", background="#edf2f7", bordercolor="#d9e2ee")
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")])
        style.configure("Treeview", rowheight=34, background="white", fieldbackground="white", borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), padding=(8, 10), background="#eaf0f6", relief="flat")
        style.map("Treeview", background=[("selected", "#dcefeb")], foreground=[("selected", "#123c38")])
        style.configure("Horizontal.TProgressbar", troughcolor="#e6edf3", background="#167b76", borderwidth=0, thickness=9)

    def _build_ui(self) -> None:
        self._loading_task = False
        self._last_selection = ()
        self._pending_setting = None
        self.more_window = tk.Toplevel(self)
        self.more_window.title('更多设置 · 翻译方案管理')
        self.more_window.geometry('1200x720')
        self.more_window.withdraw()
        self.more_window.protocol('WM_DELETE_WINDOW', self.more_window.withdraw)
        self.more_window.columnconfigure(0, weight=1)
        self._fit_viewport = lambda: None
        self._build_more_settings()

        shell=ttk.Frame(self,padding=22);shell.pack(fill='both',expand=True)
        shell.columnconfigure(0,weight=1);shell.rowconfigure(4,weight=1)
        header=ttk.Frame(shell);header.grid(row=0,column=0,sticky='ew',pady=(0,16))
        ttk.Label(header,text='双语视频工坊',style='Title.TLabel').pack(side='left')
        ttk.Label(header,textvariable=self.status_text,style='Muted.TLabel').pack(side='right')
        card=ttk.Frame(shell,style='Card.TFrame',padding=14);card.grid(row=1,column=0,sticky='ew')
        for col in (1,3,5):card.columnconfigure(col,weight=1)
        ttk.Label(card,text='模式',style='Card.TLabel').grid(row=0,column=0,padx=6)
        modes=ttk.Combobox(card,textvariable=self.content_mode,values=['英语视频','日本动漫（日→中）'],state='readonly',width=18)
        modes.grid(row=0,column=1,sticky='ew');modes.bind('<<ComboboxSelected>>',self._mode_changed)
        ttk.Label(card,text='翻译方案',style='Card.TLabel').grid(row=0,column=2,padx=10)
        self.quick_scheme=tk.StringVar();self.scheme_box=ttk.Combobox(card,textvariable=self.quick_scheme,state='readonly',width=24)
        self.scheme_box.grid(row=0,column=3,sticky='ew');self.scheme_box.bind('<<ComboboxSelected>>',self._pick_scheme)
        ttk.Label(card,text='字幕位置',style='Card.TLabel').grid(row=0,column=4,padx=10)
        ttk.Combobox(card,textvariable=self.render_mode,values=['独立字幕带 · 保留完整画面','画面内叠加 · 底部显示'],state='readonly',width=24).grid(row=0,column=5,sticky='ew')
        self.selection_note=tk.StringVar(value='导入后设置，再开始。默认处理全片。')
        ttk.Label(card,textvariable=self.selection_note,style='CardMuted.TLabel',wraplength=760).grid(row=1,column=0,columnspan=5,sticky='w',pady=(10,0))
        self.refine_quick=ttk.Checkbutton(card,text='自动精修 · API',variable=self.auto_refine)
        self.refine_quick.grid(row=1,column=5,sticky='e',pady=(10,0))
        actions=ttk.Frame(shell);actions.grid(row=2,column=0,sticky='ew',pady=12)
        add=ttk.Menubutton(actions,text='＋ 添加视频 ▾');add.pack(side='left')
        menu=tk.Menu(add,tearoff=False);add.configure(menu=menu)
        for label,fn in [('选择视频',self._choose_videos),('选择文件夹',self._choose_folder),('粘贴链接下载',self._download_dialog)]:menu.add_command(label=label,command=fn)
        ttk.Button(actions,text='选择片段',command=self._select_range).pack(side='left',padx=6)
        ttk.Button(actions,text='开始选中',style='Accent.TButton',command=self._begin_jobs).pack(side='left',padx=6)
        start=ttk.Menubutton(actions,text='更多操作 ▾');start.pack(side='left')
        menu=tk.Menu(start,tearoff=False);start.configure(menu=menu)
        groups=[('开始与队列',[
            ('开始全部',lambda:self._begin_jobs(all_jobs=True)),('批量应用当前设置',self._apply_selected_settings),
            ('取消排队',self._cancel_queued),('重试失败 / 已停止',self._retry_selected),('移除待开始任务',self._remove_pending)]),
            ('校对与检查',[('原文字幕',self._source_subtitles_dialog),('先识别 / 校对',lambda:self._begin_jobs(recognize=True)),
            ('校对原文 / 继续翻译',self._edit_source),('译名检查',self._name_review),('查看全局理解',self._show_understanding),
            ('查看精修修改',self._show_refinement),('校对 PPT 注释',self._edit_ppt)]),
            ('预览与导出',[('按当前设置重新导出',self._rerender_result),('预览当前字幕样式（8 秒）',self._preview_result)])]
        for title,commands in groups:
            submenu=tk.Menu(menu,tearoff=False)
            for label,fn in commands:submenu.add_command(label=label,command=fn)
            menu.add_cascade(label=title,menu=submenu)
        ttk.Button(actions,text='更多设置',command=self._open_more).pack(side='right')
        queue_header = ttk.Frame(shell)
        queue_header.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(queue_header, text="处理队列", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        ttk.Label(queue_header, textvariable=self.queue_summary, style="Muted.TLabel").pack(side="right")

        table_frame = ttk.Frame(shell)
        table_frame.grid(row=4, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=("name", "translator", "range", "status", "progress", "stage"), show="headings", height=5, selectmode="extended")
        columns = [("name", "视频文件", 240, "w"), ("translator", "翻译方式", 165, "w"), ("range", "处理范围", 215, "w"), ("status", "状态", 85, "center"), ("progress", "进度", 75, "center"), ("stage", "当前步骤", 160, "w")]
        for key, title, width, anchor in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, anchor=anchor, stretch=key in {"name", "stage"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("done", foreground="#167b58")
        self.tree.tag_configure("failed", foreground="#aa4d33")
        self.tree.tag_configure("stopped", foreground="#7a8390")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_log)
        self.tree.bind("<Double-1>", self._open_selected_result)


        self.tree.bind('<<TreeviewSelect>>',self._select_task)
        row=ttk.Frame(shell);row.grid(row=5,column=0,sticky='ew',pady=10)
        self.stop_button=ttk.Button(row,text='停止当前任务',command=self._stop_current,state='disabled');self.stop_button.pack(side='left')
        self.resume_button=ttk.Button(row,text='继续队列',command=self._resume_queue,state='disabled');self.resume_button.pack(side='left',padx=6)
        ttk.Button(row,text='打开选中结果',command=self._open_selected_result).pack(side='right')
        ttk.Button(row,text='详细记录',command=self._toggle_log).pack(side='right',padx=6)
        progress=ttk.Frame(shell);progress.grid(row=6,column=0,sticky='ew')
        ttk.Progressbar(progress,variable=self.progress_value,maximum=100).pack(fill='x')
        ttk.Label(progress,textvariable=self.progress_text,style='Muted.TLabel').pack(anchor='w',pady=6)
        self.log_frame=ttk.Frame(shell);self.log_frame.grid(row=7,column=0,sticky='ew')
        self.log=tk.Text(self.log_frame,height=5,wrap='word',state='disabled');self.log.pack(fill='x');self.log_frame.grid_remove()
        ttk.Label(shell,textvariable=self.output_root,style='Muted.TLabel').grid(row=8,column=0,sticky='w',pady=6)
        self._refresh_schemes()
        for variable in (self.content_mode,self.translator,self.profile_name,self.render_mode,self.asr_model,self.domain,self.quality,self.ppt_annotations,self.output_root,self.api_base,self.api_key,self.model_name,self.work_name,self.subtitles_only,self.global_understanding,self.economy_api,self.auto_refine):
            variable.trace_add('write',self._settings_changed)

    def _build_more_settings(self):
        self.more_window.title('更多设置')
        self.more_window.geometry('920x620')
        self.more_window.minsize(880,600)
        self.more_window.rowconfigure(0,weight=1)
        self.settings_tabs=ttk.Notebook(self.more_window)
        self.settings_tabs.grid(row=0,column=0,sticky='nsew',padx=16,pady=16)
        tabs=[]
        for title in ('翻译与精修','识别与作品','画面与导出','方案管理'):
            frame=ttk.Frame(self.settings_tabs,style='Card.TFrame',padding=20)
            frame.columnconfigure(1,weight=1);self.settings_tabs.add(frame,text=title);tabs.append(frame)
        translation,recognition,output,schemes=tabs
        def label(parent,text,row):
            ttk.Label(parent,text=text,style='Card.TLabel').grid(row=row,column=0,sticky='w',padx=(0,16),pady=10)
        def hint(parent,text,row):
            ttk.Label(parent,text=text,style='CardMuted.TLabel',wraplength=780).grid(row=row,column=0,columnspan=2,sticky='w',pady=10)
        label(translation,'翻译方式',0)
        self.translator_box=ttk.Combobox(translation,textvariable=self.translator,values=list(TRANSLATORS),state='readonly')
        self.translator_box.grid(row=0,column=1,sticky='ew');self.translator_box.bind('<<ComboboxSelected>>',self._translator_changed)
        self.test_button=ttk.Button(translation,text='测试当前翻译',command=self._test_translation)
        self.test_button.grid(row=1,column=1,sticky='w')
        self.refine_detail=ttk.Checkbutton(translation,text='自动精修（默认关闭）',variable=self.auto_refine)
        self.refine_detail.grid(row=2,column=0,columnspan=2,sticky='w',pady=(20,0))
        hint(translation,'翻译后用当前 API 方案再校对一遍，改善生硬表达和上下文衔接。固定译名和称呼保持一致；可疑修改保留原译。额外调用可能计费，重复导出复用精修缓存。',3)
        self.api_frame=ttk.Frame(translation,style='Card.TFrame')
        self.api_frame.grid(row=4,column=0,columnspan=2,sticky='ew')
        ttk.Checkbutton(self.api_frame,text='先理解全部原文',variable=self.global_understanding).pack(anchor='w',pady=6)
        ttk.Checkbutton(self.api_frame,text='省用量模式（支持的 DeepSeek 模型）',variable=self.economy_api).pack(anchor='w',pady=6)
        self.privacy=ttk.Label(translation,style='CardMuted.TLabel',wraplength=780)
        self.privacy.grid(row=5,column=0,columnspan=2,sticky='w',pady=16)
        hint(translation,'密钥、模型和已保存的方案在“方案管理”中设置。单选任务自动保存，多选请批量应用；处理中的任务设置固定。',6)
        label(recognition,'处理模式',0)
        modes=ttk.Combobox(recognition,textvariable=self.content_mode,values=['英语视频','日本动漫（日→中）'],state='readonly')
        modes.grid(row=0,column=1,sticky='ew');modes.bind('<<ComboboxSelected>>',self._mode_changed)
        label(recognition,'识别模型',1)
        row=ttk.Frame(recognition,style='Card.TFrame');row.grid(row=1,column=1,sticky='ew')
        ttk.Combobox(row,textvariable=self.asr_model,values=['base','small'],state='readonly',width=14).pack(side='left')
        ttk.Button(row,text='准备识别模型',command=self._prepare_model).pack(side='left',padx=10)
        label(recognition,'作品',2)
        self.work_box=ttk.Combobox(recognition,textvariable=self.work_name,values=['',*self._work_labels()],state='readonly')
        self.work_box.grid(row=2,column=1,sticky='ew')
        ttk.Button(recognition,text='作品与译名表',command=self._edit_work).grid(row=3,column=1,sticky='w',pady=8)
        label(recognition,'内容领域',4)
        ttk.Combobox(recognition,textvariable=self.domain,values=['通用内容','无线通信课程'],state='readonly').grid(row=4,column=1,sticky='ew')
        hint(recognition,'有原文字幕时优先复用，无需重新识别。外挂字幕和识别校对针对单个视频，可从“更多操作 → 校对与检查”打开。',5)
        label(output,'字幕位置',0)
        self.render_box=ttk.Combobox(output,textvariable=self.render_mode,values=['独立字幕带 · 保留完整画面','画面内叠加 · 底部显示'],state='readonly')
        self.render_box.grid(row=0,column=1,sticky='ew')
        label(output,'导出画质',1)
        ttk.Combobox(output,textvariable=self.quality,values=['高保真 · 推荐','标准 · 文件较小','无损编码 · 文件很大'],state='readonly').grid(row=1,column=1,sticky='ew')
        hint(output,'高保真保留原始分辨率和帧率；压制更快，文件通常略大。默认全片，主界面“选择片段”可选范围。',2)
        ttk.Checkbutton(output,text='仅导出字幕（跳过视频压制）',variable=self.subtitles_only).grid(row=3,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Checkbutton(output,text='PPT 中文注释（默认关闭）',variable=self.ppt_annotations,command=self._ppt_changed).grid(row=4,column=0,columnspan=2,sticky='w',pady=8)
        label(output,'导出位置',5)
        row=ttk.Frame(output,style='Card.TFrame');row.grid(row=5,column=1,sticky='ew');row.columnconfigure(0,weight=1)
        ttk.Entry(row,textvariable=self.output_root).grid(row=0,column=0,sticky='ew')
        ttk.Button(row,text='更改',command=self._choose_output).grid(row=0,column=1,padx=8)
        self.hardware_text=tk.StringVar(value='正在读取本机配置；默认均衡占用…')
        ttk.Button(output,text='本机配置 / 均衡占用',command=lambda:messagebox.showinfo('本机配置与资源预算',self.hardware_text.get()+'\n\n默认保留响应余量；内存偏低时暂缓计算，不降低导出画质。硬件信息仅保存在本地。',parent=self.more_window)).grid(row=6,column=1,sticky='w',pady=14)
        label(schemes,'已保存的方案',0)
        self.profile_box=ttk.Combobox(schemes,textvariable=self.profile_name,values=[p['name'] for p in self.profile_store.list()] if self.profile_store else [])
        self.profile_box.grid(row=0,column=1,sticky='ew');self.profile_box.bind('<<ComboboxSelected>>',self._load_profile)
        for row,title,var in [(1,'API 地址',self.api_base),(2,'模型名称',self.model_name),(3,'API 密钥',self.api_key)]:
            label(schemes,title,row)
            ttk.Entry(schemes,textvariable=var,show='●' if row==3 else '').grid(row=row,column=1,sticky='ew')
        buttons=ttk.Frame(schemes,style='Card.TFrame');buttons.grid(row=4,column=1,sticky='w',pady=14)
        ttk.Button(buttons,text='保存方案',command=self._save_profile).pack(side='left')
        ttk.Button(buttons,text='删除方案',command=self._delete_profile).pack(side='left',padx=8)
        hint(schemes,'可分别保存 DS Flash、DS Pro 等方案，主界面直接切换。密钥用当前 Windows 账户加密保存在本机；测试和精修均可能计费。',5)
        ttk.Button(self.more_window,text='完成',command=self.more_window.withdraw).grid(row=1,column=0,sticky='e',padx=16,pady=(0,12))

    def _show_refinement(self):
        from engine import _read_json
        selection=self.tree.selection();job=self.jobs.get(selection[0]) if len(selection)==1 else None
        data=_read_json(job.output/'refinement.json',{}) if job and job.output else {}
        if not data:messagebox.showinfo('尚无精修记录','选择开启自动精修并已生成记录的任务。',parent=self);return
        dialog=tk.Toplevel(self);dialog.title('自动精修 · 修改与保留记录');dialog.geometry('900x650')
        text=tk.Text(dialog,wrap='word',font=('Microsoft YaHei UI',11));text.pack(fill='both',expand=True)
        summary=data['summary']
        text.insert('end',f"完成 {summary['completed']}/{summary['total']} 条，修改 {summary['changed']} 条，检查后保留原译 {summary['retained_after_check']} 条。\n本次请求 {summary['api_requests_this_run']} 次，复用 {summary['reused']} 条，用时 {summary['seconds_this_run']} 秒。\n\n")
        tokens=summary.get('api_usage_this_run',{}).get('total_tokens')
        text.insert('end',f"本次精修总 tokens：{tokens if tokens is not None else '服务未返回或本次全部复用缓存'}\n\n")
        for row in data.get('changes',[]):
            text.insert('end',f"第 {row['index']} 条\n原文：{row['source']}\n原译：{row['before']}\n精修：{row['after']}\n\n")
        for row in data.get('rejected',[]):text.insert('end',f"第 {row['index']} 条保留原译：{row['reason']}\n")
        text.configure(state='disabled')

    def _open_more(self):
        self.more_window.deiconify();self.more_window.lift()

    def _toggle_log(self):
        if self.log_frame.winfo_ismapped():self.log_frame.grid_remove()
        else:self.log_frame.grid()

    def _refresh_schemes(self):
        names=[p['name'] for p in self.profile_store.list()] if self.profile_store else []
        self.scheme_box.configure(values=[*[k for k,v in TRANSLATORS.items() if self.content_mode.get()!='日本动漫（日→中）' or v!='argos'],*['方案：'+n for n in names]])
        self.quick_scheme.set('方案：'+self.profile_name.get() if self.translator.get().startswith('API') and self.profile_name.get() in names else self.translator.get())

    def _pick_scheme(self,_event=None):
        value=self.quick_scheme.get()
        if value.startswith('方案：'):
            self.translator.set(next(k for k,v in TRANSLATORS.items() if v=='deepseek'))
            self.profile_name.set(value[3:]);self._load_profile()
        else:self.translator.set(value)
        self._translator_changed()

    def _select_task(self,_event=None):
        selection=tuple(self.tree.selection())
        if selection==self._last_selection:return
        self._last_selection=selection
        if self._pending_setting:self.after_cancel(self._pending_setting);self._pending_setting=None
        self._show_selected_log()
        selected=self.tree.selection()
        self._loading_task=True
        try:
            if len(selected)==1:
                job=self.jobs[selected[0]];self._fill_task_settings(job)
                self.subtitles_only.set(job.options.get('subtitles_only',False))
                self.global_understanding.set(job.options.get('global_understanding',True))
                self.economy_api.set(job.options.get('economy_api',True))
                self.selection_note.set(job.video.name+' · '+('可直接修改设置' if job.status=='待开始' else '设置已固定；修改前先取消排队或新建任务'))
            else:self.selection_note.set(f'选中 {len(selected)} 个视频；通过“更多操作”批量应用，保留各自片段范围。')
            self._refresh_schemes()
        finally:self._loading_task=False

    def _settings_changed(self,*_):
        if self._loading_task:return
        if self._pending_setting:self.after_cancel(self._pending_setting)
        self._pending_setting=self.after_idle(self._save_single_settings)

    def _save_single_settings(self):
        if self._pending_setting:self.after_cancel(self._pending_setting)
        self._pending_setting=None
        if len(self.tree.selection())==1 and self._editable_jobs():self._apply_selected_settings()
        self._refresh_schemes()

    def _rerender_result(self):
        import copy
        selected=self.tree.selection();old=self.jobs.get(selected[0]) if len(selected)==1 else None
        if not old or not old.output or old.status!='已完成':
            messagebox.showinfo('选择已完成任务','选择已完成的字幕或视频，再重新导出。',parent=self);return
        options=self._capture_settings(validate=False)
        if not options:return
        # Preserve source language, context snapshot and local transcript of this task.
        for key in ('source_language','content_mode','work_snapshot','clip_enabled','clip_start','clip_end','model'):
            if key in old.options:options[key]=copy.deepcopy(old.options[key])
        options['reviewed_srt']=str(old.output/(options.get('source_language','en')+'.srt'))
        options['subtitles_only']=False
        job=Job(old.video,options,info=dict(old.info))
        self.jobs[job.id]=job;self.tree.insert('','end',iid=job.id,values=self._row(job))
        self.tree.selection_set(job.id);self._select_task();self._update_summary()

    def _show_understanding(self):
        from engine import _read_json
        selected=self.tree.selection();job=self.jobs.get(selected[0]) if len(selected)==1 else None
        data=_read_json(job.output/'global-context.json',{}) if job and job.output else {}
        if not data:messagebox.showinfo('尚无全局理解','选择已完成全局理解的 API 任务；可在更多设置中开启。',parent=self);return
        import json
        dialog=tk.Toplevel(self);dialog.title('全局原文理解 · 自动译名为本作品约定，并非官方译名');dialog.geometry('900x650')
        text=tk.Text(dialog,wrap='word',font=('Microsoft YaHei UI',11));text.pack(fill='both',expand=True)
        text.insert('1.0',json.dumps(data,ensure_ascii=False,indent=2));text.configure(state='disabled')

    def _preview_result(self):
        selected=self.tree.selection();job=self.jobs.get(selected[0]) if len(selected)==1 else None
        if not job or not job.output or not (job.output/'bilingual.ass').is_file():
            messagebox.showinfo('先生成字幕','可在更多设置中勾选“仅导出字幕”，完成后预览 8 秒效果。',parent=self);return
        if self.active_id:return
        options=dict(job.options)
        options.update(render_mode='band' if self.render_mode.get().startswith('独立') else 'overlay',ppt_annotations=self.ppt_annotations.get(),preview_only=True)
        self.cancel_event=threading.Event();cancel=self.cancel_event
        def run():
            try:
                from engine import Engine
                path=Engine(self.app_root,lambda e:self.messages.put(('progress',job.id,e)),cancel).preview(job.video,job.output,options)
                self.messages.put(('ui_call',None,lambda:self._open_folder(path)))
            except Exception as e:self.messages.put(('ui_call',None,lambda text=str(e):messagebox.showerror('预览失败',text,parent=self)))
        threading.Thread(target=run,daemon=True).start()

    def _ppt_changed(self) -> None:
        if self.ppt_annotations.get():
            self.render_mode.set("独立字幕带 · 保留完整画面")
            self.render_box.configure(values=["独立字幕带 · 保留完整画面"])
        else:
            self.render_box.configure(values=["独立字幕带 · 保留完整画面", "画面内叠加 · 底部显示"])

    def _translator_changed(self, _event=None) -> None:
        code = TRANSLATORS[self.translator.get()]
        if self.test_cancel is None:self.test_button.configure(text='测试 API 调用' if code=='deepseek' else '测试当前翻译')
        for control in (self.refine_quick,self.refine_detail):control.configure(state="normal" if code=="deepseek" else "disabled")
        if code != "deepseek":self.auto_refine.set(False)
        if code == "deepseek":
            self.api_frame.grid()
            self.privacy.configure(text="API 会发送字幕。日语模式先自动整理固定译名（关闭全局理解时仍有名称分析调用）；全局理解每批只带精简摘要。密钥用 Windows 账户加密保存，硬件配置不发送。")
        else:
            self.api_frame.grid_remove()
            notes = {
                "argos": "Argos 离线备用 · 无需密钥 · 音视频及字幕文字均不上传。",
                "bing": "必应免费在线翻译 · 会发送字幕及 PPT 识别文字，音视频仍在本机。网页接口可能限流，失败后可手动改选 Argos 离线。",
                "google": "Google 免费接口可能限流，不保证可用。会发送字幕及 PPT 识别文字；遇限流立即停止，不自动切换或反复请求。",
            }
            note = notes[code]
            if self.content_mode.get()=='日本动漫（日→中）':
                note += ' 动漫模式：复用已有作品译名；新名称可保留日文原名以保持一致，不自动调用付费 API。复杂关系和语气不支持提示词控制。' if code!='argos' else ' 动漫模式不可使用当前英中离线包。'
            self.privacy.configure(text=note)
        self.after_idle(self._fit_viewport)

    def _choose_videos(self) -> None:
        paths = filedialog.askopenfilenames(parent=self, title="选择视频（可多选）", filetypes=[("视频文件", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mpeg *.mpg"), ("所有文件", "*.*")])
        if paths:
            self.enqueue([Path(p) for p in paths])

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="选择视频文件夹（仅当前层）")
        if not folder:
            return
        try:
            videos = sorted((p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES), key=lambda p: p.name.casefold())
        except OSError as exc:
            messagebox.showerror("无法读取文件夹", str(exc), parent=self)
            return
        if not videos:
            messagebox.showinfo("没有找到视频", "此文件夹的当前层没有支持的视频文件。", parent=self)
            return
        self.enqueue(videos)

    def _choose_output(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="选择导出位置")
        if folder:
            self.output_root.set(folder)

    def _load_profile(self,_event=None):
        if not self.profile_store:return
        try:
            item=self.profile_store.load(self.profile_name.get())
            self.api_base.set(item['api_base']);self.model_name.set(item['model_name']);self.api_key.set(item['api_key'])
        except (OSError,ValueError,RuntimeError,StopIteration) as error:
            messagebox.showerror('无法读取方案',str(error),parent=self)

    def _save_profile(self):
        try:
            if not self.profile_store:raise ValueError('翻译方案文件无法读取，原文件已保留。')
            code=self.profile_store.save(self.profile_name.get(),self.api_base.get(),self.model_name.get(),self.api_key.get())
            self.profile_box.configure(values=[p['name'] for p in self.profile_store.list()]);self._refresh_schemes()
            messagebox.showinfo('方案已保存',f'已保存“{self.profile_name.get().strip()}”（编号 {code:03d}）。\n下次选择此方案即可恢复地址、模型和密钥。密钥只可由当前 Windows 账户解密。',parent=self)
        except (OSError,ValueError,RuntimeError) as error:
            messagebox.showerror('无法保存方案',str(error),parent=self)

    def _delete_profile(self):
        if not self.profile_store:return
        name=self.profile_name.get().strip()
        if name not in [p['name'] for p in self.profile_store.list()]:return
        self.profile_store.delete(name);self.profile_name.set('');self.api_key.set('')
        self.profile_box.configure(values=[p['name'] for p in self.profile_store.list()]);self._refresh_schemes()

    def _test_translation(self):
        if self.test_cancel is not None:return
        options=self._snapshot_options()
        if options is None:return
        self.test_cancel=threading.Event();cancel=self.test_cancel
        self.test_button.configure(text='正在测试…',state='disabled')
        def finish(text,success):
            self.test_cancel=None;self.test_button.configure(text='测试 API 调用' if TRANSLATORS[self.translator.get()]=='deepseek' else '测试当前翻译',state='normal')
            if success:messagebox.showinfo('翻译测试成功','已使用当前地址、密钥和模型，实际翻译短句：\n'+('また明日、学校で会おう。' if options.get('source_language')=='ja' else 'The signal is clear.')+'\n\n返回译文：'+text,parent=self)
            else:messagebox.showerror('翻译测试未通过',self._redact(text),parent=self)
        def run():
            from engine import Engine
            try:
                text=Engine(self.app_root,None,cancel).test_translation(options)
                self.messages.put(('ui_call',None,lambda text=text:finish(text,True)))
            except Exception as error:
                text=str(error).replace(options.get('api_key') or '\0','[密钥已隐藏]')
                self.messages.put(('ui_call',None,lambda text=text:finish(text,False)))
        threading.Thread(target=run,daemon=True,name='translation-test').start()

    def _download_dialog(self):
        from downloads import validate_url
        if getattr(self,'download_window',None) is not None and self.download_window.winfo_exists():
            self.download_window.lift();return
        dialog=tk.Toplevel(self);self.download_window=dialog
        dialog.title('链接下载 · YouTube / X');dialog.geometry('790x540');dialog.minsize(670,540)
        dialog.transient(self)
        body=ttk.Frame(dialog,padding=20);body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=1)
        ttk.Label(body,text='粘贴 YouTube 或 X/Twitter 的具体视频链接',font=('Microsoft YaHei UI',12,'bold')).grid(row=0,column=0,columnspan=2,sticky='w')
        url=tk.StringVar();entry=ttk.Entry(body,textvariable=url,name='download_url');entry.grid(row=1,column=0,sticky='ew',pady=12)
        def paste():
            try:url.set(self.clipboard_get().strip())
            except tk.TclError:pass
        ttk.Button(body,text='粘贴',command=paste).grid(row=1,column=1,padx=(8,0))
        path_row=ttk.Frame(body);path_row.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(0,10))
        ttk.Label(path_row,text='保存位置').pack(side='left',padx=(0,10))
        path_entry=ttk.Entry(path_row,textvariable=self.download_parent,name='download_parent');path_entry.pack(side='left',fill='x',expand=True)
        def choose_parent():
            selected=filedialog.askdirectory(parent=dialog,title='选择下载保存位置')
            if selected:self.download_parent.set(selected)
        browse_button=ttk.Button(path_row,text='选择文件夹',command=choose_parent);browse_button.pack(side='left',padx=(8,0))
        name_row=ttk.Frame(body);name_row.grid(row=3,column=0,columnspan=2,sticky='ew')
        ttk.Label(name_row,text='文件夹与视频名称').pack(side='left',padx=(0,10))
        name=tk.StringVar(value='视频下载_'+datetime.now().strftime('%y%m%d%H%M%S'))
        name_entry=ttk.Entry(name_row,textvariable=name,name='download_name');name_entry.pack(side='left',fill='x',expand=True)
        ttk.Label(body,text='保存位置下新建此名称的文件夹，视频也使用此名称。无需填写扩展名，同名文件夹自动编号。',wraplength=710).grid(row=4,column=0,columnspan=2,sticky='w',pady=(5,10))
        quality=tk.StringVar(value='最高可用画质')
        ttk.Combobox(body,textvariable=quality,values=['最高可用画质','最高 1080p','最高 720p'],state='readonly').grid(row=5,column=0,sticky='w')
        ttk.Label(body,text='只下载单个视频；音视频合并不重新压缩。登录或网站验证可能影响下载。',wraplength=700).grid(row=6,column=0,columnspan=2,sticky='w',pady=10)
        auto=tk.BooleanVar(value=False)
        ttk.Checkbutton(body,text='下载完成后导入处理队列（仍按当前翻译设置确认）',variable=auto).grid(row=7,column=0,columnspan=2,sticky='w')
        status=tk.StringVar(value='下载前可以修改保存位置和名称，原有文件不会被覆盖。')
        ttk.Label(body,textvariable=status,wraplength=710).grid(row=8,column=0,columnspan=2,sticky='w',pady=12)
        progress=ttk.Progressbar(body,maximum=100);progress.grid(row=9,column=0,columnspan=2,sticky='ew')
        buttons=ttk.Frame(body);buttons.grid(row=10,column=0,columnspan=2,sticky='e',pady=14)
        result=[None]
        def finish(event,error=None):
            self.download_cancel=None
            if not dialog.winfo_exists():return
            start_button.configure(state='normal');cancel_button.configure(state='disabled')
            for widget in (path_entry,name_entry,browse_button):widget.configure(state='normal')
            if error:status.set(error);return
            result[0]=Path(event['path']);progress['value']=100
            status.set(f"下载完成 · {event.get('width') or '?'}×{event.get('height') or '?'}\n{result[0]}")
            open_button.configure(state='normal')
            if auto.get():self.enqueue([result[0]])
        def begin():
            if self.download_cancel is not None:return
            try:link=validate_url(url.get())
            except ValueError as error:messagebox.showerror('链接无效',str(error),parent=dialog);return
            from engine import Engine
            from downloads import reserve_download_folder
            try:
                if not self.download_parent.get().strip():raise ValueError('请选择保存位置。')
                folder=reserve_download_folder(self.download_parent.get().strip(),name.get())
            except (OSError,ValueError,RuntimeError) as error:messagebox.showerror('无法创建下载目录',str(error),parent=dialog);return
            self.download_cancel=threading.Event();cancel=self.download_cancel
            payload={'url':link,'folder':str(folder),'filename':folder.name,'ffmpeg':str(self.app_root/'bin/ffmpeg.exe'),
                     'height':{'最高可用画质':'best','最高 1080p':'1080','最高 720p':'720'}[quality.get()]}
            start_button.configure(state='disabled');cancel_button.configure(state='normal');open_button.configure(state='disabled')
            for widget in (path_entry,name_entry,browse_button):widget.configure(state='disabled')
            status.set('正在读取视频信息…');progress['value']=0
            def update(event):
                if not dialog.winfo_exists():return
                status.set(event.get('message',''))
                if event.get('percent') is not None:progress['value']=event['percent']
            def run():
                completed=[]
                def event(data):
                    if data.get('type')=='download_done':completed.append(data)
                    elif data.get('type')=='download_progress':self.messages.put(('ui_call',None,lambda data=data:update(data)))
                try:
                    Engine(self.app_root,None,cancel)._worker('download',payload,event)
                    if not completed:raise RuntimeError('未获得下载文件。')
                    self.messages.put(('ui_call',None,lambda:finish(completed[0])))
                except Exception as error:
                    text='下载已停止。' if cancel.is_set() else str(error)
                    self.messages.put(('ui_call',None,lambda text=text:finish({},text)))
            threading.Thread(target=run,daemon=True,name='video-download').start()
        def stop():
            if self.download_cancel:self.download_cancel.set();status.set('正在停止下载…')
        def close():stop();dialog.destroy()
        open_button=ttk.Button(buttons,text='打开下载位置',command=lambda:self._open_folder(result[0].parent) if result[0] else None,state='disabled');open_button.pack(side='left',padx=5)
        cancel_button=ttk.Button(buttons,text='取消下载',command=stop,state='disabled');cancel_button.pack(side='left',padx=5)
        start_button=ttk.Button(buttons,text='下载',style='Accent.TButton',command=begin);start_button.pack(side='left',padx=5)
        dialog.protocol('WM_DELETE_WINDOW',close);entry.focus_set()

    def _snapshot_options(self) -> dict | None:
        return self._capture_settings(validate=True)

    def enqueue(self, paths: list[Path]) -> None:
        self._import_jobs(paths)

    def _confirm_online(self, count: int, options: dict) -> bool:
        provider = "必应" if options["translator"] == "bing" else "Google"
        return messagebox.askyesno("确认发送待翻译文字", f"本批 {count} 个视频将使用 {provider} 免费在线翻译。\n\n原文字幕及已启用的 PPT 识别文字会发送给该服务，音视频不上传。免费接口不接收人物表和上下文提示。请确认文字中没有你不希望发送的私人内容。\n\n选择“否”将保留待开始任务，不发送文字。是否继续？", parent=self, default="no")

    def _confirm_paid(self, count: int, options: dict) -> bool:
        refinement_note='开启，沿用当前方案再校对，可能增加 API 费用' if options.get('auto_refine') else '关闭'
        return messagebox.askyesno("确认使用付费翻译", f"即将使用 {options['model_name']} 处理 {count} 个视频的字幕。\n全局理解：{'开启，先分析本次全部原文，长稿分段归纳' if options.get('global_understanding') else '关闭，日语模式仍会分析原文以自动统一译名'}。\n自动精修：{refinement_note}。\nDeepSeek 省用量：{'开启，低思考分析／无思考翻译' if options.get('economy_api',True) else '关闭，使用服务默认思考设置'}（仅已支持的模型）。\n\n原文字幕、相关上下文、作品资料（动漫模式）及已启用的 PPT 文字将发送到：\n{options['api_base']}\n\n分析和翻译均可能计费，缓存命中则复用，失败不会自动重发。硬件配置不发送。\n确认后本批任务才会排队开始。是否继续？", parent=self, default="no")

    def _row(self, job: Job) -> tuple:
        service = {"bing": "必应 · 免费", "google": "Google · 免费", "argos": "Argos · 离线", "deepseek": job.options.get('profile_name') or job.options.get('model_name','API')}[job.options["translator"]]
        if job.options.get('auto_refine'):service+=' · 精修'
        a=job.options.get("clip_start",0);b=job.options.get("clip_end",0)
        from range_picker import time_text
        span=time_text(a)+"–"+time_text(b) if job.options.get("clip_enabled") else "全片"
        language="日→中" if job.options.get("source_language")=="ja" else "英→中"
        return job.video.name, language+" · "+service, span, job.status, f"{job.progress:.0f}%", job.stage

    def _refresh_job(self, job: Job) -> None:
        tag = "done" if job.status == "已完成" else "failed" if job.status == "失败" else "stopped" if job.status == "已停止" else ""
        self.tree.item(job.id, values=self._row(job), tags=(tag,) if tag else ())

    def _start_next(self) -> None:
        if self.active_id or self.closing or self.queue_paused:
            return
        job = next((j for j in self.jobs.values() if j.status == "待处理"), None)
        if job is None:
            self.status_text.set("准备就绪" if not self.jobs else "队列处理结束")
            self._update_summary()
            return
        self.active_id = job.id
        job.status = "处理中"
        job.stage = "准备中"
        self.cancel_event = threading.Event()
        self.progress_value.set(0)
        self.progress_text.set(f"正在处理：{job.video.name}")
        self.status_text.set("正在处理")
        self.stop_button.configure(state="normal")
        self._refresh_job(job)
        self.tree.selection_set(job.id)
        self.tree.see(job.id)
        self._show_selected_log()
        self._update_summary()
        self.worker = threading.Thread(target=self._run_job, args=(job, self.cancel_event), daemon=True, name="bilingual-video-worker")
        self.worker.start()

    def _run_job(self, job: Job, cancel: threading.Event) -> None:
        def callback(event: dict) -> None:
            self.messages.put(("progress", job.id, dict(event)))
        try:
            from engine import Engine
            options=dict(job.options)
            if job.output:options['resume_from']=str(job.output)
            output = Engine(self.app_root, callback, cancel).run(str(job.video), options)
            if cancel.is_set():
                self.messages.put(("stopped", job.id, None))
            elif output:
                from engine import _read_json
                phase = 'review' if _read_json(output/'project.json',{}).get('status')=='awaiting_review' else 'done'
                self.messages.put((phase, job.id, str(output)))
            else:
                self.messages.put(("failed", job.id, "处理引擎未返回导出目录，请查看处理记录。"))
        except Exception as exc:
            if cancel.is_set():
                self.messages.put(("stopped", job.id, None))
            else:
                self.messages.put(("failed", job.id, str(exc) or type(exc).__name__))

    def _redact(self, text: str) -> str:
        # Do not allow a provider's exception text to echo a credential into the UI.
        keys = [self.api_key.get()] + [j.options.get("api_key", "") for j in self.jobs.values()]
        for key in keys:
            if key:
                text = text.replace(key, "[密钥已隐藏]")
        return text

    def _poll_messages(self) -> None:
        try:
            while True:
                kind, job_id, data = self.messages.get_nowait()
                if kind=='ui_call':
                    if not self.closing:data()
                    continue
                job = self.jobs.get(job_id)
                if job is None:
                    continue
                if kind == "progress":
                    if data.get('output_directory'):job.output=Path(data['output_directory'])
                    stage = str(data.get("stage") or "")
                    if stage:
                        job.stage = STAGES.get(stage, stage)
                    try:
                        progress = float(data.get("progress", job.progress))
                        job.progress = max(0.0, min(100.0, progress))
                    except (TypeError, ValueError):
                        pass
                    message = self._redact(str(data.get("message") or ""))
                    if message and (not job.logs or message != job.logs[-1]):
                        job.logs.append(message)
                        job.logs = job.logs[-800:]
                    if job_id == self.active_id:
                        self.progress_value.set(job.progress)
                        self.progress_text.set(f"{job.video.name}  ·  {job.stage}  ·  {job.progress:.0f}%  ·  已用 {float(data.get('elapsed_seconds',0))/60:.1f} 分钟")
                else:
                    if kind == "review":
                        job.status, job.stage, job.progress = "待校对", "原文已准备，点击校对后继续", 42.0
                        job.output = Path(data)
                        job.logs.append("尚未翻译。点击“校对原文 / 继续翻译”编辑台词和作品译名表。")
                    elif kind == "done":
                        job.status, job.stage, job.progress = "已完成", "导出完成", 100.0
                        job.output = Path(data)
                        job.logs.append(f"处理完成。结果保存在：{data}")
                        from engine import _read_json
                        warnings=_read_json(job.output/"project.json",{}).get("name_warning_count",0)
                        if warnings:job.stage=f"已导出 · {warnings} 处译名待核对"
                    elif kind == "stopped":
                        job.status, job.stage = "已停止", "可重新加入队列"
                        job.logs.append("已停止当前任务。队列已暂停；点击“继续队列”处理其他视频。")
                    else:
                        job.status, job.stage = "失败", "查看记录后重试"
                        job.logs.append("处理失败：" + self._redact(str(data)))
                    self.progress_value.set(job.progress)
                    from engine import _read_json
                    timing=_read_json(job.output/'timings.json',{}) if job.output else {}
                    if timing:job.logs.append('阶段耗时：'+' · '.join(f'{STAGES.get(k,k)} {v:.1f} 秒' for k,v in timing.get('stages_seconds',{}).items()))
                    self.progress_text.set(f"{job.video.name}  ·  {job.status}  ·  用时 {timing.get('total_seconds',0)/60:.1f} 分钟")
                    self.active_id = None
                    self.cancel_event = None
                    self.stop_button.configure(state="disabled")
                    if self.queue_paused:
                        self.status_text.set("队列已暂停")
                        self.resume_button.configure(state="normal")
                    elif not self.closing:
                        self.after(150, self._start_next)
                self._refresh_job(job)
                self._update_summary()
                selected = self.tree.selection()
                if selected and selected[0] == job_id:
                    self._show_selected_log()
        except queue.Empty:
            pass
        if self.closing and self.active_id is None:
            self.destroy()
            return
        self.after(100, self._poll_messages)

    def _stop_current(self) -> None:
        if self.cancel_event is None or self.active_id is None:
            return
        self.queue_paused = True
        self.cancel_event.set()
        job = self.jobs[self.active_id]
        job.status = "正在停止"
        job.stage = "等待当前步骤退出"
        self._refresh_job(job)
        self.stop_button.configure(state="disabled")
        self.status_text.set("正在停止")
        self.progress_text.set("正在安全停止当前任务；其余任务保留在队列。")

    def _resume_queue(self) -> None:
        if self.active_id or self.closing:
            return
        self.queue_paused = False
        self.resume_button.configure(state="disabled")
        self._start_next()

    def _retry_selected(self) -> None:
        for identifier in self.tree.selection():
            job = self.jobs[identifier]
            if job.status in {'失败', '已停止'}:
                job.status, job.stage, job.progress = '待开始', '可修改或点击开始重试', 0.0
                self._refresh_job(job)
        self._update_summary()

    def _remove_pending(self) -> None:
        selected = self.tree.selection()
        removable = [j for j in selected if self.jobs[j].status in {"待开始", "待处理"}]
        if not removable:
            messagebox.showinfo("选择待处理任务", "只有尚未开始的任务可以从队列移除。", parent=self)
            return
        for job_id in removable:
            self.tree.delete(job_id)
            del self.jobs[job_id]
        self._update_summary()
        self._show_selected_log()

    def _update_summary(self) -> None:
        counts = {status: sum(j.status == status for j in self.jobs.values()) for status in ('待开始','待处理','待校对','已完成','失败')}
        self.queue_summary.set('  ·  '.join(f'{status} {count}' for status,count in counts.items()) if self.jobs else '还没有视频')

    def _set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _show_selected_log(self, _event=None) -> None:
        selected = self.tree.selection()
        if selected and selected[0] in self.jobs:
            job = self.jobs[selected[0]]
            self._set_log("\n".join(job.logs))

    def _edit_ppt(self) -> None:
        import json
        selected = self.tree.selection()
        job = self.jobs.get(selected[0]) if selected else None
        if not job or job.status != "已完成" or not job.output:
            messagebox.showinfo("先选择已完成的任务", "选中已启用 PPT 翻译并完成的任务，再校对注释。", parent=self)
            return
        folder = job.output / "ppt"
        try:
            data = json.loads((folder / "annotations.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            messagebox.showinfo("没有 PPT 注释", "此任务未启用 PPT 翻译。请勾选该选项后重新导入视频。", parent=self)
            return
        blocks = {}
        for page in data["pages"]:
            for block in page["blocks"]:
                blocks.setdefault(block["id"], block)
        if not blocks:
            messagebox.showinfo("未找到稳定说明文字", "没有识别到符合条件的稳定 PPT 说明。原画面仍完整保留；识别记录在工程的 ppt 文件夹。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("校对 PPT 中文注释")
        dialog.geometry("1040x690")
        dialog.transient(self)
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text="选择文字块，修改中文或取消显示；保存后可重新导出。", padding=16).grid(row=0, column=0, columnspan=2, sticky="w")
        listing = tk.Listbox(dialog, width=38, font=("Microsoft YaHei UI", 10), exportselection=False)
        listing.grid(row=1, column=0, sticky="nsew", padx=(16, 10), pady=10)
        detail = ttk.Frame(dialog, padding=12)
        detail.grid(row=1, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)
        shown = tk.BooleanVar(value=True)
        ttk.Checkbutton(detail, text="在成片中显示此注释", variable=shown).grid(row=0, column=0, sticky="w")
        original = tk.Text(detail, height=7, wrap="word", font=("Microsoft YaHei UI", 11))
        original.grid(row=1, column=0, sticky="ew", pady=12)
        ttk.Label(detail, text="中文注释（不修改原英文画面）").grid(row=2, column=0, sticky="w")
        chinese = tk.Text(detail, height=10, wrap="word", font=("Microsoft YaHei UI", 12))
        chinese.grid(row=3, column=0, sticky="nsew", pady=10)
        keys = list(blocks)
        from engine import _read_json
        saved = _read_json(folder / "overrides.json", {})
        edits = {key: {"translation": saved.get(key, {}).get("translation", b["translation"]),
                       "enabled": saved.get(key, {}).get("enabled", b.get("enabled", True))} for key, b in blocks.items()}
        current = [None]
        for key in keys:
            listing.insert("end", blocks[key]["text"][:38])
        def stash():
            if current[0] is not None:
                text = chinese.get("1.0", "end-1c").strip()
                if not text:
                    messagebox.showinfo("注释不能为空", "请输入译文；如不需要这条注释，请取消显示。", parent=dialog)
                    return False
                edits[current[0]] = {"translation": text, "enabled": shown.get()}
            return True
        def choose(_event=None):
            selection = listing.curselection()
            if not selection or not stash(): return
            key = keys[selection[0]]
            current[0] = key
            original.configure(state="normal")
            original.delete("1.0", "end")
            original.insert("end", blocks[key]["text"])
            original.configure(state="disabled")
            chinese.delete("1.0", "end")
            chinese.insert("end", edits[key]["translation"])
            shown.set(edits[key]["enabled"])
        def save(rerender=False):
            if not stash(): return
            from engine import _atomic_json
            _atomic_json(folder / "overrides.json", edits)
            if rerender:
                if self.active_id:
                    messagebox.showinfo("已有任务在处理", "校对已保存。请在当前任务结束后再次点击重新导出。", parent=dialog)
                    return
                if job.options["translator"] in ("bing", "google") and not self._confirm_online(1, job.options): return
                if job.options["translator"] == "deepseek" and not self._confirm_paid(1, job.options): return
                job.status, job.stage, job.progress = "待处理", "应用 PPT 校对后重新导出", 0.0
                job.options['rerender_ppt']=True
                self._refresh_job(job)
                self.queue_paused = False
                dialog.destroy()
                self._start_next()
            else:
                messagebox.showinfo("已保存", "校对已保存。点击“保存并重新导出”后，成片才会应用修改。", parent=dialog)
        buttons = ttk.Frame(dialog, padding=12)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="保存校对", command=save).pack(side="left", padx=6)
        ttk.Button(buttons, text="保存并重新导出", command=lambda: save(True)).pack(side="left", padx=6)
        listing.bind("<<ListboxSelect>>", choose)
        listing.selection_set(0)
        choose()


    def _open_output(self) -> None:
        selected = self.tree.selection()
        job = self.jobs.get(selected[0]) if selected else None
        folder = job.output if job and job.output else Path(self.output_root.get()).expanduser()
        self._open_folder(folder)

    def _open_selected_result(self, _event=None) -> None:
        selected = self.tree.selection()
        job = self.jobs.get(selected[0]) if selected else None
        if job and job.output:
            self._open_folder(job.output)

    def _open_folder(self, folder: Path) -> None:
        try:
            folder = folder.resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        except OSError as exc:
            messagebox.showerror("无法打开文件夹", str(exc), parent=self)

    def _on_close(self) -> None:
        if self.closing:
            return
        if self.asset_cancel:self.asset_cancel.set()
        if self.glossary_cancel:self.glossary_cancel.set()
        if self.test_cancel:self.test_cancel.set()
        if self.download_cancel:self.download_cancel.set()
        if self.active_id:
            if not messagebox.askyesno("停止处理并退出？", "当前视频还在处理中。\n\n退出会停止当前任务，并清空本次窗口的等待队列。已导出的文件会保留。\n是否停止处理并退出？", parent=self, default="no"):
                return
            self.closing = True
            self._stop_current()
            self.status_text.set("正在退出")
            self.progress_text.set("正在停止处理，完成后窗口会自动关闭。")
        else:
            if any(j.status in {"待开始", "待处理", "待校对"} for j in self.jobs.values()) and not messagebox.askyesno("退出并清空等待队列？", "等待队列仅保存在当前窗口，退出后需要重新导入。已导出的文件会保留。", parent=self, default="no"):
                return
            self.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="本地中英双语视频桌面工具")
    parser.add_argument("--smoke-test", action="store_true", help="创建真实窗口，短暂显示后退出")
    args = parser.parse_args()
    app = BilingualApp()
    if args.smoke_test:
        app.after(1000, app.destroy)
    app.mainloop()
    if args.smoke_test:
        print("GUI_SMOKE_OK: native Tk window created and closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
