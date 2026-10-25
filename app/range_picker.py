"""Optional two-handle selection, expressed in the original video's timeline."""
import math
import tkinter as tk
from tkinter import ttk,messagebox


def time_text(seconds):
    total=round(seconds*1000);s,ms=divmod(total,1000);m,s=divmod(s,60);h,m=divmod(m,60)
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def time_value(text):
    parts=text.strip().split(':')
    if len(parts)>3:raise ValueError('时间格式应为 时:分:秒。')
    value=0.0
    for part in parts:
        n=float(part)
        if n<0 or not math.isfinite(n):raise ValueError('请输入有效时间。')
        value=value*60+n
    return value


class RangePicker(tk.Toplevel):
    def __init__(self,parent,video,info,initial=None):
        super().__init__(parent)
        self.title('选择需要翻译的片段');self.geometry('820x310');self.minsize(650,310)
        self.transient(parent);self.grab_set();self.result=None
        self.duration=info['duration'];self.start,self.end=initial or (0.,self.duration)
        self.start=max(0,min(self.start,self.duration-.1));self.end=max(self.start+.1,min(self.end,self.duration))
        self.active=None
        body=ttk.Frame(self,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text=video.name,font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(body,text=f"原画面 {info['width']}×{info['height']} · 总时长 {time_text(self.duration)}").pack(anchor='w',pady=(5,3))
        ttk.Label(body,text='拖动两端的圆点选取范围，也可以直接输入时间；字幕会从片段的 00:00 开始。').pack(anchor='w')
        self.canvas=tk.Canvas(body,height=65,bg='#f3f6fa',highlightthickness=0,cursor='hand2')
        self.canvas.pack(fill='x',pady=8)
        self.canvas.bind('<Configure>',self.draw);self.canvas.bind('<Button-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'active',None))
        row=ttk.Frame(body);row.pack(fill='x')
        self.a=tk.StringVar(value=time_text(self.start));self.b=tk.StringVar(value=time_text(self.end))
        ttk.Label(row,text='开始').pack(side='left')
        for var,label in [(self.a,'— 结束'),(self.b,None)]:
            entry=ttk.Entry(row,textvariable=var,width=17);entry.pack(side='left',padx=8)
            entry.bind('<Return>',self.apply_entries);entry.bind('<FocusOut>',self.apply_entries)
            if label:ttk.Label(row,text=label).pack(side='left')
        self.selected=tk.StringVar();ttk.Label(row,textvariable=self.selected).pack(side='right')
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=(15,0))
        ttk.Button(buttons,text='恢复全片',command=self.reset).pack(side='left')
        ttk.Button(buttons,text='取消修改',command=self.destroy).pack(side='right')
        ttk.Button(buttons,text='使用此片段',style='Accent.TButton',command=self.accept).pack(side='right',padx=8)
        self.bind('<Escape>',lambda e:self.destroy());self.draw()

    def draw(self,_event=None):
        w=max(1,self.canvas.winfo_width());self.left=18;self.right=max(19,w-18)
        self.canvas.delete('all');y=22
        x=lambda t:self.left+(self.right-self.left)*t/self.duration
        self.canvas.create_line(self.left,y,self.right,y,width=7,fill='#ccd7e0')
        self.canvas.create_line(x(self.start),y,x(self.end),y,width=7,fill='#167b76')
        for t in (self.start,self.end):
            self.canvas.create_oval(x(t)-8,y-10,x(t)+8,y+10,fill='#167b76',outline='white',width=2)
        self.canvas.create_text(self.left,50,text='00:00',anchor='w',fill='#607187')
        self.canvas.create_text(self.right,50,text=time_text(self.duration),anchor='e',fill='#607187')
        self.selected.set(f'已选 {self.end-self.start:.2f} 秒') if hasattr(self,'selected') else None

    def press(self,event):
        t=(event.x-self.left)/(self.right-self.left)*self.duration
        self.active='start' if abs(t-self.start)<=abs(t-self.end) else 'end';self.drag(event)

    def drag(self,event):
        if not self.active:return
        t=max(0,min(self.duration,(event.x-self.left)/(self.right-self.left)*self.duration))
        if self.active=='start':self.start=min(t,self.end-.1)
        else:self.end=max(t,self.start+.1)
        self.a.set(time_text(self.start));self.b.set(time_text(self.end));self.draw()

    def apply_entries(self,_event=None):
        try:
            a,b=time_value(self.a.get()),time_value(self.b.get())
            if not 0<=a<b<=self.duration+.001 or b-a<.1:raise ValueError('结束时间需晚于开始时间，且范围不能超出原视频。')
            self.start,self.end=a,min(b,self.duration);self.draw();return True
        except ValueError as error:
            if _event is None:messagebox.showerror('时间无效',str(error),parent=self)
            return False

    def reset(self):
        self.start,self.end=0.,self.duration;self.a.set(time_text(self.start));self.b.set(time_text(self.end));self.draw()

    def accept(self):
        if self.apply_entries():self.result=(self.start,self.end);self.destroy()
