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


def _normalize_code(raw: str) -> Optional[str]:
    token = (raw or "").strip().upper()
    if not token:
        return None
    token = token.replace('–', '-').replace('—', '-').replace('_', '-')
    token = re.sub(r'^[^A-Z0-9-]+', '', token)
    token = re.sub(r'[^A-Z0-9-]+$', '', token)
    token = re.sub(r'[\*\(\)\[\]{}:]+', '', token)
    token = re.sub(r'\s+', '', token)
    if '-' not in token and re.match(r'[A-Z]{2,4}\d+', token):
        token = re.sub(r'^([A-Z]+)(\d+)', r'\1-\2', token)
    if not re.search(r'\d', token):
        return None
    return token


def _extract_codes_from_text(text: str, patterns: List[re.Pattern]) -> List[str]:
    found: List[str] = []
    seen = set()
    txt = (text or "").upper()
    txt = re.sub(r'[\*\(\)\[\]{}:]+', ' ', txt)

    def _add_code(raw_code: str):
        norm = _normalize_code(raw_code)
        if norm and norm not in seen:
            seen.add(norm)
            found.append(norm)
        return norm

    # pre-expand patterns like "FOAM 1A 1B 2A" or "CO2 -4 -5" where the prefix appears once
    combo_pat = re.compile(r'\b([A-Z]{2,8})\s*-?\s*((?:\d+[A-Z]?)(?:[,/\s]+\d+[A-Z]?)+)')
    for m in combo_pat.finditer(txt):
        prefix = m.group(1)
        suffix_block = m.group(2)
        for suf in re.split(r'[,/\s]+', suffix_block):
            suf = suf.strip()
            if not suf:
                continue
            _add_code(f"{prefix}-{suf}")

    # direct regex matches
    last_prefix = None
    for pat in patterns:
        for m in pat.finditer(txt):
            norm = _add_code(m.group(1))
            if norm:
                m_pref = re.match(r'^([A-Z]+)', norm)
                if m_pref:
                    last_prefix = m_pref.group(1)

    # token-based fallback with chained suffix support (e.g., "FOAM-1A,1B/2A")
    for token in re.split(r'[\s,;]+', txt):
        if not token:
            continue
        for sub in re.split(r'[/]+', token):
            if not sub:
                continue
            sub = re.sub(r'^[^A-Z0-9-]+', '', sub)
            sub = re.sub(r'[^A-Z0-9-]+$', '', sub)
            if not sub:
                continue

            norm = _normalize_code(sub)
            if norm:
                prefix_match = re.match(r'^([A-Z]+)', norm)
                if prefix_match:
                    last_prefix = prefix_match.group(1)
                _add_code(norm)
                continue

            # store prefixes like "FOAM" or "CO2" even when digits are absent, so "-1A" attaches
            prefix_candidate = re.sub(r'[^A-Z0-9]', '', sub)
            if prefix_candidate and re.fullmatch(r'[A-Z]+\d*', prefix_candidate):
                last_prefix = prefix_candidate
                continue

            if last_prefix and re.fullmatch(r'-?\d+[A-Z]?', sub):
                candidate = f"{last_prefix}-{sub.lstrip('-')}"
                _add_code(candidate)

    return found


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
        "aliases": [
            "BUSTIE",           # 공백 없음
            "BUSTIEPANEL",      # PANEL 붙음
            "BUS-TIE",          # 하이픈 포함
            "BUSTIESWITCHBOARD",
            "BUSTIESWBD",
        ],
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

# ------------------------
# PANEL 감지 개선 함수들
# ------------------------

def _find_panel_headers_from_top(page) -> Dict[str, float]:
    """
    도면 상단(Y < 150)에서 PANEL 헤더 텍스트 찾기
    ※ NO.1/NO.2 INCOMING은 병합되어 있어 구분 불가 → 체크박스로 판단
    """
    words = page.extract_words() or []
    panel_positions = {}
    
    print("[DEBUG] 상단 헤더 스캔 중...")
    
    for word in words:
        wy = (word["top"] + word["bottom"]) / 2.0
        wx = (word["x0"] + word["x1"]) / 2.0
        
        # 상단 150px 이내만 확인
        if wy > 150:
            continue
        
        text = (word.get("text") or "").strip().upper()
        
        # BUS TIE 감지 (명확한 헤더)
        if "BUS" in text or "TIE" in text:
            # 주변 단어 확인
            nearby_words = [
                w for w in words 
                if abs((w["top"] + w["bottom"]) / 2.0 - wy) < 20
                and abs((w["x0"] + w["x1"]) / 2.0 - wx) < 100
            ]
            nearby_text = " ".join([w.get("text", "").upper() for w in nearby_words])
            
            if "BUS" in nearby_text and "TIE" in nearby_text:
                if "bus" not in panel_positions:
                    # BUS TIE 영역의 중심 X 좌표 계산
                    bus_words = [w for w in nearby_words if "BUS" in w.get("text", "").upper() or "TIE" in w.get("text", "").upper()]
                    if bus_words:
                        bus_x_coords = [(w["x0"] + w["x1"]) / 2.0 for w in bus_words]
                        bus_center = sum(bus_x_coords) / len(bus_x_coords)
                        panel_positions["bus"] = bus_center
                        print(f"  ✓ bus 발견 (header): BUS TIE at X={bus_center:.1f}, Y={wy:.1f}")
        
        # LINK TO EMCY 감지 (명확한 헤더)
        if "LINK" in text or "EMCY" in text or "EMERGENCY" in text or "SWITCHBOARD" in text:
            if "emg" not in panel_positions:
                # EMCY 영역의 중심 X 좌표 계산
                nearby_words = [
                    w for w in words 
                    if abs((w["top"] + w["bottom"]) / 2.0 - wy) < 20
                    and abs((w["x0"] + w["x1"]) / 2.0 - wx) < 100
                ]
                emcy_words = [
                    w for w in nearby_words 
                    if any(kw in w.get("text", "").upper() for kw in ["LINK", "EMCY", "EMERGENCY", "SWITCHBOARD"])
                ]
                if emcy_words:
                    emcy_x_coords = [(w["x0"] + w["x1"]) / 2.0 for w in emcy_words]
                    emcy_center = sum(emcy_x_coords) / len(emcy_x_coords)
                    panel_positions["emg"] = emcy_center
                    print(f"  ✓ emg 발견 (header): at X={emcy_center:.1f}, Y={wy:.1f}")
    
    # NO.1/NO.2는 여기서 찾지 않음 (체크박스로 판단)
    print("  ※ NO.1/NO.2 INCOMING은 체크박스 클러스터링으로 판단 예정")
    
    return panel_positions

# 이 아래에 기존 _find_acb_setting_page() 함수가 있어야 함
def _find_acb_setting_page(pdf) -> Tuple[Optional[int], Optional["pdfplumber.page.Page"]]:
    ...

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
    체크박스 감지 - 더 넓은 범위 스캔 (개선 버전)
    """
    checkboxes = []
    rects = page.rects or []
    
    print(f"[DEBUG] 전체 사각형 개수: {len(rects)}")
    
    for rect in rects:
        width = rect.get("x1", 0) - rect.get("x0", 0)
        height = rect.get("y1", 0) - rect.get("y0", 0)
        
        # 크기 범위 확대: 3~25px (기존 3~20)
        if not (3 <= width <= 25 and 3 <= height <= 25):
            continue
        
        # 정사각형에 가까운지 확인
        aspect_ratio = max(width, height) / min(width, height)
        if aspect_ratio > 2.0:  # 너비/높이 비율이 2배 이상 차이나면 제외
            continue
        
        # Fill color 체크
        fill = rect.get("non_stroking_color")
        is_filled = False
        
        if fill is not None:
            if isinstance(fill, (tuple, list)):
                # 0.3 이하면 검은색 (기존 0.25)
                is_filled = sum(fill) / len(fill) < 0.3
            elif isinstance(fill, (int, float)):
                is_filled = fill < 0.3
        
        # Stroke(테두리)만 있어도 체크박스로 간주
        stroke = rect.get("stroking_color")
        if stroke is not None and not is_filled:
            # 테두리가 있고 내부가 비어있으면 체크 안된 박스
            # 하지만 주변에 'X'나 체크 표시가 있을 수 있으므로 일단 포함
            is_filled = True  # 임시로 포함
        
        if is_filled:
            cx = (rect["x0"] + rect["x1"]) / 2.0
            cy = (rect["top"] + rect["bottom"]) / 2.0
            checkboxes.append({"x": cx, "y": cy, "width": width, "height": height})
    
    print(f"[DEBUG] 체크박스 후보: {len(checkboxes)}개")
    
    # Y 좌표별로 그룹화하여 같은 행의 체크박스 찾기
    y_groups = {}
    for cb in checkboxes:
        y_key = round(cb["y"] / 10) * 10  # 10px 단위로 그룹화
        if y_key not in y_groups:
            y_groups[y_key] = []
        y_groups[y_key].append(cb)
    
    print(f"[DEBUG] Y 좌표 그룹: {len(y_groups)}개")
    for y_key, group in sorted(y_groups.items())[:5]:  # 상위 5개만 출력
        x_coords = [f"{cb['x']:.1f}" for cb in group]
        print(f"  Y≈{y_key}: {len(group)}개 at X=[{', '.join(x_coords)}]")
    
    return checkboxes

def _determine_panel_columns(page, checkboxes: List[Dict[str, float]]) -> Dict[str, Tuple[float, float]]:
    """
    PANEL 컬럼 감지 - 체크박스 클러스터링 (v4 - 50px threshold)
    """
    words = page.extract_words() or []
    
    print("\n[DEBUG] PANEL 컬럼 감지 시작")
    print("="*60)
    
    # 1단계: 헤더에서 BUS/EMCY 찾기
    panel_positions = _find_panel_headers_from_top(page)
    
    print(f"\n[1단계] 헤더 감지: {len(panel_positions)}개")
    for slot, x in sorted(panel_positions.items(), key=lambda item: item[1]):
        print(f"  {slot}: X={x:.1f}")
    
    # 2단계: 체크박스 클러스터링
    print("\n[2단계] 체크박스 클러스터링")
    
    if not checkboxes:
        print("[ERROR] 체크박스가 없습니다!")
        return {}
    
    # 디버깅: Y 분포 확인
    y_coords = [cb["y"] for cb in checkboxes]
    print(f"  전체: {len(checkboxes)}개, Y범위: {min(y_coords):.1f}~{max(y_coords):.1f}")
    print(f"  Y<100: {len([y for y in y_coords if y < 100])}개")
    print(f"  Y<150: {len([y for y in y_coords if y < 150])}개")
    print(f"  Y<200: {len([y for y in y_coords if y < 200])}개")
    
    # 상단 영역 선택 (Y < 150)
    top_checkboxes = [cb for cb in checkboxes if cb["y"] < 150]
    print(f"\n  → 선택: Y<150, {len(top_checkboxes)}개")
    
    if len(top_checkboxes) < 10:
        print(f"[WARN] 부족 → Y<200 확대")
        top_checkboxes = [cb for cb in checkboxes if cb["y"] < 200]
        print(f"  → 재선택: {len(top_checkboxes)}개")
    
    if len(top_checkboxes) < 5:
        print(f"[ERROR] 너무 적음 → 전체 사용")
        top_checkboxes = checkboxes
    
    # X 좌표 추출 (중복 제거)
    x_coords = sorted(set([cb["x"] for cb in top_checkboxes]))
    print(f"  고유 X: {len(x_coords)}개, 범위: {min(x_coords):.1f}~{max(x_coords):.1f}")
    
    # 클러스터링 (50px threshold)
    clusters = []
    current = [x_coords[0]]
    
    for x in x_coords[1:]:
        if x - current[-1] < 50:  # ← 핵심: 120→50
            current.append(x)
        else:
            avg = sum(current) / len(current)
            clusters.append((avg, len(current)))
            current = [x]
    
    if current:
        avg = sum(current) / len(current)
        clusters.append((avg, len(current)))
    
    print(f"\n  클러스터: {len(clusters)}개")
    for i, (x, cnt) in enumerate(clusters):
        print(f"    [{i+1}] X={x:6.1f} ({cnt:2d}개)")
    
    cluster_centers = [c[0] for c in clusters]
    
    # 3단계: 매핑
    if len(cluster_centers) < 4:
        print(f"\n[WARN] {len(cluster_centers)}개만 발견 (4개 필요)")
    
    bus_x = panel_positions.get("bus")
    emg_x = panel_positions.get("emg")
    
    print(f"\n[3단계] 매핑")
    
    slot_assignment = {}
    remaining = list(cluster_centers)
    
    # BUS 매칭
    if bus_x and remaining:
        idx = min(range(len(remaining)), key=lambda i: abs(remaining[i] - bus_x))
        slot_assignment["bus"] = remaining.pop(idx)
        print(f"  ✓ bus: X={slot_assignment['bus']:.1f} (헤더:{bus_x:.1f})")
    
    # EMCY 매칭
    if emg_x and remaining:
        idx = min(range(len(remaining)), key=lambda i: abs(remaining[i] - emg_x))
        slot_assignment["emg"] = remaining.pop(idx)
        print(f"  ✓ emg: X={slot_assignment['emg']:.1f} (헤더:{emg_x:.1f})")
    
    # NO.1, NO.2 할당
    remaining.sort()
    if len(remaining) >= 1:
        slot_assignment["no1"] = remaining[0]
        print(f"  ✓ no1: X={slot_assignment['no1']:.1f}")
        
        # NO.2는 NO.1과 같은 위치 or 다음 클러스터
        if len(remaining) >= 2:
            slot_assignment["no2"] = remaining[1]
            print(f"  ✓ no2: X={slot_assignment['no2']:.1f}")
        else:
            # 클러스터가 하나만 있으면 NO.1과 같은 위치로 설정
            slot_assignment["no2"] = remaining[0]
            print(f"  ✓ no2: X={slot_assignment['no2']:.1f} (no1과 동일 위치)")
    
    # 폴백
    if "bus" not in slot_assignment and len(remaining) >= 1:
        slot_assignment["bus"] = remaining.pop(0)
        print(f"  ✓ bus(폴백): X={slot_assignment['bus']:.1f}")
    if "emg" not in slot_assignment and len(remaining) >= 1:
        slot_assignment["emg"] = remaining.pop(0)
        print(f"  ✓ emg(폴백): X={slot_assignment['emg']:.1f}")
    
    # 4단계: 범위 계산
    if not slot_assignment:
        print("\n[ERROR] PANEL 없음!")
        return {}
    
    print(f"\n[4단계] X축 범위")
    
    sorted_panels = sorted(slot_assignment.items(), key=lambda x: x[1])
    panel_columns = {}
    page_width = page.width
    
    for idx, (slot, cx) in enumerate(sorted_panels):
        if idx > 0:
            x_min = (sorted_panels[idx-1][1] + cx) / 2.0
        else:
            x_min = max(0, cx - 100)
        
        if idx < len(sorted_panels) - 1:
            x_max = (cx + sorted_panels[idx+1][1]) / 2.0
        else:
            x_max = min(page_width, cx + 100)
        
        panel_columns[slot] = (x_min, x_max)
        print(f"  {slot:5s}: {x_min:6.1f} ~ {x_max:6.1f} (중심:{cx:6.1f}, 폭:{x_max-x_min:6.1f})")
    
    print("="*60 + "\n")
    
    return panel_columns


def _extract_acb_type(page, x_min: float, x_max: float, checkboxes: List[Dict[str, float]]) -> str:
    """
    ACB TYPE 추출 v9 - 숫자 크기 우선순위
    1. HGN 숫자가 클수록 우선 (63 > 50 > 32 > 10)
    2. 같은 숫자면 거리 가까운 것 선택
    3. PANEL 범위 100px로 확대
    """
    words = page.extract_words() or []
    text = page.extract_text() or ""
    text_upper = text.upper()
    
    print(f"\n[DEBUG] ACB TYPE 추출 v9 (PANEL X: {x_min:.1f}~{x_max:.1f})")
    
    # HGN 패턴 (매우 유연하게)
    hgn_patterns = [
        re.compile(r'\bHGN\s*(\d{2,3})[A-Z]?\b', re.I),     # HGN63, HGN 63, HGN10A
        re.compile(r'\bHGN[-\s]*(\d{2,3})\b', re.I),        # HGN-63, HGN 63
        re.compile(r'\b([H][G][N])(\d{2,3})\b', re.I),      # HGN63 (공백 없음)
        re.compile(r'\bH\s*G\s*N\s*(\d{2,3})\b', re.I),     # H G N 63
    ]
    
    # STEP 1: TYPE 행 찾기
    type_row_y = None
    for word in words:
        word_text = (word.get("text") or "").strip().upper()
        if "TYPE" in word_text and ("MAKER" in word_text or "ACB" in text_upper):
            type_row_y = (word["top"] + word["bottom"]) / 2.0
            print(f"  [1] TYPE 행: Y={type_row_y:.1f}")
            break
    
    if not type_row_y:
        print(f"  [1] TYPE 행 없음 → Y=150 가정")
        type_row_y = 150
    
    # STEP 1.5: TYPE 행 근처의 모든 단어 출력 (디버깅)
    print(f"  [1.5] TYPE 행 근처 단어 스캔 (Y={type_row_y:.1f} ±50px):")
    nearby_words = [
        w for w in words
        if abs((w["top"] + w["bottom"]) / 2.0 - type_row_y) < 50
    ]
    
    # PANEL 근처의 단어만 출력
    panel_nearby = [
        w for w in nearby_words
        if (x_min - 100) <= ((w["x0"] + w["x1"]) / 2.0) <= (x_max + 100)
    ]
    
    for w in panel_nearby[:20]:  # 최대 20개
        wx = (w["x0"] + w["x1"]) / 2.0
        wy = (w["top"] + w["bottom"]) / 2.0
        word_text = (w.get("text") or "").strip()
        print(f"       '{word_text}' at X={wx:.1f}, Y={wy:.1f}")
    
    # STEP 2: 모든 HGN 텍스트 수집
    all_hgn = []
    
    # 방법 A: 단일 word에서 HGN 패턴 찾기
    for word in words:
        wx = (word["x0"] + word["x1"]) / 2.0
        wy = (word["top"] + word["bottom"]) / 2.0
        word_text = (word.get("text") or "").strip()
        
        for pattern in hgn_patterns:
            match = pattern.search(word_text)
            if match:
                if len(match.groups()) == 2:  # ([H][G][N])(\d{2,3}) 패턴
                    hgn_number = match.group(2)
                else:
                    hgn_number = match.group(1)
                
                hgn_type = f"HGN {hgn_number}"
                all_hgn.append({
                    'text': hgn_type,
                    'x': wx,
                    'y': wy,
                    'dist_from_type': abs(wy - type_row_y),
                    'source': 'single_word'
                })
                break
    
    # 방법 B: 인접한 단어 결합 (HGN과 숫자가 분리된 경우)
    for i, word in enumerate(words):
        word_text = (word.get("text") or "").strip().upper()
        if word_text in ["HGN", "HG", "H"]:
            # 다음 1~3개 단어 확인
            for j in range(i + 1, min(i + 4, len(words))):
                next_word = words[j]
                next_text = (next_word.get("text") or "").strip()
                
                # 숫자인지 확인
                if re.match(r'^\d{2,3}[A-Z]?$', next_text):
                    wx = (word["x0"] + next_word["x1"]) / 2.0  # 중간점
                    wy = (word["top"] + next_word["bottom"]) / 2.0
                    
                    hgn_type = f"HGN {next_text}"
                    all_hgn.append({
                        'text': hgn_type,
                        'x': wx,
                        'y': wy,
                        'dist_from_type': abs(wy - type_row_y),
                        'source': 'combined_words'
                    })
                    break
    
    print(f"  [2] 전체 HGN: {len(all_hgn)}개")
    if all_hgn:
        for h in all_hgn:
            in_range = "✓" if (x_min - 300 <= h['x'] <= x_max + 300) else "✗"
            print(f"      {in_range} {h['text']} at X={h['x']:.1f}, Y={h['y']:.1f} ({h['source']})")
    
    if not all_hgn:
        print(f"  [ERROR] HGN 텍스트를 찾을 수 없습니다!")
        print(f"  → TYPE 행 근처 단어를 확인하세요 (위 [1.5] 참고)")
        return ""
    
    # STEP 3: 체크박스 기반 매칭 (숫자 크기 우선 + 거리 보조)
    if checkboxes:
        print(f"  [3] 전체 체크박스: {len(checkboxes)}개")
        
        # HGN 숫자 추출 함수
        def extract_hgn_number(hgn_text):
            match = re.search(r'(\d+)', hgn_text)
            return int(match.group(1)) if match else 0
        
        # PANEL 영역의 체크박스 필터링 (점진적 확대)
        for margin in [100, 150, 200, 300]:  # 100px부터 시작 (확대)
            panel_checkboxes = [
                cb for cb in checkboxes
                if (x_min - margin) <= cb['x'] <= (x_max + margin)
            ]
            
            if not panel_checkboxes:
                continue
            
            print(f"  [3] PANEL 체크박스: {len(panel_checkboxes)}개 (margin={margin}px)")
            
            # 각 체크박스에 가장 가까운 HGN 찾기
            candidates = []
            
            for cb in panel_checkboxes:
                for hgn in all_hgn:
                    dx = abs(hgn['x'] - cb['x'])
                    dy = abs(hgn['y'] - cb['y'])
                    
                    # Y축 3배 가중치 (같은 행 우선)
                    weighted_dist = ((dx ** 2) + ((dy * 3) ** 2)) ** 0.5
                    
                    # 조건: X축 250px 이내, Y축 30px 이내
                    if dx < 250 and dy < 30:
                        hgn_num = extract_hgn_number(hgn['text'])
                        in_panel_tight = (x_min - 50) <= hgn['x'] <= (x_max + 50)
                        in_panel_wide = (x_min - 100) <= hgn['x'] <= (x_max + 100)
                        
                        candidates.append({
                            'hgn': hgn['text'],
                            'hgn_num': hgn_num,
                            'dist': weighted_dist,
                            'dx': dx,
                            'dy': dy,
                            'hgn_x': hgn['x'],
                            'in_panel_tight': in_panel_tight,
                            'in_panel_wide': in_panel_wide,
                        })
            
            if not candidates:
                continue
            
            # 후보 출력 (디버깅) - 숫자 큰 순으로 정렬
            print(f"      총 {len(candidates)}개 후보 (숫자 큰 순):")
            sorted_candidates = sorted(candidates, key=lambda x: (-x['hgn_num'], x['dist']))
            for c in sorted_candidates[:10]:
                tight = "✓" if c['in_panel_tight'] else "✗"
                wide = "✓" if c['in_panel_wide'] else "✗"
                print(f"      {tight}/{wide} {c['hgn']} (거리={c['dist']:.1f}, dx={c['dx']:.1f}, dy={c['dy']:.1f}, 숫자={c['hgn_num']})")
            
            # 우선순위 1: PANEL 범위 내(±100px) + 가장 큰 숫자
            wide_candidates = [c for c in candidates if c['in_panel_wide']]
            
            if wide_candidates:
                # 숫자가 가장 큰 것들 중에서 거리가 가장 가까운 것
                max_num = max(c['hgn_num'] for c in wide_candidates)
                max_num_candidates = [c for c in wide_candidates if c['hgn_num'] == max_num]
                best = min(max_num_candidates, key=lambda c: c['dist'])
                
                print(f"  [✓] PANEL 내 최대 숫자 선택: {best['hgn']} (거리={best['dist']:.1f}px, 숫자={best['hgn_num']})")
                return best['hgn']
            
            # 우선순위 2: 타이트한 범위(±50px) 후보
            tight_candidates = [c for c in candidates if c['in_panel_tight']]
            
            if tight_candidates:
                max_num = max(c['hgn_num'] for c in tight_candidates)
                max_num_candidates = [c for c in tight_candidates if c['hgn_num'] == max_num]
                best = min(max_num_candidates, key=lambda c: c['dist'])
                
                print(f"  [✓] PANEL 타이트 범위 선택: {best['hgn']} (거리={best['dist']:.1f}px)")
                return best['hgn']
    
    # STEP 4: PANEL 영역 직접 검색 (체크박스 실패 시)
    print(f"  [4] 체크박스 매칭 실패 → PANEL 영역 직접 검색")
    
    # HGN 숫자 추출
    def extract_number(hgn_text):
        match = re.search(r'(\d+)', hgn_text)
        return int(match.group(1)) if match else 0
    
    # PANEL 범위 확대 (200px까지)
    for margin in [100, 150, 200, 300]:
        panel_hgn = [
            h for h in all_hgn
            if (x_min - margin) <= h['x'] <= (x_max + margin)
        ]
        
        if panel_hgn:
            print(f"      margin={margin}px: {len(panel_hgn)}개 HGN")
            
            # 가장 큰 숫자의 HGN 선택 (63 > 50 > 32 > 10)
            best = max(panel_hgn, key=lambda h: extract_number(h['text']))
            best_num = extract_number(best['text'])
            
            print(f"  [✓] PANEL 영역 선택 (최대 숫자): {best['text']} (X={best['x']:.1f}, 숫자={best_num})")
            return best['text']
    
    print(f"  [✗] PANEL 범위 내에 HGN이 없습니다!")
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
                if record["rated_current_in"] and record["ir_percent"]:
                    try:
                        rated_val = float(re.sub(r'[^0-9.]', '', record["rated_current_in"]))
                        ir_pct_val = float(record["ir_percent"])
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

    def _clean_em_name(text: str) -> str:
        cleaned = re.sub(r'\b(ES|CO2|PT|FOAM)-?\d+[A-Z]?\b', ' ', text, flags=re.I)
        cleaned = re.sub(r'\b(' + '|'.join(color_keywords) + r')\b', ' ', cleaned, flags=re.I)
        cleaned = re.sub(r'[\[\]{}<>]+', ' ', cleaned)
        cleaned = cleaned.replace('·', ' ')
        cleaned = re.sub(r'[,:;]+', ' ', cleaned)
        tokens = []
        prev = ""
        for tok in re.split(r'\s+', cleaned):
            tok = tok.strip()
            if not tok:
                continue
            letters = re.sub(r'[^A-Za-z]', '', tok)
            digits = re.sub(r'[^0-9]', '', tok)
            upper_prev = (prev or '').upper()
            # drop digit-only noise unless it is tied to NO./BUS context
            if digits and not letters:
                if upper_prev.startswith('NO') or upper_prev.endswith('BUS'):
                    tokens.append(tok)
                    prev = tok
                    continue
                # 짧은 숫자(예: 10, 90)도 불필요하게 앞에 붙어 나오는 경우가 많으므로 제외
                prev = tok
                continue
            tokens.append(tok)
            prev = tok
        text_joined = re.sub(r'\s+', ' ', ' '.join(tokens)).strip(' -,:;')
        text_joined = re.sub(r'^\d+\s+', '', text_joined)
        # collapse duplicated one-letter fragments (예: "H H")
        text_joined = re.sub(r'\b([A-Z])\s+\1\b', r'\1', text_joined, flags=re.I)
        return text_joined

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

        name_parts: List[str] = []
        code_pos = line_upper.find(found_code)
        if code_pos != -1:
            before_code = line[:code_pos].strip()
            after_code = line[code_pos + len(found_code):].strip()

            for kw in color_keywords:
                before_code = re.sub(r'\b' + kw + r'\b', '', before_code, flags=re.I)
                after_code = re.sub(r'\b' + kw + r'\b', '', after_code, flags=re.I)

            before_code = re.sub(r'[\[\]{}<>:;]+', ' ', before_code)
            after_code = re.sub(r'[\[\]{}<>:;]+', ' ', after_code)
            before_code = re.sub(r'\s+', ' ', before_code).strip()
            after_code = re.sub(r'\s+', ' ', after_code).strip()

            if len(before_code) > 1:
                name_parts.append(before_code)
            if len(after_code) > 1:
                name_parts.append(after_code)

        look_ahead_limit = 3
        for offset in range(1, look_ahead_limit + 1):
            if i + offset >= len(lines):
                break
            next_line = lines[i + offset].strip()
            next_upper = next_line.upper()
            if not next_line:
                continue
            if any(p.search(next_upper) for p in emergency_patterns):
                break
            cleaned_next = re.sub(r'\b(' + '|'.join(color_keywords) + r')\b', '', next_line, flags=re.I)
            cleaned_next = re.sub(r'\s+', ' ', cleaned_next).strip()
            if len(cleaned_next) > 1:
                name_parts.append(cleaned_next)

        name = _clean_em_name(' '.join(name_parts))

        if found_code:
            code_map[found_code] = {"color": color, "name": name}

    return code_map


def _parse_colorplate_table(table: List[List], table_idx: int) -> Dict[str, Dict[str, str]]:
    """테이블에서 CODE, COLOR, NAME 추출"""
    code_map: Dict[str, Dict[str, str]] = {}

    if not table or len(table) < 1:
        return code_map

    emergency_patterns = [
        re.compile(r'\b(ES-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(CO2-?\d+[A-Z]?)\b', re.I),
        re.compile(r'\b(PT-?\d+)\b', re.I),
        re.compile(r'\b(FOAM-?\d+[A-Z]?)\b', re.I),
    ]

    color_keywords = {
        'RED', 'PINK', 'BROWN', 'BLUE', 'GREEN', 'YELLOW',
        'GOLDEN', 'SILVER', 'PURPLE', 'ORANGE', 'WHITE', 'BLACK',
        'LIGHT', 'DARK', 'NAVY', 'LT', 'DK'
    }

    def _clean_em_name(text: str) -> str:
        cleaned = re.sub(r'\b(ES|CO2|PT|FOAM)-?\d+[A-Z]?\b', ' ', text, flags=re.I)
        cleaned = re.sub(r'\b(' + '|'.join(color_keywords) + r')\b', ' ', cleaned, flags=re.I)
        cleaned = re.sub(r'[\[\]{}<>]+', ' ', cleaned)
        cleaned = cleaned.replace('·', ' ')
        cleaned = re.sub(r'[,:;]+', ' ', cleaned)
        tokens = []
        prev = ""
        for tok in re.split(r'\s+', cleaned):
            tok = tok.strip()
            if not tok:
                continue
            letters = re.sub(r'[^A-Za-z]', '', tok)
            digits = re.sub(r'[^0-9]', '', tok)
            upper_prev = (prev or '').upper()
            if digits and not letters:
                if upper_prev.startswith('NO') or upper_prev.endswith('BUS'):
                    tokens.append(tok)
                    prev = tok
                    continue
                prev = tok
                continue
            tokens.append(tok)
            prev = tok
        text_joined = re.sub(r'\s+', ' ', ' '.join(tokens)).strip(' -,:;')
        text_joined = re.sub(r'^\d+\s+', '', text_joined)
        text_joined = re.sub(r'\b([A-Z])\s+\1\b', r'\1', text_joined, flags=re.I)
        return text_joined

    # 헤더 위치 파악 (이름/코드/색상 컬럼이 명시된 경우에만 사용)
    color_col = name_col = code_col = None
    for idx, row in enumerate(table[:5]):
        if not row:
            continue
        upper_cells = [str(c or "").upper() for c in row]
        if any("COLOR" in c or "COLOUR" in c for c in upper_cells) and "CODE" in " ".join(upper_cells):
            for c_idx, raw in enumerate(upper_cells):
                if color_col is None and ("COLOR" in raw or "COLOUR" in raw):
                    color_col = c_idx
                if name_col is None and ("NAME" in raw or "DESC" in raw):
                    name_col = c_idx
                if code_col is None and "CODE" in raw:
                    code_col = c_idx
            break

    pending_code: Optional[str] = None

    for row_idx, row in enumerate(table):
        if not row:
            continue

        found_code = None
        for col_idx, cell in enumerate(row):
            cell_text_raw = str(cell or "").strip()
            cell_text = cell_text_raw.upper()
            for pattern in emergency_patterns:
                match = pattern.search(cell_text)
                if match:
                    found_code = match.group(1).upper()
                    if '-' not in found_code and re.match(r'[A-Z]{2,4}\d+', found_code):
                        found_code = re.sub(r'^([A-Z]+)(\d+)', r'\1-\2', found_code)
                    break
            if found_code:
                break

        if found_code:
            # 헤더가 없으면 현재 위치로 code_col 추론
            if code_col is None:
                try:
                    code_col = row.index(next(cell for cell in row if str(cell or "").upper().find(found_code) != -1))
                except StopIteration:
                    code_col = None

            # 헤더에서 NAME을 못 찾았지만 COLOR, CODE가 둘 다 있으면 사이 컬럼을 이름 후보로 사용
            if name_col is None and color_col is not None and code_col is not None and color_col != code_col:
                between = list(range(min(color_col, code_col) + 1, max(color_col, code_col)))
                if between:
                    sample_row = table[min(row_idx, len(table) - 1)]
                    best_col = None
                    best_len = 0
                    for c_idx in between:
                        if c_idx >= len(sample_row):
                            continue
                        cand = str(sample_row[c_idx] or "").strip()
                        if not cand or cand.upper() in color_keywords:
                            continue
                        if re.fullmatch(r'[0-9./-]+', cand):
                            continue
                        if len(cand) > best_len:
                            best_len = len(cand)
                            best_col = c_idx
                    if best_col is not None:
                        name_col = best_col

            color_val = ""
            name_parts: List[str] = []

            if color_col is not None and color_col < len(row):
                color_val = str(row[color_col] or "").strip().upper()

            if not color_val:
                # 코드 셀 좌/우를 탐색해 색상 키워드 찾기
                for c_idx, cell in enumerate(row):
                    if c_idx == code_col:
                        continue
                    cell_upper = str(cell or "").upper()
                    words = re.split(r'[\s/\\,+-]+', cell_upper)
                    for w in words:
                        if w in color_keywords:
                            color_val = w
                            break
                    if color_val:
                        break

            if name_col is not None and name_col < len(row):
                raw_name = str(row[name_col] or "").strip()
                if raw_name:
                    name_parts.append(raw_name)

                # 색상과 코드 사이에 있는 텍스트를 모두 이름으로 병합 (표에서 NAME 헤더가 없더라도 대응)
                side_a, side_b = (color_col, code_col) if color_col is not None else (name_col, code_col)
                if side_a is not None and side_b is not None:
                    start, end = sorted((side_a, side_b))
                    for extra_idx in range(start + 1, end):
                        if extra_idx in (color_col, code_col, name_col):
                            continue
                        extra = str(row[extra_idx] or "").strip()
                        if extra and not re.fullmatch(r'[0-9./-]+', extra):
                            name_parts.append(extra)
                else:
                    for extra_idx in range(name_col + 1, len(row)):
                        if extra_idx == code_col:
                            continue
                        extra = str(row[extra_idx] or "").strip()
                        if extra and not re.fullmatch(r'[0-9./-]+', extra):
                            name_parts.append(extra)

            name_val = _clean_em_name(" ".join(name_parts))

            if not name_val:
                if name_col is None and color_col is not None and code_col is not None and color_col != code_col:
                    between_parts = []
                    start, end = sorted((color_col, code_col))
                    for c_idx in range(start + 1, end):
                        if c_idx in (color_col, code_col):
                            continue
                        cell_text = str(row[c_idx] or "").strip()
                        cell_upper = cell_text.upper()
                        if not cell_text or cell_upper in color_keywords:
                            continue
                        if re.fullmatch(r'[0-9./-]+', cell_text):
                            continue
                        between_parts.append(cell_text)
                    if between_parts:
                        name_val = _clean_em_name(' '.join(between_parts))

                # 헤더가 없을 때: 코드 셀을 제외한 다른 셀을 모두 이름 후보로 사용
                for c_idx, cell in enumerate(row):
                    if c_idx == code_col:
                        continue
                    cell_text = str(cell or "").strip()
                    cell_upper = cell_text.upper()
                    if not cell_text:
                        continue
                    if cell_upper in color_keywords:
                        continue
                    if re.fullmatch(r'[0-9./-]+', cell_text):
                        continue
                    name_val = name_val + (' ' if name_val else '') + cell_text
                name_val = _clean_em_name(name_val)

            # look ahead to capture continuation rows that hold more name text
            lookahead_idx = row_idx + 1
            while lookahead_idx < len(table):
                next_row = table[lookahead_idx]
                lookahead_idx += 1
                if not next_row:
                    continue

                next_cells_upper = [str(c or "").upper() for c in next_row]
                if any(pat.search(cu) for cu in next_cells_upper for pat in emergency_patterns):
                    break

                extra_parts: List[str] = []
                if name_col is not None and name_col < len(next_row):
                    cand = str(next_row[name_col] or "").strip()
                    if cand:
                        extra_parts.append(cand)

                if not extra_parts:
                    for c_idx, cell in enumerate(next_row):
                        if c_idx in (code_col, color_col):
                            continue
                        cell_text = str(cell or "").strip()
                        cell_upper = cell_text.upper()
                        if not cell_text or cell_upper in color_keywords:
                            continue
                        if re.fullmatch(r'[0-9./-]+', cell_text):
                            continue
                        extra_parts.append(cell_text)

                if extra_parts:
                    extra = _clean_em_name(' '.join(extra_parts))
                    if extra:
                        name_val = (name_val + ' ' if name_val else '') + extra
                else:
                    continue

            name_val = _clean_em_name(name_val)

            code_map[found_code] = {"color": color_val, "name": name_val}
            pending_code = found_code
        else:
            if pending_code and pending_code in code_map and name_col is not None:
                continuation = str(row[name_col] or "").strip() if name_col < len(row) else ""
                if continuation:
                    extra = _clean_em_name(continuation)
                    if extra:
                        if code_map[pending_code]["name"]:
                            code_map[pending_code]["name"] += " " + extra
                        else:
                            code_map[pending_code]["name"] = extra
            elif pending_code and pending_code in code_map and name_col is None:
                # 이름 컬럼을 찾지 못했을 때 이어지는 행도 이름에 병합
                extra_parts = []
                for cell in row:
                    cell_text = str(cell or "").strip()
                    cell_upper = cell_text.upper()
                    if not cell_text:
                        continue
                    if cell_upper in color_keywords:
                        continue
                    if any(pat.search(cell_upper) for pat in emergency_patterns):
                        continue
                    extra_parts.append(cell_text)
                if extra_parts:
                    extra = _clean_em_name(' '.join(extra_parts))
                    if extra:
                        if code_map[pending_code]["name"]:
                            code_map[pending_code]["name"] += " " + extra
                        else:
                            code_map[pending_code]["name"] = extra

    return code_map


def _extract_emergency_circuits(pdf) -> List[Dict[str, str]]:
    """MCCB/FEEDER/GSP 페이지에서 Emergency Circuit 추출"""
    all_circuits = []
    max_scan_pages = min(len(pdf.pages), 80)
    circuit_pattern = re.compile(r'P\d{2}-\d{2,3}-\d{2}-[A-Z]{2}', re.I)

    for page_idx in range(max_scan_pages):
        page = pdf.pages[page_idx]
        text = page.extract_text() or ""
        text_upper = text.upper()

        tables = page.extract_tables() or []
        header_snapshot = ""
        if tables:
            head_rows = []
            for tbl in tables[:2]:
                for r in tbl[:3]:
                    head_rows.append(" ".join(str(c or "") for c in (r or [])[:8]))
            header_snapshot = " ".join(head_rows)

        is_circuit_page = False
        if "NAME PLATE" in text_upper and "MCCB" in text_upper:
            is_circuit_page = True
        elif "SPECIFICATION" in text_upper and "LIST" in text_upper:
            if circuit_pattern.search(text_upper):
                is_circuit_page = True
        elif circuit_pattern.search(text_upper) and "REMARKS" in text_upper:
            if any(kw in text_upper for kw in ['FEEDER', 'PANEL', 'GSP', 'GROUP STARTER']):
                is_circuit_page = True

        if not is_circuit_page and tables:
            joined_header = header_snapshot.upper()
            if circuit_pattern.search(joined_header):
                is_circuit_page = True
            else:
                circuit_hits = 0
                for tbl in tables:
                    for row in tbl:
                        for cell in (row or []):
                            if cell and circuit_pattern.search(str(cell).upper()):
                                circuit_hits += 1
                                if circuit_hits >= 2:
                                    break
                        if circuit_hits >= 2:
                            break
                    if circuit_hits >= 2:
                        break
                if circuit_hits >= 2:
                    is_circuit_page = True

        if not is_circuit_page:
            continue

        panel_name, doc_type = _detect_emergency_panel_info(text + " " + header_snapshot)
        print(f"[DEBUG] Page {page_idx + 1}: {panel_name} ({doc_type})")

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
    emcy_col = None
    control_col = None
    code_cols: List[int] = []

    col_count = max((len(r) for r in table if r), default=0)

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

                if re.search(r"EM'?CY|EMERGENCY", cell_upper):
                    if emcy_col is None:
                        emcy_col = col_idx
                    code_cols.append(col_idx)
                if 'STOP' in cell_upper or 'CONTROL' in cell_upper or 'REMARK' in cell_upper:
                    code_cols.append(col_idx)
                if 'CONTROL' in cell_upper and control_col is None:
                    control_col = col_idx

            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                cell_upper = str(cell).upper().strip()

                if 'NO' in cell_upper and ('CIR' in cell_upper or 'CIRCUIT' in cell_upper):
                    if 'NAME' not in cell_upper and 'TYPE' not in cell_upper:
                        cir_no_col = col_idx

                if 'NAME' in cell_upper or 'LOAD' in cell_upper:
                    if 'BREAKER' not in cell_upper:
                        if cir_name_col is None:
                            cir_name_col = col_idx

            if cir_no_col is not None:
                break

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

    if cir_no_col is None:
        hits = [0] * col_count
        for row in table:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if idx >= col_count:
                    continue
                cell_text = str(cell or '')
                if any(p.search(cell_text) for p in circuit_patterns):
                    hits[idx] += 1
        if any(hits):
            cir_no_col = max(range(len(hits)), key=lambda i: hits[i])

    if remarks_col is None and header_idx is not None and table[header_idx]:
        for col_idx in range(len(table[header_idx]) - 1, -1, -1):
            if str(table[header_idx][col_idx] or '').strip():
                remarks_col = col_idx
                break

    if not code_cols:
        code_hits = [0] * col_count
        for row in table:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if idx >= col_count:
                    continue
                cell_text = str(cell or '')
                if _extract_codes_from_text(cell_text, emergency_code_patterns):
                    code_hits[idx] += 1
        for idx, hit in enumerate(code_hits):
            if hit:
                code_cols.append(idx)

    if remarks_col is not None:
        code_cols.append(remarks_col)
    if control_col is not None:
        code_cols.append(control_col)
    if emcy_col is not None:
        code_cols.append(emcy_col)

    code_cols = sorted(set([c for c in code_cols if c is not None]))

    if cir_name_col is None and cir_no_col is not None:
        name_scores = [0] * col_count
        for row in table:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if idx >= col_count or idx == cir_no_col:
                    continue
                cell_text = str(cell or '').strip()
                if not cell_text:
                    continue
                if re.fullmatch(r'[0-9./-]+', cell_text):
                    continue
                letter_count = len(re.sub(r'[^A-Za-z]', '', cell_text))
                name_scores[idx] += letter_count + len(cell_text) * 0.1
        if any(name_scores):
            cir_name_col = max(range(len(name_scores)), key=lambda i: name_scores[i])

    start_row = header_idx + 1 if header_idx is not None else 0

    if cir_no_col is None or start_row >= len(table):
        return []
    
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
        
        codes_from_remarks: List[str] = []

        def _extend_codes(text: str):
            for code in _extract_codes_from_text(text, emergency_code_patterns):
                if code not in codes_from_remarks:
                    codes_from_remarks.append(code)

        for col_idx in code_cols:
            if col_idx < len(row):
                cell_text = str(row[col_idx] or '').strip()
                if cell_text:
                    _extend_codes(cell_text)

        if not codes_from_remarks:
            # REMARKS/CONTROL 컬럼이 없을 때도 다른 셀에서 CODE를 회수
            for c_idx, cell in enumerate(row):
                if c_idx == cir_no_col:
                    continue
                cell_text = str(cell or '').strip()
                _extend_codes(cell_text)

        if not codes_from_remarks:
            # 테이블 컬럼 감지가 빗나갔을 때, 회로번호를 제외한 전체 행 텍스트에서 재시도
            row_text = ' '.join(str(cell or '') for idx, cell in enumerate(row) if idx != cir_no_col)
            for code in _extract_codes_from_text(row_text, emergency_code_patterns):
                if code not in codes_from_remarks:
                    codes_from_remarks.append(code)

        if not codes_from_remarks:
            continue
        
        circuit_name = ""
        if cir_name_col is not None and cir_name_col < len(row):
            name_cell = str(row[cir_name_col] or '').strip()
            name_cell = name_cell.replace(circuit_no, '').strip()
            name_cell = re.sub(r'\s+', ' ', name_cell).strip()
            if name_cell and len(name_cell) > 1:
                circuit_name = name_cell
        
        if not circuit_name and cir_name_col is not None and row_idx + 1 < len(table):
            next_row = table[row_idx + 1]
            if cir_name_col < len(next_row):
                next_name = str(next_row[cir_name_col] or '').strip()
                has_next_circuit = any(pattern.search(str(next_row[cir_no_col] or '')) for pattern in circuit_patterns) if cir_no_col < len(next_row) else False
                if not has_next_circuit and len(next_name) > 1:
                    circuit_name = next_name

        if not circuit_name:
            # 다른 컬럼의 텍스트도 회수하여 최소한 이름 단서를 확보
            fallback_cells = []
            for idx, cell in enumerate(row):
                if idx in (cir_no_col, remarks_col, emcy_col):
                    continue
                cell_text = str(cell or '').strip()
                if len(cell_text) < 2:
                    continue
                if re.fullmatch(r'[0-9./-]+', cell_text):
                    continue
                fallback_cells.append(cell_text)

            if fallback_cells:
                circuit_name = re.sub(r'\s+', ' ', ' '.join(fallback_cells)).strip()

        for code_from_remarks in codes_from_remarks:
            circuits.append({
                'circuit_no': circuit_no,
                'circuit_name': circuit_name,
                'panel': panel_name,
                'doc_type': doc_type,
                'code': code_from_remarks
            })

    # 동일 코드/회로 조합의 중복을 제거하면서 더 긴 회로명을 보존
    deduped = {}
    for c in circuits:
        key = (c['code'], c['circuit_no'], c['panel'], c['doc_type'])
        if key not in deduped:
            deduped[key] = c
        else:
            if len(c.get('circuit_name', '')) > len(deduped[key].get('circuit_name', '')):
                deduped[key] = c

    return list(deduped.values())


def _group_emergency_by_code(
    circuits: List[Dict[str, str]],
    code_info_map: Dict[str, Dict[str, str]]
) -> List[Dict[str, object]]:
    """CODE별로 Circuit 그룹화 (GSP/MSBD 구분 표시)"""
    code_circuits = {}

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

        circuit_no_val = circuit.get('circuit_no', '')
        panel_val = circuit.get('panel', '')
        if not any(c.get('circuit_no') == circuit_no_val and c.get('panel') == panel_val for c in target_list):
            target_list.append({
                'circuit_no': circuit_no_val,
                'circuit_name': circuit.get('circuit_name', ''),
                'panel': panel_val
            })
    
    result = []
    
    for code in sorted(code_info_map.keys()):
        info = code_info_map.get(code, {})
        color = info.get("color", "")
        name = info.get("name", "")
        
        gsp_circuits = code_circuits.get(code, {}).get('gsp', [])
        msbd_circuits = code_circuits.get(code, {}).get('msbd', [])
        
        all_circuits = gsp_circuits + msbd_circuits
        if (not name or len(name) < 8) and all_circuits:
            longest = max([c.get('circuit_name', '') for c in all_circuits], key=len)
            if len(longest) > len(name):
                name = longest
        
        groups = []
        
        if gsp_circuits:
            gsp_panel_groups = {}
            for circuit in gsp_circuits:
                panel = circuit['panel']
                if panel not in gsp_panel_groups:
                    gsp_panel_groups[panel] = []
                gsp_panel_groups[panel].append(circuit['circuit_no'])
            
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
                msbd_panel_groups[panel].append(circuit['circuit_no'])
            
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