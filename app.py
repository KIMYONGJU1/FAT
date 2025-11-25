
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

FUNCTION_TEST_KEYS = ["gsp_function_no1", "gsp_function_no2"]

PANEL_VALUE_FIELDS = [
    "panel",
    "acb_type",
    "ocr_type",
    "ampere_frame",
    "rated_current_in",
    "ir_percent",
    "ir_amps",
]

PANEL_FIELD_LABELS = {
    "panel": "Panel Name",
    "acb_type": "ACB Type",
    "ocr_type": "OCR Type",
    "ampere_frame": "Ampere Frame",
    "rated_current_in": "Rated Current (In)",
    "ir_percent": "IR (%)",
    "ir_amps": "IR (A)",
}

PANEL_PLACEHOLDER_MAP = {
    "no1": {
        "panel": "ms_panel1",
        "acb_type": "ms_acb_type1",
        "ocr_type": "ms_ocr_type1",
        "ampere_frame": "ms_ampere_frame1",
        "rated_current_in": "ms_rated_current_in1",
        "ir_percent": "ms_ir_percent1",
        "ir_amps": "ms_ir_amps1",
    },
    "no2": {
        "panel": "ms_panel2",
        "acb_type": "ms_acb_type2",
        "ocr_type": "ms_ocr_type2",
        "ampere_frame": "ms_ampere_frame2",
        "rated_current_in": "ms_rated_current_in2",
        "ir_percent": "ms_ir_percent2",
        "ir_amps": "ms_ir_amps2",
    },
    "bus": {
        "panel": "ms_panel3",
        "acb_type": "ms_acb_type3",
        "ocr_type": "ms_ocr_type3",
        "ampere_frame": "ms_ampere_frame3",
        "rated_current_in": "ms_rated_current_in3",
        "ir_percent": "ms_ir_percent3",
        "ir_amps": "ms_ir_amps3",
    },
    "emg": {
        "panel": "ms_panel4",
        "acb_type": "ms_acb_type4",
        "ocr_type": "ms_ocr_type4",
        "ampere_frame": "ms_ampere_frame4",
        "rated_current_in": "ms_rated_current_in4",
        "ir_percent": "ms_ir_percent4",
        "ir_amps": "ms_ir_amps4",
    },
}

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

    def _init_panel_slots(self) -> List[Dict[str, object]]:
        specs = getattr(ex, "PANEL_SLOT_SPECS", None)
        if not specs:
            specs = [
                {"slot": "no1", "title": "No.1 INCOMING PANEL"},
                {"slot": "no2", "title": "No.2 INCOMING PANEL"},
                {"slot": "bus", "title": "BUS-TIE"},
                {"slot": "emg", "title": "EMERGENCY PANEL"},
            ]
        defs: List[Dict[str, object]] = []
        for spec in specs:
            slot_key = spec.get("slot")
            placeholders = PANEL_PLACEHOLDER_MAP.get(slot_key)
            if not slot_key or not placeholders:
                continue
            defs.append(
                {
                    "slot": slot_key,
                    "title": spec.get("title") or spec.get("panel") or "PANEL",
                    "placeholders": placeholders,
                }
            )
        return defs

    @staticmethod
    def _color_to_hex(name: str) -> str:
        base = (name or "").upper()
        palette = {
            "RED": "#d9534f",
            "PINK": "#f497b5",
            "BROWN": "#8d6e63",
            "BLUE": "#5bc0de",
            "LIGHT BLUE": "#8fd3f4",
            "GREEN": "#5cb85c",
            "LIGHT GREEN": "#9ad89a",
            "YELLOW": "#f0ad4e",
            "GOLD": "#c9b037",
            "SILVER": "#bfbfbf",
            "PURPLE": "#b39ddb",
        }
        for key, val in palette.items():
            if key in base:
                return val
        return "#d9d9d9"

    def _update_color_chip(self, color_text: str):
        try:
            hex_color = self._color_to_hex(color_text)
            self.em_color_chip.configure(bg=hex_color)
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

        self.em_color = tk.StringVar()

        self._build_ui()
        try:
            self._panel_fill_ui()
            self._gsp_refresh_ui()
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

        self.panel_slot_defs = self._init_panel_slots()
        self.panel_template_keys = sorted(
            {ph for slot in self.panel_slot_defs for ph in slot["placeholders"].values()}
        )
        self.panel_slot_vars: Dict[str, Dict[str, tk.StringVar]] = {}
        self.panels_data = []
        self.em_stops_data = []
        self.gsp_function_data = []
        self.gsp_function_slots = [
            ("No.1 GROUP STARTER PANEL", FUNCTION_TEST_KEYS[0]),
            ("No.2 GROUP STARTER PANEL", FUNCTION_TEST_KEYS[1]),
        ]
        self.gsp_tree_widgets: Dict[str, ttk.Treeview] = {}

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
        self.page_gsp = ttk.Frame(self.values_nb)
        self.values_nb.add(self.page_spec, text="① 표지 / GENERAL SPEC")
        self.values_nb.add(self.page_panel, text="② PANEL INFORMATION")
        self.values_nb.add(self.page_gsp, text="③ FUNCTION TEST OF GSP")
        self.values_nb.add(self.page_estop, text="④ EMERGENCY STOP PANEL")
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
        panel_wrap.columnconfigure(0, weight=1)
        panel_wrap.rowconfigure(1, weight=1)

        ttk.Label(
            panel_wrap,
            text="ACB SETTING TABLE 페이지에서 추출된 패널 기본 정보를 확인/수정하세요.",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        # 스크롤 가능한 캔버스 추가
        canvas = tk.Canvas(panel_wrap, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel_wrap, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # 캔버스 너비를 scrollable_frame에 맞춤
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(10, 0))

        # 패널 그리드를 스크롤 가능한 프레임 안에 생성
        slots_grid = ttk.Frame(scrollable_frame)
        slots_grid.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 2열 레이아웃
        columns_count = 2
        for col in range(columns_count):
            slots_grid.columnconfigure(col, weight=1)

        for idx, slot in enumerate(self.panel_slot_defs):
            frame = ttk.LabelFrame(slots_grid, text=f"{idx + 1}. {slot['title']}", padding=12)
            row_idx = idx // columns_count
            col_idx = idx % columns_count
            frame.grid(row=row_idx, column=col_idx, sticky="nsew", padx=8, pady=8)
            frame.columnconfigure(1, weight=1)
            
            vars_map = self.panel_slot_vars.setdefault(slot["slot"], {})
            for f_idx, field in enumerate(PANEL_VALUE_FIELDS):
                label_text = PANEL_FIELD_LABELS.get(field, field)
                ttk.Label(frame, text=label_text).grid(row=f_idx, column=0, sticky="w", pady=2)
                var = vars_map.get(field)
                if var is None:
                    var = tk.StringVar()
                    vars_map[field] = var
                ttk.Entry(frame, textvariable=var).grid(row=f_idx, column=1, sticky="ew", pady=2)

        # 마우스 휠 스크롤 지원
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        ttk.Button(
            panel_wrap,
            text="적용(패널 정보 저장)",
            command=self._panel_apply_from_ui,
        ).grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))


        gsp_wrap = ttk.Frame(self.page_gsp, padding=12)
        gsp_wrap.pack(fill="both", expand=True)
        gsp_wrap.columnconfigure(0, weight=1)
        gsp_wrap.columnconfigure(1, weight=1)
        gsp_wrap.rowconfigure(1, weight=1)

        info_label = ttk.Label(
            gsp_wrap,
            text="NAME PLATE (MCCB) 페이지에서 추출된 회로를 확인하세요. 좌우 스크롤로 긴 회로명을 볼 수 있습니다.",
            justify="left",
        )
        info_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        for idx, (panel_label, placeholder) in enumerate(self.gsp_function_slots):
            frame = ttk.LabelFrame(gsp_wrap, text=panel_label, padding=12)
            frame.grid(row=1, column=idx, sticky="nsew", padx=(0 if idx == 0 else 12, 0))
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=0)
            frame.rowconfigure(0, weight=1)

            tree_holder = ttk.Frame(frame)
            tree_holder.grid(row=0, column=0, sticky="nsew")
            tree_holder.columnconfigure(0, weight=1)
            tree_holder.columnconfigure(1, weight=0)
            tree_holder.rowconfigure(0, weight=1)
            tree_holder.rowconfigure(1, weight=0)

            tree = ttk.Treeview(tree_holder, columns=("code", "name"), show="headings", height=14)
            tree.heading("code", text="Circuit No.")
            tree.heading("name", text="Circuit Name")
            tree.column("code", width=180, anchor="w", stretch=False)
            tree.column("name", width=380, anchor="w")
            tree.grid(row=0, column=0, sticky="nsew")
            vsb = ttk.Scrollbar(tree_holder, orient="vertical", command=tree.yview)
            vsb.grid(row=0, column=1, sticky="ns")
            hsb = ttk.Scrollbar(tree_holder, orient="horizontal", command=tree.xview)
            hsb.grid(row=1, column=0, sticky="ew")
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            self.gsp_tree_widgets[placeholder] = tree

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
        em_columns = ("code", "color", "name")
        self.em_tree = ttk.Treeview(list_frame, columns=em_columns, show="headings", selectmode="browse")
        self.em_tree.grid(row=0, column=0, sticky="nsew")
        self.em_tree.heading("code", text="CODE")
        self.em_tree.heading("color", text="COLOR")
        self.em_tree.heading("name", text="NAME")
        self.em_tree.column("code", width=110, anchor="w", stretch=False)
        self.em_tree.column("color", width=120, anchor="w", stretch=False)
        self.em_tree.column("name", width=360, anchor="w", stretch=False)
        em_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.em_tree.yview)
        em_hscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.em_tree.xview)
        self.em_tree.configure(yscrollcommand=em_scroll.set, xscrollcommand=em_hscroll.set)
        # shift + 휠로 좌우 이동, 트리폭보다 긴 이름을 드래그로 확인
        self.em_tree.bind("<Shift-MouseWheel>", lambda e: self.em_tree.xview_scroll(int(-1 * (e.delta/120)), "units"))
        em_scroll.grid(row=0, column=1, sticky="ns")
        em_hscroll.grid(row=1, column=0, sticky="ew")
        self.em_tree.bind("<<TreeviewSelect>>", lambda e: self._em_select())
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        ttk.Button(left_estop, text="새로고침", command=self._em_refresh_list).pack(fill="x", pady=(6, 0))

        info_estop = ttk.LabelFrame(right_estop, text="비상정지 기본 정보", padding=12)
        info_estop.pack(fill="x")
        self.em_code = tk.StringVar()
        self.em_name = tk.StringVar()
        info_estop.columnconfigure(1, weight=1)
        ttk.Label(info_estop, text="CODE").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(info_estop, textvariable=self.em_code, width=20).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(info_estop, text="COLOR").grid(row=1, column=0, sticky="w", pady=2)
        color_holder = ttk.Frame(info_estop)
        color_holder.grid(row=1, column=1, sticky="ew", pady=2)
        color_holder.columnconfigure(0, weight=1)
        ttk.Entry(color_holder, textvariable=self.em_color).grid(row=0, column=0, sticky="ew")
        self.em_color_chip = tk.Label(color_holder, width=10, relief="groove", borderwidth=1)
        self.em_color_chip.grid(row=0, column=1, padx=(6,0))
        ttk.Label(info_estop, text="NAME").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(info_estop, textvariable=self.em_name, width=40).grid(row=2, column=1, sticky="ew", pady=2)

        groups_frame = ttk.LabelFrame(right_estop, text="회로 그룹 (CODE별 패널)", padding=12)
        groups_frame.pack(fill="both", expand=True, pady=(10, 0))
        groups_frame.columnconfigure(0, weight=1)
        groups_frame.rowconfigure(0, weight=1)
        ttk.Label(groups_frame, text="예: ES-1A [No.1 AC440V FEEDER PANEL]\nP31-001-01-PN, P31-002-01-PN", justify="left").grid(row=0, column=0, sticky="w", pady=(0,6))
        self.txt_em_circuits = tk.Text(groups_frame, wrap="word")
        self.txt_em_circuits.grid(row=1, column=0, sticky="nsew")
        em_vsb = ttk.Scrollbar(groups_frame, orient="vertical", command=self.txt_em_circuits.yview)
        em_vsb.grid(row=1, column=1, sticky="ns")
        em_hsb = ttk.Scrollbar(groups_frame, orient="horizontal", command=self.txt_em_circuits.xview)
        em_hsb.grid(row=2, column=0, sticky="ew")
        self.txt_em_circuits.configure(yscrollcommand=em_vsb.set, xscrollcommand=em_hsb.set)
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
        
        ex.set_progress_cb(self._subprogress(10, 20))
        cov_msbd = ex.parse_cover_info(msbd)
        cov_gsp = ex.parse_cover_info(gsp)
        merged_cover = merge_cover(cov_msbd, cov_gsp)
        self.hull_to_class = dict(merged_cover.get("hull_to_class", {}))

        ex.set_progress_cb(self._subprogress(30, 15))
        spec_msbd = ex.parse_general_spec(msbd)
        ex.set_progress_cb(self._subprogress(45, 15))
        spec_gsp = ex.parse_general_spec(gsp)

        hulls = sorted(self.hull_to_class.keys())
        
        def ui_fill():
            # Hull selector populate
            self.hull_options = hulls
            self.cmb_hull["values"] = hulls
            if hulls:
                self.selected_hull.set(hulls[0])
                self._on_hull_change()

            # Combine spec fields
            fields = merged_cover["fields"]
            fields = combine_all(fields, spec_msbd)
            fields = combine_all(fields, spec_gsp)

            # IP fallback
            for _k in ('ms_ip','gsp_ip'):
                _v = (fields.get(_k) or '').strip().upper()
                if _v != 'IP22':
                    fields[_k] = 'IP22'

            # Parse panels
            try:
                ex.set_progress_cb(self._subprogress(60, 12))
                self.panels_data = ex.parse_panel_blocks_v2(msbd, gsp) or []
            except Exception as e:
                self.log(f"[WARN] 패널 파싱 실패: {e}")
                self.panels_data = []
            
            # Parse GSP function
            try:
                ex.set_progress_cb(self._subprogress(72, 8))
                self.gsp_function_data = ex.parse_function_test_of_gsp(gsp) or []
            except Exception as e:
                self.log(f"[WARN] GSP Function 파싱 실패: {e}")
                self.gsp_function_data = []
            
            # Parse Emergency Stop
            try:
                ex.set_progress_cb(self._subprogress(80, 10))
                
                # 신규 범용 파서 사용
                ems = ex.parse_emergency_stop_from_mccb(msbd)
                
                # MSBD 실패 시 GSP 시도
                if not ems:
                    ems = ex.parse_emergency_stop_from_mccb(gsp)
                
                # 둘 다 실패 시 기존 파서
                if not ems:
                    ems = ex.parse_emergency_colorplate(msbd)
                
                self.em_stops_data = ems or []
                
            except Exception as e:
                self.log(f"[WARN] Emergency 파싱 실패: {e}")
                import traceback
                traceback.print_exc()
                self.em_stops_data = []

            # Fill GENERAL SPEC entries
            for k, e in self.entries.items():
                e.delete(0, "end")
                if k in fields:
                    e.insert(0, str(fields[k]))

            # Refresh lists in tabs
            try:
                self._panel_fill_ui()
                self._gsp_refresh_ui()
                self._em_refresh_list()
            except Exception:
                pass

            self.progress(100, "완료")
            self.log("[OK] Extract finished.")
        
        self.after(0, ui_fill)

    def _validate_template_worker(self): 

        tpl = self.template_path.get().strip()
        if not os.path.isfile(tpl):
            self.after(0, lambda: messagebox.showerror("오류", "템플릿 DOCX를 먼저 선택하세요."))
            return
        missing = []
        keys_to_check = FIELDS + self.panel_template_keys + FUNCTION_TEST_KEYS
        try:
            with open(tpl, "rb") as f:
                data = f.read()
            text = data.decode(errors="ignore").lower()
            for key in keys_to_check:
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
        ctx.update(self._panel_collect_placeholders())
        gsp_panels_ctx = self._gsp_collect_from_ui()
        placeholder_map = {item.get("placeholder"): item for item in gsp_panels_ctx}
        for _, placeholder in self.gsp_function_slots:
            ctx[placeholder] = (placeholder_map.get(placeholder, {}).get("content") or "").strip()
        ctx["gsp_function_panels"] = [
            {
                "panel": item.get("panel", ""),
                "placeholder": item.get("placeholder", ""),
                "content": item.get("content", ""),
                "rows": [
                    {"code": row.get("code", ""), "name": row.get("name", "")}
                    for row in item.get("rows") or []
                ],
            }
            for item in gsp_panels_ctx
        ]
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


    def _panel_fill_ui(self):
        data_map: Dict[str, Dict[str, str]] = {}
        for item in self.panels_data or []:
            slot = str(item.get("slot")) if item.get("slot") else None
            if not slot:
                panel_name = (item.get("panel") or "").strip().upper()
                for spec in self.panel_slot_defs:
                    if spec.get("title", "").strip().upper() == panel_name:
                        slot = spec["slot"]
                        break
            if slot and slot not in data_map:
                data_map[slot] = item
        for slot in self.panel_slot_defs:
            vars_map = self.panel_slot_vars.setdefault(slot["slot"], {})
            values = data_map.get(slot["slot"], {})
            for field in PANEL_VALUE_FIELDS:
                var = vars_map.get(field)
                if var is None:
                    var = tk.StringVar()
                    vars_map[field] = var
                val = values.get(field, "") if isinstance(values, dict) else ""
                if not val and field == "panel":
                    val = slot["title"]
                var.set(str(val or ""))

    def _panel_snapshot(self) -> List[Dict[str, str]]:
        snapshot: List[Dict[str, str]] = []
        for slot in self.panel_slot_defs:
            vars_map = self.panel_slot_vars.get(slot["slot"], {})
            record: Dict[str, str] = {"slot": slot["slot"]}
            for field in PANEL_VALUE_FIELDS:
                var = vars_map.get(field)
                value = var.get().strip() if var else ""
                if field == "panel" and not value:
                    value = slot["title"]
                record[field] = value
            snapshot.append(record)
        self.panels_data = snapshot
        return snapshot

    def _panel_collect_placeholders(self) -> Dict[str, str]:
        snapshot = self._panel_snapshot()
        data_map = {item.get("slot"): item for item in snapshot}
        result: Dict[str, str] = {}
        for slot in self.panel_slot_defs:
            placeholders = slot["placeholders"]
            data = data_map.get(slot["slot"], {})
            for field, placeholder in placeholders.items():
                value = data.get(field, "") if isinstance(data, dict) else ""
                if field == "panel" and not value:
                    value = slot["title"]
                result[placeholder] = value
        return result

    def _panel_apply_from_ui(self):
        snapshot = self._panel_snapshot()
        names = ", ".join(item.get("panel", "") for item in snapshot if item.get("panel")) or "없음"
        self.log(f"[OK] 패널 정보 업데이트: {names}")

    def _gsp_placeholder_for_label(self, label: str) -> Optional[str]:
        target = (label or "").strip().lower()
        for title, key in self.gsp_function_slots:
            if title.lower() == target:
                return key
        return None

    @staticmethod
    def _circuit_sort_key(code: str) -> tuple:
        pattern = re.compile(r'P(\d+)-(\d+)-(\d+)-([A-Z]+)', re.I)
        m = pattern.match(code or "")
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).upper())
        return (9999, 9999, 9999, (code or "").upper())

    def _gsp_collect_from_ui(self) -> List[Dict[str, object]]:
        results: List[Dict[str, object]] = []
        data_map: Dict[str, Dict[str, object]] = {}
        for item in self.gsp_function_data:
            key = item.get("placeholder") or self._gsp_placeholder_for_label(item.get("panel", ""))
            if key and key not in data_map:
                data_map[key] = dict(item)
        for label, placeholder in self.gsp_function_slots:
            entry = data_map.get(placeholder) or {"panel": label, "rows": []}
            rows = entry.get("rows") or []
            sorted_rows = sorted(
                rows,
                key=lambda r: (self._circuit_sort_key(r.get("code", "")), r.get("order", 0)),
            )
            content = "\n".join(
                f"{row.get('code', '')} {row.get('name', '')}".strip()
                for row in sorted_rows
                if row.get("code") and row.get("name")
            ).strip()
            results.append(
                {
                    "panel": label,
                    "placeholder": placeholder,
                    "content": content,
                    "rows": sorted_rows,
                }
            )
        return results

    def _gsp_refresh_ui(self):
        data_map: Dict[str, Dict[str, object]] = {}
        for item in self.gsp_function_data:
            key = item.get("placeholder") or self._gsp_placeholder_for_label(item.get("panel", ""))
            if key:
                data_map[key] = item
        for label, placeholder in self.gsp_function_slots:
            tree = self.gsp_tree_widgets.get(placeholder)
            if tree:
                for child in tree.get_children():
                    tree.delete(child)
                rows = data_map.get(placeholder, {}).get("rows") or []
                if rows:
                    sorted_rows = sorted(
                        rows,
                        key=lambda r: (self._circuit_sort_key(r.get("code", "")), r.get("order", 0)),
                    )
                    for row in sorted_rows:
                        tree.insert("", "end", values=(row.get("code", ""), row.get("name", "")))
                else:
                    tree.insert("", "end", values=("", "추출된 데이터 없음"))

    def _em_refresh_list(self):
        if not hasattr(self, "em_tree"):
            return
        current = None
        sel = self.em_tree.selection()
        if sel:
            current = sel[0]
        for item in self.em_tree.get_children():
            self.em_tree.delete(item)
        for idx, e in enumerate(self.em_stops_data):
            code = e.get("code", "")
            color = e.get("color", "")
            name = e.get("name", "")
            self.em_tree.insert("", "end", iid=str(idx), values=(code, color, name))
        target = current if current in self.em_tree.get_children() else None
        if target is None and self.em_stops_data:
            target = "0"
        if target is not None:
            self.em_tree.selection_set(target)
            self.em_tree.focus(target)
            self._em_select()
        elif hasattr(self, "txt_em_circuits"):
            self.em_code.set("")
            self.em_color.set("")
            self.em_name.set("")
            self._update_color_chip("")
            self.txt_em_circuits.delete("1.0", "end")

    def _em_select(self):
        if not hasattr(self, "em_tree"):
            return
        sel = self.em_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.em_stops_data)):
            return
        e = self.em_stops_data[idx]
        self.em_code.set(e.get("code",""))
        self.em_color.set(e.get("color",""))
        self.em_name.set(e.get("name",""))
        self._update_color_chip(e.get("color",""))
        blocks = []
        code = e.get("code", "")
        for g in e.get("groups", []):
            header = g.get("panel_header","")
            circs = ", ".join(g.get("circuits", []))
            prefix = f"{code} " if code else ""
            body = circs if circs else ""
            blocks.append(f"{prefix}[{header}]\n{body}".strip())
        self.txt_em_circuits.delete("1.0","end")
        self.txt_em_circuits.insert("1.0","\n\n".join(blocks))

    def _em_apply(self):
        if not hasattr(self, "em_tree"):
            return
        sel = self.em_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.em_stops_data)):
            return
        e = self.em_stops_data[idx]
        e["code"] = self.em_code.get().strip()
        e["color"] = self.em_color.get().strip()
        e["name"] = self.em_name.get().strip()
        raw_blocks = self.txt_em_circuits.get("1.0","end").strip()
        blocks = [b.strip() for b in raw_blocks.split("\n\n") if b.strip()]
        groups = []
        for b in blocks:
            lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
            if not lines:
                continue
            first = lines[0]
            header = first
            if '[' in first and ']' in first:
                header = first[first.find('[')+1:first.rfind(']')]
            header = header.replace('*','').strip()
            rest_text = "\n".join(lines[1:])
            circs: List[str] = []
            tokens = re.findall(r'P\d{2}-\d{3}-\d{2}-[A-Z]{2}', rest_text.upper())
            if not tokens:
                tokens = re.findall(r'P\d{2}-\d{3}-\d{2}-[A-Z]{2}', first.upper())
            if tokens:
                seen: List[str] = []
                for t in tokens:
                    if t not in seen:
                        seen.append(t)
                circs = seen
            else:
                raw = rest_text if rest_text else "".join(lines[1:])
                if not raw:
                    raw = " ".join(lines[1:])
                for ln in lines[1:]:
                    for part in re.split(r'[,、;]+', ln):
                        val = part.strip()
                        if val:
                            circs.append(val)
            groups.append({"panel_header": header, "circuits": circs})
        e["groups"] = groups
        self.em_stops_data[idx] = e
        self._em_refresh_list()
        item_id = str(idx)
        if item_id in self.em_tree.get_children():
            self.em_tree.selection_set(item_id)
            self.em_tree.focus(item_id)
        self.log(f"[OK] Emergency 항목 업데이트: {e.get('code')}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
