# -*- coding: utf-8 -*-
"""
FAT AutoFill Extractors (v2.1)
- MSBD/GSP PDF에서 표지 & GENERAL SPEC 영역 특정 항목을 안정적으로 추출
- Pure-Python: pdfplumber + regex 기반
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
import os, re
import pdfplumber

# ------------------------
# Progress Hook (non-breaking)
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
        pass
    return "\n".join(out)


# ------------------------
# Helpers

# --- Added helpers: class/ip/tr capacity from NAME PLATE & text ---
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
        # fallback: largest kVA in doc
        nums = [int(x) for x in kva_pat.findall(msbd_text or '')]
        best_val = max(nums) if nums else None
    return f"{best_val} kVA" if best_val else None

# ------------------------
def find_hull_in_bottom_right(pdf_path: str) -> Optional[str]:
    """Read page0 bottom-right quadrant to find SN#### explicitly on the cover footer area."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages: 
                return None
            p0 = pdf.pages[0]
            w, h = p0.width, p0.height
            # conservative bottom-right box (works for most title blocks)
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
    """Parse CLASS table lines like:
       SN2670/71/72/73/74/75  ABS
       SN2676~2681            NK
       SN2682/83/84/85        LR
    Return mapping {'SN2670':'ABS', ...} (first match wins)."""
    result: Dict[str, str] = {}
    lines = [ln.strip() for ln in (p0 or "").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if "SN" not in ln.upper():
            continue
        # find class token on this or next line
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
        # ~ range
        mrg = re.search(r'~\s*(\d{4})', tail)
        if mrg:
            end = int(mrg.group(1))
            lo, hi = sorted((base, end))
            for n in range(lo, hi+1):
                nums.add(n)
        # / list
        for tok in re.findall(r'/\s*(\d{2,4})', tail):
            n = int(tok) if len(tok)==4 else int(str(base)[:2]+tok)
            nums.add(n)
        for n in sorted(nums):
            result.setdefault(f"SN{n}", cls)  # first match wins
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
    for idx, page in enumerate(pdf.pages):
        text_u = (page.extract_text() or "").upper()
        if "ACB" not in text_u or "SETTING" not in text_u:
            continue
        if re.search(r"TABL[EI]|TABEL|TANLE|TABLE", text_u):
            return idx, page
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


def extract_acb_setting_panels(msbd_pdf: str) -> List[Dict[str, str]]:
    base_records = _blank_panel_records()
    if not (msbd_pdf and os.path.exists(msbd_pdf)):
        return base_records
    try:
        with pdfplumber.open(msbd_pdf) as pdf:
            _, page = _find_acb_setting_page(pdf)
            if page is None:
                return base_records
            words = page.extract_words() or []
            slot_ranges = _slot_ranges_from_words(words)
            row_positions = _row_positions_from_words(words)
            record_map = {rec["slot"]: rec for rec in base_records}
            for spec in PANEL_SLOT_SPECS:
                record = record_map.get(spec["slot"])
                bounds = slot_ranges.get(spec["slot"])
                if not record or not bounds:
                    continue
                x0, x1 = bounds
                # ACB TYPE
                y = row_positions.get("acb_type")
                if y is not None:
                    texts = [
                        (w.get("text") or "").strip().upper()
                        for w in _words_in_band(words, x0, x1, y, band=18.0)
                        if (w.get("text") or "").strip()
                    ]
                    picks = [t for t in texts if re.match(r"[A-Z]{2,}[0-9][A-Z0-9\-]*$", t)]
                    if picks:
                        record["acb_type"] = picks[0]

                # OCR TYPE
                y = row_positions.get("ocr_type")
                if y is not None:
                    texts = [
                        (w.get("text") or "").strip().upper()
                        for w in _words_in_band(words, x0, x1, y, band=18.0)
                        if (w.get("text") or "").strip()
                    ]
                    picks = [t for t in texts if re.match(r"[A-Z]{2,}[0-9]{0,3}[A-Z]?$", t)]
                    if picks:
                        record["ocr_type"] = picks[0]

                # AMPERE FRAME
                y = row_positions.get("ampere_frame")
                if y is not None:
                    nums = [n for n in _numbers_from_words(_words_in_band(words, x0, x1, y, band=20.0)) if n >= 400]
                    if nums:
                        record["ampere_frame"] = str(max(nums))

                # RATED CURRENT IN
                y = row_positions.get("rated_current_in")
                if y is not None:
                    nums = _numbers_from_words(_words_in_band(words, x0, x1, y, band=20.0))
                    if nums:
                        record["rated_current_in"] = str(max(nums))

                # IR (%)
                y = row_positions.get("ir_percent")
                if y is not None:
                    nums = [
                        n
                        for n in _numbers_from_words(_words_in_band(words, x0, x1, y, band=20.0))
                        if 10 <= n <= 150
                    ]
                    if nums:
                        record["ir_percent"] = str(max(nums))

                # IR (A)
                y = row_positions.get("ir_amps")
                if y is not None:
                    nums = [n for n in _numbers_from_words(_words_in_band(words, x0, x1, y, band=20.0)) if n >= 100]
                    if nums:
                        record["ir_amps"] = str(max(nums))
        return base_records
    except Exception:
        return base_records

# ------------------------
# Cover Parser
# ------------------------
def parse_cover_info(pdf_path: str) -> Dict[str, object]:
    p0 = read_page_text(pdf_path, 0)
    P0U = p0.upper()
    data: Dict[str, object] = {"fields": {}, "hull_to_class": {}, "titles": []}
    fields: Dict[str, str] = {}

    # Common
    if "SAMSUNG HEAVY INDUSTRIES" in P0U:
        fields["customer"] = "SAMSUNG HEAVY INDUSTRIES"
    hv = find_hull_in_bottom_right(pdf_path)
    if not hv:
        m = re.search(r'\bSN\s*(\d{4})\b', p0, flags=re.IGNORECASE) or re.search(r'\bSN\s*(\d{4})\b', os.path.basename(pdf_path), flags=re.IGNORECASE)
        hv = "SN"+m.group(1) if m else None
    if hv:
        fields["hull_no"] = hv

    # Item title
    if "GROUP STARTER PANEL" in P0U or "GSP" in P0U:
        data["titles"].append("GROUP STARTER PANEL")
    if "SWITCHBOARD" in P0U:
        data["titles"].append("AC440V LV SWITCHBOARD")
    if data["titles"]:
        fields["item"] = " & ".join(dict.fromkeys(data["titles"]))  # dedup while preserving order

    # DWG No (best-effort on cover)
    m = re.search(r'(?:DWG|DRAWING)\s*NO\.?[\s:\-]*([A-Z]{2,5}SE-\d{4,6})', p0, flags=re.IGNORECASE)
    if m:
        dwg = m.group(1).upper()
        name = os.path.basename(pdf_path).upper()
        if "GSP" in name:
            fields["gsp_dwg_no"] = dwg
        else:
            fields["ms_dwg_no"] = dwg
    else:
        # DWG fallback across full doc
        T_all = read_text(pdf_path, max_pages=6)
        m2 = re.search(r'([A-Z]{2,5}SE-\d{4,6})', T_all)
        if m2:
            dwg = m2.group(1).upper()
            name = os.path.basename(pdf_path).upper()
            if "GSP" in name:
                fields.setdefault("gsp_dwg_no", dwg)
            else:
                fields.setdefault("ms_dwg_no", dwg)

    # REV (cover first → filename fallback)
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

    # Owner / Kind of Vessel (best-effort)
    m = re.search(r'\bOWNER\b\s*[:\-]?\s*([A-Z0-9 ]{2,})', p0, flags=re.IGNORECASE)
    if m:
        fields["owner"] = clean_num(m.group(1))
    else:
        fields.setdefault("owner", "[직접 입력]")
    if "CONTAINER VESSEL" in P0U:
        fields["Kind_of_Vessel"] = "16,500TEU CONTAINER VESSEL"

    # Class mapping from CLASS table
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

    msbd_text = T  # raw text
    gsp_text = T  # if needed, same source; in UI we pass GSP separately when available


    # Fault Level block
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
    # Fallback scan for rms/peak anywhere
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

    # OUTSIDE Munsell
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

    # GSP quantity
    q = re.search(r'QUANT(?:ITY|\.)\s*[:\-]?\s*(\d+)\s*SET\s*(?:\(\s*(\d+)\s*PNL\s*\))?', T, flags=re.IGNORECASE) \
        or re.search(r"Q[’'\s]?TY\s*[:\-]?\s*(\d+)\s*SET(?:\s*\(\s*(\d+)\s*PNL\s*\))?", T, flags=re.IGNORECASE)
    if q:
        set_n, pnl_n = q.group(1), q.group(2)
        out["gsp_quantity"] = f"{set_n} SET" + (f" ( {pnl_n} PNL )" if pnl_n else "")

    # MSBD quantity (from general spec / cover summary)
    if "GSP" not in os.path.basename(pdf_path).upper():
        q2 = re.search(r'QUANT(?:ITY|\.)\s*[:\-]?\s*(\d+)\s*SET\s*(?:\(\s*(\d+)\s*PNL\s*\))?', T, flags=re.IGNORECASE)
        if q2:
            set_n, pnl_n = q2.group(1), q2.group(2)
            out["ms_quantity"] = f"{set_n} SET" + (f" ( {pnl_n} PNL )" if pnl_n else "")

    # Basic numeric specs (best-effort)
    # Current and Main Bus
    m = re.search(r'RATED\s*CURRENT.*?(\d{3,6})\s*A', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_current", m.group(1) + "A")
    m = re.search(r'MAIN\s*BUS.*?(\d{3,6})\s*A', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_main_bus", m.group(1) + "A")

    # TR capacity
    m = re.search(r'(?:TRANSFORMER\s*RATING|TR\s*CAP(?:ACITY)?)\D{0,40}(\d{3,5})\s*kVA', U, flags=re.IGNORECASE)
    if m: out.setdefault("ms_tr_capacity", f"{m.group(1)} kVA")

    # Rating
    if "AC 440V" in U and "60HZ" in U and ("3W" in U or "3Φ" in U or "3PH" in U):
        out.setdefault("ms_rating", "AC 440V 60Hz 3Φ 3W")

    # IP
    m = re.search(r'\bIP\s*2[12]\b', U)
    if m: out.setdefault("ms_ip", m.group(0).replace(" ", ""))

    # fallback: if GSP doc but gsp_munsell_code missing, copy ms_munsell_code
    if "GSP" in os.path.basename(pdf_path).upper() and "gsp_munsell_code" not in out and "ms_munsell_code" in out:
        out["gsp_munsell_code"] = out["ms_munsell_code"]
    if ip_checked:
        if 'GSP' in os.path.basename(pdf_path).upper():
            out['gsp_ip'] = ip_checked
        else:
            out['ms_ip'] = ip_checked
    # === post-processing from NAME PLATE/GENERAL SPEC ===
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
    # class from NAME PLATE (OTHER)
    try:
        hull = out.get('hull_no') or ''
        cls_guess = guess_class_from_nameplate_other(msbd_text, hull)
        if cls_guess:
            out['class'] = cls_guess
    except Exception:
        pass
    return out


# ---- Checkbox-based IP detection ----
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
                # Text-glyph fallback (■/☑ before IPxx)
                if re.search(r"(■|☑|●)\s*IP\s*22", txt): return "IP22"
                if re.search(r"(■|☑|●)\s*IP\s*44", txt): return "IP44"
                words = page.extract_words(use_text_flow=True) or []
                rects = page.rects or []
                # map candidates
                ips = [w for w in words if w.get("text","").upper().replace(" ","") in ("IP22","IP44","IP23","IP54","IP55")]
                for w in ips:
                    cy = (w["top"] + w["bottom"]) / 2.0
                    left_limit = w["x0"] - 4
                    right_limit = w["x0"] - 40
                    if right_limit > left_limit:
                        left_limit, right_limit = right_limit, left_limit
                    # find small filled rects just left of the label
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

    code_pat = re.compile(r'P3[12]-\d{3}-\d{2}-PN', re.I)
    header_pat = re.compile(
        r'^(CIRCUIT\s+NAME|CIR\.?\s*NO|TYPE|MAT\'|RATING|MOTOR|SELECTING|SWITCH|LOAD|CONTROL|AMMETER|VOLTMETER|FREQUENCY|REMARK|NOTE|RESULT|STATUS|TEST|FRAME|CAPACITY|WIRING|WIRE|PANEL|POWER|MODEL|SPEC|SIZE|DATE|UNIT)',
        re.I,
    )

    def circuit_sort_key(code: str) -> Tuple[int, int, int, str]:
        pattern = re.compile(r'P(\d+)-(\d+)-(\d+)-([A-Z]+)', re.I)
        m = pattern.match(code or "")
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4).upper())
        return (9999, 9999, 9999, (code or "").upper())

    def clean(text: str) -> str:
        text = re.sub(r'\s+', ' ', text or '')
        return text.strip(" :-·•")

    def group_words(words: List[Dict[str, Any]], y_tol: float = 2.5) -> List[List[Dict[str, Any]]]:
        lines: List[Dict[str, Any]] = []
        for w in sorted(words, key=lambda w: (w.get("top", 0), w.get("x0", 0))):
            mid = (w.get("top", 0) + w.get("bottom", 0)) / 2.0
            if not lines or abs(lines[-1]["mid"] - mid) > y_tol:
                lines.append({"mid": mid, "words": [w]})
            else:
                bucket = lines[-1]
                prev = len(bucket["words"])
                bucket["words"].append(w)
                bucket["mid"] = (bucket["mid"] * prev + mid) / (prev + 1)
        return [sorted(item["words"], key=lambda w: w.get("x0", 0)) for item in lines if item.get("words")]

    def detect_name_column_bounds(lines: List[List[Dict[str, Any]]]) -> Optional[Tuple[float, float]]:
        """Return (x_start, x_end) bounds for CIRCUIT NAME column."""
        for words in lines[:60]:
            tokens = [(w.get("text", "") or "") for w in words]
            joined = " ".join(t.upper() for t in tokens)
            if "CIRCUIT" not in joined or "NAME" not in joined:
                continue
            start = None
            end = None
            for idx, w in enumerate(words):
                token = (w.get("text", "") or "").upper()
                if "NAME" in token and start is None:
                    start = w.get("x0", 0) - 2
                    # look for the next header word (e.g., ELASTIC, RATING, INITIAL, USE)
                    for nxt in words[idx + 1 :]:
                        nxt_token = (nxt.get("text", "") or "").upper()
                        if header_pat.match(nxt_token):
                            end = nxt.get("x0", 0) - 2
                            break
                        if re.search(r"ELASTIC|RATING|INITIAL|USED|USE|CONTROL|CURRENT", nxt_token):
                            end = nxt.get("x0", 0) - 2
                            break
                    if end is None:
                        # fallback to a generous width if we cannot locate the next column header
                        end = start + 220
                    break
            if start is not None:
                return (start, end if end is not None else start + 220)
        return None

    def detect_panel_label(text: str) -> Optional[str]:
        if not text:
            return None
        match_no1 = re.search(r'NO\.?\s*1\s*(?:GROUP\s+STARTER\s+PANEL|GSP)', text)
        match_no2 = re.search(r'NO\.?\s*2\s*(?:GROUP\s+STARTER\s+PANEL|GSP)', text)
        if match_no1 and match_no2:
            return "No.1 GROUP STARTER PANEL" if match_no1.start() <= match_no2.start() else "No.2 GROUP STARTER PANEL"
        if match_no1:
            return "No.1 GROUP STARTER PANEL"
        if match_no2:
            return "No.2 GROUP STARTER PANEL"
        return None

    def finalize_pending(pending: Optional[Dict[str, Any]], store: Dict[str, List[Dict[str, Any]]]):
        if not pending:
            return
        label = pending.get("label")
        if not label:
            return
        name = clean(" ".join(pending.get("name_parts", [])))
        if name:
            store[label].append(
                {
                    "code": pending["code"],
                    "name": name,
                    "order": pending.get("order", 0),
                }
            )

    panel_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    panel_order: Dict[str, int] = defaultdict(int)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    continue
                upper = text.upper()
                if "NAME PLATE" not in upper or "GSP" not in upper:
                    continue
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                if not words:
                    continue
                lines = group_words(words)
                if not lines:
                    continue
                name_bounds = detect_name_column_bounds(lines)
                name_col = name_bounds[0] if name_bounds else None
                name_col_end = name_bounds[1] if name_bounds else None

                pending: Optional[Dict[str, Any]] = None
                current_label: Optional[str] = None

                for idx, line_words in enumerate(lines):
                    line_text = clean(" ".join(w.get("text", "") for w in line_words))
                    if not line_text:
                        finalize_pending(pending, panel_rows)
                        pending = None
                        continue
                    upper_line = line_text.upper()
                    panel_label = detect_panel_label(upper_line)
                    if panel_label:
                        finalize_pending(pending, panel_rows)
                        pending = None
                        current_label = panel_label
                        continue
                    if upper_line.startswith("NAME PLATE") or header_pat.match(upper_line):
                        finalize_pending(pending, panel_rows)
                        pending = None
                        continue
                    match = code_pat.search(upper_line)
                    if match:
                        finalize_pending(pending, panel_rows)
                        if not current_label:
                            continue
                        code = match.group(0).upper()
                        code_norm = re.sub(r'[^A-Z0-9]+', '', code)
                        code_word = None
                        for w in line_words:
                            word_norm = re.sub(r'[^A-Z0-9]+', '', (w.get("text", "") or '').upper())
                            if code_norm and code_norm in word_norm:
                                code_word = w
                                break
                        code_x0 = code_word.get("x0", 0) if code_word else None
                        code_x1 = code_word.get("x1", 0) if code_word else None

                        # Prefer header-derived name bounds. If unavailable, capture the text
                        # to the RIGHT of the circuit code (standard GSP layout) and only fall
                        # back to the left when no right-side words exist.
                        name_words: List[Dict[str, Any]]
                        name_x0 = name_col if name_col is not None else None
                        name_x1 = name_col_end

                        if name_col is not None:
                            name_words = [
                                w
                                for w in line_words
                                if w.get("x0", 0) >= name_col - 1
                                and (name_col_end is None or w.get("x1", 0) <= name_col_end + 2)
                            ]
                        else:
                            # GSP layout lists CIRCUIT NAME to the RIGHT of CIRCUIT NO. Prefer
                            # right-side words; use the left only if the right side is empty.
                            left_words = [
                                w for w in line_words if code_x0 is None or w.get("x1", 0) <= code_x0 - 1
                            ]
                            right_words = [
                                w for w in line_words if code_x1 is None or w.get("x0", 0) >= code_x1 + 1
                            ]
                            name_words = right_words if right_words else left_words
                            if name_words:
                                name_x0 = min((w.get("x0", 0) for w in name_words), default=name_x0)
                                name_x1 = max((w.get("x1", 0) for w in name_words), default=name_x1)
                            else:
                                # fallback: treat everything after the code as the name region
                                fallback_start = (code_x1 or code_x0 or 0) + 4
                                name_words = [w for w in line_words if w.get("x0", 0) >= fallback_start - 1]
                                name_x0 = fallback_start

                        if name_col is not None and not name_words:
                            for look_ahead in lines[idx + 1 :]:
                                look_text = clean(" ".join(w.get("text", "") for w in look_ahead))
                                look_upper = look_text.upper()
                                if not look_text:
                                    continue
                                if detect_panel_label(look_upper):
                                    break
                                if look_upper.startswith("NAME PLATE") or header_pat.match(look_upper):
                                    break
                                if code_pat.search(look_upper):
                                    break
                                column_words = [
                                    w
                                    for w in look_ahead
                                    if w.get("x0", 0) >= name_col - 1
                                    and (name_col_end is None or w.get("x1", 0) <= name_col_end + 2)
                                ]
                                if column_words:
                                    name_words = column_words
                                    name_x0 = min((w.get("x0", 0) for w in column_words), default=name_x0)
                                    name_x1 = max((w.get("x1", 0) for w in column_words), default=name_x1)
                                    break

                        name_part = clean(" ".join(w.get("text", "") for w in name_words))
                        pending = {
                            "code": code,
                            "name_parts": [],
                            "order": panel_order[current_label],
                            "name_x0": name_x0 if name_x0 is not None else 0,
                            "name_x1": name_x1,
                            "label": current_label,
                        }
                        panel_order[current_label] += 1
                        if name_part and not header_pat.match(name_part.upper()):
                            pending["name_parts"].append(name_part)
                        continue
                    if pending:
                        name_x0 = pending.get("name_x0", 0)
                        name_x1 = pending.get("name_x1")
                        min_x = min((w.get("x0", 0) for w in line_words), default=0)
                        max_x = max((w.get("x1", 0) for w in line_words), default=0)
                        within_left = min_x >= name_x0 - 4
                        within_right = True if name_x1 is None else max_x <= name_x1 + 4
                        if within_left and within_right:
                            part = clean(" ".join(w.get("text", "") for w in line_words))
                            if part and not header_pat.match(part.upper()):
                                pending["name_parts"].append(part)
                                continue
                        finalize_pending(pending, panel_rows)
                        pending = None

                finalize_pending(pending, panel_rows)
    except Exception:
        return []

    results: List[Dict[str, object]] = []
    for num, label in ((1, "No.1 GROUP STARTER PANEL"), (2, "No.2 GROUP STARTER PANEL")):
        rows = panel_rows.get(label)
        if not rows:
            continue
        unique: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            code = (row.get("code") or "").upper()
            name = (row.get("name") or "").strip()
            if not code or not name:
                continue
            if code not in unique or len(name) > len(unique[code]["name"]):
                unique[code] = {
                    "code": code,
                    "name": name,
                    "order": row.get("order", 0),
                }
        if not unique:
            continue
        sorted_rows = sorted(unique.values(), key=lambda r: (circuit_sort_key(r.get("code", "")), r.get("order", 0)))
        content = "\n".join(f"{row['code']} {row['name']}" for row in sorted_rows).strip()
        results.append(
            {
                "panel": label,
                "placeholder": f"gsp_function_no{num}",
                "content": content,
                "rows": sorted_rows,
            }
        )

    return results


def parse_emergency_stop(pdf_path: str) -> List[Dict[str, object]]:
    """Parse EMERGENCY STOP TEST table including COLOR and panel groups."""
    raw = read_text(pdf_path, max_pages=80)
    if not raw:
        return []
    text = raw.replace("\r", "\n").replace("\x0c", "\n")
    upper = text.upper()
    code_pattern = re.compile(r'\b(?:ES|CO2|FOAM|PT)-\d+[A-Z]?\b')
    matches = list(code_pattern.finditer(upper))
    if not matches:
        return []

    def clean_line(line: str) -> str:
        line = re.sub(r'\s+', ' ', line)
        return line.strip(" :-·•.\t")

    records: List[Dict[str, object]] = []
    for idx, match in enumerate(matches):
        code = match.group(0)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block = text[start:end]
        remainder = block[len(code):]
        remainder = remainder.lstrip()
        color = ""
        if remainder.startswith("("):
            close_idx = remainder.find(")")
            if close_idx != -1:
                color = remainder[1:close_idx].strip()
                remainder = remainder[close_idx + 1 :].lstrip()

        lines = remainder.splitlines()
        name_lines: List[str] = []
        consumed = 0
        for line in lines:
            cleaned = clean_line(line)
            consumed += 1
            if not cleaned:
                continue
            if cleaned.upper().startswith("SATISFACTORY"):
                continue
            if cleaned.startswith("[") or code_pattern.search(cleaned.upper()):
                consumed -= 1
                break
            if re.search(r'P\d{2}-\d{3}-\d{2}-', cleaned.upper()):
                consumed -= 1
                break
            name_lines.append(cleaned)
            if "[" in line:
                break
        if consumed < 0:
            consumed = 0
        name = " ".join(name_lines).strip()
        remaining_text = "\n".join(lines[consumed:])

        groups: List[Dict[str, object]] = []
        panel_matches = list(re.finditer(r'\[([^\]]{2,120})\]', remaining_text))
        if panel_matches:
            for g_idx, gm in enumerate(panel_matches):
                header = gm.group(1).replace('*', '').strip()
                seg_start = gm.end()
                seg_end = panel_matches[g_idx + 1].start() if g_idx + 1 < len(panel_matches) else len(remaining_text)
                segment = remaining_text[seg_start:seg_end]
                circuits = _parse_circuit_list(segment)
                groups.append({"panel_header": header, "circuits": circuits})
        else:
            # fallback: scan lines for headers starting with NO.
            pending_header = None
            buffer_text: List[str] = []
            for line in remaining_text.splitlines():
                cleaned = clean_line(line)
                if not cleaned:
                    continue
                if cleaned.startswith("NO.") or cleaned.startswith("№"):
                    if pending_header:
                        circuits = _parse_circuit_list("\n".join(buffer_text))
                        groups.append({"panel_header": pending_header, "circuits": circuits})
                    pending_header = cleaned
                    buffer_text = []
                    continue
                buffer_text.append(cleaned)
            if pending_header:
                circuits = _parse_circuit_list("\n".join(buffer_text))
                groups.append({"panel_header": pending_header, "circuits": circuits})

        records.append({
            "code": code,
            "color": color,
            "name": name,
            "groups": groups,
        })

    merged: Dict[str, Dict[str, object]] = {}
    for rec in records:
        code = rec.get("code", "")
        if code in merged:
            existing = merged[code]
            if not existing.get("name") and rec.get("name"):
                existing["name"] = rec.get("name")
            if not existing.get("color") and rec.get("color"):
                existing["color"] = rec.get("color")
            existing_groups = existing.setdefault("groups", [])
            for g in rec.get("groups", []):
                if g not in existing_groups:
                    existing_groups.append(g)
        else:
            merged[code] = rec
    return list(merged.values())


def _parse_circuit_list(chunk: str) -> List[str]:
    tokens = re.findall(r'P\d{2}-\d{3}-\d{2}-[A-Z]{2}', chunk.upper())
    if tokens:
        seen: List[str] = []
        for tok in tokens:
            if tok not in seen:
                seen.append(tok)
        return seen
    parts: List[str] = []
    for line in chunk.splitlines():
        for part in re.split(r'[\s,;\u3001]+', line):
            val = part.strip()
            if val:
                parts.append(val)
    return parts


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
# ===== Overwrite with checkbox-aware IP extractor =====
def extract_ip_grade(pdf_path: str) -> str:  # type: ignore[override]
    """Detect IP grade from GENERAL SPEC via checkbox detection."""
    try:
        import pdfplumber, re
        found = None
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text_u = (page.extract_text() or "").upper()
                if "GENERAL" not in text_u or "SPEC" not in text_u:
                    continue
                words = page.extract_words() or []
                ips = []
                for w in words:
                    m = re.match(r"IP[-\s]?([0-9]{2})\b", w["text"].upper())
                    if m:
                        ips.append((int(m.group(1)), w))
                if not ips:
                    continue
                chars = page.chars or []
                marks = [c for c in chars if c.get("text") in ("■","●","◼","▪","∙") ]
                rects = [r for r in (page.rects or []) if r.get("non_stroking_color") is not None and 2.0 <= r.get("width",0) <= 12.0 and 2.0 <= r.get("height",0) <= 12.0]
                def has_mark_near(w):
                    x0,x1,y0,y1 = w["x0"], w["x1"], w["top"], w["bottom"]
                    mx0, mx1, my0, my1 = x0-40, x0-4, y0-6, y1+6
                    for c in marks:
                        if mx0 <= c["x0"] <= mx1 and my0 <= c["top"] <= my1:
                            return True
                    for r in rects:
                        cx = (r["x0"] + r["x1"])/2.0
                        cy = (r["top"] + r["bottom"])/2.0
                        if mx0 <= cx <= mx1 and my0 <= cy <= my1:
                            return True
                    return False
                for val, w in ips:
                    if has_mark_near(w):
                        found = val
                        break
                if found is None:
                    ips.sort(key=lambda t: (t[1]["x0"], t[1]["top"]))
                    found = ips[0][0]
                break
        return f"IP{int(found):02d}" if found is not None else ""
    except Exception:
        import re
        txt = extract_text_fast(pdf_path).upper()
        m = re.search(r"\bIP\s*([0-9]{2})\b", txt)
        return f"IP{m.group(1)}" if m else ""

# ==================== Patch: robust IP extractor & panel table reader (fix10) ====================

def extract_ip_grade(pdf_path: str) -> str:  # type: ignore[override]
    """
    Robustly detect IP grade:
    - Scan all pages, prefer page containing "GENERAL" & "SPEC" (but not required)
    - Detect check mark to LEFT or RIGHT of IPxx (■ glyphs or filled small rects)
    - Fallback to first/left-most IP token on preferred page
    - Normalize to "IP{nn}"
    """
    import re
    try:
        import pdfplumber
    except Exception:
        txt = extract_text_fast(pdf_path).upper()
        m = re.search(r"\bIP\s*([0-9]{2})\b", txt)
        return f"IP{m.group(1)}" if m else ""

    def ip_tokens(page):
        words = page.extract_words() or []
        toks = []
        for w in words:
            t = w.get("text","").upper()
            m = re.match(r"IP[-\s]?([0-9]{2})\b", t)
            if m:
                toks.append((int(m.group(1)), w))
        return toks

    with pdfplumber.open(pdf_path) as pdf:
        pages = list(pdf.pages)
        scored = []
        for i, pg in enumerate(pages):
            text_u = (pg.extract_text() or "").upper()
            score = 0
            if "GENERAL" in text_u: score += 2
            if "SPEC" in text_u: score += 2
            score += len(ip_tokens(pg))
            scored.append((score, i, pg))
        scored.sort(reverse=True)
        chosen = [pg for score, i, pg in scored if score > 0] or [pages[0]]

        def has_mark_near(page, w):
            x0,x1,y0,y1 = w["x0"], w["x1"], w["top"], w["bottom"]
            # left window and right window
            windows = [(x0-40, x0-4, y0-8, y1+8), (x1+4, x1+40, y0-8, y1+8)]
            chars = page.chars or []
            rects = [r for r in (page.rects or []) if r.get("non_stroking_color") is not None and 1.5 <= r.get("width",0) <= 14.0 and 1.5 <= r.get("height",0) <= 14.0]
            for (mx0, mx1, my0, my1) in windows:
                for c in chars:
                    if c.get("text") in ("■","●","◼","▪","∙") and mx0 <= c.get("x0",0) <= mx1 and my0 <= c.get("top",0) <= my1:
                        return True
                for r in rects:
                    cx = (r["x0"]+r["x1"])/2.0; cy = (r["top"]+r["bottom"])/2.0
                    if mx0 <= cx <= mx1 and my0 <= cy <= my1:
                        return True
            return False

        for pg in chosen:
            toks = ip_tokens(pg)
            if not toks:
                continue
            for val, w in toks:
                if has_mark_near(pg, w):
                    return f"IP{val:02d}"
            toks.sort(key=lambda t: (t[1]["x0"], t[1]["top"]))
            return f"IP{toks[0][0]:02d}"
    return ""



# ---------------------------

extract_panel_info_from_msbd = extract_acb_setting_panels
