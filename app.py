
# -*- coding: utf-8 -*-
"""
FAT AutoFill Pro (v2.4.2_fix13b)
- 안정 진짜수정: SyntaxError 제거, 스레드 기반 Progressbar로 무응답 방지
- Hull 변경 시 Class 자동 반영
"""
from __future__ import annotations

APP_NAME = "FAT AutoFill Pro (v2.4.2_fix13c)"

import os
import re
import datetime
import threading
import traceback
from typing import Dict, Optional, List, Callable
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
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
            self.after(0, lambda: self._append_log(msg))
        except Exception:
            pass

    def _append_log(self, msg: str):
        try:
            self.txt.insert("end", msg + "\n")
            self.txt.see("end")
            self._set_status(msg)
        except Exception:
            pass

    def _set_status(self, text: str):
        try:
            short = (text or "").strip()
            if len(short) > 70:
                short = short[:67] + "..."
            self.status_var.set(short or "준비 완료")
        except Exception:
            pass

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x780")
        self.resizable(True, True)
        self._init_style()

        self.template_path = tk.StringVar()
        self.msbd_path = tk.StringVar()
        self.gsp_path = tk.StringVar()
        self.save_dir = tk.StringVar(value=os.getcwd())

        self.hull_options: List[str] = []
        self.hull_to_class: Dict[str,str] = {}
        self.selected_hull = tk.StringVar()

        self.status_var = tk.StringVar(value="준비 완료")

        self._build_ui()
        try:
            self._panel_refresh_list()
            self._em_refresh_list()
        except Exception:
            pass


    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Card.TLabelframe", padding=(12, 10))
        style.configure("Card.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", foreground="#3a3a3a")


    def progress(self, pct:int, stage:str=None):
        try:
            if stage:
                display = f"{stage} {pct}%" if pct is not None else stage
                self.title(f"{APP_NAME} - {display}")
                self._set_status(display)
            self.pbar["value"] = max(0, min(100, int(pct)))
        except Exception:
            pass

    
    def _build_ui(self):

        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=5)
        container.rowconfigure(4, weight=2)

        files = ttk.LabelFrame(container, text="파일 선택", style="Card.TLabelframe")
        files.grid(row=0, column=0, sticky="ew")

        pickers = [
            ("템플릿 DOCX", self.template_path, self._pick_template, "찾기..."),
            ("MSBD PDF", self.msbd_path, self._pick_msbd, "찾기..."),
            ("GSP PDF", self.gsp_path, self._pick_gsp, "찾기..."),
            ("저장 폴더", self.save_dir, self._pick_dir, "폴더 선택"),
        ]
        for row, (label, var, cmd, btn_text) in enumerate(pickers):
            ttk.Label(files, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            entry = ttk.Entry(files, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Button(files, text=btn_text, width=12, command=cmd).grid(row=row, column=2, sticky="e", pady=4)
        files.columnconfigure(1, weight=1)

        self.panels_data = []
        self.em_stops_data = []

        actions = ttk.Frame(container)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)

        buttons = ttk.Frame(actions)
        buttons.grid(row=0, column=0, sticky="w")
        ttk.Button(buttons, text="1) 추출", command=lambda: self._start_task(self._extract_worker)).pack(side="left", padx=4)
        ttk.Button(buttons, text="2) 보고서 생성", command=lambda: self._start_task(self._generate_worker)).pack(side="left", padx=4)
        ttk.Button(buttons, text="템플릿 진단", command=lambda: self._start_task(self._validate_template_worker)).pack(side="left", padx=4)

        status_box = ttk.Frame(actions)
        status_box.grid(row=0, column=1, sticky="e")
        self.pbar = ttk.Progressbar(status_box, mode="determinate", maximum=100, length=240)
        self.pbar.pack(fill="x", padx=4)
        ttk.Label(status_box, textvariable=self.status_var, style="Status.TLabel").pack(anchor="e", pady=(4, 0))

        sel = ttk.LabelFrame(container, text="호선 선택 & 선급 자동 반영", style="Card.TLabelframe")
        sel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(sel, text="Hull No").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.cmb_hull = ttk.Combobox(sel, textvariable=self.selected_hull, values=self.hull_options, state="readonly", width=20)
        self.cmb_hull.grid(row=0, column=1, sticky="w", pady=4)
        self.cmb_hull.bind("<<ComboboxSelected>>", self._on_hull_change)
        ttk.Label(sel, text="Class (자동)").grid(row=0, column=2, sticky="w", padx=(20, 6), pady=4)
        self.class_var = tk.StringVar()
        self.ent_class = ttk.Entry(sel, textvariable=self.class_var, width=24, state="disabled")
        self.ent_class.grid(row=0, column=3, sticky="ew", pady=4)
        sel.columnconfigure(1, weight=1)
        sel.columnconfigure(3, weight=1)

        grid = ttk.LabelFrame(container, text="추출된 값 (수정 가능)", style="Card.TLabelframe")
        grid.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)

        self.values_nb = ttk.Notebook(grid)
        self.page_spec = ttk.Frame(self.values_nb)
        self.page_panel = ttk.Frame(self.values_nb)
        self.page_estop = ttk.Frame(self.values_nb)
        self.values_nb.add(self.page_spec, text="① 표지 / GENERAL SPEC")
        self.values_nb.add(self.page_panel, text="② PANEL INFORMATION")
        self.values_nb.add(self.page_estop, text="③ EMERGENCY STOP INFORMATION")
        self.values_nb.grid(row=0, column=0, sticky="nsew")

        self.entries: Dict[str, tk.Entry] = {}
        ui_fields = [k for k in FIELDS if k != 'class']
        left_fields = ui_fields[:len(ui_fields)//2]
        right_fields = ui_fields[len(ui_fields)//2:]

        spec_wrap = ttk.Frame(self.page_spec, padding=16)
        spec_wrap.pack(fill="both", expand=True)
        spec_wrap.columnconfigure(0, weight=1)
        spec_wrap.columnconfigure(1, weight=1)

        def build_column(parent, col_index, fields):
            frame = ttk.Frame(parent)
            frame.grid(row=0, column=col_index, sticky="nsew", padx=8)
            frame.columnconfigure(1, weight=1)
            for r, key in enumerate(fields):
                ttk.Label(frame, text=key).grid(row=r, column=0, sticky="w", pady=3)
                entry = ttk.Entry(frame)
                entry.grid(row=r, column=1, sticky="ew", pady=3)
                self.entries[key] = entry

        build_column(spec_wrap, 0, left_fields)
        build_column(spec_wrap, 1, right_fields)

        panel_wrap = ttk.Frame(self.page_panel, padding=12)
        panel_wrap.pack(fill="both", expand=True)
        paned = ttk.PanedWindow(panel_wrap, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left_panel = ttk.Frame(paned)
        paned.add(left_panel, weight=1)
        right_panel = ttk.Frame(paned)
        paned.add(right_panel, weight=2)

        tree_frame = ttk.Frame(left_panel)
        tree_frame.pack(fill="both", expand=True)
        columns = ("panel", "acb", "ocr", "in")
        self.panel_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse", height=12)
        headings = {
            "panel": "Panel",
            "acb": "ACB Type",
            "ocr": "OCR Type",
            "in": "Rated In (A)",
        }
        for key, text in headings.items():
            self.panel_tree.heading(key, text=text)
            anchor = "e" if key == "in" else "w"
            width = 140 if key == "panel" else 120
            self.panel_tree.column(key, anchor=anchor, width=width, stretch=True)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.panel_tree.yview)
        self.panel_tree.configure(yscrollcommand=vsb.set)
        self.panel_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.panel_tree.bind("<<TreeviewSelect>>", lambda e: self._panel_select())

        ttk.Button(left_panel, text="새로고침", command=self._panel_refresh_list).pack(fill="x", pady=(6, 0))

        info_frame = ttk.LabelFrame(right_panel, text="패널 기본 정보", padding=12)
        info_frame.pack(fill="x")
        panel_fields = [
            'panel','acb_type','ocr_type','ampere_frame','rated_current_in','ip','paint',
            'ir_percent','ir_amps','isd_percent','isd_amps','setting_time_s','setting_time_ms','remarks'
        ]
        self.panel_vars = {k: tk.StringVar() for k in panel_fields}
        info_frame.columnconfigure(1, weight=1)
        for r, key in enumerate(panel_fields):
            ttk.Label(info_frame, text=key).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(info_frame, textvariable=self.panel_vars[key]).grid(row=r, column=1, sticky="ew", pady=2)

        circuits_frame = ttk.LabelFrame(right_panel, text="회로 목록", padding=12)
        circuits_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.txt_panel_circuits = ScrolledText(circuits_frame, height=8, wrap="none")
        self.txt_panel_circuits.pack(fill="both", expand=True)

        ttk.Button(right_panel, text="적용(현 패널)", command=self._panel_apply).pack(anchor="e", pady=(8, 0))

        estop_wrap = ttk.Frame(self.page_estop, padding=12)
        estop_wrap.pack(fill="both", expand=True)
        estop_paned = ttk.PanedWindow(estop_wrap, orient="horizontal")
        estop_paned.pack(fill="both", expand=True)

        left_estop = ttk.Frame(estop_paned)
        estop_paned.add(left_estop, weight=1)
        right_estop = ttk.Frame(estop_paned)
        estop_paned.add(right_estop, weight=2)

        list_frame = ttk.Frame(left_estop)
        list_frame.pack(fill="both", expand=True)
        self.lst_em_codes = tk.Listbox(list_frame, height=16, exportselection=False)
        self.lst_em_codes.grid(row=0, column=0, sticky="nsew")
        self.lst_em_codes.bind("<<ListboxSelect>>", lambda e: self._em_select())
        em_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.lst_em_codes.yview)
        self.lst_em_codes.configure(yscrollcommand=em_scroll.set)
        em_scroll.grid(row=0, column=1, sticky="ns")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        ttk.Button(left_estop, text="새로고침", command=self._em_refresh_list).pack(fill="x", pady=(6, 0))

        info_estop = ttk.LabelFrame(right_estop, text="비상정지 정보", padding=12)
        info_estop.pack(fill="x")
        self.em_code = tk.StringVar()
        self.em_name = tk.StringVar()
        info_estop.columnconfigure(1, weight=1)
        ttk.Label(info_estop, text="CODE").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(info_estop, textvariable=self.em_code, width=20).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(info_estop, text="NAME").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(info_estop, textvariable=self.em_name, width=40).grid(row=1, column=1, sticky="ew", pady=2)

        ttk.Label(right_estop, text="회로 그룹(한 블록 = 한 패널)\n예: [No.1 INCOMING]\nP31-001-01-PN, P31-002-01-PN", justify="left").pack(anchor="w", pady=(10, 4))
        self.txt_em_circuits = ScrolledText(right_estop, height=10, wrap="word")
        self.txt_em_circuits.pack(fill="both", expand=True)
        ttk.Button(right_estop, text="적용(현 항목)", command=self._em_apply).pack(anchor="e", pady=(8, 0))

        log_frame = ttk.LabelFrame(container, text="로그", style="Card.TLabelframe")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.txt = ScrolledText(log_frame, height=8, wrap="word")
        self.txt.grid(row=0, column=0, sticky="nsew")


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
        if not hasattr(self, "panel_tree"):
            return
        for item in self.panel_tree.get_children():
            self.panel_tree.delete(item)
        for idx, panel in enumerate(self.panels_data):
            values = (
                panel.get("panel", ""),
                panel.get("acb_type", ""),
                panel.get("ocr_type", ""),
                panel.get("rated_current_in", ""),
            )
            self.panel_tree.insert("", "end", iid=str(idx), values=values)

    def _panel_select(self):
        if not hasattr(self, "panel_tree"):
            return
        sel = self.panel_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.panels_data)):
            return
        p = self.panels_data[idx]
        for k,v in self.panel_vars.items():
            v.set(str(p.get(k,"")))
        self.txt_panel_circuits.delete("1.0","end")
        self.txt_panel_circuits.insert("1.0", "\n".join(p.get("circuits", [])))

    def _panel_apply(self):
        if not hasattr(self, "panel_tree"):
            return
        sel = self.panel_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.panels_data)):
            return
        p = self.panels_data[idx]
        for k,v in self.panel_vars.items():
            p[k] = v.get().strip()
        cir_text = self.txt_panel_circuits.get("1.0","end").strip()
        p["circuits"] = [ln.strip() for ln in cir_text.splitlines() if ln.strip()]
        self.panels_data[idx] = p
        self._panel_refresh_list()
        item_id = str(idx)
        if item_id in self.panel_tree.get_children():
            self.panel_tree.selection_set(item_id)
            self.panel_tree.focus(item_id)
        self.log(f"[OK] 패널 업데이트: {p.get('panel')}")

    def _em_refresh_list(self):
        self.lst_em_codes.delete(0, "end")
        for e in self.em_stops_data:
            self.lst_em_codes.insert("end", f"{e.get('code','')}: {e.get('name','')}")
        if self.em_stops_data:
            self.lst_em_codes.selection_set(0)
            self._em_select()

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