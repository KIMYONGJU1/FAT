
# -*- coding: utf-8 -*-
"""
FAT AutoFill Pro (v2.4.2_fix13b)
- 안정 진짜수정: SyntaxError 제거, 스레드 기반 Progressbar로 무응답 방지
- Hull 변경 시 Class 자동 반영
"""
from __future__ import annotations

APP_NAME = "FAT AutoFill Pro (v3.4.3_TEMPLATE_PRESERVATION_FIX)"

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
from docx import Document
from copy import deepcopy
import tempfile


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



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DynamicTemplateFiller - 동적 행 생성 (v3.3.0 FINAL)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DynamicTemplateFiller:
    """Word 템플릿의 샘플 행을 복제해서 데이터 개수만큼 행 생성"""
    
    # ✅ v3.4.7: 범용 Circuit No 패턴 (모든 프로젝트 지원)
    CIRCUIT_NO_PATTERN = re.compile(r'^[A-Z]\d{2}-\d{3}-\d{2}-PN$')
    
    def __init__(self, doc_path):
        if isinstance(doc_path, str):
            self.doc = Document(doc_path)
        else:
            self.doc = doc_path
    
    @staticmethod
    def is_valid_circuit_no(circuit_no):
        """
        Circuit No 유효성 검사 (범용)
        
        Args:
            circuit_no: Circuit 번호 (예: P31-021-01-PN, P42-015-03-PN, S11-023-02-PN)
        
        Returns:
            bool: 유효하면 True
        
        Examples:
            >>> is_valid_circuit_no('P31-021-01-PN')  # SN2670 프로젝트
            True
            >>> is_valid_circuit_no('P42-015-03-PN')  # 다른 프로젝트
            True
            >>> is_valid_circuit_no('S11-023-02-PN')  # 다른 프로젝트
            True
            >>> is_valid_circuit_no('15')  # 숫자만
            False
            >>> is_valid_circuit_no('NO.1')  # 텍스트만
            False
        """
        if not circuit_no or not isinstance(circuit_no, str):
            return False
        return bool(DynamicTemplateFiller.CIRCUIT_NO_PATTERN.match(circuit_no))
    
    @staticmethod
    def get_panel_number(circuit_no):
        """
        Circuit No에서 Panel 번호 추출 (1 또는 2)
        
        Args:
            circuit_no: Circuit 번호 (예: P31-021-01-PN, P32-015-03-PN)
        
        Returns:
            int: Panel 번호 (1 또는 2), 실패 시 None
        
        Logic:
            - 두 번째 숫자가 홀수 → NO.1
            - 두 번째 숫자가 짝수 → NO.2
        
        Examples:
            >>> get_panel_number('P31-021-01-PN')  # 3[1] → 홀수 → NO.1
            1
            >>> get_panel_number('P32-015-03-PN')  # 3[2] → 짝수 → NO.2
            2
            >>> get_panel_number('P41-023-02-PN')  # 4[1] → 홀수 → NO.1
            1
            >>> get_panel_number('P42-012-05-PN')  # 4[2] → 짝수 → NO.2
            2
        """
        match = re.match(r'^[A-Z](\d)(\d)-', circuit_no)
        if match:
            second_digit = int(match.group(2))
            # 짝수면 NO.2, 홀수면 NO.1
            return 2 if second_digit % 2 == 0 else 1
        return None
    
    
    def _find_table_with_placeholder(self, placeholder):
        for t_idx, table in enumerate(self.doc.tables):
            for r_idx, row in enumerate(table.rows):
                for cell in row.cells:
                    if placeholder in cell.text:
                        return (t_idx, r_idx)
        return None
    
    def _clone_row(self, table, row_index):
        original_row = table.rows[row_index]
        new_row_element = deepcopy(original_row._element)
        table._element.append(new_row_element)
        return table.rows[-1]
    
    def _replace_placeholders_in_cell(self, cell, replacements):
        for paragraph in cell.paragraphs:
            for key, value in replacements.items():
                if key in paragraph.text:
                    for run in paragraph.runs:
                        if key in run.text:
                            run.text = run.text.replace(key, str(value))
    
    def fill_panel_information_dynamic(self, panel_data):
        """PANEL INFORMATION 동적 생성"""
        result = self._find_table_with_placeholder("{{panel_name_1}}")
        if not result:
            print("[INFO] PANEL INFORMATION 표 없음 (스킵)")
            return
        
        table_idx, template_row_idx = result
        table = self.doc.tables[table_idx]
        print(f"\n[INFO] PANEL INFORMATION 표 발견: Table {table_idx+1}")
        template_row = table.rows[template_row_idx]
        
        for idx, item in enumerate(panel_data):
            # ✅ v3.4.3: 첫 번째 행도 복제하여 템플릿 보존!
            new_row = self._clone_row(table, template_row_idx)
            
            replacements = {
                '{{panel_name_1}}': item.get('panel', ''),
                '{{panel_acb_type_1}}': item.get('acb_type', ''),
                '{{panel_ocr_type_1}}': item.get('ocr_type', ''),
                '{{panel_frame_1}}': item.get('ampere_frame', ''),
                '{{panel_rated_1}}': item.get('rated_current_in', ''),
                '{{panel_ir_pct_1}}': item.get('ir_percent', ''),
                '{{panel_ir_amp_1}}': item.get('ir_amps', ''),
                '{{panel_isd_1}}': '', '{{panel_key_1}}': '',
                '{{panel_set_1}}': '', '{{panel_time_1}}': ''
            }
            for cell in new_row.cells:
                self._replace_placeholders_in_cell(cell, replacements)
            print(f"  ✓ {item.get('panel', '')} 추가")
        
        # ✅ v3.4.3: 템플릿 행 삭제
        table._element.remove(template_row._element)
        print(f"  최종 행 개수: {len(table.rows)}")
    
    def fill_gsp_function_test_dynamic(self, gsp_data):
        """GSP FUNCTION TEST 동적 생성 - NO.1과 NO.2 섹션 분리 (범용)"""
        # NO.1과 NO.2 데이터 분리
        no1_circuits = []
        no2_circuits = []
        
        print(f"\n[DEBUG] ===== GSP 데이터 구조 분석 시작 =====")
        print(f"[DEBUG] gsp_data 타입: {type(gsp_data)}")
        print(f"[DEBUG] gsp_data 길이: {len(gsp_data) if isinstance(gsp_data, (list, dict)) else 'N/A'}")
        
        for panel_idx, panel_item in enumerate(gsp_data):
            print(f"\n[DEBUG] Panel {panel_idx+1}:")
            print(f"  타입: {type(panel_item)}")
            
            panel_name = panel_item.get('panel_name', '') if isinstance(panel_item, dict) else ''
            panel_hint = None
            placeholder = panel_item.get('placeholder', '') if isinstance(panel_item, dict) else ''
            if isinstance(placeholder, str):
                if 'no1' in placeholder.lower():
                    panel_hint = 1
                elif 'no2' in placeholder.lower():
                    panel_hint = 2

            rows = panel_item.get('rows', []) if isinstance(panel_item, dict) else []
            
            print(f"  panel_name: {panel_name}")
            print(f"  rows 타입: {type(rows)}")
            print(f"  rows 길이: {len(rows) if isinstance(rows, (list, dict)) else 'N/A'}")
            
            # ✅ v3.4.9: 데이터 구조 자동 감지 및 처리
            if isinstance(rows, dict):
                # 딕셔너리 구조: {circuit_no: [values]}
                print(f"  [구조] 딕셔너리 ({len(rows)}개 Circuit)")
                print(f"  [샘플] 첫 3개 키: {list(rows.keys())[:3]}")
                
                for circuit_no, values in rows.items():
                    # Circuit No 유효성 검사
                    if self.is_valid_circuit_no(circuit_no):
                        # circuit_name 추출
                        circuit_name = ""
                        if isinstance(values, list):
                            for val in values:
                                if isinstance(val, str) and len(val) > 10 and not val.replace('.', '').replace('-', '').isdigit():
                                    circuit_name = val
                                    break
                        
                        row_data = {
                            'circuit_no': circuit_no,
                            'circuit_name': circuit_name
                        }
                        
                        # Panel 번호로 자동 분리
                        panel_num = self.get_panel_number(circuit_no) or panel_hint
                        if panel_num == 1:
                            no1_circuits.append(row_data)
                        elif panel_num == 2:
                            no2_circuits.append(row_data)
            
            elif isinstance(rows, list) and len(rows) > 0:
                # 리스트 구조
                print(f"  [구조] 리스트 ({len(rows)}개 행)")
                
                # 첫 번째 항목 분석
                first_row = rows[0]
                print(f"  [샘플] 첫 번째 행 타입: {type(first_row)}")
                
                if isinstance(first_row, dict):
                    # 리스트 of 딕셔너리
                    print(f"  [샘플] 첫 번째 행 키: {list(first_row.keys())[:5]}")
                    
                    valid_rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        
                        circuit_no = row.get('circuit_no', '')
                        
                        # Circuit No 형식 검증
                        if self.is_valid_circuit_no(circuit_no):
                            valid_rows.append(row)
                    
                    print(f"  [필터링] {len(rows)}개 → {len(valid_rows)}개 (유효)")
                    
                    # Panel 번호로 자동 분리
                    for row in valid_rows:
                        circuit_no = row.get('circuit_no', '')
                        panel_num = self.get_panel_number(circuit_no) or panel_hint
                        
                        if panel_num == 1:
                            no1_circuits.append(row)
                        elif panel_num == 2:
                            no2_circuits.append(row)
                
                else:
                    # 리스트 of 기타 (문자열, 숫자 등)
                    print(f"  [샘플] 첫 번째 행 값: {first_row}")
                    print(f"  [경고] 예상치 못한 데이터 구조 - 건너뜀")
        
        print(f"\n[DEBUG] ===== GSP 데이터 구조 분석 완료 =====")
        print(f"[DEBUG] NO.1 GSP: {len(no1_circuits)}개 Circuit (필터링 후)")
        print(f"[DEBUG] NO.2 GSP: {len(no2_circuits)}개 Circuit (필터링 후)")
        
        # NO.1 샘플 출력
        if no1_circuits:
            print(f"[DEBUG] NO.1 샘플 (첫 3개):")
            for circ in no1_circuits[:3]:
                print(f"  - {circ.get('circuit_no', 'N/A')}: {circ.get('circuit_name', 'N/A')}")
        
        # NO.2 샘플 출력
        if no2_circuits:
            print(f"[DEBUG] NO.2 샘플 (첫 3개):")
            for circ in no2_circuits[:3]:
                print(f"  - {circ.get('circuit_no', 'N/A')}: {circ.get('circuit_name', 'N/A')}")
        
        # ✅ v3.4.9: NO.1 섹션 처리
        result_no1 = self._find_table_with_placeholder("{{gsp_circuit_1}}")
        if result_no1:
            table_idx, template_row_idx = result_no1
            table = self.doc.tables[table_idx]
            print(f"\n[INFO] GSP FUNCTION TEST (NO.1) 표 발견: Table {table_idx+1}")
            template_row = table.rows[template_row_idx]
            
            for circuit in no1_circuits:
                new_row = self._clone_row(table, template_row_idx)
                replacements = {
                    '{{gsp_circuit_1}}': circuit.get('circuit_no', ''),
                    '{{gsp_name_1}}': circuit.get('circuit_name', ''),
                    '{{gsp_local_1}}': '□', '{{gsp_remote_1}}': '□',
                    '{{gsp_heater_1}}': '□', '{{gsp_phase_1}}': '□',
                    '{{gsp_remark_1}}': ''
                }
                for cell in new_row.cells:
                    self._replace_placeholders_in_cell(cell, replacements)
            
            # 템플릿 행 삭제
            table._element.remove(template_row._element)
            print(f"  ✓ NO.1: {len(no1_circuits)}개 Circuit 추가")
        else:
            print("[INFO] GSP FUNCTION TEST (NO.1) 표 없음 (스킵)")
        
        # ✅ v3.4.9: NO.2 섹션 처리
        result_no2 = self._find_table_with_placeholder("{{gsp_circuit_2}}")
        if result_no2:
            table_idx, template_row_idx = result_no2
            table = self.doc.tables[table_idx]
            print(f"\n[INFO] GSP FUNCTION TEST (NO.2) 표 발견: Table {table_idx+1}")
            template_row = table.rows[template_row_idx]
            
            for circuit in no2_circuits:
                new_row = self._clone_row(table, template_row_idx)
                replacements = {
                    '{{gsp_circuit_2}}': circuit.get('circuit_no', ''),
                    '{{gsp_name_2}}': circuit.get('circuit_name', ''),
                    '{{gsp_local_2}}': '□', '{{gsp_remote_2}}': '□',
                    '{{gsp_heater_2}}': '□', '{{gsp_phase_2}}': '□',
                    '{{gsp_remark_2}}': ''
                }
                for cell in new_row.cells:
                    self._replace_placeholders_in_cell(cell, replacements)
            
            # 템플릿 행 삭제
            table._element.remove(template_row._element)
            print(f"  ✓ NO.2: {len(no2_circuits)}개 Circuit 추가")
        else:
            print("[INFO] GSP FUNCTION TEST (NO.2) 표 없음 (스킵)")
        
        print(f"  최종 행 개수: {len(self.doc.tables[table_idx].rows) if result_no1 or result_no2 else 0}")
    
    
    def fill_emergency_table_dynamic(self, emergency_data):
        """EMERGENCY STOP 동적 생성"""
        result = self._find_table_with_placeholder("{{emcy_code_1}}")
        if not result:
            print("[INFO] EMERGENCY 표 없음 (스킵)")
            return
        
        table_idx, template_row_idx = result
        table = self.doc.tables[table_idx]
        print(f"\n[INFO] EMERGENCY 표 발견: Table {table_idx+1}")
        template_row = table.rows[template_row_idx]
        
        for idx, item in enumerate(emergency_data):
            # ✅ v3.4.3: 첫 번째 행도 복제하여 템플릿 보존!
            new_row = self._clone_row(table, template_row_idx)
            
            circuit_text = ""
            groups_list = item.get('groups', [])
            
            for group in groups_list:
                panel_header = group.get('panel_header', '')
                circuits = group.get('circuits', [])
                
                circuit_text += f"[{panel_header}]\n"
                for i in range(0, len(circuits), 3):
                    chunk = circuits[i:i+3]
                    circuit_text += ", ".join(chunk)
                    circuit_text += ",\n" if i + 3 < len(circuits) else "\n"
                circuit_text += "\n"
            circuit_text = circuit_text.strip()
            
            replacements = {
                '{{emcy_code_1}}': item.get('code', ''),
                '{{emcy_color_1}}': item.get('color', ''),
                '{{emcy_name_1}}': item.get('name', ''),
                '{{emcy_circuit_1}}': circuit_text
            }
            for cell in new_row.cells:
                self._replace_placeholders_in_cell(cell, replacements)
            print(f"  ✓ {item.get('code', '')} 추가")
        
        # ✅ v3.4.3: 템플릿 행 삭제
        table._element.remove(template_row._element)
        print(f"  최종 행 개수: {len(table.rows)}")
    
    def fill_preferential_table_dynamic(self, preferential_data):
        """PREFERENTIAL TRIP 동적 생성 (NO1/NO2 분리, 범용)"""
        result = self._find_table_with_placeholder("{{pref_code_1}}")
        if not result:
            print("[INFO] PREFERENTIAL 표 없음 (스킵)")
            return
        
        table_idx, template_row_idx = result
        table = self.doc.tables[table_idx]
        print(f"\n[INFO] PREFERENTIAL 표 발견: Table {table_idx+1}")
        template_row = table.rows[template_row_idx]
        
        for idx, item in enumerate(preferential_data):
            # ✅ v3.4.3: 첫 번째 행도 복제하여 템플릿 보존!
            new_row = self._clone_row(table, template_row_idx)
            
            # ✅ v3.4.7: 두 가지 데이터 구조 지원 + 범용 분리
            no1_circuits = []
            no2_circuits = []
            
            # groups 구조 처리
            groups_list = item.get('groups', [])
            if groups_list:
                for group in groups_list:
                    panel_header = group.get('panel_header', '')
                    circuits = group.get('circuits', [])
                    
                    if 'No.1' in panel_header or 'NO.1' in panel_header:
                        no1_circuits.extend(circuits)
                    elif 'No.2' in panel_header or 'NO.2' in panel_header:
                        no2_circuits.extend(circuits)
            else:
                # ✅ v3.4.7: circuits 구조 처리 (범용 자동 분리)
                circuits = item.get('circuits', [])
                for circuit in circuits:
                    # Circuit No 유효성 검사
                    if self.is_valid_circuit_no(circuit):
                        panel_num = self.get_panel_number(circuit)
                        if panel_num == 1:
                            no1_circuits.append(circuit)
                        elif panel_num == 2:
                            no2_circuits.append(circuit)
            
            print(f"  [DEBUG] {item.get('code', '')}: NO.1={len(no1_circuits)}개, NO.2={len(no2_circuits)}개")
            
            # NO1 텍스트 생성 (3개씩 묶어서)
            no1_text = ""
            for i in range(0, len(no1_circuits), 3):
                chunk = no1_circuits[i:i+3]
                no1_text += ", ".join(chunk)
                if i + 3 < len(no1_circuits):
                    no1_text += ",\n"
            
            # NO2 텍스트 생성 (3개씩 묶어서)
            no2_text = ""
            for i in range(0, len(no2_circuits), 3):
                chunk = no2_circuits[i:i+3]
                no2_text += ", ".join(chunk)
                if i + 3 < len(no2_circuits):
                    no2_text += ",\n"
            
            # COLOR 괄호 처리
            color = item.get('color', '').strip()
            if color and not color.startswith('('):
                color = f"({color})"
            
            replacements = {
                '{{pref_code_1}}': item.get('code', ''),
                '{{pref_color_1}}': color,
                '{{pref_no1_circuit_1}}': no1_text,  # NO1 Panel
                '{{pref_no2_circuit_1}}': no2_text   # NO2 Panel
            }
            for cell in new_row.cells:
                self._replace_placeholders_in_cell(cell, replacements)
            print(f"  ✓ {item.get('code', '')} 추가")
        
        # ✅ v3.4.3: 템플릿 행 삭제
        table._element.remove(template_row._element)
        print(f"  최종 행 개수: {len(table.rows)}")



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
            if hasattr(self, "em_color_chip"):
                self.em_color_chip.configure(bg=hex_color)
            if hasattr(self, "pt_color_chip"):
                self.pt_color_chip.configure(bg=hex_color)
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
        self.pt_trips_data = []
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
        self.page_ptrip = ttk.Frame(self.values_nb)
        self.page_gsp = ttk.Frame(self.values_nb)
        self.values_nb.add(self.page_spec, text="① 표지 / GENERAL SPEC")
        self.values_nb.add(self.page_panel, text="② PANEL INFORMATION")
        self.values_nb.add(self.page_gsp, text="③ FUNCTION TEST OF GSP")
        self.values_nb.add(self.page_estop, text="④ EMERGENCY STOP PANEL")
        self.values_nb.add(self.page_ptrip, text="⑤ PREFERENTIAL TRIP LIST")
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
        self.em_tree.column("name", width=360, anchor="w", stretch=True)
        em_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.em_tree.yview)
        em_hscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.em_tree.xview)
        self.em_tree.configure(yscrollcommand=em_scroll.set, xscrollcommand=em_hscroll.set)
        # shift + 휠로 좌우 이동, 트리폭보다 긴 이름을 드래그로 확인
        self.em_tree.bind("<Shift-MouseWheel>", lambda e: self.em_tree.xview_scroll(int(-1 * (e.delta/120)), "units"))
        self.em_tree.bind("<ButtonPress-2>", lambda e: self.em_tree.scan_mark(e.x, e.y))
        self.em_tree.bind("<B2-Motion>", lambda e: self.em_tree.scan_dragto(e.x, e.y, gain=1))
        self.em_tree.bind("<ButtonPress-1>", self._em_tree_drag_start, add="+")
        self.em_tree.bind("<B1-Motion>", self._em_tree_drag_move, add="+")
        self.em_tree.bind("<Configure>", lambda e: self._em_resize_columns())
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

        # Preferential Trip tab (⑤)
        ptrip_wrap = ttk.Frame(self.page_ptrip, padding=12)
        ptrip_wrap.pack(fill="both", expand=True)
        ptrip_paned = ttk.PanedWindow(ptrip_wrap, orient="horizontal")
        ptrip_paned.pack(fill="both", expand=True)

        left_ptrip = ttk.Frame(ptrip_paned)
        ptrip_paned.add(left_ptrip, weight=1)
        right_ptrip = ttk.Frame(ptrip_paned)
        ptrip_paned.add(right_ptrip, weight=2)

        pt_list_frame = ttk.Frame(left_ptrip)
        pt_list_frame.pack(fill="both", expand=True)
        pt_columns = ("code", "color", "name")
        self.pt_tree = ttk.Treeview(pt_list_frame, columns=pt_columns, show="headings", selectmode="browse")
        self.pt_tree.grid(row=0, column=0, sticky="nsew")
        self.pt_tree.heading("code", text="CODE")
        self.pt_tree.heading("color", text="COLOR")
        self.pt_tree.heading("name", text="NAME")
        self.pt_tree.column("code", width=110, anchor="w", stretch=False)
        self.pt_tree.column("color", width=120, anchor="w", stretch=False)
        self.pt_tree.column("name", width=360, anchor="w", stretch=True)
        pt_scroll = ttk.Scrollbar(pt_list_frame, orient="vertical", command=self.pt_tree.yview)
        pt_hscroll = ttk.Scrollbar(pt_list_frame, orient="horizontal", command=self.pt_tree.xview)
        self.pt_tree.configure(yscrollcommand=pt_scroll.set, xscrollcommand=pt_hscroll.set)
        self.pt_tree.bind("<Shift-MouseWheel>", lambda e: self.pt_tree.xview_scroll(int(-1 * (e.delta/120)), "units"))
        self.pt_tree.bind("<ButtonPress-2>", lambda e: self.pt_tree.scan_mark(e.x, e.y))
        self.pt_tree.bind("<B2-Motion>", lambda e: self.pt_tree.scan_dragto(e.x, e.y, gain=1))
        self.pt_tree.bind("<ButtonPress-1>", self._pt_tree_drag_start, add="+")
        self.pt_tree.bind("<B1-Motion>", self._pt_tree_drag_move, add="+")
        self.pt_tree.bind("<Configure>", lambda e: self._pt_resize_columns())
        pt_scroll.grid(row=0, column=1, sticky="ns")
        pt_hscroll.grid(row=1, column=0, sticky="ew")
        self.pt_tree.bind("<<TreeviewSelect>>", lambda e: self._pt_select())
        pt_list_frame.columnconfigure(0, weight=1)
        pt_list_frame.rowconfigure(0, weight=1)
        ttk.Button(left_ptrip, text="새로고침", command=self._pt_refresh_list).pack(fill="x", pady=(6, 0))

        info_ptrip = ttk.LabelFrame(right_ptrip, text="PREFERENTIAL TRIP 기본 정보", padding=12)
        info_ptrip.pack(fill="x")
        self.pt_code = tk.StringVar()
        self.pt_name = tk.StringVar()
        self.pt_color = tk.StringVar()
        ttk.Label(info_ptrip, text="CODE").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(info_ptrip, textvariable=self.pt_code, width=20).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(info_ptrip, text="COLOR").grid(row=1, column=0, sticky="w", pady=2)
        pt_color_holder = ttk.Frame(info_ptrip)
        pt_color_holder.grid(row=1, column=1, sticky="ew", pady=2)
        pt_color_holder.columnconfigure(0, weight=1)
        ttk.Entry(pt_color_holder, textvariable=self.pt_color).grid(row=0, column=0, sticky="ew")
        self.pt_color_chip = tk.Label(pt_color_holder, width=10, relief="groove", borderwidth=1)
        self.pt_color_chip.grid(row=0, column=1, padx=(6,0))
        ttk.Label(info_ptrip, text="NAME").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(info_ptrip, textvariable=self.pt_name, width=40).grid(row=2, column=1, sticky="ew", pady=2)
        info_ptrip.columnconfigure(1, weight=1)

        pt_groups_frame = ttk.LabelFrame(right_ptrip, text="회로 그룹 (CODE별 패널)", padding=12)
        pt_groups_frame.pack(fill="both", expand=True, pady=(10, 0))
        pt_groups_frame.columnconfigure(0, weight=1)
        pt_groups_frame.rowconfigure(0, weight=1)
        ttk.Label(pt_groups_frame, text="예: PT-1 [No.1 AC440V FEEDER PANEL]\nP31-001-01-PN, P31-002-01-PN", justify="left").grid(row=0, column=0, sticky="w", pady=(0,6))
        self.txt_pt_circuits = tk.Text(pt_groups_frame, wrap="word")
        self.txt_pt_circuits.grid(row=1, column=0, sticky="nsew")
        pt_vsb = ttk.Scrollbar(pt_groups_frame, orient="vertical", command=self.txt_pt_circuits.yview)
        pt_vsb.grid(row=1, column=1, sticky="ns")
        pt_hsb = ttk.Scrollbar(pt_groups_frame, orient="horizontal", command=self.txt_pt_circuits.xview)
        pt_hsb.grid(row=2, column=0, sticky="ew")
        self.txt_pt_circuits.configure(yscrollcommand=pt_vsb.set, xscrollcommand=pt_hsb.set)
        ttk.Button(right_ptrip, text="적용(현 항목)", command=self._pt_apply).pack(anchor="e", pady=(8, 0))

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
                
                # MSBD와 GSP 둘 다 스캔하고 병합
                ems_msbd = ex.parse_emergency_stop_from_mccb(msbd) or []
                ems_gsp = ex.parse_emergency_stop_from_mccb(gsp) or []
                
                # 두 결과 병합 (CODE가 같으면 groups를 합침)
                if ems_msbd and ems_gsp:
                    self.log("[INFO] MSBD와 GSP 결과 병합 중...")
                    ems_combined = {}
                    
                    # MSBD 결과 먼저 추가
                    for item in ems_msbd:
                        code = item.get('code', '')
                        ems_combined[code] = item
                    
                    # GSP 결과 병합
                    for item in ems_gsp:
                        code = item.get('code', '')
                        if code in ems_combined:
                            # 기존 항목에 groups 추가
                            existing_groups = ems_combined[code].get('groups', [])
                            new_groups = item.get('groups', [])
                            ems_combined[code]['groups'] = existing_groups + new_groups
                            self.log(f"  [MERGE] {code}: {len(existing_groups)} + {len(new_groups)} circuits")
                        else:
                            # 새로운 CODE
                            ems_combined[code] = item
                    
                    ems = list(ems_combined.values())
                    self.log(f"[OK] 병합 완료: 총 {len(ems)}개 CODE")
                
                elif ems_msbd:
                    ems = ems_msbd
                    self.log("[INFO] MSBD 결과만 사용")
                elif ems_gsp:
                    ems = ems_gsp
                    self.log("[INFO] GSP 결과만 사용")
                else:
                    # 둘 다 실패 시 기존 파서
                    ems = ex.parse_emergency_colorplate(msbd)
                    self.log("[WARN] 기존 파서 사용 (MSBD/GSP 실패)")
                
                ems = ems or []
                self._split_em_and_pt(ems)

            except Exception as e:
                self.log(f"[WARN] Emergency 파싱 실패: {e}")
                import traceback
                traceback.print_exc()
                self.em_stops_data = []
                self.pt_trips_data = []

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
                self._pt_refresh_list()
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
        """v3.3.0 FINAL 보고서 생성 - 동적 행 생성 포함"""
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
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 동적 행 생성용 데이터 준비
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        # 1. PANEL INFORMATION
        panel_data = self.panels_data if hasattr(self, 'panels_data') and self.panels_data else []
        
        # 2. FUNCTION TEST OF GSP
        gsp_function_data = self.gsp_function_data if hasattr(self, 'gsp_function_data') and self.gsp_function_data else []
        
        # 3. EMERGENCY STOP / PREFERENTIAL TRIP
        emergency_data = self.em_stops_data if hasattr(self, 'em_stops_data') and self.em_stops_data else []
        preferential_data = self.pt_trips_data if hasattr(self, 'pt_trips_data') and self.pt_trips_data else []
        
        if panel_data:
            self.log(f"[INFO] Panel: {len(panel_data)}개")
        if gsp_function_data:
            self.log(f"[INFO] GSP: {len(gsp_function_data)}개 Panel")
        if emergency_data or preferential_data:
            self.log(f"[INFO] Emergency: {len(emergency_data)}개, Preferential: {len(preferential_data)}개")
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 동적 플레이스홀더를 ctx에 추가 (DocxTemplate이 건드리지 않도록)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 중요: DocxTemplate.render()는 ctx에 없는 {{...}} 플레이스홀더를 삭제할 수 있음
        # 따라서 동적으로 사용할 플레이스홀더들을 빈 값이 아닌 자기 자신으로 설정
        dynamic_placeholders = {
            # PANEL INFORMATION - 자기 자신으로 설정하여 보존
            'panel_name_1': '{{panel_name_1}}',
            'panel_acb_type_1': '{{panel_acb_type_1}}',
            'panel_ocr_type_1': '{{panel_ocr_type_1}}',
            'panel_frame_1': '{{panel_frame_1}}',
            'panel_rated_1': '{{panel_rated_1}}',
            'panel_ir_pct_1': '{{panel_ir_pct_1}}',
            'panel_ir_amp_1': '{{panel_ir_amp_1}}',
            'panel_isd_1': '{{panel_isd_1}}',
            'panel_key_1': '{{panel_key_1}}',
            'panel_set_1': '{{panel_set_1}}',
            'panel_time_1': '{{panel_time_1}}',
            
            # GSP FUNCTION TEST
            'gsp_circuit_1': '{{gsp_circuit_1}}',
            'gsp_name_1': '{{gsp_name_1}}',
            'gsp_local_1': '{{gsp_local_1}}',
            'gsp_remote_1': '{{gsp_remote_1}}',
            'gsp_heater_1': '{{gsp_heater_1}}',
            'gsp_phase_1': '{{gsp_phase_1}}',
            'gsp_remark_1': '{{gsp_remark_1}}',
            'gsp_circuit_2': '{{gsp_circuit_2}}',
            'gsp_name_2': '{{gsp_name_2}}',
            'gsp_local_2': '{{gsp_local_2}}',
            'gsp_remote_2': '{{gsp_remote_2}}',
            'gsp_heater_2': '{{gsp_heater_2}}',
            'gsp_phase_2': '{{gsp_phase_2}}',
            'gsp_remark_2': '{{gsp_remark_2}}',
            
            # EMERGENCY STOP
            'emcy_code_1': '{{emcy_code_1}}',
            'emcy_color_1': '{{emcy_color_1}}',
            'emcy_name_1': '{{emcy_name_1}}',
            'emcy_circuit_1': '{{emcy_circuit_1}}',

            # PREFERENTIAL TRIP
            'pref_code_1': '{{pref_code_1}}',
            'pref_color_1': '{{pref_color_1}}',
            'pref_no1_circuit_1': '{{pref_no1_circuit_1}}',
            'pref_no2_circuit_1': '{{pref_no2_circuit_1}}',
        }
        ctx.update(dynamic_placeholders)
        self.log("[DEBUG] 동적 플레이스홀더 보존 설정 완료")
        
        try:
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 1단계: DocxTemplate로 기본 placeholder 치환
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            doc = DocxTemplate(tpl)
            doc.render(ctx)
            
            # 임시 파일로 저장
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
            temp_path = temp_file.name
            temp_file.close()
            doc.save(temp_path)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 2단계: DynamicTemplateFiller로 동적 행 생성
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            filler = DynamicTemplateFiller(temp_path)
            
            if panel_data:
                self.log("[INFO] PANEL TABLE 동적 생성...")
                filler.fill_panel_information_dynamic(panel_data)
            
            if gsp_function_data:
                self.log("[INFO] GSP TABLE 동적 생성...")
                filler.fill_gsp_function_test_dynamic(gsp_function_data)
            
            if emergency_data:
                self.log("[INFO] EMERGENCY TABLE 동적 생성...")
                filler.fill_emergency_table_dynamic(emergency_data)
            
            if preferential_data:
                self.log("[INFO] PREFERENTIAL TABLE 동적 생성...")
                filler.fill_preferential_table_dynamic(preferential_data)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 3단계: 최종 파일로 저장
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            hull = ctx.get("hull_no","SNXXXX")
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            out_path = os.path.join(self.save_dir.get().strip() or os.getcwd(), f"FAT_Report_{hull}_{now}.docx")
            
            filler.doc.save(out_path)
            
            # 임시 파일 삭제
            try:
                os.unlink(temp_path)
            except:
                pass
            
            self.after(0, lambda: [
                self.log(f"[OK] 보고서 생성 완료: {out_path}"),
                messagebox.showinfo("완료", f"보고서 생성 완료:\n{out_path}")
            ])
            
        except Exception as e:
            self.after(0, lambda: [
                self.log(f"[ERROR] 보고서 생성 실패: {e}"),
                messagebox.showerror("오류", f"보고서 생성 실패:\n{e}")
            ])
            import traceback
            traceback.print_exc()


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
    def _normalize_gsp_row(row: Dict[str, object]) -> Dict[str, str]:
        code = ""
        name = ""
        order = 0
        if isinstance(row, dict):
            code = row.get("code") or row.get("circuit_no") or ""
            name = row.get("name") or row.get("circuit_name") or ""
            try:
                order = int(row.get("order", 0))
            except Exception:
                order = 0
        return {"code": str(code).strip(), "name": str(name).strip(), "order": order}

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
            rows = [self._normalize_gsp_row(r) for r in (entry.get("rows") or [])]
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
                rows = [self._normalize_gsp_row(r) for r in (data_map.get(placeholder, {}).get("rows") or [])]
                if rows:
                    sorted_rows = sorted(
                        rows,
                        key=lambda r: (self._circuit_sort_key(r.get("code", "")), r.get("order", 0)),
                    )
                    for row in sorted_rows:
                        tree.insert("", "end", values=(row.get("code", ""), row.get("name", "")))
                else:
                    tree.insert("", "end", values=("", "추출된 데이터 없음"))

    def _split_em_and_pt(self, items: List[Dict[str, object]]):
        self.em_stops_data = []
        self.pt_trips_data = []
        for item in items or []:
            code = (item.get("code") or "").upper()
            name = (item.get("name") or "").upper()
            is_pt = code.startswith("PT") or "PREFERENTIAL TRIP" in name
            if is_pt:
                self.pt_trips_data.append(dict(item))
            else:
                self.em_stops_data.append(dict(item))

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
        self._em_resize_columns()
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

    def _em_tree_drag_start(self, event):
        if not hasattr(self, "em_tree"):
            return
        if event.state & 0x0001:  # Shift + drag
            self.em_tree.scan_mark(event.x, event.y)
            return "break"

    def _em_tree_drag_move(self, event):
        if not hasattr(self, "em_tree"):
            return
        if event.state & 0x0001:
            self.em_tree.scan_dragto(event.x, event.y, gain=1)
            return "break"

    def _em_resize_columns(self):
        try:
            total = self.em_tree.winfo_width()
            fixed = self.em_tree.column("code", "width") + self.em_tree.column("color", "width") + 28
            self.em_tree.column("name", width=max(220, total - fixed))
        except Exception:
            pass

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
            # CODE prefix 제거 - header만 표시
            body = circs if circs else ""
            blocks.append(f"[{header}]\n{body}".strip())
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

    # ---------- Preferential Trip helpers ----------
    def _pt_refresh_list(self):
        if not hasattr(self, "pt_tree"):
            return
        current = None
        sel = self.pt_tree.selection()
        if sel:
            current = sel[0]
        for item in self.pt_tree.get_children():
            self.pt_tree.delete(item)
        for idx, e in enumerate(self.pt_trips_data):
            code = e.get("code", "")
            color = e.get("color", "")
            name = e.get("name", "")
            self.pt_tree.insert("", "end", iid=str(idx), values=(code, color, name))
        self._pt_resize_columns()
        target = current if current in self.pt_tree.get_children() else None
        if target is None and self.pt_trips_data:
            target = "0"
        if target is not None:
            self.pt_tree.selection_set(target)
            self.pt_tree.focus(target)
            self._pt_select()
        elif hasattr(self, "txt_pt_circuits"):
            self.pt_code.set("")
            self.pt_color.set("")
            self.pt_name.set("")
            self._update_color_chip("")
            self.txt_pt_circuits.delete("1.0", "end")

    def _pt_tree_drag_start(self, event):
        if not hasattr(self, "pt_tree"):
            return
        if event.state & 0x0001:
            self.pt_tree.scan_mark(event.x, event.y)
            return "break"

    def _pt_tree_drag_move(self, event):
        if not hasattr(self, "pt_tree"):
            return
        if event.state & 0x0001:
            self.pt_tree.scan_dragto(event.x, event.y, gain=1)
            return "break"

    def _pt_resize_columns(self):
        try:
            total = self.pt_tree.winfo_width()
            fixed = self.pt_tree.column("code", "width") + self.pt_tree.column("color", "width") + 28
            self.pt_tree.column("name", width=max(220, total - fixed))
        except Exception:
            pass

    def _pt_select(self):
        if not hasattr(self, "pt_tree"):
            return
        sel = self.pt_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.pt_trips_data)):
            return
        e = self.pt_trips_data[idx]
        self.pt_code.set(e.get("code",""))
        self.pt_color.set(e.get("color",""))
        self.pt_name.set(e.get("name",""))
        self._update_color_chip(e.get("color",""))
        blocks = []
        code = e.get("code", "")
        for g in e.get("groups", []):
            header = g.get("panel_header","")
            circs = ", ".join(g.get("circuits", []))
            # CODE prefix 제거 - header만 표시
            body = circs if circs else ""
            blocks.append(f"[{header}]\n{body}".strip())
        self.txt_pt_circuits.delete("1.0","end")
        self.txt_pt_circuits.insert("1.0","\n\n".join(blocks))

    def _pt_apply(self):
        if not hasattr(self, "pt_tree"):
            return
        sel = self.pt_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if not (0 <= idx < len(self.pt_trips_data)):
            return
        e = self.pt_trips_data[idx]
        e["code"] = self.pt_code.get().strip()
        e["color"] = self.pt_color.get().strip()
        e["name"] = self.pt_name.get().strip()
        raw_blocks = self.txt_pt_circuits.get("1.0","end").strip()
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
        self.pt_trips_data[idx] = e
        self._pt_refresh_list()
        item_id = str(idx)
        if item_id in self.pt_tree.get_children():
            self.pt_tree.selection_set(item_id)
            self.pt_tree.focus(item_id)
        self.log(f"[OK] PREFERENTIAL 항목 업데이트: {e.get('code')}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
