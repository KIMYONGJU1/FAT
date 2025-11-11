
# -*- coding: utf-8 -*-
"""
FAT AutoFill Pro (v2.4.2_fix13b)
- 안정 진짜수정: SyntaxError 제거, 스레드 기반 Progressbar로 무응답 방지
- Hull 변경 시 Class 자동 반영
"""
from __future__ import annotations

APP_NAME = "FAT AutoFill Pro (v2.4.2_fix13c)"

import os
import re, re, datetime, threading, traceback
from typing import Dict, Optional, List, Callable
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
# lazy import to prevent startup crash if docxtpl is missing
def DocxTemplate(*args, **kwargs):
    try:
        from docxtpl import DocxTemplate as _DocxTemplate
    except Exception:
        print("[ERROR] docxtpl is not installed. Run: python -m pip install -r requirements.txt")
        raise
    return _DocxTemplate(*args, **kwargs)


import extractors as ex

FIELDS = [
    "customer","hull_no","owner","class","Kind_of_Vessel","item",
    "ms_quantity","ms_tr_capacity","ms_fault_level","ms_current","ms_main_bus",
    "ms_munsell_code","ms_ip","ms_rating","ms_dwg_no","ms_rev_no",
    "gsp_paint","gsp_ip","gsp_quantity","gsp_dwg_no","gsp_rev_no"
]

def merge_cover(msbd_cover: Dict, gsp_cover: Dict) -> Dict:
    fields: Dict[str,str] = {}
    hull_to_class: Dict[str,str] = {}
    titles: List[str] = []
    for src in (msbd_cover, gsp_cover):
        if not src:
            continue
        fields.update(src.get("fields", {}))
        for k,v in src.get("hull_to_class", {}).items():
            hull_to_class.setdefault(k, v)
        for t in src.get("titles", []):
            if t not in titles:
                titles.append(t)
    if titles:
        fields["item"] = " & ".join(titles)
    return {"fields": fields, "hull_to_class": hull_to_class}

def combine_all(a: Dict[str,str], b: Dict[str,str]) -> Dict[str,str]:
    out = dict(a)
    for k,v in b.items():
        if v and not out.get(k):
            out[k] = v
    return out

class App(tk.Tk):
    @staticmethod
    def _slug_panel(name: str) -> str:
        try:
            import re
            s = (name or '').upper()
            # unify BUS TIE vs BUS-TIE, remove spaces/dots
            s = s.replace('BUS TIE','BUS-TIE')
            s = s.replace('NO. ', 'NO.')
            return re.sub(r'[^A-Z0-9]+','', s)
        except Exception:
            return (name or '').upper()

    def log(self, msg: str):
        try:
            self.after(0, lambda: (self.txt.insert("end", msg + "\n"), self.txt.see("end")))
        except Exception:
            pass

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x740")
        self.resizable(True, True)

        self.template_path = tk.StringVar()
        self.msbd_path = tk.StringVar()
        self.gsp_path = tk.StringVar()
        self.save_dir = tk.StringVar(value=os.getcwd())

        self.hull_options: List[str] = []
        self.hull_to_class: Dict[str,str] = {}
        self.selected_hull = tk.StringVar()

        self._build_ui()
        try:
            self._panel_refresh_list()
            self._em_refresh_list()
        except Exception:
            pass

    
    def progress(self, pct:int, stage:str=None):
            try:
                if stage:
                    self.title(f"{APP_NAME} - {stage} {pct}%")
                self.pbar["value"] = max(0, min(100, int(pct)))
            except Exception:
                pass

    
    def _build_ui(self):

        pad = {"padx":8,"pady":6}

        frm = ttk.LabelFrame(self, text="파일 선택")
        frm.pack(fill="x", **pad)

        ttk.Label(frm, text="템플릿 DOCX").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.template_path, width=90).grid(row=0, column=1, sticky="ew")
        ttk.Button(frm, text="찾기...", command=self._pick_template).grid(row=0, column=2, sticky="e")

        ttk.Label(frm, text="MSBD PDF").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.msbd_path, width=90).grid(row=1, column=1, sticky="ew")
        ttk.Button(frm, text="찾기...", command=self._pick_msbd).grid(row=1, column=2, sticky="e")

        ttk.Label(frm, text="GSP PDF").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.gsp_path, width=90).grid(row=2, column=1, sticky="ew")
        ttk.Button(frm, text="찾기...", command=self._pick_gsp).grid(row=2, column=2, sticky="e")

        ttk.Label(frm, text="저장 폴더").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.save_dir, width=90).grid(row=3, column=1, sticky="ew")
        ttk.Button(frm, text="변경...", command=self._pick_dir).grid(row=3, column=2, sticky="e")

        for i in range(3):
            frm.columnconfigure(i, weight=1)

        
        self.panels_data = []
        self.em_stops_data = []

        act = ttk.Frame(self)
        act.pack(fill="x", **pad)
        ttk.Button(act, text="1) 추출", command=lambda: self._start_task(self._extract_worker)).pack(side="left", padx=4)
        ttk.Button(act, text="2) 보고서 생성", command=lambda: self._start_task(self._generate_worker)).pack(side="left", padx=4)
        ttk.Button(act, text="템플릿 진단", command=lambda: self._start_task(self._validate_template_worker)).pack(side="left", padx=4)
        self.pbar = ttk.Progressbar(act, mode="determinate", maximum=100, length=220)
        self.pbar.pack(side="right", padx=6)

        sel = ttk.LabelFrame(self, text="호선 선택 & 선급 자동 반영")
        sel.pack(fill="x", **pad)

        ttk.Label(sel, text="Hull No").grid(row=0, column=0, sticky="w")
        self.cmb_hull = ttk.Combobox(sel, textvariable=self.selected_hull, values=self.hull_options, state="readonly", width=20)
        self.cmb_hull.grid(row=0, column=1, sticky="w", padx=6)
        self.cmb_hull.bind("<<ComboboxSelected>>", self._on_hull_change)

        ttk.Label(sel, text="Class (자동)").grid(row=0, column=2, sticky="w")
        self.class_var = tk.StringVar()
        self.ent_class = ttk.Entry(sel, width=20, textvariable=self.class_var, state="disabled")
        self.ent_class.grid(row=0, column=3, sticky="w")

        for i in range(4):
            sel.columnconfigure(i, weight=1)

        
        grid = ttk.LabelFrame(self, text="추출된 값 (수정 가능)")
        grid.pack(fill="both", expand=True, **pad)

        # --- Tabs (always visible) ---
        self.values_nb = ttk.Notebook(grid)
        self.page_spec   = ttk.Frame(self.values_nb)
        self.page_panel  = ttk.Frame(self.values_nb)
        self.page_estop  = ttk.Frame(self.values_nb)
        self.values_nb.add(self.page_spec,  text="① 표지 / GENERAL SPEC")
        self.values_nb.add(self.page_panel, text="② PANEL INFORMATION")
        self.values_nb.add(self.page_estop, text="③ EMERGENCY STOP INFORMATION")
        self.values_nb.pack(fill="both", expand=True)

        # --- Page 1: Spec key-value form ---
        self.entries: Dict[str, tk.Entry] = {}
        ui_fields = [k for k in FIELDS if k != 'class']
        left_fields = ui_fields[:len(ui_fields)//2]
        right_fields = ui_fields[len(ui_fields)//2:]

        def add_col(parent, col_fields, col_index):
            for r, key in enumerate(col_fields):
                ttk.Label(parent, text=key).grid(row=r, column=col_index*2, sticky="w", padx=4, pady=2)
                e = ttk.Entry(parent)
                e.grid(row=r, column=col_index*2+1, sticky="ew", padx=4, pady=2)
                self.entries[key] = e

        add_col(self.page_spec, left_fields, 0)
        add_col(self.page_spec, right_fields, 1)
        for c in range(4):
            self.page_spec.columnconfigure(c, weight=1)

        # --- Page 2: Panels editor (inline) ---
        tp = self.page_panel
        left = ttk.Frame(tp); left.pack(side="left", fill="y")
        right = ttk.Frame(tp); right.pack(side="right", fill="both", expand=True)

        self.lst_panels = tk.Listbox(left, height=12)
        self.lst_panels.pack(side="left", fill="y")
        self.lst_panels.bind("<<ListboxSelect>>", lambda e: self._panel_select())
        ttk.Button(left, text="새로고침", command=self._panel_refresh_list).pack(side="left", padx=4)

        pgrid = ttk.Frame(right); pgrid.pack(fill="both", expand=True, padx=8, pady=8)
        labels = ['panel','acb_type','ocr_type','ampere_frame','rated_current_in','ir_percent','ir_amps','isd_percent','isd_amps','remarks']
        self.panel_vars = {k: tk.StringVar() for k in labels}
        for r,k in enumerate(labels):
            ttk.Label(pgrid, text=k).grid(row=r, column=0, sticky="w")
            ttk.Entry(pgrid, textvariable=self.panel_vars[k]).grid(row=r, column=1, sticky="ew")
        pgrid.columnconfigure(1, weight=1)

        ttk.Label(pgrid, text="Circuits").grid(row=len(labels), column=0, sticky="nw")
        self.txt_panel_circuits = tk.Text(pgrid, height=10, wrap="none")
        self.txt_panel_circuits.grid(row=len(labels), column=1, sticky="nsew")
        sc = ttk.Scrollbar(pgrid, orient="vertical", command=self.txt_panel_circuits.yview)
        self.txt_panel_circuits.configure(yscrollcommand=sc.set)
        sc.grid(row=len(labels), column=2, sticky="ns")
        pgrid.rowconfigure(len(labels), weight=1)

        pbtns = ttk.Frame(right); pbtns.pack(fill="x")
        ttk.Button(pbtns, text="적용(현 패널)", command=self._panel_apply).pack(side="left")

        # --- Page 3: Emergency editor (inline) ---
        te = self.page_estop
        left2 = ttk.Frame(te); left2.pack(side="left", fill="y")
        right2 = ttk.Frame(te); right2.pack(side="right", fill="both", expand=True)

        self.lst_em_codes = tk.Listbox(left2, height=12)
        self.lst_em_codes.pack(side="left", fill="y")
        self.lst_em_codes.bind("<<ListboxSelect>>", lambda e: self._em_select())
        ttk.Button(left2, text="새로고침", command=self._em_refresh_list).pack(side="left", padx=4)

        eform = ttk.Frame(right2); eform.pack(fill="x", padx=8, pady=8)
        self.em_code = tk.StringVar(); self.em_name = tk.StringVar()
        ttk.Label(eform, text="CODE").grid(row=0, column=0, sticky="w")
        ttk.Entry(eform, textvariable=self.em_code, width=20).grid(row=0, column=1, sticky="ew")
        ttk.Label(eform, text="NAME").grid(row=1, column=0, sticky="w")
        ttk.Entry(eform, textvariable=self.em_name, width=50).grid(row=1, column=1, sticky="ew")
        eform.columnconfigure(1, weight=1)

        ttk.Label(right2, text="회로 그룹(한 블록 = 한 패널)\n예: [No.1 INCOMING]\nP31-001-01-PN, P31-002-01-PN").pack(anchor="w", padx=8)
        self.txt_em_circuits = tk.Text(right2, height=12, wrap="word")
        self.txt_em_circuits.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Button(right2, text="적용(현 항목)", command=self._em_apply).pack(anchor="w", padx=8, pady=6)

        self.txt = tk.Text(self, height=8)
        self.txt.pack(fill="both", expand=False, **pad)


    def _open_panels_editor(self):
        win = tk.Toplevel(self)
        win.title("Panels / Emergency")
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True)

        # Panels tab
        tp = ttk.Frame(nb); nb.add(tp, text="Panels")
        left = ttk.Frame(tp); left.pack(side="left", fill="y")
        right = ttk.Frame(tp); right.pack(side="right", fill="both", expand=True)

        self.lst_panels = tk.Listbox(left, height=12)
        self.lst_panels.pack(side="left", fill="y")
        self.lst_panels.bind("<<ListboxSelect>>", lambda e: self._panel_select())

        ttk.Button(left, text="새로고침", command=self._panel_refresh_list).pack(side="left", padx=4)

        grid = ttk.Frame(right); grid.pack(fill="both", expand=True, padx=8, pady=8)
        labels = ['panel','acb_type','ocr_type','ampere_frame','rated_current_in','ir_percent','ir_amps','isd_percent','isd_amps','remarks']
        self.panel_vars = {k: tk.StringVar() for k in labels}
        for r,k in enumerate(labels):
            ttk.Label(grid, text=k).grid(row=r, column=0, sticky="w")
            ttk.Entry(grid, textvariable=self.panel_vars[k]).grid(row=r, column=1, sticky="ew")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Circuits").grid(row=len(labels), column=0, sticky="nw")
        self.txt_panel_circuits = tk.Text(grid, height=10, wrap="none")
        self.txt_panel_circuits.grid(row=len(labels), column=1, sticky="nsew")
        sc = ttk.Scrollbar(grid, orient="vertical", command=self.txt_panel_circuits.yview)
        self.txt_panel_circuits.configure(yscrollcommand=sc.set)
        sc.grid(row=len(labels), column=2, sticky="ns")
        grid.rowconfigure(len(labels), weight=1)

        btns = ttk.Frame(right); btns.pack(fill="x")
        ttk.Button(btns, text="적용(현 패널)", command=self._panel_apply).pack(side="left")

        # Emergency tab
        te = ttk.Frame(nb); nb.add(te, text="Emergency")
        left2 = ttk.Frame(te); left2.pack(side="left", fill="y")
        right2 = ttk.Frame(te); right2.pack(side="right", fill="both", expand=True)
        self.lst_em_codes = tk.Listbox(left2, height=12)
        self.lst_em_codes.pack(side="left", fill="y")
        self.lst_em_codes.bind("<<ListboxSelect>>", lambda e: self._em_select())
        ttk.Button(left2, text="새로고침", command=self._em_refresh_list).pack(side="left", padx=4)

        form = ttk.Frame(right2); form.pack(fill="x", padx=8, pady=8)
        self.em_code = tk.StringVar(); self.em_name = tk.StringVar()
        ttk.Label(form, text="CODE").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.em_code, width=20).grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="NAME").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.em_name, width=50).grid(row=1, column=1, sticky="ew")
        form.columnconfigure(1, weight=1)

        ttk.Label(right2, text="회로 그룹(한 블록 = 한 패널)\n예: [No.1 INCOMING]\nP31-001-01-PN, P31-002-01-PN").pack(anchor="w", padx=8)
        self.txt_em_circuits = tk.Text(right2, height=12, wrap="word")
        self.txt_em_circuits.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Button(right2, text="적용(현 항목)", command=self._em_apply).pack(anchor="w", padx=8, pady=6)


    # ---------- pickers ----------
    def _pick_template(self):
        p = filedialog.askopenfilename(filetypes=[("DOCX","*.docx")])
        if p:
            self.template_path.set(p)

    def _pick_msbd(self):
        p = filedialog.askopenfilename(filetypes=[("PDF","*.pdf")])
        if p:
            self.msbd_path.set(p)

    def _pick_gsp(self):
        p = filedialog.askopenfilename(filetypes=[("PDF","*.pdf")])
        if p:
            self.gsp_path.set(p)

    def _pick_dir(self):
        p = filedialog.askdirectory()
        if p:
            self.save_dir.set(p)

    # ---------- utilities ----------
    
    def _on_hull_change(self, event=None):
        hull = self.selected_hull.get().strip()
        cls = self.hull_to_class.get(hull, "")
        self.class_var.set(cls)
        if 'hull_no' in self.entries:
            self.entries['hull_no'].delete(0,'end')
            self.entries['hull_no'].insert(0, hull)

    # ---------- threaded tasks ----------
    
    def _subprogress(self, base:int, span:int):
        def cb(pct:int, tag:str=None):
            val = base + int(span * (pct or 0) / 100)
            self.progress(val, f"{tag or ''}")
        return cb

    def _start_task(self, worker: Callable[[], None]):

        # start progress bar and run worker in background
        try:
            self.pbar["value"]=0
        except Exception:
            pass
        self._set_actions_state("disabled")
        t = threading.Thread(target=self._safe_run, args=(worker,), daemon=True)
        t.start()
        self._poll_thread(t)

    def _poll_thread(self, t: threading.Thread):
        if t.is_alive():
            self.after(100, lambda: self._poll_thread(t))
        else:
            try:
                self.pbar.stop()
            except Exception:
                pass
            self._set_actions_state("normal"); self.progress(0,'')

    def _set_actions_state(self, state: str):
        for child in self.children.values():
            pass  # placeholder
        # disable/enable buttons in the 'act' frame
        # simple approach: just set state on all buttons
        for w in self.winfo_children():
            if isinstance(w, ttk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, ttk.Button):
                        try: c.configure(state=state)
                        except Exception: pass

    def _safe_run(self, worker: Callable[[], None]):
        try:
            worker()
        except Exception as e:
            self.log("[ERROR] " + str(e))
            self.log(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror("오류", str(e)))

    # ---------- workers ----------
    def _extract_worker(self):
        self.log("[INFO] Extract started.")
        msbd, gsp = self.msbd_path.get().strip(), self.gsp_path.get().strip()
        if not (os.path.isfile(msbd) and os.path.isfile(gsp)):
            self.after(0, lambda: messagebox.showerror("오류", "MSBD, GSP PDF를 모두 선택하세요."))
            return
        ex.set_progress_cb(self._subprogress(10, 20)); cov_msbd = ex.parse_cover_info(msbd)
        cov_gsp = ex.parse_cover_info(gsp)
        merged_cover = merge_cover(cov_msbd, cov_gsp)
        self.hull_to_class = dict(merged_cover.get("hull_to_class", {}))

        ex.set_progress_cb(self._subprogress(30, 15)); spec_msbd = ex.parse_general_spec(msbd)
        ex.set_progress_cb(self._subprogress(45, 15)); spec_gsp = ex.parse_general_spec(gsp)

        hulls = sorted(self.hull_to_class.keys())
        
        def ui_fill():
            # Hull selector populate
            self.hull_options = hulls
            self.cmb_hull["values"] = hulls
            if hulls:
                self.selected_hull.set(hulls[0])
                self._on_hull_change()

            # Combine spec fields and fill Page-1 entries
            fields = merged_cover["fields"]
            fields = combine_all(fields, spec_msbd)
            fields = combine_all(fields, spec_gsp)

            # enforce IP fallback: always normalize to IP22 (per request)
            for _k in ('ms_ip','gsp_ip'):
                _v = (fields.get(_k) or '').strip().upper()
                if _v != 'IP22':
                    fields[_k] = 'IP22'


            # Parse panels & emergency
            try:
                ex.set_progress_cb(self._subprogress(60, 15))
                self.panels_data = ex.parse_panel_blocks_v2(msbd, gsp) or []
            except Exception as e:
                self.log(f"[WARN] 패널 파싱 실패: {e}")
                self.panels_data = []
            try:
                ex.set_progress_cb(self._subprogress(75, 10))
                ems = ex.parse_emergency_stop(gsp)
                if not ems:
                    ems = ex.parse_emergency_colorplate(msbd)
                self.em_stops_data = ems or []
            except Exception as e:
                self.log(f"[WARN] Emergency 파싱 실패: {e}")
                self.em_stops_data = []

            # Fill GENERAL SPEC entries
            for k, e in self.entries.items():
                e.delete(0, "end")
                if k in fields:
                    e.insert(0, str(fields[k]))

            # Refresh lists in tabs
            try:
                self._panel_refresh_list()
                self._em_refresh_list()
            except Exception:
                pass

            self.progress(100, "완료"); self.log("[OK] Extract finished.")
        self.after(0, ui_fill)

    def _validate_template_worker(self):
        tpl = self.template_path.get().strip()
        if not os.path.isfile(tpl):
            self.after(0, lambda: messagebox.showerror("오류", "템플릿 DOCX를 먼저 선택하세요."))
            return
        missing = []
        try:
            with open(tpl, "rb") as f:
                data = f.read()
            text = data.decode(errors="ignore").lower()
            for key in FIELDS:
                if (("{{ "+key+" }}" not in text) and ("{{"+key+"}}" not in text)):
                    missing.append(key)
        except Exception:
            pass
        def ui_done():
            if missing:
                self.log("[WARN] 템플릿에서 다음 placeholder가 안 보입니다: " + ", ".join(missing))
                messagebox.showwarning("템플릿 진단", "일부 placeholder가 보이지 않습니다. 하단 로그 참고.")
            else:
                self.log("[OK] 템플릿 placeholder가 모두 감지되었습니다.")
        self.after(0, ui_done)

    def _generate_worker(self):
        tpl = self.template_path.get().strip()
        if not os.path.isfile(tpl):
            self.after(0, lambda: messagebox.showerror("오류", "템플릿 DOCX를 먼저 선택하세요."))
            return
        ctx = {k:(self.entries[k].get().strip() if k in self.entries else '') for k in FIELDS}
        sel_hull = self.selected_hull.get().strip()
        if sel_hull:
            ctx["hull_no"] = sel_hull
            ctx["class"] = self.hull_to_class.get(sel_hull) or ctx.get("class","") or self.class_var.get().strip()
        try:
            doc = DocxTemplate(tpl)
            doc.render(ctx)
            hull = ctx.get("hull_no","SNXXXX")
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            out_path = os.path.join(self.save_dir.get().strip() or os.getcwd(), f"FAT_Report_{hull}_{now}.docx")
            doc.save(out_path)
            self.after(0, lambda: [self.log(f"[OK] 보고서 생성 완료: {out_path}"), messagebox.showinfo("완료", f"보고서 생성 완료:\n{out_path}")])
        except Exception as e:
            self.after(0, lambda: [self.log(f"[ERROR] 보고서 생성 실패: {e}"), messagebox.showerror("오류", f"보고서 생성 실패:\n{e}")])


    def _panel_refresh_list(self):
        self.lst_panels.delete(0, "end")
        for p in self.panels_data:
            self.lst_panels.insert("end", p.get("panel","(panel)"))

    def _panel_select(self):
        i = self.lst_panels.curselection()
        if not i: return
        p = self.panels_data[i[0]]
        for k,v in self.panel_vars.items():
            v.set(str(p.get(k,"")))
        self.txt_panel_circuits.delete("1.0","end")
        self.txt_panel_circuits.insert("1.0", "\n".join(p.get("circuits", [])))

    def _panel_apply(self):
        i = self.lst_panels.curselection()
        if not i: return
        idx = i[0]
        p = self.panels_data[idx]
        for k,v in self.panel_vars.items():
            p[k] = v.get().strip()
        cir_text = self.txt_panel_circuits.get("1.0","end").strip()
        p["circuits"] = [ln.strip() for ln in cir_text.splitlines() if ln.strip()]
        self.panels_data[idx] = p
        self.log(f"[OK] 패널 업데이트: {p.get('panel')}")

    def _em_refresh_list(self):
        self.lst_em_codes.delete(0, "end")
        for e in self.em_stops_data:
            self.lst_em_codes.insert("end", f"{e.get('code','')}: {e.get('name','')}")

    def _em_select(self):
        i = self.lst_em_codes.curselection()
        if not i: return
        e = self.em_stops_data[i[0]]
        self.em_code.set(e.get("code",""))
        self.em_name.set(e.get("name",""))
        blocks = []
        for g in e.get("groups", []):
            header = g.get("panel_header","")
            circs = ", ".join(g.get("circuits", []))
            blocks.append(f"[{header}]\n{circs}")
        self.txt_em_circuits.delete("1.0","end")
        self.txt_em_circuits.insert("1.0","\n\n".join(blocks))

    def _em_apply(self):
        i = self.lst_em_codes.curselection()
        if not i: return
        idx = i[0]
        e = self.em_stops_data[idx]
        e["code"] = self.em_code.get().strip()
        e["name"] = self.em_name.get().strip()
        blocks = [b.strip() for b in self.txt_em_circuits.get("1.0","end").strip().split("\n\n") if b.strip()]
        groups = []
        for b in blocks:
            lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
            if not lines: continue
            header = lines[0].strip("[]")
            circs = []
            if len(lines) > 1:
                for part in ",".join(lines[1:]).split(","):
                    t = part.strip()
                    if t: circs.append(t)
            groups.append({"panel_header": header, "circuits": circs})
        e["groups"] = groups
        self.em_stops_data[idx] = e
        self._em_refresh_list()
        self.log(f"[OK] Emergency 항목 업데이트: {e.get('code')}")

if __name__ == "__main__":
    app = App()
    app.mainloop()