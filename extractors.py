# -*- coding: utf-8 -*-
"""
FAT AutoFill Extractors (v2.4.4 - Emergency Circuit REMARKS 집중)
- REMARKS 컬럼에서 Emergency CODE 추출
- MSBD/GSP NAME PLATE (MCCB) 페이지 정확히 파싱
- Circuit 매칭 여부와 상관없이 모든 CODE 표시
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
import os, re
import pdfplumber

# ------------------------
# Progress Hook
# ------------------------
PROGRESS_CB = None

def set_progress_cb(cb):
    global PROGRESS_CB
    PROGRESS_CB = cb

def _notify_progress(pct:int, tag:str=None):
    cb = PROGRESS_CB
    if cb:
        try:
            cb(int(pct), tag)
        except Exception:
            pass

# ------------------------
# Text Readers
# ------------------------
def read_page_text(pdf_path: str, page_index: int) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if 0 <= page_index < len(pdf.pages):
                return pdf.pages[page_index].extract_text() or ""
    except Exception:
        pass
    return ""

def read_text(pdf_path: str, max_pages: int = 20) -> str:
    out: List[str] = []
    try:
        import pdfplumber, os
        with pdfplumber.open(pdf_path) as pdf:
            N = min(max_pages, len(pdf.pages)) if max_pages else len(pdf.pages)
            N = max(1, N)
            for i in range(N):
                try:
                    out.append(pdf.pages[i].extract_text() or "")
                except Exception:
                    out.append("")
                _notify_progress(int((i+1)*100/N), os.path.basename(pdf_path))
    except Exception:
        pass
    return "\n".join(out)

# ------------------------
# Helpers
# ------------------------
SN_BLOCK = re.compile(r'SN\d{4}(?:/\d{2})*')

def _expand_sn_block(block: str) -> List[str]:
    token = block.replace(' ', '')
    m = re.match(r'SN(\d{4})(.*)$', token)
    if not m:
        return []
    base = int(m.group(1))
    tail = m.group(2) or ''
    codes = {f"SN{base:04d}"}

    range_match = re.search(r'~\s*(\d{4})', tail)
    if range_match:
        end = int(range_match.group(1))
        lo, hi = sorted((base, end))
        for val in range(lo, hi + 1):
            codes.add(f"SN{val:04d}")

    for part in re.findall(r'/\s*(\d{2,4})', tail):
        if len(part) == 4:
            codes.add(f"SN{int(part):04d}")
        else:
            prefix = str(base)[:4-len(part)]
            codes.add(f"SN{int(prefix + part):04d}")

    return sorted(codes)

def guess_class_from_nameplate_other(text: str, hull_no: str) -> Optional[str]:
    cls = None
    mapping: Dict[str, str] = {}
    for raw in (ln.strip() for ln in (text or "").splitlines() if ln.strip()):
        if re.search(r'\bABS\b', raw): cls = 'ABS'; continue
        if re.search(r'\bNK\b',  raw): cls = 'NK';  continue
        if re.search(r'\bLR\b',  raw): cls = 'LR';  continue
        if cls:
            for blk in SN_BLOCK.findall(raw.replace(' ', '')):
                for sn in _expand_sn_block(blk):
                    if sn not in mapping:
                        mapping[sn] = cls
    return mapping.get(hull_no) if hull_no else None

def extract_ip_grade(msbd_text: str, gsp_text: str) -> Tuple[Optional[str], Optional[str]]:
    enc_pat = re.compile(r'Enclosure\s*IP[-\s]?(\d{2})', re.I)
    ip_pat  = re.compile(r'\bIP[-\s]?(\d{2})\b', re.I)
    def pick(text: str) -> Optional[str]:
        if not text: return None
        m = enc_pat.search(text)
        if m: 
            return f"IP{m.group(1)}"
        cands = sorted({int(x) for x in ip_pat.findall(text)}, reverse=True)
        return f"IP{cands[0]}" if cands else None
    return pick(msbd_text), pick(gsp_text)

def extract_tr_capacity(msbd_text: str) -> Optional[str]:
    kva_pat = re.compile(r'(\d{3,5})\s*kVA', re.I)
    near_pat = re.compile(r'(MAIN\s+TRANSFORMER|TR\s*CAPACITY|NAME\s*PLATE|INCOMING\s*PANEL)', re.I)
    best_val = None
    for m in kva_pat.finditer(msbd_text or ''):
        val = int(m.group(1))
        win = msbd_text[max(0, m.start()-150): m.end()+150]
        score = 0
        if near_pat.search(win): score += 10
        if 100 <= val <= 50000: score += min(val/1000.0, 10)
        if (best_val or -1) < val and score >= 10:
            best_val = val
    if not best_val:
        nums = [int(x) for x in kva_pat.findall(msbd_text or '')]
        best_val = max(nums) if nums else None
    return f"{best_val} kVA" if best_val else None

def find_hull_in_bottom_right(pdf_path: str) -> Optional[str]:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages: 
                return None
            p0 = pdf.pages[0]
            w, h = p0.width, p0.height
            crop = (w*0.55, h*0.65, w*0.99, h*0.99)
            sub = p0.within_bbox(crop)
            txt = sub.extract_text() or ""
            m = re.search(r'\bSN\s*(\d{4})\b', txt, flags=re.IGNORECASE)
            if m:
                return "SN" + m.group(1)
    except Exception:
        pass
    return None

MUNSELL_RE = re.compile(r'\b\d{1,2}\s*(?:N|R|YR|Y|GY|G|BG|B|PB|P|RP)\s*\d(?:\.\d)?/\d(?:\.\d)?\b', re.IGNORECASE)

def clean_num(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip())

PANEL_SLOT_SPECS = [
    {
        "slot": "no1",
        "title": "No.1 INCOMING PANEL",
        "aliases": ["NO1INCOMING", "NO1INCOMINGPANEL", "NO1MAININCOMING"],
    },
    {
        "slot": "no2",
        "title": "No.2 INCOMING PANEL",
        "aliases": ["NO2INCOMING", "NO2INCOMINGPANEL", "NO2MAININCOMING"],
    },
    {
        "slot": "bus",
        "title": "BUS-TIE",
        "aliases": ["BUSTIE", "BUSTIEPANEL", "BUSTIESWBD", "BUSTIESWITCHBOARD"],
    },
    {
        "slot": "emg",
        "title": "EMERGENCY PANEL",
        "aliases": [
            "EMERGENCYPANEL",
            "EMERCYSWITCHBOARD",
            "LINKTOEMCYSWITCHBOARD",
            "LINKTOEMERGENCYSWITCHBOARD",
        ],
    },
]

PANEL_ROW_MARKERS = {
    "acb_type": [r"ACB\s*(TYPE|MODEL)", r"AIR\s+CIRCUIT\s+BREAKER"],
    "ocr_type": [r"OVERCURRENT\s+TRIP\s+TYPE", r"OCR\s*TYPE", r"TRIP\s*UNIT"],
    "ampere_frame": [r"AMPERE\s*FRAME", r"\bAF\b", r"\bMCR\b"],
    "rated_current_in": [r"RATED\s+CURRENT", r"\bI[NO]\b", r"IN\s*\(A\)"],
    "ir_percent": [r"IR\s*\(%\)", r"IR\s*%", r"IR\s*SETTING"],
    "ir_amps": [r"IR\s*\(A\)", r"IR\s*AMP"],
}

def find_rev_in_cover(p0: str) -> Optional[str]:
    pats = [
        r'\bREV\.?\s*NO\.?[\s:\-]*([A-Z0-9]+)',
        r'\bREV\.?[\s:\-]*([A-Z0-9]+)',
    ]
    for pat in pats:
        m = re.search(pat, p0, flags=re.IGNORECASE)
        if m:
            tok = re.sub(r'[^A-Z0-9]', '', m.group(1).upper())
            if tok:
                return tok
    return None

def find_rev_in_filename(path: str) -> Optional[str]:
    m = re.search(r'(^|[+_\-])REV[._\-]?([A-Z0-9]+)', os.path.basename(path), flags=re.IGNORECASE)
    if m:
        tok = re.sub(r'[^A-Z0-9]', '', m.group(2).upper())
        if tok:
            return tok
    return None

def parse_class_table(p0: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    lines = [ln.strip() for ln in (p0 or "").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if "SN" not in ln.upper():
            continue
        cls = None
        for j in (i, i+1 if i+1 < len(lines) else i):
            m = re.search(r'\b(ABS|NK|LR|KR|DNV|BV|LRS|RINA)\b', lines[j], flags=re.IGNORECASE)
            if m:
                cls = m.group(1).upper()
                break
        if not cls:
            continue
        m = re.search(r'SN\s*(\d{4})(.*)$', ln, flags=re.IGNORECASE)
        if not m:
            continue
        base = int(m.group(1)); tail = m.group(2)
        nums = {base}
        mrg = re.search(r'~\s*(\d{4})', tail)
        if mrg:
            end = int(mrg.group(1))
            lo, hi = sorted((base, end))
            for n in range(lo, hi+1):
                nums.add(n)
        for tok in re.findall(r'/\s*(\d{2,4})', tail):
            n = int(tok) if len(tok)==4 else int(str(base)[:2]+tok)
            nums.add(n)
        for n in sorted(nums):
            result.setdefault(f"SN{n}", cls)
    return result

def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0

def _find_acb_setting_page(pdf) -> Tuple[Optional[int], Optional["pdfplumber.page.Page"]]:
    """
    ACB SETTING TABLE 페이지 찾기 (Contents 페이지 제외)
    """
    for idx, page in enumerate(pdf.pages):
        text_u = (page.extract_text() or "").upper()
        
        # Contents 페이지는 건너뛰기
        if "TABLE OF CONTENTS" in text_u or "CONTENTS" in text_u:
            continue
        
        # ACB 키워드 필수
        if "ACB" not in text_u:
            continue
        
        # 실제 테이블의 특징적인 키워드들
        has_air_circuit_breaker = "AIR CIRCUIT BREAKER" in text_u
        has_ampere_frame = "AMPERE FRAME" in text_u or "AMPERE" in text_u
        has_rated_current = "RATED CURRENT" in text_u
        
        # 조건1: AIR CIRCUIT BREAKER + AMPERE FRAME (실제 테이블 페이지의 특징)
        if has_air_circuit_breaker and has_ampere_frame:
            print(f"[INFO] ACB SETTING TABLE 페이지 발견: Page {idx + 1}")
            return idx, page
        
        # 조건2: ACB + SETTING + 주요 테이블 키워드
        if "SETTING" in text_u and has_ampere_frame and has_rated_current:
            print(f"[INFO] ACB SETTING TABLE 페이지 발견: Page {idx + 1}")
            return idx, page
    
    print("[WARN] ACB SETTING TABLE 페이지를 찾을 수 없습니다.")
    return None, None

def _slot_ranges_from_words(words: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    hits: Dict[str, List[float]] = defaultdict(list)
    for w in words:
        text = (w.get("text") or "").strip()
        if not text:
            continue
        norm = re.sub(r'[^A-Z0-9]', '', text.upper())
        if not norm:
            continue
        cx = (w.get("x0", 0.0) + w.get("x1", 0.0)) / 2.0
        for spec in PANEL_SLOT_SPECS:
            for alias in spec["aliases"]:
                if alias and alias in norm:
                    hits[spec["slot"]].append(cx)
                    break
    centers: List[Tuple[float, str]] = []
    for slot, values in hits.items():
        med = _median(values)
        if med is not None:
            centers.append((med, slot))
    centers.sort()
    ranges: Dict[str, Tuple[float, float]] = {}
    for idx, (cx, slot) in enumerate(centers):
        left = (centers[idx - 1][0] + cx) / 2.0 if idx > 0 else cx - 150.0
        right = (cx + centers[idx + 1][0]) / 2.0 if idx + 1 < len(centers) else cx + 150.0
        ranges[slot] = (left, right)
    return ranges

def _row_positions_from_words(words: List[Dict[str, Any]]) -> Dict[str, float]:
    positions: Dict[str, float] = {}
    for field, patterns in PANEL_ROW_MARKERS.items():
        hits: List[float] = []
        for w in words:
            text = (w.get("text") or "").upper()
            for pat in patterns:
                if re.search(pat, text):
                    hits.append((w.get("top", 0.0) + w.get("bottom", 0.0)) / 2.0)
                    break
        med = _median(hits)
        if med is not None:
            positions[field] = med
    return positions

def _words_in_band(
    words: List[Dict[str, Any]], x0: float, x1: float, center_y: Optional[float], band: float = 18.0
) -> List[Dict[str, Any]]:
    if center_y is None:
        return []
    result: List[Dict[str, Any]] = []
    for w in words:
        cx = (w.get("x0", 0.0) + w.get("x1", 0.0)) / 2.0
        if not (x0 <= cx <= x1):
            continue
        cy = (w.get("top", 0.0) + w.get("bottom", 0.0)) / 2.0
        if abs(cy - center_y) <= band:
            result.append(w)
    return result

def _numbers_from_words(words: List[Dict[str, Any]]) -> List[int]:
    numbers: List[int] = []
    for w in words:
        text = str(w.get("text", ""))
        for token in re.findall(r'\d+', text):
            try:
                numbers.append(int(token))
            except Exception:
                continue
    return numbers

def _blank_panel_records() -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    for spec in PANEL_SLOT_SPECS:
        records.append(
            {
                "slot": spec["slot"],
                "panel": spec["title"],
                "acb_type": "",
                "ocr_type": "",
                "ampere_frame": "",
                "rated_current_in": "",
                "ir_percent": "",
                "ir_amps": "",
            }
        )
    return records

def _find_filled_checkboxes(page) -> List[Dict[str, float]]:
    """
    페이지에서 채워진 체크박스(검은색 네모) 찾기
    """
    checkboxes = []
    rects = page.rects or []
    
    for rect in rects:
        width = rect.get("x1", 0) - rect.get("x0", 0)
        height = rect.get("y1", 0) - rect.get("y0", 0)
        
        # 3~20px 크기의 사각형
        if not (3 <= width <= 20 and 3 <= height <= 20):
            continue
        
        # 검은색 체크 (fill color가 어두운지 확인)
        fill = rect.get("non_stroking_color")
        is_filled = False
        
        if fill is not None:
            if isinstance(fill, (tuple, list)):
                # RGB/CMYK: 평균이 0.25 이하면 검은색
                is_filled = sum(fill) / len(fill) < 0.25
            elif isinstance(fill, (int, float)):
                # Grayscale: 0.25 이하면 검은색
                is_filled = fill < 0.25
        
        if is_filled:
            cx = (rect["x0"] + rect["x1"]) / 2.0
            cy = (rect["top"] + rect["bottom"]) / 2.0
            checkboxes.append({"x": cx, "y": cy})
    
    coords_preview = [f"({c['x']:.1f}, {c['y']:.1f})" for c in checkboxes[:5]]
    print(f"  체크박스 좌표: {coords_preview}")
    return checkboxes

def _determine_panel_columns(page, checkboxes: List[Dict[str, float]]) -> Dict[str, Tuple[float, float]]:
    """
    PANEL 헤더 텍스트와 체크박스 위치로 각 PANEL의 X축 범위 결정 (개선 버전)
    """
    words = page.extract_words() or []
    text = page.extract_text() or ""
    panel_positions = {}
    
    print("[DEBUG] PANEL 텍스트 검색 중...")
    
    # 방법1: 기존 aliases로 찾기
    for spec in PANEL_SLOT_SPECS:
        for word in words:
            text_word = (word.get("text") or "").strip().upper()
            text_norm = re.sub(r'[^A-Z0-9]', '', text_word)
            
            for alias in spec["aliases"]:
                if alias in text_norm:
                    cx = (word["x0"] + word["x1"]) / 2.0
                    if spec["slot"] not in panel_positions:
                        panel_positions[spec["slot"]] = cx
                        print(f"  ✓ {spec['slot']} 발견 (alias): {text_word} at X={cx:.1f}")
                    break
            if spec["slot"] in panel_positions:
                break
    
    # 방법2: 특정 패턴으로 찾기 (EMERGENCY 패턴 강화)
    patterns = {
        "no1": [
            r'NO\.?\s*1.*INCOMING',
            r'P11-007-01A-PN',
            r'NO\.?1&2.*INCOMING',
            r'NO\.?\s*1\s*INCOMING\s*PANEL'
        ],
        "no2": [
            r'NO\.?\s*2.*INCOMING',
            r'P12-007-01A-PN',
            r'NO\.?\s*2\s*INCOMING\s*PANEL'
        ],
        "bus": [
            r'BUS[\s\-]*TIE',
            r'BUS\s*TIE\s*PANEL',
            r'BUSTIE'
        ],
        "emg": [
            r'LINK.*EMC?Y',
            r'EMERGENCY.*PANEL',
            r'P31-003-11-PN',
            r'LINK\s*TO\s*EMC?Y',
            r'EMC?Y\s*SWITCHBOARD',
            r'LINK\s*TO\s*EMERGENCY',
            r'LINK.*SWITCHBOARD'
        ]
    }
    
    for slot, pats in patterns.items():
        if slot in panel_positions:
            continue
        
        for pattern in pats:
            matches = re.finditer(pattern, text.upper())
            for match in matches:
                # 매칭된 텍스트의 위치 찾기
                matched_text = match.group(0)
                for word in words:
                    if matched_text in (word.get("text") or "").upper():
                        cx = (word["x0"] + word["x1"]) / 2.0
                        panel_positions[slot] = cx
                        print(f"  ✓ {slot} 발견 (pattern): {matched_text} at X={cx:.1f}")
                        break
                if slot in panel_positions:
                    break
            if slot in panel_positions:
                break
    
    # 방법3: 체크박스 X 좌표 클러스터링으로 추정
    if len(panel_positions) < 3:
        print("[DEBUG] PANEL 텍스트 부족, 체크박스 클러스터링 시도...")
        
        # 체크박스 X 좌표 수집
        x_coords = [cb["x"] for cb in checkboxes]
        if x_coords:
            x_coords_sorted = sorted(set(x_coords))
            
            # X 좌표를 그룹으로 묶기 (50px 이내는 같은 그룹)
            clusters = []
            current_cluster = [x_coords_sorted[0]]
            
            for x in x_coords_sorted[1:]:
                if x - current_cluster[-1] < 50:
                    current_cluster.append(x)
                else:
                    clusters.append(sum(current_cluster) / len(current_cluster))
                    current_cluster = [x]
            if current_cluster:
                clusters.append(sum(current_cluster) / len(current_cluster))
            
            print(f"  체크박스 클러스터: {len(clusters)}개 발견")
            
            # 클러스터를 PANEL에 매핑
            slot_names = ["no1", "no2", "bus", "emg"]
            for i, cluster_x in enumerate(clusters[:4]):
                if i < len(slot_names):
                    slot = slot_names[i]
                    if slot not in panel_positions:
                        panel_positions[slot] = cluster_x
                        print(f"  ✓ {slot} 추정 (cluster): X={cluster_x:.1f}")
    
    # X축 범위 계산
    if not panel_positions:
        print("[ERROR] PANEL 위치를 전혀 찾을 수 없습니다!")
        return {}

    sorted_panels = sorted(panel_positions.items(), key=lambda x: x[1])

    # BUS-TIE가 누락된 경우, No.1/No.2 사이 중간 위치로 보간
    slot_to_center = {slot: cx for slot, cx in sorted_panels}
    if "bus" not in slot_to_center:
        c1, c2 = slot_to_center.get("no1"), slot_to_center.get("no2")
        if c1 and c2:
            cx = (c1 + c2) / 2.0
            span = abs(c2 - c1) / 3.0 if abs(c2 - c1) > 0 else 120.0
            panel_positions["bus"] = cx
            sorted_panels.append(("bus", cx))
            sorted_panels = sorted(sorted_panels, key=lambda x: x[1])
            print(f"  ✓ bus 보간: X={cx:.1f} (span≈{span:.1f})")
        elif len(sorted_panels) >= 2:
            # 전체 테이블 폭을 균등 분할하여 BUS-TIE 대략 위치 지정
            xs = [cx for _, cx in sorted_panels]
            span = max(xs) - min(xs)
            if span > 0:
                cx = min(xs) + span / 2.0
                panel_positions["bus"] = cx
                sorted_panels.append(("bus", cx))
                sorted_panels = sorted(sorted_panels, key=lambda x: x[1])
                print(f"  ✓ bus 균등 분할 추정: X={cx:.1f}")

    panel_columns = {}
    
    for idx, (slot, center_x) in enumerate(sorted_panels):
        if idx > 0:
            prev_x = sorted_panels[idx - 1][1]
            x_min = (prev_x + center_x) / 2.0
        else:
            x_min = center_x - 100.0
        
        if idx < len(sorted_panels) - 1:
            next_x = sorted_panels[idx + 1][1]
            x_max = (center_x + next_x) / 2.0
        else:
            x_max = center_x + 100.0
        
        panel_columns[slot] = (x_min, x_max)
    
    return panel_columns

def _extract_acb_type(page, x_min: float, x_max: float, checkboxes: List[Dict[str, float]]) -> str:
    """
    ACB TYPE 추출 (HGN 63, HGN 10 등) - HGN 시리즈 전용
    OCR Type(GPR-SA)과 명확히 구분하여 추출
    AIR CIRCUIT BREAKER 섹션에서만 HGN 시리즈 찾기
    """
    words = page.extract_words() or []
    text = page.extract_text() or ""
    text_upper = text.upper()
    
    # AIR CIRCUIT BREAKER 섹션 찾기 (ACB TYPE의 핵심 위치)
    if "AIR CIRCUIT BREAKER" not in text_upper and "ACB TYPE" not in text_upper:
        # 이름plate가 불분명할 때는 행 마커 기반 탐색으로 바로 이동
        acb_section_y = None
    else:
        # AIR CIRCUIT BREAKER 키워드의 Y 좌표 찾기
        acb_section_y = None
        for word in words:
            word_text = (word.get("text") or "").strip().upper()
            # "AIR CIRCUIT BREAKER" 또는 "ACB TYPE" 찾기
            if ("AIR" in word_text and "CIRCUIT" in text_upper) or ("ACB" in word_text and "TYPE" in word_text):
                acb_section_y = (word["top"] + word["bottom"]) / 2.0
                break

    row_markers = _row_positions_from_words(words)
    if not acb_section_y:
        acb_section_y = row_markers.get("acb_type")
    
    # HGN 시리즈만 찾기 (GPR-SA는 OCR Type이므로 제외!)
    hgn_pattern = re.compile(r'\bHGN\s*(\d{2})\b', re.I)
    
    hgn_candidates = []
    for word in words:
        wy = (word["top"] + word["bottom"]) / 2.0
        wx = (word["x0"] + word["x1"]) / 2.0
        
        # AIR CIRCUIT BREAKER 섹션 아래 150px 이내만 확인
        if not (0 < (wy - acb_section_y) < 150):
            continue
        
        # 해당 PANEL 영역 내 (여유있게 확인)
        if not (x_min - 30 <= wx <= x_max + 30):
            continue
        
        word_text = (word.get("text") or "").strip()
        match = hgn_pattern.search(word_text)
        
        if match:
            hgn_type = f"HGN {match.group(1)}"
            hgn_candidates.append({
                'text': hgn_type,
                'x': wx,
                'y': wy
            })
    
    if hgn_candidates:
        print(f"    [DEBUG] HGN 후보: {[c['text'] for c in hgn_candidates]}")

        # 체크박스가 있으면 체크박스와 가장 가까운 HGN 선택
        if checkboxes:
            # ACB TYPE 행 근처의 체크박스 찾기 (범위 확대)
            type_checkboxes = [
                cb for cb in checkboxes
                if abs(cb['y'] - (acb_section_y or cb['y'])) < 100
                and x_min - 30 <= cb['x'] <= x_max + 30
            ]

            print(f"    [DEBUG] 체크박스: {len(type_checkboxes)}개")

            if type_checkboxes:
                best_match = None
                min_dist = float('inf')

                for cb in type_checkboxes:
                    for candidate in hgn_candidates:
                        dist_x = abs(candidate['x'] - cb['x'])
                        dist_y = abs(candidate['y'] - cb['y'])
                        dist = (dist_x ** 2 + dist_y ** 2) ** 0.5

                        # X축 거리가 80px 이내이고 전체 거리가 가장 가까운 것 선택
                        if dist < min_dist and dist_x < 80:
                            min_dist = dist
                            best_match = candidate['text']

                if best_match:
                    print(f"    [DEBUG] 체크박스 기반 선택: {best_match}")
                    return best_match

        # 체크박스가 없거나 매칭 실패 시 PANEL 중심과 가장 가까운 HGN 후보 반환
        best = min(hgn_candidates, key=lambda c: abs(c['x'] - (x_min + x_max) / 2.0))
        print(f"    [DEBUG] 기본값 선택: {best['text']}")
        return best['text']

    # 일반 텍스트 기반 추출 (ACB TYPE 행 근처의 가장 긴 단어 선택)
    band_y = acb_section_y if acb_section_y else row_markers.get("acb_type")
    candidate_words = _words_in_band(words, x_min - 10, x_max + 10, band_y, band=35.0)
    cleaned: List[str] = []
    for w in candidate_words:
        t = (w.get("text") or "").strip()
        t_norm = re.sub(r'[^A-Z0-9\- ]', '', t.upper()).strip()
        if not t_norm:
            continue
        if any(bad in t_norm for bad in ["OCR", "TRIP", "LTD", "IR", "AF", "AMPERE", "RATED", "CURRENT", "TYPE"]):
            continue
        if 2 <= len(t_norm) <= 12:
            cleaned.append(t_norm)

    if cleaned:
        best = max(cleaned, key=len)
        print(f"    [DEBUG] HGN 미검출 - 일반 텍스트 사용: {best}")
        return best

    print(f"    [DEBUG] ACB TYPE 후보를 찾을 수 없음 (PANEL X: {x_min:.1f}~{x_max:.1f})")
    return ""

def _extract_ocr_type(page) -> str:
    """
    OCR TYPE 추출 (GPR-SA 등) - 범용성 개선
    LONG TIME DELAY TRIP 섹션 또는 TYPE 행에서 찾기
    """
    words = page.extract_words() or []
    text = page.extract_text() or ""
    text_upper = text.upper()
    
    # 우선순위 1: LONG TIME DELAY TRIP 섹션의 TYPE
    if "LONG TIME" in text_upper and "DELAY" in text_upper:
        # LTD 섹션 시작 Y 좌표 찾기
        ltd_y = None
        for word in words:
            word_text = (word.get("text") or "").strip().upper()
            if "LONG" in word_text or ("DELAY" in word_text and "TRIP" in text_upper):
                ltd_y = (word["top"] + word["bottom"]) / 2.0
                break
        
        if ltd_y:
            # LTD 섹션 내의 TYPE 찾기
            for word in words:
                wy = (word["top"] + word["bottom"]) / 2.0
                
                # LTD 섹션 이후 200px 이내
                if not (0 < (wy - ltd_y) < 200):
                    continue
                
                word_text = (word.get("text") or "").strip().upper()
                if word_text == "TYPE":
                    # TYPE 근처에서 GPR-SA 등 찾기
                    type_y = wy
                    
                    for w2 in words:
                        w2y = (w2["top"] + w2["bottom"]) / 2.0
                        
                        if abs(w2y - type_y) > 30:
                            continue
                        
                        text2 = (w2.get("text") or "").strip().upper()
                        
                        # OCR 타입 패턴
                        if re.match(r'GPR-[A-Z]{1,2}', text2):
                            return text2
                        if re.match(r'[A-Z]{2,4}-[A-Z0-9]{1,3}', text2):
                            return text2
    
    # 우선순위 2: 페이지 전체에서 OCR 타입 패턴 찾기
    ocr_patterns = [
        re.compile(r'GPR-[A-Z]{1,2}', re.I),
        re.compile(r'SOLID\s+STATE', re.I),
    ]
    
    for pattern in ocr_patterns:
        for word in words:
            text = (word.get("text") or "").strip().upper()
            if pattern.search(text):
                return text
    
    # 우선순위 3: 여러 단어 조합 (예: "SOLID STATE TYPE")
    text_lines = text.split('\n')
    for line in text_lines:
        if "TRIP" in line.upper() and "TYPE" in line.upper():
            # R (UPR), SOLID STATE 등 추출
            match = re.search(r'([A-Z]{2,10}(?:\s+[A-Z]{2,10})?)\s*TYPE', line.upper())
            if match:
                ocr_type = match.group(1).strip()
                if len(ocr_type) > 2:  # 의미있는 길이
                    return ocr_type
    
    return ""

def _extract_checked_value(
    page, 
    x_min: float, 
    x_max: float, 
    checkboxes: List[Dict[str, float]], 
    row_keyword1: str,
    row_keyword2: str = "",
    value_type: str = "integer"
) -> str:
    """
    특정 행에서 체크박스가 있는 값 추출 (개선 버전)
    """
    words = page.extract_words() or []
    text_upper = (page.extract_text() or "").upper()
    
    # 행 키워드 찾기
    if row_keyword1 not in text_upper:
        return ""
    
    # 행의 Y 좌표 찾기 (더 유연하게)
    row_y = None
    for word in words:
        text = (word.get("text") or "").strip().upper()
        if row_keyword1 in text or (row_keyword2 and row_keyword2 in text):
            row_y = (word["top"] + word["bottom"]) / 2.0
            break
    
    if row_y is None:
        return ""
    
    # 해당 행에서 체크박스 찾기 (범위 확대: 30 → 50)
    row_checkboxes = [cb for cb in checkboxes if abs(cb["y"] - row_y) < 50]
    
    # 해당 PANEL 영역의 체크박스만 필터링
    panel_checkboxes = [cb for cb in row_checkboxes if x_min <= cb["x"] <= x_max]
    
    if not panel_checkboxes:
        return ""
    
    # 모든 체크박스 근처의 값 수집 (첫 번째만이 아닌 전부)
    candidates = []
    for cb in panel_checkboxes:
        for word in words:
            wx = (word["x0"] + word["x1"]) / 2.0
            wy = (word["top"] + word["bottom"]) / 2.0
            
            # 체크박스와 같은 행인지 확인 (범위 확대: 15 → 25)
            if abs(wy - cb["y"]) > 25:
                continue
            
            # X축이 가까운지 확인 (범위 확대: 50 → 80)
            if abs(wx - cb["x"]) > 80:
                continue
            
            text = (word.get("text") or "").strip()
            
            # 값 형식 검증
            if value_type == "integer":
                # 숫자만 (800A, 5000A, 5000 등)
                if re.match(r'^\d+A?$', text):
                    num_value = re.sub(r'A$', '', text)
                    candidates.append(int(num_value))
            elif value_type == "decimal":
                # 소수 (0.7, 1.0, 1 등)
                if re.match(r'^\d+\.?\d*$', text):
                    candidates.append(float(text))
    
    # 가장 큰 값 반환 (일반적으로 올바른 값이 더 큼)
    if candidates:
        if value_type == "integer":
            return str(max(candidates))
        elif value_type == "decimal":
            return str(max(candidates))
    
    return ""

def _extract_ampere_frame(page, x_min: float, x_max: float, checkboxes: List[Dict[str, float]]) -> str:
    """
    AMPERE FRAME 값 추출 (800, 1000, 6300 등) - 범용성 및 정확도 개선
    PANEL 영역 내의 값만 추출, 체크박스 우선
    """
    words = page.extract_words() or []
    text_upper = (page.extract_text() or "").upper()
    
    # AMPERE FRAME 행 찾기
    if "AMPERE" not in text_upper or "FRAME" not in text_upper:
        return ""
    
    # AMPERE FRAME 키워드의 Y 좌표 찾기
    frame_y = None
    for word in words:
        text = (word.get("text") or "").strip().upper()
        if "AMPERE" in text or "FRAME" in text:
            frame_y = (word["top"] + word["bottom"]) / 2.0
            break
    
    if not frame_y:
        return ""
    
    # 프레임 값 후보들 수집 (AMPERE FRAME 행 아래, PANEL 영역 내)
    frame_values = []
    for word in words:
        wy = (word["top"] + word["bottom"]) / 2.0
        wx = (word["x0"] + word["x1"]) / 2.0
        
        # AMPERE FRAME 행 아래 200px 이내
        if not (0 < (wy - frame_y) < 200):
            continue
        
        # PANEL 영역 내 (여유 있게)
        if not (x_min - 50 <= wx <= x_max + 50):
            continue
        
        text = (word.get("text") or "").strip()
        
        # 숫자+A 패턴 (더 넓은 범위)
        match = re.match(r'^(\d{3,5})A?$', text)
        if match:
            num = int(match.group(1))
            # 600 ~ 10000까지 허용 (1000A도 포함)
            if 600 <= num <= 10000:
                frame_values.append({
                    'value': num,
                    'x': wx,
                    'y': wy
                })
    
    if not frame_values:
        print(f"    [DEBUG] AMPERE FRAME 후보 없음 (PANEL X: {x_min:.1f}~{x_max:.1f})")
        return ""
    
    print(f"    [DEBUG] AMPERE FRAME 후보: {[fv['value'] for fv in frame_values]}")
    
    # 체크박스가 있는 값 찾기 (우선순위 1)
    if checkboxes:
        checked_values = []
        
        for fv in frame_values:
            nearby_checkboxes = [
                cb for cb in checkboxes
                if abs(cb['y'] - fv['y']) < 40  # 같은 행 (범위 확대)
                and abs(cb['x'] - fv['x']) < 100  # X축 거리
                and x_min - 50 <= cb['x'] <= x_max + 50  # PANEL 영역
            ]
            
            if nearby_checkboxes:
                checked_values.append(fv['value'])
        
        if checked_values:
            result = str(max(checked_values))
            print(f"    [DEBUG] 체크박스 기반 선택: {result}")
            return result
    
    # 체크박스 없으면 PANEL 영역의 가장 적절한 값 (우선순위 2)
    panel_values = [fv['value'] for fv in frame_values if x_min - 30 <= fv['x'] <= x_max + 30]
    
    if panel_values:
        # 여러 후보 중 중간값 선택 (노이즈 제거)
        panel_values_sorted = sorted(panel_values)
        result = str(panel_values_sorted[len(panel_values_sorted) // 2])
        print(f"    [DEBUG] PANEL 영역 기반 선택: {result}")
        return result
    
    print(f"    [DEBUG] AMPERE FRAME 추출 실패")
    return ""

def _extract_rated_current(page, x_min: float, x_max: float) -> str:
    """
    RATED CURRENT(Io) 값 추출 (5774A, 1000A 등) - 범용성 및 정확도 개선
    PANEL 영역 내의 값만 추출
    """
    words = page.extract_words() or []
    text_upper = (page.extract_text() or "").upper()
    
    # RATED CURRENT 행 찾기 (여러 표현)
    rated_keywords = ["RATED CURRENT", "RATED", "CURRENT(IO)", "CURRENT (IO)", "IN(A)", "CURRENT"]
    
    rated_y = None
    for keyword in rated_keywords:
        if keyword in text_upper:
            for word in words:
                text = (word.get("text") or "").strip().upper()
                if keyword in text or any(k in text for k in keyword.split()):
                    rated_y = (word["top"] + word["bottom"]) / 2.0
                    break
            if rated_y:
                break
    
    if not rated_y:
        return ""
    
    # 해당 행 및 아래 행에서 PANEL 영역의 값 찾기
    candidates = []
    for word in words:
        wx = (word["x0"] + word["x1"]) / 2.0
        wy = (word["top"] + word["bottom"]) / 2.0
        
        # 같은 행 또는 바로 아래 100px 이내 (범위 확대)
        if not (0 <= (wy - rated_y) <= 100):
            continue
        
        # PANEL 영역 확인 (여유 있게)
        if not (x_min - 50 <= wx <= x_max + 50):
            continue
        
        text = (word.get("text") or "").strip()
        
        # 숫자+A 패턴
        match = re.match(r'^(\d{3,5})A?$', text)
        if match:
            num = int(match.group(1))
            # Rated Current 범위: 100~10000 (1000A도 포함)
            if 100 <= num <= 10000:
                candidates.append({
                    'value': num,
                    'x': wx,
                    'y': wy
                })
    
    if not candidates:
        print(f"    [DEBUG] RATED CURRENT 후보 없음 (PANEL X: {x_min:.1f}~{x_max:.1f})")
        return ""
    
    print(f"    [DEBUG] RATED CURRENT 후보: {[c['value'] for c in candidates]}")
    
    # PANEL 중심 영역에 가장 가까운 값 선택
    panel_center = (x_min + x_max) / 2.0
    best_value = None
    min_dist = float('inf')
    
    for candidate in candidates:
        # PANEL 영역 내에 있는지 확인 (타이트하게)
        if x_min - 30 <= candidate['x'] <= x_max + 30:
            dist = abs(candidate['x'] - panel_center)
            if dist < min_dist:
                min_dist = dist
                best_value = candidate['value']
    
    if best_value:
        print(f"    [DEBUG] PANEL 중심 기반 선택: {best_value}")
        return str(best_value)
    
    # 후보가 없으면 가장 큰 값 (fallback)
    values = [c['value'] for c in candidates]
    if values:
        result = str(max(values))
        print(f"    [DEBUG] Fallback 선택 (최대값): {result}")
        return result
    
    print(f"    [DEBUG] RATED CURRENT 추출 실패")
    return ""

def extract_acb_setting_panels(msbd_pdf: str) -> List[Dict[str, str]]:
    """ACB SETTING TABLE에서 체크박스 기반으로 PANEL 정보 추출 - 범용성 개선"""
    base_records = _blank_panel_records()
    if not (msbd_pdf and os.path.exists(msbd_pdf)):
        return base_records
    
    try:
        with pdfplumber.open(msbd_pdf) as pdf:
            _, page = _find_acb_setting_page(pdf)
            if page is None:
                print("[WARN] ACB SETTING TABLE 페이지를 찾을 수 없습니다.")
                return base_records
            
            print(f"\n{'='*60}")
            print(f"ACB SETTING TABLE 파싱 시작")
            print(f"{'='*60}\n")
            
            # 1단계: 체크박스 위치 찾기
            checkboxes = _find_filled_checkboxes(page)
            print(f"[STEP 1] 체크박스 감지: {len(checkboxes)}개 발견")
            
            if not checkboxes:
                print("[WARN] 체크박스를 찾을 수 없습니다.")
            
            # 2단계: PANEL 컬럼 영역 결정
            panel_columns = _determine_panel_columns(page, checkboxes)
            print(f"[STEP 2] PANEL 컬럼 매핑: {len(panel_columns)}개")
            for slot, (x_min, x_max) in panel_columns.items():
                print(f"  • {slot:10s} → X: {x_min:.1f} ~ {x_max:.1f}")
            
            if not panel_columns:
                print("[ERROR] PANEL 위치를 찾을 수 없습니다. 기본값 반환.")
                return base_records
            
            # 3단계: 행별 정보 추출
            record_map = {rec["slot"]: rec for rec in base_records}
            
            # OCR TYPE 추출 (모든 PANEL 공통)
            ocr_type_value = _extract_ocr_type(page)
            print(f"\n[STEP 3] OCR TYPE 추출: {ocr_type_value or '(없음)'}")
            
            # 각 PANEL별로 추출
            for slot, (x_min, x_max) in panel_columns.items():
                record = record_map.get(slot)
                if not record:
                    continue
                
                print(f"\n[{slot}] 추출 중...")
                
                # ACB TYPE 추출 (HGN 시리즈 등)
                acb_type = _extract_acb_type(page, x_min, x_max, checkboxes)
                if acb_type:
                    record["acb_type"] = acb_type
                    print(f"  ACB Type: {acb_type}")
                else:
                    print(f"  ACB Type: (추출 실패)")
                
                # OCR TYPE (공통값)
                if ocr_type_value:
                    record["ocr_type"] = ocr_type_value
                    print(f"  OCR Type: {ocr_type_value}")
                else:
                    print(f"  OCR Type: (추출 실패)")
                
                # AMPERE FRAME 추출
                frame = _extract_ampere_frame(page, x_min, x_max, checkboxes)
                if frame:
                    record["ampere_frame"] = frame
                    print(f"  Ampere Frame: {frame}")
                else:
                    print(f"  Ampere Frame: (추출 실패)")
                
                # RATED CURRENT 추출
                rated = _extract_rated_current(page, x_min, x_max)
                if rated:
                    record["rated_current_in"] = rated
                    print(f"  Rated Current: {rated}")
                else:
                    print(f"  Rated Current: (추출 실패)")
                
                # IR (%) 추출 (LTD RANGE)
                ir_pct = _extract_ir_percent(page, x_min, x_max, checkboxes)
                if ir_pct:
                    record["ir_percent"] = ir_pct
                    print(f"  IR (%): {ir_pct}")
                else:
                    print(f"  IR (%): (추출 실패)")

                # IR (A) 계산
                def _safe_float(val: Any) -> Optional[float]:
                    if val is None:
                        return None
                    text = str(val)
                    m = re.search(r"\d+(?:\.\d+)?", text)
                    return float(m.group(0)) if m else None

                rated_val = _safe_float(record.get("rated_current_in"))
                ir_pct_val = _safe_float(record.get("ir_percent"))

                if rated_val and ir_pct_val:
                    try:
                        ir_amps = int(rated_val * ir_pct_val)
                        record["ir_amps"] = str(ir_amps)
                        print(f"  IR (A): {ir_amps}")
                    except Exception as e:
                        print(f"  IR (A): 계산 실패 ({e})")
            
            print(f"\n{'='*60}")
            print(f"ACB SETTING TABLE 파싱 완료")
            print(f"{'='*60}\n")
            
            return base_records
            
    except Exception as e:
        print(f"[ERROR] ACB SETTING TABLE 파싱 실패: {e}")
        import traceback
        traceback.print_exc()
        return base_records

def _extract_ir_percent(page, x_min: float, x_max: float, checkboxes: List[Dict[str, float]]) -> str:
    """
    IR (%) 추출 - LONG TIME DELAY TRIP (LTD) 섹션의 RANGE - 범용성 개선
    Ir = In x set. 또는 Ir = Io x set. 근처
    """
    words = page.extract_words() or []
    text_upper = (page.extract_text() or "").upper()
    
    # LONG TIME DELAY TRIP 섹션 찾기
    if "LONG TIME" not in text_upper:
        return ""
    
    # LTD 섹션 시작 Y 찾기
    ltd_y = None
    for word in words:
        text = (word.get("text") or "").strip().upper()
        if "LONG" in text or ("DELAY" in text and "TRIP" in text_upper):
            ltd_y = (word["top"] + word["bottom"]) / 2.0
            break
    
    if not ltd_y:
        return ""
    
    # "PICK UP CURRENT" 또는 "Ir" 찾기 (LTD 섹션 내)
    pickup_y = None
    for word in words:
        wy = (word["top"] + word["bottom"]) / 2.0
        
        # LTD 섹션 이후 200px 이내
        if not (0 < (wy - ltd_y) < 200):
            continue
        
        text = (word.get("text") or "").strip().upper()
        
        # "PICK UP", "Ir =", "Ir=" 등
        if "PICK" in text or "IR" in text or "UP" in text:
            pickup_y = wy
            break
    
    if not pickup_y:
        return ""
    
    # RANGE 키워드 찾기 (PICK UP 근처)
    range_y = None
    for word in words:
        wy = (word["top"] + word["bottom"]) / 2.0
        
        # PICK UP 이후 100px 이내
        if not (0 < (wy - pickup_y) < 100):
            continue
        
        text = (word.get("text") or "").strip().upper()
        if text == "RANGE":
            range_y = wy
            break
    
    if not range_y:
        # RANGE 키워드 없으면 PICK UP 바로 아래 체크박스 찾기
        range_y = pickup_y + 30
    
    # RANGE 행의 체크박스 찾기 (넓은 범위)
    range_checkboxes = [
        cb for cb in checkboxes 
        if abs(cb['y'] - range_y) < 50
        and x_min - 30 <= cb['x'] <= x_max + 30
    ]
    
    if not range_checkboxes:
        return ""
    
    # 체크박스 근처의 IR% 값 찾기
    for cb in range_checkboxes:
        for word in words:
            wx = (word["x0"] + word["x1"]) / 2.0
            wy = (word["top"] + word["bottom"]) / 2.0
            
            # 같은 행, 가까운 거리
            if abs(wy - cb['y']) > 30 or abs(wx - cb['x']) > 100:
                continue
            
            text = (word.get("text") or "").strip()
            
            # 소수값 패턴 (0.7, 0.8, 1.0, 1.15 등)
            if re.match(r'^[01]\.?\d{0,2}$', text):
                try:
                    val = float(text)
                    # IR% 범위: 0.5 ~ 1.5
                    if 0.5 <= val <= 1.5:
                        return str(val)
                except:
                    pass
    
    return ""

# ------------------------
# Cover Parser
# ------------------------
def parse_cover_info(pdf_path: str) -> Dict[str, object]:
    p0 = read_page_text(pdf_path, 0)
    P0U = p0.upper()
    data: Dict[str, object] = {"fields": {}, "hull_to_class": {}, "titles": []}
    fields: Dict[str, str] = {}

    if "SAMSUNG HEAVY INDUSTRIES" in P0U:
        fields["customer"] = "SAMSUNG HEAVY INDUSTRIES"
    hv = find_hull_in_bottom_right(pdf_path)
    if not hv:
        m = re.search(r'\bSN\s*(\d{4})\b', p0, flags=re.IGNORECASE) or re.search(r'\bSN\s*(\d{4})\b', os.path.basename(pdf_path), flags=re.IGNORECASE)
        hv = "SN"+m.group(1) if m else None
    if hv:
        fields["hull_no"] = hv

    if "GROUP STARTER PANEL" in P0U or "GSP" in P0U:
        data["titles"].append("GROUP STARTER PANEL")
    if "SWITCHBOARD" in P0U:
        data["titles"].append("AC440V LV SWITCHBOARD")
    if data["titles"]:
        fields["item"] = " & ".join(dict.fromkeys(data["titles"]))

    m = re.search(r'(?:DWG|DRAWING)\s*NO\.?[\s:\-]*([A-Z]{2,5}SE-\d{4,6})', p0, flags=re.IGNORECASE)
    if m:
        dwg = m.group(1).upper()
        name = os.path.basename(pdf_path).upper()
        if "GSP" in name:
            fields["gsp_dwg_no"] = dwg
        else:
            fields["ms_dwg_no"] = dwg
    else:
        T_all = read_text(pdf_path, max_pages=6)
        m2 = re.search(r'([A-Z]{2,5}SE-\d{4,6})', T_all)
        if m2:
            dwg = m2.group(1).upper()
            name = os.path.basename(pdf_path).upper()
            if "GSP" in name:
                fields.setdefault("gsp_dwg_no", dwg)
            else:
                fields.setdefault("ms_dwg_no", dwg)

    rev = find_rev_in_cover(p0) or find_rev_in_filename(pdf_path)
    if rev:
        bad = {'I','IE','IEW','IEWE','IEWED'}
        if rev.upper() in bad:
            rev = None
    if not rev:
        rev = find_rev_in_filename(pdf_path)
    if rev:
        name = os.path.basename(pdf_path).upper()
        if "GSP" in name:
            fields["gsp_rev_no"] = rev
        else:
            fields["ms_rev_no"] = rev

    m = re.search(r'\bOWNER\b\s*[:\-]?\s*([A-Z0-9 ]{2,})', p0, flags=re.IGNORECASE)
    if m:
        fields["owner"] = clean_num(m.group(1))
    else:
        fields.setdefault("owner", "[직접 입력]")
    if "CONTAINER VESSEL" in P0U:
        fields["Kind_of_Vessel"] = "16,500TEU CONTAINER VESSEL"

    data["hull_to_class"] = parse_class_table(p0)
    data["fields"] = fields
    return data

# ------------------------
# General Spec Parser
# ------------------------
def parse_general_spec(pdf_path: str) -> Dict[str, str]:
    ip_checked = detect_checked_ip(pdf_path) if 'detect_checked_ip' in globals() else ''
    T = read_text(pdf_path, max_pages=20)
    U = T.upper()
    out: Dict[str, str] = {}

    msbd_text = T
    gsp_text = T

    m = re.search(r'SHORT\s*CIRCUIT\s*FAULT\s*LEVEL[\s\S]{0,800}', T, flags=re.IGNORECASE)
    block = m.group(0) if m else ""
    if block:
        rows = [re.sub(r'\s+', ' ', ln).strip() for ln in block.splitlines() if ln.strip()]
        hdr = next((i for i,ln in enumerate(rows) if "AC440" in ln.replace(" ","") and "AC110" in ln.replace(" ","")), None)
        def last_two_floats(s: str):
            nums = [float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', s)]
            if len(nums) >= 2:
                return nums[-2], nums[-1]
            return None, None
        r440=r110=p440=p110=None
        if hdr is not None:
            body = rows[hdr+1:hdr+6]
            rms_row = next((ln for ln in body if re.search(r'Sym.*rms', ln, re.IGNORECASE)), None)
            peak_row = next((ln for ln in body if re.search(r'Asym.*peak', ln, re.IGNORECASE)), None)
            if rms_row:
                r440, r110 = last_two_floats(rms_row)
            if peak_row:
                p440, p110 = last_two_floats(peak_row)
        if None not in (r440, r110, p440, p110):
            out["ms_fault_level"] = f"AC440V: {r440:.2f}/{p440:.2f} kA, AC110V: {r110:.2f}/{p110:.2f} kA"
    if "ms_fault_level" not in out:
        rms_line = re.search(r'Sym\.?\s*rms[^\n]{0,120}', T, flags=re.IGNORECASE)
        peak_line = re.search(r'Asym\.?\s*peak[^\n]{0,120}', T, flags=re.IGNORECASE)
        def two_last(s):
            if not s: return (None,None)
            nums=[float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', s.group(0))]
            if len(nums)>=2: return nums[-2], nums[-1]
            return (None,None)
        r440,r110 = two_last(rms_line)
        p440,p110 = two_last(peak_line)
        if None not in (r440, r110, p440, p110):
            out["ms_fault_level"] = f"AC440V: {r440:.2f}/{p440:.2f} kA, AC110V: {r110:.2f}/{p110:.2f} kA"

    m = re.search(r'PAINT\s*COLOR[\s\S]{0,400}', T, flags=re.IGNORECASE)
    scope = m.group(0) if m else T
    outside_line = next((ln for ln in scope.splitlines() if "OUTSIDE" in ln.upper()), "")
    mc = MUNSELL_RE.search(outside_line)
    if mc:
        code = re.sub(r'\s+', ' ', mc.group(0).strip())
        out["ms_munsell_code"] = code
        if "GSP" in os.path.basename(pdf_path).upper():
            out["gsp_munsell_code"] = code
            out["gsp_paint"] = code

    q = re.search(r'QUANT(?:ITY|\.)\s*[:\-]?\s*(\d+)\s*SET\s*(?:\(\s*(\d+)\s*PNL\s*\))?', T, flags=re.IGNORECASE) \
        or re.search(r"Q['''\s]?TY\s*[:\-]?\s*(\d+)\s*SET(?:\s*\(\s*(\d+)\s*PNL\s*\))?", T, flags=re.IGNORECASE)
    if q:
        set_n, pnl_n = q.group(1), q.group(2)
        out["gsp_quantity"] = f"{set_n} SET" + (f" ( {pnl_n} PNL )" if pnl_n else "")

    if "GSP" not in os.path.basename(pdf_path).upper():
        q2 = re.search(r'QUANT(?:ITY|\.)\s*[:\-]?\s*(\d+)\s*SET\s*(?:\(\s*(\d+)\s*PNL\s*\))?', T, flags=re.IGNORECASE)
        if q2:
            set_n, pnl_n = q2.group(1), q2.group(2)
            out["ms_quantity"] = f"{set_n} SET" + (f" ( {pnl_n} PNL )" if pnl_n else "")

    m = re.search(r'RATED\s*CURRENT.*?(\d{3,6})\s*A', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_current", m.group(1) + "A")
    m = re.search(r'MAIN\s*BUS.*?(\d{3,6})\s*A', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_main_bus", m.group(1) + "A")

    m = re.search(r'(?:TRANSFORMER\s*RATING|TR\s*CAP(?:ACITY)?)\D{0,40}(\d{3,5})\s*kVA', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_tr_capacity", f"{m.group(1)} kVA")

    if "AC 440V" in U and "60HZ" in U and ("3W" in U or "3Φ" in U or "3PH" in U):
        out.setdefault("ms_rating", "AC 440V 60Hz 3Φ 3W")

    m = re.search(r'\bIP\s*2[12]\b', U)
    if m: out.setdefault("ms_ip", m.group(0).replace(" ", ""))

    if "GSP" in os.path.basename(pdf_path).upper() and "gsp_munsell_code" not in out and "ms_munsell_code" in out:
        out["gsp_munsell_code"] = out["ms_munsell_code"]
    if ip_checked:
        if 'GSP' in os.path.basename(pdf_path).upper():
            out['gsp_ip'] = ip_checked
        else:
            out['ms_ip'] = ip_checked
    try:
        cap = extract_tr_capacity(msbd_text)
        if cap:
            out['ms_tr_capacity'] = cap
    except Exception:
        pass
    try:
        ms_ip, gsp_ip = extract_ip_grade(msbd_text, gsp_text)
        if ms_ip:
            out['ms_ip'] = ms_ip
        if gsp_ip:
            out['gsp_ip'] = gsp_ip
    except Exception:
        pass
    try:
        hull = out.get('hull_no') or ''
        cls_guess = guess_class_from_nameplate_other(msbd_text, hull)
        if cls_guess:
            out['class'] = cls_guess
    except Exception:
        pass
    return out

def detect_checked_ip(pdf_path: str) -> str | None:
    try:
        import pdfplumber, os, re
        if not (pdf_path and os.path.exists(pdf_path)):
            return None
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                txt = (page.extract_text() or "").upper()
                if "DEGREE OF PROTECTION" not in txt:
                    continue
                if re.search(r"(■|☑|◼)\s*IP\s*22", txt): return "IP22"
                if re.search(r"(■|☑|◼)\s*IP\s*44", txt): return "IP44"
                words = page.extract_words(use_text_flow=True) or []
                rects = page.rects or []
                ips = [w for w in words if w.get("text","").upper().replace(" ","") in ("IP22","IP44","IP23","IP54","IP55")]
                for w in ips:
                    cy = (w["top"] + w["bottom"]) / 2.0
                    left_limit = w["x0"] - 4
                    right_limit = w["x0"] - 40
                    if right_limit > left_limit:
                        left_limit, right_limit = right_limit, left_limit
                    cands = []
                    for r in rects:
                        width = r["x1"] - r["x0"]
                        height = r["y1"] - r["y0"]
                        if 3 <= width <= 20 and 3 <= height <= 20:
                            ry = (r["y0"] + r["y1"]) / 2.0
                            if abs(ry - cy) <= 8 and right_limit <= r["x1"] <= left_limit:
                                fill = r.get("non_stroking_color")
                                if isinstance(fill, (tuple, list)):
                                    filled = sum(fill)/len(fill) < 0.25
                                elif isinstance(fill, (int, float)):
                                    filled = (fill < 0.25)
                                else:
                                    filled = False
                                if filled:
                                    cands.append(r)
                    if cands:
                        return w["text"].upper().replace(" ","")
        return None
    except Exception:
        return None

def parse_panel_blocks_v2(msbd_pdf: str, gsp_pdf: str) -> List[Dict[str, object]]:
    _notify_progress(40, "PANELS:MSBD")
    records = extract_acb_setting_panels(msbd_pdf) or []
    return records

def parse_function_test_of_gsp(pdf_path: str) -> List[Dict[str, object]]:
    if not (pdf_path and os.path.exists(pdf_path)):
        return []

    code_pat = re.compile(r'P\d{2}-\d{2,3}-\d{2}-PN', re.I)
    
    panel_circuits = {
        "No.1 GROUP STARTER PANEL": [],
        "No.2 GROUP STARTER PANEL": []
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            max_pages = min(25, len(pdf.pages))
            for page_num in range(max_pages):
                page = pdf.pages[page_num]
                try:
                    text = page.extract_text() or ""
                except Exception:
                    continue

                text_upper = text.upper()
                
                is_gsp_table_page = False
                
                if "NAME PLATE" in text_upper and "MCCB" in text_upper:
                    is_gsp_table_page = True
                
                elif "SPECIFICATION LIST" in text_upper and "GROUP STARTER PANEL" in text_upper:
                    is_gsp_table_page = True
                
                elif ("GSP" in text_upper or "GROUP STARTER" in text_upper) and \
                     ("CIRCUIT NAME" in text_upper or ("CIR" in text_upper and "NO" in text_upper)):
                    is_gsp_table_page = True
                
                if not is_gsp_table_page:
                    continue

                current_panel = None
                if re.search(r'NO\.?\s*1|GSP\s*NO\.?\s*1', text_upper):
                    current_panel = "No.1 GROUP STARTER PANEL"
                elif re.search(r'NO\.?\s*2|GSP\s*NO\.?\s*2', text_upper):
                    current_panel = "No.2 GROUP STARTER PANEL"
                else:
                    continue

                tables = page.extract_tables()
                if not tables:
                    continue

                for table_idx, table in enumerate(tables):
                    if not table or len(table) < 2:
                        continue

                    header_row_idx = None
                    cir_no_col = None
                    circuit_name_col = None

                    for idx, row in enumerate(table[:15]):
                        if not row:
                            continue
                        
                        row_text = " ".join([str(cell or "").upper() for cell in row])
                        
                        has_cir_no = ("CIR" in row_text and "NO" in row_text) or "CIRCUIT NO" in row_text
                        has_circuit_name = "CIRCUIT NAME" in row_text or ("CIRCUIT" in row_text and "NAME" in row_text)
                        
                        if has_cir_no and has_circuit_name:
                            header_row_idx = idx
                            
                            for col_idx, cell in enumerate(row):
                                if not cell:
                                    continue
                                cell_text = str(cell).upper()
                                
                                if (("CIR" in cell_text or "CIRCUIT" in cell_text) and "NO" in cell_text and "NAME" not in cell_text):
                                    cir_no_col = col_idx
                                
                                if ("CIRCUIT" in cell_text and "NAME" in cell_text) or \
                                   (cell_text.strip() == "NAME" and cir_no_col is not None):
                                    if circuit_name_col is None:
                                        circuit_name_col = col_idx
                            
                            if cir_no_col is not None and circuit_name_col is not None:
                                break

                    if header_row_idx is None or cir_no_col is None or circuit_name_col is None:
                        continue

                    pending_code = None
                    pending_name_parts = []

                    for row in table[header_row_idx + 1:]:
                        if not row or len(row) <= max(cir_no_col, circuit_name_col):
                            continue

                        cir_no_cell = str(row[cir_no_col] or "").strip()
                        circuit_name_cell = str(row[circuit_name_col] or "").strip()

                        code_match = code_pat.search(cir_no_cell)

                        if code_match:
                            if pending_code and pending_name_parts:
                                full_name = " ".join(pending_name_parts)
                                full_name = re.sub(r'\s+', ' ', full_name).strip()
                                full_name = full_name.replace(pending_code, "").strip()
                                
                                if full_name:
                                    if not any(c["code"] == pending_code for c in panel_circuits[current_panel]):
                                        panel_circuits[current_panel].append({
                                            "code": pending_code,
                                            "name": full_name
                                        })

                            pending_code = code_match.group(0).upper()
                            pending_name_parts = []
                            
                            if circuit_name_cell:
                                clean_name = circuit_name_cell.replace(pending_code, "").strip()
                                if clean_name and \
                                   clean_name.upper() not in ["CIR", "NO", "CIRCUIT", "NAME", "-"] and \
                                   len(clean_name) > 1:
                                    pending_name_parts.append(clean_name)

                        elif pending_code and circuit_name_cell:
                            clean_name = circuit_name_cell.strip()
                            if clean_name and \
                               clean_name.upper() not in ["CIR", "NO", "CIRCUIT", "NAME", "-"] and \
                               len(clean_name) > 1:
                                pending_name_parts.append(clean_name)

                    if pending_code and pending_name_parts:
                        full_name = " ".join(pending_name_parts)
                        full_name = re.sub(r'\s+', ' ', full_name).strip()
                        full_name = full_name.replace(pending_code, "").strip()
                        
                        if full_name:
                            if not any(c["code"] == pending_code for c in panel_circuits[current_panel]):
                                panel_circuits[current_panel].append({
                                    "code": pending_code,
                                    "name": full_name
                                })

    except Exception as e:
        print(f"[ERROR] GSP 파싱 실패: {e}")
        import traceback
        traceback.print_exc()

    results: List[Dict[str, object]] = []
    
    for panel_num, (panel_label, circuits) in enumerate([
        ("No.1 GROUP STARTER PANEL", panel_circuits["No.1 GROUP STARTER PANEL"]),
        ("No.2 GROUP STARTER PANEL", panel_circuits["No.2 GROUP STARTER PANEL"])
    ], start=1):
        
        if not circuits:
            continue
        
        circuits.sort(key=lambda c: c["code"])
        content = "\n".join([f"{c['code']} {c['name']}" for c in circuits])
        
        results.append({
            "panel": panel_label,
            "placeholder": f"gsp_function_no{panel_num}",
            "content": content,
            "rows": circuits
        })

    return results   

def parse_emergency_colorplate(msbd_pdf: str) -> List[Dict[str, object]]:
    raw = read_text(msbd_pdf, max_pages=60)
    if not raw:
        return []
    upper = raw.upper()
    pos = upper.find("COLOR PLATE SPECIFICATION")
    window = raw[max(0, pos-2000): pos+8000] if pos != -1 else raw

    pattern = re.compile(r'\b((?:ES|CO2|FOAM|PT)-\d+[A-Z]?)\b', re.I)
    items: List[Dict[str, object]] = []
    for m in pattern.finditer(window):
        code = m.group(1).upper()
        tail = window[m.end(): m.end() + 160]
        tail_strip = tail.lstrip()
        color = ""
        if tail_strip.startswith("("):
            end = tail_strip.find(")")
            if end != -1:
                color = tail_strip[1:end].strip()
                tail_strip = tail_strip[end + 1 :].lstrip()
        first_line = tail_strip.splitlines()[0] if tail_strip else ""
        name = first_line.strip(" :-·().")
        items.append({"code": code, "name": name, "color": color, "groups": []})

    seen: Dict[str, Dict[str, object]] = {}
    for it in items:
        code = it.get("code", "")
        if code in seen:
            target = seen[code]
            if not target.get("name") and it.get("name"):
                target["name"] = it.get("name")
            if not target.get("color") and it.get("color"):
                target["color"] = it.get("color")
        else:
            seen[code] = it
    return list(seen.values())

extract_panel_info_from_msbd = extract_acb_setting_panels

# ==================== Emergency Stop 완전 개선 버전 v2 ====================

def parse_emergency_stop_from_mccb(pdf_path: str) -> List[Dict[str, object]]:
    """Emergency Stop 완전 범용 파서 (v3.2 - REMARKS 컬럼 집중)"""
    if not pdf_path or not os.path.exists(pdf_path):
        return []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"\n{'='*60}")
            print(f"Emergency Stop 파싱: {os.path.basename(pdf_path)}")
            print(f"총 {len(pdf.pages)} 페이지")
            print(f"{'='*60}\n")
            
            print("[STEP 1] NAME PLATE (COLOR PLATE) 스캔...")
            code_info_map = _extract_emergency_codes_from_nameplate(pdf)
            
            if not code_info_map:
                print("[WARN] NAME PLATE에서 CODE를 찾을 수 없습니다.")
                return []
            
            print(f"\n✓ {len(code_info_map)}개 CODE 감지:")
            for code, info in sorted(code_info_map.items()):
                color = info.get('color', '')
                name = info.get('name', '')[:40]
                print(f"  • {code:10s} {color:15s} {name}...")
            
            print(f"\n[STEP 2] NAME PLATE (MCCB) 페이지 스캔...")
            all_circuits = _extract_emergency_circuits(pdf)
            
            print(f"\n✓ 총 {len(all_circuits)}개 Circuit 추출")
            
            code_circuit_count = {}
            for circuit in all_circuits:
                code = circuit.get('code', '')
                code_circuit_count[code] = code_circuit_count.get(code, 0) + 1
            
            print(f"\nCODE별 Circuit 매칭 현황:")
            for code in sorted(code_info_map.keys()):
                count = code_circuit_count.get(code, 0)
                status = "✓" if count > 0 else "✗"
                print(f"  {status} {code:10s} → {count} circuits")
            
            print(f"\n[STEP 3] 그룹화 및 결과 생성...")
            grouped = _group_emergency_by_code(all_circuits, code_info_map)
            
            print(f"\n✓ {len(grouped)}개 CODE 결과 생성")
            print(f"  - Circuit 매칭된 CODE: {len([g for g in grouped if g['groups']])}개")
            print(f"  - Circuit 매칭 안된 CODE: {len([g for g in grouped if not g['groups']])}개")
            print(f"{'='*60}\n")
            
            return grouped
    
    except Exception as e:
        print(f"[ERROR] Emergency Stop 파싱 실패: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_emergency_codes_from_nameplate(pdf) -> Dict[str, Dict[str, str]]:
    """NAME PLATE (COLOR PLATE)에서 Emergency CODE 추출"""
    code_map = {}
    max_scan_pages = min(50, len(pdf.pages))
    
    for page_idx in range(max_scan_pages):
        page = pdf.pages[page_idx]
        text = page.extract_text() or ""
        text_upper = text.upper()
        
        if not ("COLOR PLATE" in text_upper or "COLOUR PLATE" in text_upper):
            continue
        
        print(f"[INFO] COLOR PLATE 페이지: Page {page_idx + 1}")
        
        text_codes = _parse_colorplate_comprehensive(text)
        for code, info in text_codes.items():
            if code not in code_map:
                code_map[code] = info
                print(f"  추가: {code} = {info['color']} / {info['name'][:40] if info['name'] else ''}...")
            else:
                if not code_map[code].get('color') and info.get('color'):
                    code_map[code]['color'] = info['color']
                if not code_map[code].get('name') and info.get('name'):
                    code_map[code]['name'] = info['name']
        
        tables = page.extract_tables()
        if tables:
            for table_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                
                table_codes = _parse_colorplate_table(table, table_idx)
                for code, info in table_codes.items():
                    if code not in code_map:
                        code_map[code] = info
                    else:
                        if not code_map[code].get('color') and info.get('color'):
                            code_map[code]['color'] = info['color']
                        if not code_map[code].get('name') and info.get('name'):
                            code_map[code]['name'] = info['name']
    
    print(f"[INFO] 이 {len(code_map)}개 CODE 추출\n")
    return code_map


def _parse_colorplate_comprehensive(text: str) -> Dict[str, Dict[str, str]]:
    """텍스트에서 모든 CODE 패턴 추출"""
    code_map = {}
    
    emergency_patterns = [
        re.compile(r'\b(ES-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(CO2-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(PT-?\d+)\b', re.I),
        re.compile(r'\b(FOAM-?\d+[A-Z]?)\b', re.I),
    ]
    
    color_keywords = [
        'RED', 'PINK', 'BROWN', 'BLUE', 'GREEN', 'YELLOW',
        'GOLDEN', 'SILVER', 'PURPLE', 'ORANGE', 'WHITE', 'BLACK',
        'LIGHT', 'DARK', 'NAVY'
    ]
    
    lines = text.split('\n')
    
    for i, line in enumerate(lines):
        line_upper = line.upper()
        
        found_code = None
        for pattern in emergency_patterns:
            match = pattern.search(line_upper)
            if match:
                found_code = match.group(1).upper()
                if '-' not in found_code and re.match(r'[A-Z]{2,4}\d+', found_code):
                    found_code = re.sub(r'^([A-Z]+)(\d+)', r'\1-\2', found_code)
                break
        
        if not found_code:
            continue
        
        color = ""
        words = line_upper.split()
        for word in words:
            if word in color_keywords:
                color = word
                break
        
        name = ""
        code_pos = line_upper.find(found_code)
        if code_pos != -1:
            after_code = line[code_pos + len(found_code):].strip()
            for kw in color_keywords:
                after_code = re.sub(r'\b' + kw + r'\b', '', after_code, flags=re.I)
            after_code = re.sub(r'\s+', ' ', after_code).strip()
            if len(after_code) > 10:
                name = after_code
        
        if found_code:
            code_map[found_code] = {"color": color, "name": name}
    
    return code_map


def _parse_colorplate_table(table: List[List], table_idx: int) -> Dict[str, Dict[str, str]]:
    """테이블에서 CODE, COLOR, NAME 추출"""
    code_map = {}
    
    if not table or len(table) < 1:
        return code_map
    
    emergency_patterns = [
        re.compile(r'\b(ES-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(CO2-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(PT-?\d+)\b', re.I),
        re.compile(r'\b(FOAM-?\d+[A-Z]?)\b', re.I),
    ]

    color_keywords = {
        "RED", "PINK", "BROWN", "BLUE", "GREEN", "YELLOW", "GOLDEN", "SILVER",
        "PURPLE", "ORANGE", "WHITE", "BLACK", "LIGHT", "DARK", "NAVY", "GREY", "GRAY",
    }

    def _pick_color(cells: List[str]) -> str:
        for cell in cells:
            words = [w for w in re.split(r'[^A-Z]', cell.upper()) if w]
            for w in words:
                if w in color_keywords:
                    return w
        return ""

    for row in table:
        if not row:
            continue

        normalized_row = [str(cell or "").strip() for cell in row]
        normalized_upper = [cell.upper() for cell in normalized_row]

        found_code = None
        code_col_idx = None
        for col_idx, cell_text in enumerate(normalized_upper):
            for pattern in emergency_patterns:
                match = pattern.search(cell_text)
                if match:
                    found_code = match.group(1).upper()
                    code_col_idx = col_idx
                    if '-' not in found_code and re.match(r'[A-Z]{2,4}\d+', found_code):
                        found_code = re.sub(r'^([A-Z]+)(\d+)', r'\1-\2', found_code)
                    break
            if found_code:
                break

        if not found_code:
            continue

        before_cells = normalized_upper[:code_col_idx] if code_col_idx is not None else []
        after_cells = normalized_row[code_col_idx + 1 :] if code_col_idx is not None else []

        color = _pick_color(before_cells) or _pick_color(after_cells)

        name_candidates = [
            cell for cell in after_cells
            if cell and len(cell) > 1 and not re.search(r'\b(CODE|COLOR|COLOUR)\b', cell, flags=re.I)
            and not re.search(r'ES-?\d+|CO2-?\d+|FOAM-?\d+|PT-?\d+', cell, flags=re.I)
        ]
        name = max(name_candidates, key=len).strip(" :-·().") if name_candidates else ""

        code_map[found_code] = {"color": color, "name": name}

    return code_map


def _extract_emergency_circuits(pdf) -> List[Dict[str, str]]:
    """MCCB/FEEDER/GSP 페이지에서 Emergency Circuit 추출"""
    all_circuits = []
    max_scan_pages = min(len(pdf.pages), 60)
    circuit_pattern = re.compile(r'P\d{2}-\d{2,3}-\d{2}-[A-Z]{2}', re.I)
    
    for page_idx in range(max_scan_pages):
        page = pdf.pages[page_idx]
        text = page.extract_text() or ""
        text_upper = text.upper()
        
        is_circuit_page = False
        if "NAME PLATE" in text_upper and "MCCB" in text_upper:
            is_circuit_page = True
        elif "SPECIFICATION" in text_upper and "LIST" in text_upper:
            if circuit_pattern.search(text_upper):
                is_circuit_page = True
        elif circuit_pattern.search(text_upper) and "REMARKS" in text_upper:
            if any(kw in text_upper for kw in ['FEEDER', 'PANEL', 'GSP', 'GROUP STARTER']):
                is_circuit_page = True
        
        if not is_circuit_page:
            continue
        
        panel_name, doc_type = _detect_emergency_panel_info(text)
        print(f"[DEBUG] Page {page_idx + 1}: {panel_name} ({doc_type})")
        
        tables = page.extract_tables()
        if tables:
            for table_idx, table in enumerate(tables):
                circuits = _parse_emergency_circuit_table(table, panel_name, doc_type, page_idx + 1)
                if circuits:
                    print(f"  └─ Table {table_idx + 1}: {len(circuits)} circuits")
                    for c in circuits:
                        print(f"     {c['circuit_no']} → {c['code']}")
                all_circuits.extend(circuits)
    
    return all_circuits


def _detect_emergency_panel_info(text: str) -> Tuple[str, str]:
    """Panel 이름과 문서 타입(GSP/MSBD) 감지"""
    text_upper = text.upper()
    
    if "GROUP STARTER" in text_upper or "GSP" in text_upper:
        doc_type = "GSP"
        if re.search(r'NO\.?\s*1|GSP\s*NO\.?\s*1', text_upper):
            return "No.1 GROUP STARTER PANEL", doc_type
        elif re.search(r'NO\.?\s*2|GSP\s*NO\.?\s*2', text_upper):
            return "No.2 GROUP STARTER PANEL", doc_type
        else:
            return "GROUP STARTER PANEL", doc_type
    else:
        doc_type = "MSBD"
        if "FEEDER" in text_upper:
            if re.search(r'NO\.?\s*1', text_upper):
                return "No.1 AC440V FEEDER PANEL", doc_type
            elif re.search(r'NO\.?\s*2', text_upper):
                return "No.2 AC440V FEEDER PANEL", doc_type
            else:
                return "AC440V FEEDER PANEL", doc_type
        elif "EMERGENCY" in text_upper or "EMCY" in text_upper:
            return "EMERGENCY PANEL", doc_type
        else:
            if re.search(r'NO\.?\s*1', text_upper):
                return "No.1 PANEL", doc_type
            elif re.search(r'NO\.?\s*2', text_upper):
                return "No.2 PANEL", doc_type
            else:
                return "MSBD PANEL", doc_type


def _parse_emergency_circuit_table(
    table: List[List], 
    panel_name: str, 
    doc_type: str, 
    page_num: int
) -> List[Dict[str, str]]:
    """Circuit 테이블에서 Emergency 관련 Circuit 추출"""
    if not table or len(table) < 2:
        return []
    
    circuits = []
    header_idx = None
    cir_no_col = None
    cir_name_col = None
    remarks_col = None
    
    for idx, row in enumerate(table[:20]):
        if not row:
            continue
        
        row_text = ' '.join([str(cell or '').upper() for cell in row])
        
        if 'CIR' in row_text or 'CIRCUIT' in row_text or 'NAME PLATE' in row_text:
            header_idx = idx
            
            for col_idx in range(len(row) - 1, -1, -1):
                cell = row[col_idx]
                if not cell:
                    continue
                cell_upper = str(cell).upper().strip()
                if 'REMARK' in cell_upper and remarks_col is None:
                    remarks_col = col_idx
                    break
            
            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                cell_upper = str(cell).upper().strip()
                
                if 'NO' in cell_upper and ('CIR' in cell_upper or 'CIRCUIT' in cell_upper):
                    if 'NAME' not in cell_upper and 'TYPE' not in cell_upper:
                        cir_no_col = col_idx
                
                if 'NAME' in cell_upper:
                    if 'CIR' in cell_upper or 'CIRCUIT' in cell_upper or 'BREAKER' not in cell_upper:
                        if cir_name_col is None:
                            cir_name_col = col_idx
            
            if cir_no_col is not None:
                break
    
    if header_idx is None or cir_no_col is None:
        return []
    
    circuit_patterns = [
        re.compile(r'P\d{2}-\d{3}-\d{2}-[A-Z]{2}', re.I),
        re.compile(r'P\d{2}-\d{2,3}-\d{2}-[A-Z]{2}', re.I),
    ]
    
    emergency_code_patterns = [
        re.compile(r'\b(ES-\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(CO2-\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(PT-\d+)\b', re.I),
        re.compile(r'\b(FOAM-\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(ES\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(CO2\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(FOAM\d+[A-Z]?)\b', re.I),
    ]
    color_keywords = {
        "RED", "PINK", "BROWN", "BLUE", "GREEN", "YELLOW", "GOLDEN", "SILVER",
        "PURPLE", "ORANGE", "WHITE", "BLACK", "LIGHT", "DARK", "NAVY", "GREY", "GRAY",
    }
    
    for row_idx in range(header_idx + 1, len(table)):
        row = table[row_idx]
        if not row:
            continue
        
        cir_no_cell = str(row[cir_no_col] or '').strip() if cir_no_col < len(row) else ""
        circuit_match = None
        circuit_no = ""
        
        for pattern in circuit_patterns:
            circuit_match = pattern.search(cir_no_cell)
            if circuit_match:
                circuit_no = circuit_match.group(0).upper()
                break
        
        if not circuit_no:
            continue
        
        code_from_remarks = ""
        color_hint = ""
        remark_name = ""
        if remarks_col is not None and remarks_col < len(row):
            remarks_raw = str(row[remarks_col] or '').strip()
            remarks_text = remarks_raw.upper()
            for pattern in emergency_code_patterns:
                match = pattern.search(remarks_text)
                if match:
                    code_from_remarks = match.group(1).upper()
                    if '-' not in code_from_remarks and re.match(r'[A-Z]{2,4}\d+', code_from_remarks):
                        code_from_remarks = re.sub(r'^([A-Z]+)(\d+)', r'\1-\2', code_from_remarks)
                    break

            for word in re.split(r'[^A-Z]', remarks_text):
                if word in color_keywords:
                    color_hint = word
                    break

            cleaned = remarks_raw
            if code_from_remarks:
                cleaned = re.sub(re.escape(code_from_remarks), "", cleaned, flags=re.I)
            cleaned = re.sub(r'\b(' + '|'.join(color_keywords) + r')\b', '', cleaned, flags=re.I)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip(" :-·().")
            if cleaned and len(cleaned) > 3:
                remark_name = cleaned
        
        if not code_from_remarks:
            continue
        
        circuit_name = ""
        if cir_name_col is not None and cir_name_col < len(row):
            name_cell = str(row[cir_name_col] or '').strip()
            name_cell = name_cell.replace(circuit_no, '').strip()
            name_cell = re.sub(r'\s+', ' ', name_cell).strip()
            if name_cell and len(name_cell) > 1:
                circuit_name = name_cell
        
        if not circuit_name and row_idx + 1 < len(table):
            next_row = table[row_idx + 1]
            if cir_name_col < len(next_row):
                next_name = str(next_row[cir_name_col] or '').strip()
                has_next_circuit = any(pattern.search(str(next_row[cir_no_col] or '')) for pattern in circuit_patterns) if cir_no_col < len(next_row) else False
                if not has_next_circuit and len(next_name) > 1:
                    circuit_name = next_name
        
        if circuit_name:
            circuits.append({
                'circuit_no': circuit_no,
                'circuit_name': circuit_name,
                'panel': panel_name,
                'doc_type': doc_type,
                'code': code_from_remarks,
                'color_hint': color_hint,
                'remark_name': remark_name
            })

    return circuits


def _group_emergency_by_code(
    circuits: List[Dict[str, str]],
    code_info_map: Dict[str, Dict[str, str]]
) -> List[Dict[str, object]]:
    """CODE별로 Circuit 그룹화 (GSP/MSBD 구분 표시)"""
    code_circuits = {}
    color_hints: Dict[str, List[str]] = defaultdict(list)
    name_hints: Dict[str, List[str]] = defaultdict(list)
    
    code_variations = {}
    for code in code_info_map.keys():
        normalized = code.replace('-', '').replace(' ', '').upper()
        code_variations[normalized] = code
        code_variations[code] = code
    
    for circuit in circuits:
        circuit_code = circuit.get('code', '').upper().strip()
        if not circuit_code:
            continue
        
        matched_code = None
        if circuit_code in code_info_map:
            matched_code = circuit_code
        else:
            normalized = circuit_code.replace('-', '').replace(' ', '')
            if normalized in code_variations:
                matched_code = code_variations[normalized]
        
        if not matched_code:
            continue
        
        if matched_code not in code_circuits:
            code_circuits[matched_code] = {'gsp': [], 'msbd': []}

        doc_type = circuit.get('doc_type', 'MSBD')
        target_list = code_circuits[matched_code]['gsp'] if doc_type == 'GSP' else code_circuits[matched_code]['msbd']

        target_list.append({
            'circuit_no': circuit.get('circuit_no', ''),
            'circuit_name': circuit.get('circuit_name', ''),
            'panel': circuit.get('panel', ''),
            'remark_name': circuit.get('remark_name', '')
        })

        hint_color = circuit.get('color_hint', '')
        if hint_color:
            color_hints[matched_code].append(hint_color)
        hint_name = circuit.get('remark_name', '')
        if hint_name:
            name_hints[matched_code].append(hint_name)
    
    result = []
    
    for code in sorted(code_info_map.keys()):
        info = code_info_map.get(code, {})
        color = info.get("color", "")
        name = info.get("name", "")

        if not color:
            votes = defaultdict(int)
            for hint in color_hints.get(code, []):
                votes[hint.upper()] += 1
            if votes:
                color = max(votes.items(), key=lambda kv: kv[1])[0]

        gsp_circuits = code_circuits.get(code, {}).get('gsp', [])
        msbd_circuits = code_circuits.get(code, {}).get('msbd', [])

        if not name:
            hint_pool = name_hints.get(code, [])
            if hint_pool:
                name = max(hint_pool, key=len)
            else:
                all_circuits = gsp_circuits + msbd_circuits
                name_candidates = [c['circuit_name'] for c in all_circuits if c.get('circuit_name')]
                if name_candidates:
                    name = max(name_candidates, key=len)

        def _format_circuit_entry(c: Dict[str, str]) -> str:
            label = c.get('circuit_no', '')
            cname = c.get('circuit_name') or c.get('remark_name')
            if cname:
                return f"{label} – {cname}"
            return label
        
        groups = []
        
        if gsp_circuits:
            gsp_panel_groups = {}
            for circuit in gsp_circuits:
                panel = circuit['panel']
                if panel not in gsp_panel_groups:
                    gsp_panel_groups[panel] = []
                gsp_panel_groups[panel].append(_format_circuit_entry(circuit))

            for panel, circs in sorted(gsp_panel_groups.items()):
                groups.append({
                    'panel_header': f"[GSP] {panel}",
                    'circuits': sorted(set(circs))
                })
        
        if msbd_circuits:
            msbd_panel_groups = {}
            for circuit in msbd_circuits:
                panel = circuit['panel']
                if panel not in msbd_panel_groups:
                    msbd_panel_groups[panel] = []
                msbd_panel_groups[panel].append(_format_circuit_entry(circuit))

            for panel, circs in sorted(msbd_panel_groups.items()):
                groups.append({
                    'panel_header': f"[MSBD] {panel}",
                    'circuits': sorted(set(circs))
                })
        
        result.append({
            'code': code,
            'color': color,
            'name': name,
            'groups': groups
        })
    
    return result