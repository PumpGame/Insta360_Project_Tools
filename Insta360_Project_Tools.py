#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

#test

CFG = os.path.expanduser("~/.insta360_project_tools.json")

def load_cfg():
    if os.path.exists(CFG):
        try:
            with open(CFG,"r",encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"recent":[]}

cfg = load_cfg()

root = tk.Tk()
root.title("Insta360 Project Tools")
root.geometry("700x250")

selected = tk.StringVar()
scale = tk.DoubleVar(value=1.30)
overwrite = tk.BooleanVar(value=True)

def save_cfg():
    with open(CFG,"w",encoding="utf-8") as f:
        json.dump(cfg,f,indent=2)

def remember(path):
    path=os.path.abspath(path)
    lst=[p for p in cfg["recent"] if p!=path]
    lst.insert(0,path)
    cfg["recent"]=lst[:10]
    save_cfg()
    refresh_recent()

def refresh_recent():
    menu["menu"].delete(0,"end")
    if not cfg["recent"]:
        menu["menu"].add_command(label="(empty)")
        return
    for p in cfg["recent"]:
        menu["menu"].add_command(
            label=os.path.basename(p),
            command=lambda x=p: open_project(x)
        )

def open_project(path):
    if os.path.exists(path):
        selected.set(path)
        remember(path)

def browse():
    initial=os.path.dirname(selected.get()) if selected.get() else (
        os.path.dirname(cfg["recent"][0]) if cfg["recent"] else os.path.expanduser("~")
    )
    f=filedialog.askopenfilename(
        initialdir=initial,
        filetypes=[("Insta360 Project","*.insproj *.insprj"),("All files","*.*")]
    )
    if f:
        open_project(f)

def reveal():
    p=selected.get()
    if p and os.path.exists(p):
        if sys.platform=="darwin":
            os.system(f'open -R "{p}"')
        elif os.name=="nt":
            os.system(f'explorer /select,"{p}"')

def process():
    path=selected.get()
    if not path:
        messagebox.showerror("Error","Choose project")
        return
    with open(path,"r",encoding="utf-8") as f:
        data=json.load(f)
    count=0
    def walk(o):
        nonlocal count
        if isinstance(o,dict):
            if "fov" in o and isinstance(o["fov"],(int,float)):
                o["fov"]*=scale.get()
                count+=1
            for v in o.values():
                walk(v)
        elif isinstance(o,list):
            for i in o:
                walk(i)
    walk(data)

    if overwrite.get():
        backup=os.path.splitext(path)[0]+"_backup"+os.path.splitext(path)[1]
        if not os.path.exists(backup):
            shutil.copy2(path,backup)
        out=path
    else:
        base,ext=os.path.splitext(path)
        out=base+"_modified"+ext

    with open(out,"w",encoding="utf-8") as f:
        json.dump(data,f,ensure_ascii=False,separators=(",",":"))

    messagebox.showinfo("Done",f"Modified {count} keyframes.")

# argv support
if len(sys.argv)>1 and os.path.exists(sys.argv[1]):
    open_project(sys.argv[1])
elif cfg["recent"]:
    selected.set(cfg["recent"][0])

tk.Label(root,text="Project").pack(anchor="w",padx=10,pady=(10,2))
fr=tk.Frame(root)
fr.pack(fill="x",padx=10)

tk.Entry(fr,textvariable=selected).pack(side="left",fill="x",expand=True)

tk.Button(fr,text="Browse",command=browse).pack(side="left",padx=2)
tk.Button(fr,text="Reveal",command=reveal).pack(side="left",padx=2)

recent_var=tk.StringVar(value="Recent")
menu=tk.OptionMenu(fr,recent_var,"")
menu.pack(side="left",padx=2)
refresh_recent()

opt=tk.Frame(root)
opt.pack(fill="x",padx=10,pady=15)
tk.Label(opt,text="FOV scale").pack(side="left")
tk.Scale(opt,from_=0.5,to=2.0,resolution=0.01,orient="horizontal",length=300,variable=scale).pack(side="left")
tk.Checkbutton(root,text="Overwrite original (backup once)",variable=overwrite).pack(anchor="w",padx=10)

tk.Button(root,text="Apply",height=2,width=20,command=process).pack(pady=15)

root.mainloop()
