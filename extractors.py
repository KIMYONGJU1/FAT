# -*- coding: utf-8 -*-
"""
FAT AutoFill Extractors (v2.0)
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
    U_ms = read_text(msbd_pdf, max_pages=50).upper()
    _notify_progress(30, "PANELS:MSBD")
    U_gs = read_text(gsp_pdf, max_pages=50).upper()
    _notify_progress(50, "PANELS:GSP")
    U = U_ms + "\n" + U_gs

    panels: List[Dict[str, object]] = []
    names: List[str] = []
    for m in re.finditer(r"NO\.?\s*(1|2)\s*INCOMING", U):
        n=m.group(1); nm=f"No.{n} INCOMING"
        if nm not in names: names.append(nm)
    if re.search(r"BUS\s*-?\s*TIE\s*PANEL", U): names.append("BUS-TIE")
    if re.search(r"EM'?CY\s*(SWBD|SWITCHBOARD)", U) or re.search(r"LINK\s*TO\s*ESBD", U): names.append("EMERGENCY PANEL")

    def near(name, pat):
        for m in re.finditer(re.escape(name.upper()), U):
            s=max(0,m.start()-1200); e=min(len(U),m.end()+1200)
            chunk = U[s:e]
            mm = re.search(pat, chunk, re.I)
            if mm: return mm.group(1)
        return None

    for idx, nm in enumerate(names, start=1):
        _notify_progress(50 + int(10*idx/max(1,len(names))), f"PANEL {nm}")
        p = {
            "panel": nm,
            "acb_type": (near(nm, r"(?:AIR\s+CIRCUIT\s+BREAKER\s+TYPE|ACB\s*(?:TYPE|MODEL))\s*[:=\-]?\s*([A-Z0-9\-]+)") or ""),
            "ocr_type": (near(nm, r"(?:OVERCURRENT\s+TRIP\s+TYPE|OCR\s*(?:TYPE)?|TRIP\s*UNIT)\s*[:=\-]?\s*([A-Z0-9\-]+)") or ""),
            "ampere_frame": (near(nm, r"(?:AF|AMPERE\s*FRAME|MCR)\s*[:=\-]?\s*(\d{3,5})") or ""),
            "rated_current_in": (near(nm, r"(?:RATED\s+CURRENT\s*\(?I[NO]\)?|IN\s*\(A\)|IN\s*[:=])\s*[:=]?\s*([\d,]+)") or ""),
            "ip": (lambda x: (f"IP{x}" if x and not str(x).upper().startswith("IP") else x))(near(nm, r"\bIP[-\s]?([0-9]{2})\b")),
            "paint": near(nm, r"(?:MUNSELL|PAINT)\s*[:=\-]?\s*([0-9A-Z\s/\-]+)"),
            "ir_percent": near(nm, r"\bIR\s*[:=]\s*(\d{2,3})\s*\%"),
            "ir_amps": near(nm, r"\bIR\s*\(A\)\s*[:=]\s*(\d{3,5})"),
            "isd_percent": near(nm, r"\bISD\s*[:=]\s*(\d{2,3})\s*\%"),
            "isd_amps": near(nm, r"\bISD\s*\(A\)\s*[:=]\s*(\d{3,5})"),
            "setting_time_s": near(nm, r"TIME\s*\(SEC\)\s*(?:SET|=)\s*(\d{1,3})"),
            "setting_time_ms": near(nm, r"TIME\s*\(MSEC\)\s*(?:SET|=)\s*(\d{2,4})"),
            "remarks": "",
            "circuits": []
        }
        panels.append(p)

    cir = []
    for c in re.findall(r"P3[12]-\d{3}-\d{2}-PN", U):
        if c not in cir: cir.append(c)
    for p in panels:
        if "NO.1" in p["panel"].upper():
            p["circuits"] = [x for x in cir if x.startswith("P31-")]
        elif "NO.2" in p["panel"].upper():
            p["circuits"] = [x for x in cir if x.startswith("P32-")]
        # Merge fallback with coordinate-based ACB SETTING TABLE (only fill empty fields)
        try:
            pinfos = _extract_panel_info_from_acb_table(msbd_pdf)
            if isinstance(pinfos, list):
                norm = {p.get("panel","").upper(): p for p in pinfos}
                for p in panels:
                    key = str(p.get("panel","")).upper()
                    q = norm.get(key)
                    if not q:
                        continue
                    for k in ["acb_type","ocr_type","ampere_frame","rated_current_in","ip","paint","ir_percent","ir_amps","isd_percent","isd_amps","setting_time_s","setting_time_ms"]:
                        if not p.get(k):
                            v = q.get(k)
                            if v:
                                p[k] = v
        except Exception as _e:
            pass

    return panels


def parse_emergency_stop(pdf_path: str) -> List[Dict[str, object]]:
    # Try to find EMERGENCY STOP TEST table (report-like)
    T = read_text(pdf_path, max_pages=60)
    U = T.upper()
    items = []
    # Very light: capture lines like ES-1A ... text
    for ln in [ln.strip() for ln in U.splitlines() if ln.strip()]:
        m = re.search(r'\b(ES|CO2|FOAM|PT)-\d+[A-Z]?\b', ln)
        if m:
            code = m.group(0)
            # Name: strip code itself
            name = re.sub(code, "", ln).strip(" :-·().")
            items.append({"code": code, "name": name, "groups": []})
    # Dedup by code
    uniq = {}
    for it in items:
        uniq.setdefault(it["code"], it)
    out = list(uniq.values())
    return out


def parse_emergency_colorplate(msbd_pdf: str) -> List[Dict[str, object]]:
    U = read_text(msbd_pdf, max_pages=60).upper()
    pos = U.find("COLOR PLATE SPECIFICATION")
    window = U[max(0, pos-2000): pos+8000] if pos != -1 else U
    items = []
    for ln in [ln.strip() for ln in window.splitlines() if ln.strip()]:
        m = re.findall(r'\b(ES|CO2|FOAM|PT)-\d+[A-Z]?\b', ln)
        if not m: continue
        name = re.sub(r'\b(ES|CO2|FOAM|PT)-\d+[A-Z]?\b', "", ln).strip(" :-·().")
        for code in m:
            # code here is only prefix, fix: use full match above
            pass
    # Use robust regex again to match code+name
    items = []
    for m in re.finditer(r'\b((?:ES|CO2|FOAM|PT)-\d+[A-Z]?)\b[\s:.-]*([^\n]{0,80})', window):
        code = m.group(1).upper()
        name = m.group(2).strip()
        items.append({"code": code, "name": name, "groups": []})
    # Dedup preserve order
    seen=set(); out=[]
    for it in items:
        if it["code"] in seen: continue
        seen.add(it["code"]); out.append(it)
    return out
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

PANEL_FIELD_ORDER = [
    "panel",
    "acb_type",
    "ocr_type",
    "ampere_frame",
    "rated_current_in",
    "ip",
    "paint",
    "ir_percent",
    "ir_amps",
    "isd_percent",
    "isd_amps",
    "setting_time_s",
    "setting_time_ms",
    "remarks",
]

HEADER_ALIASES = {
    "panel": ("PANEL", "PANELNAME", "PANELINFORMATION"),
    "acb_type": ("AIRCIRCUITBREAKER", "ACBTYPE", "ACBMODEL"),
    "ocr_type": ("OVERCURRENTTRIPTYPE", "OCRTYPE", "TRIPUNIT"),
    "ampere_frame": ("AMPEREFRAME", "AF", "MCR"),
    "rated_current_in": ("RATEDCURRENTIN", "INA", "IN"),
    "ip": ("DEGREEOFPROTECTION", "IP"),
    "paint": ("PAINT", "MUNSELL"),
    "ir_percent": ("IRPERCENT", "IR"),
    "ir_amps": ("IRA",),
    "isd_percent": ("ISDPERCENT", "ISD"),
    "isd_amps": ("ISDA",),
    "setting_time_s": ("TIMESEC", "TIMES", "SECONDS"),
    "setting_time_ms": ("TIMEMSEC", "TIMEMS", "MILLISECONDS"),
    "remarks": ("REMARK", "NOTE"),
}


def _is_dark_color(color) -> bool:
    try:
        if isinstance(color, (tuple, list)) and color:
            return sum(float(c) for c in color) / len(color) < 0.6
        if isinstance(color, (int, float)):
            return float(color) < 0.6
    except Exception:
        return False
    return False


def _cells_from_rects(page) -> List[Dict[str, float]]:
    rects = getattr(page, "rects", None) or []
    cells: List[Dict[str, float]] = []
    seen = set()
    for rect in rects:
        x0, x1 = rect.get("x0"), rect.get("x1")
        y0, y1 = rect.get("y0"), rect.get("y1")
        if None in (x0, x1, y0, y1):
            continue
        width = x1 - x0
        height = y1 - y0
        if width < 40 or height < 18:
            continue
        if width > page.width * 0.95 and height > page.height * 0.95:
            continue
        stroke = rect.get("stroke") or rect.get("stroking_color") or rect.get("non_stroking_color")
        if stroke is not None and not _is_dark_color(stroke):
            continue
        top = max(0.0, page.height - y1)
        bottom = min(page.height, page.height - y0)
        key = (round(x0, 1), round(x1, 1), round(top, 1), round(bottom, 1))
        if key in seen:
            continue
        seen.add(key)
        cells.append({"x0": x0, "x1": x1, "top": top, "bottom": bottom})
    return cells


def _cells_from_image(pdf_path: str, page_index: int, page) -> List[Dict[str, float]]:
    try:
        from pdf2image import convert_from_path
        import numpy as np
        import cv2
    except Exception:
        return []
    try:
        images = convert_from_path(pdf_path, dpi=220, first_page=page_index + 1, last_page=page_index + 1)
    except Exception:
        return []
    if not images:
        return []
    img = np.array(images[0])
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    scale = max(1, int(img.shape[1] / 900))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3 * scale, 3 * scale))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    width_scale = img.shape[1] / float(page.width or 1)
    height_scale = img.shape[0] / float(page.height or 1)
    cells: List[Dict[str, float]] = []
    seen = set()
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 40 * scale or h < 18 * scale:
            continue
        if w > img.shape[1] * 0.95 and h > img.shape[0] * 0.95:
            continue
        ratio = w / float(max(h, 1))
        if ratio < 0.4 or ratio > 20:
            continue
        px0 = x / width_scale
        px1 = (x + w) / width_scale
        ptop = y / height_scale
        pbottom = (y + h) / height_scale
        key = (round(px0, 1), round(px1, 1), round(ptop, 1), round(pbottom, 1))
        if key in seen:
            continue
        seen.add(key)
        cells.append({"x0": px0, "x1": px1, "top": ptop, "bottom": pbottom})
    return cells


def _text_from_chars(chars: List[Dict[str, Any]], page_height: float) -> str:
    if not chars:
        return ""
    lines: Dict[float, List[Dict[str, Any]]] = defaultdict(list)
    for ch in chars:
        text = ch.get("text", "")
        if not text:
            continue
        top = ch.get("top")
        if top is None:
            y1 = ch.get("y1")
            if y1 is None:
                continue
            top = page_height - y1
        lines[round(float(top), 1)].append(ch)
    out_lines: List[str] = []
    for _, group in sorted(lines.items(), key=lambda kv: kv[0]):
        ordered = sorted(group, key=lambda item: item.get("x0", 0.0))
        text = "".join(item.get("text", "") for item in ordered)
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            out_lines.append(text)
    return "\n".join(out_lines)


def _assign_text_to_cells(page, cells: List[Dict[str, Any]]) -> None:
    for cell in cells:
        cell["chars"] = []
    chars = getattr(page, "chars", []) or []
    for ch in chars:
        text = ch.get("text", "")
        if not text:
            continue
        cx = (ch.get("x0", 0.0) + ch.get("x1", 0.0)) / 2.0
        if "top" in ch and "bottom" in ch:
            cy = (ch["top"] + ch["bottom"]) / 2.0
        else:
            cy = page.height - ((ch.get("y0", 0.0) + ch.get("y1", 0.0)) / 2.0)
        for cell in cells:
            if cell["x0"] <= cx <= cell["x1"] and cell["top"] - 1.0 <= cy <= cell["bottom"] + 1.0:
                cell.setdefault("chars", []).append(ch)
                break
    for cell in cells:
        cell["text"] = _text_from_chars(cell.get("chars", []), page.height)


def _cluster_rows(cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not cells:
        return rows
    for cell in sorted(cells, key=lambda c: (c["top"], c["x0"])):
        center = (cell["top"] + cell["bottom"]) / 2.0
        matched = False
        for row in rows:
            if abs(center - row["center"]) <= 4.0:
                row["cells"].append(cell)
                row["center"] = (row["center"] * (len(row["cells"]) - 1) + center) / len(row["cells"])
                matched = True
                break
        if not matched:
            rows.append({"center": center, "cells": [cell]})
    for row in rows:
        row["cells"].sort(key=lambda c: c["x0"])
    rows.sort(key=lambda r: r["center"])
    return rows


def _match_panel_header(text: str) -> Optional[str]:
    if not text:
        return None
    norm = re.sub(r'[^A-Z0-9]', '', text.upper())
    if not norm:
        return None
    for key, tokens in HEADER_ALIASES.items():
        for token in tokens:
            if token and token in norm:
                return key
    return None


def _normalize_panel_value(key: str, value: str) -> str:
    text = re.sub(r'\s+', ' ', (value or '').strip())
    if not text:
        return ''
    if key in {"acb_type", "ocr_type"}:
        return text.upper()
    if key == "panel":
        return text
    if key in {"ampere_frame", "rated_current_in", "ir_amps", "isd_amps", "setting_time_s", "setting_time_ms"}:
        nums = re.findall(r'\d+', text)
        return nums[0] if nums else text
    if key in {"ir_percent", "isd_percent"}:
        m = re.search(r'\d{1,3}', text)
        return m.group(0) if m else text
    if key == "ip":
        m = re.search(r'(\d{2})', text)
        return f"IP{int(m.group(1)):02d}" if m else text.upper()
    return text


def _build_panel_records(page, cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not cells:
        return []
    _assign_text_to_cells(page, cells)
    rows = _cluster_rows(cells)
    header_keys: List[Optional[str]] = []
    data_rows: List[List[Dict[str, Any]]] = []
    for row in rows:
        mapped = [_match_panel_header(cell.get("text", "")) for cell in row["cells"]]
        if not header_keys and any(mapped):
            header_keys = mapped
            continue
        if header_keys:
            data_rows.append(row["cells"])
    if not header_keys:
        return []
    results: List[Dict[str, Any]] = []
    for cells_row in data_rows:
        record = {k: "" for k in PANEL_FIELD_ORDER}
        for idx, cell in enumerate(cells_row):
            if idx >= len(header_keys):
                break
            key = header_keys[idx]
            if not key:
                continue
            text = cell.get("text", "").replace("\n", " ").strip()
            if text:
                record[key] = _normalize_panel_value(key, text)
        if record.get("panel"):
            results.append(record)
    return results


def _extract_panel_table_fallback(page) -> List[Dict[str, Any]]:
    try:
        words = page.extract_words() or []
    except Exception:
        words = []
    panels = []
    for w in words:
        txt = w.get("text", "").upper().strip()
        if re.match(r"NO\.\s*\d+\s+INCOMING", txt) or txt in (
            "BUS-TIE",
            "BUS TIE",
            "EMERGENCY PANEL",
            "LINK TO EM'CY SWITCHBOARD",
            "LINK TO EM’CY SWITCHBOARD",
        ):
            panels.append((txt, (w["x0"] + w["x1"]) / 2.0))
    panels = sorted({(name, cx) for name, cx in panels}, key=lambda item: item[1])
    if not panels:
        return []

    cols = []
    for i, (name, cx) in enumerate(panels):
        x_left = (panels[i - 1][1] + cx) / 2.0 if i > 0 else cx - 120
        x_right = (cx + panels[i + 1][1]) / 2.0 if i < len(panels) - 1 else cx + 120
        cols.append((name, x_left, x_right))

    def find_row_y(pattern: str) -> Optional[float]:
        hits = [((w["top"] + w["bottom"]) / 2.0) for w in words if re.search(pattern, w.get("text", "").upper())]
        if not hits:
            return None
        hits.sort()
        return hits[len(hits) // 2]

    y_acb = find_row_y(r"AIR\s+CIRCUIT\s+BREAKER\s+TYPE|ACB\s*TYPE|ACB\s*MODEL")
    y_ocr = find_row_y(r"OVERCURRENT\s+TRIP\s+TYPE|TRIP\s*UNIT|OCR\s*TYPE")
    y_af = find_row_y(r"AMPERE\s*FRAME|\bAF\b|\bMCR\b")
    y_in = find_row_y(r"RATED\s+CURRENT|\bI[NO]\b")

    def words_in_band(x0: float, x1: float, center_y: float, band: float = 8.0) -> List[Dict[str, Any]]:
        return [
            w
            for w in words
            if x0 <= (w["x0"] + w["x1"]) / 2.0 <= x1 and abs(((w["top"] + w["bottom"]) / 2.0) - center_y) <= band
        ]

    rows: List[Dict[str, Any]] = []
    for name, x0, x1 in cols:
        info = {k: "" for k in PANEL_FIELD_ORDER}
        info["panel"] = name
        if y_acb is not None:
            cands = [w["text"].upper() for w in words_in_band(x0, x1, y_acb)]
            picks = [t for t in cands if re.match(r"[A-Z]{2,}[0-9]{2,}", t)]
            if picks:
                info["acb_type"] = picks[0]
        if y_ocr is not None:
            cands = [w["text"].upper() for w in words_in_band(x0, x1, y_ocr)]
            picks = [t for t in cands if re.match(r"[A-Z]{2,}", t)]
            if picks:
                info["ocr_type"] = picks[0]
        if y_af is not None:
            nums = [re.sub(r"[^0-9]", "", w["text"]) for w in words_in_band(x0, x1, y_af)]
            nums = [n for n in nums if n]
            if nums:
                info["ampere_frame"] = nums[0]
        if y_in is not None:
            nums = [re.sub(r"[^0-9]", "", w["text"]) for w in words_in_band(x0, x1, y_in)]
            nums = [n for n in nums if n]
            if nums:
                info["rated_current_in"] = nums[0]
        rows.append(info)
    return rows


# -----------------------------------------------
# PANEL INFORMATION from MSBD "ACB SETTING TABLE"
# -----------------------------------------------
def _extract_panel_info_from_acb_table(msbd_pdf_path: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    try:
        import pdfplumber
    except Exception:
        return result

    try:
        with pdfplumber.open(msbd_pdf_path) as pdf:
            target_index = None
            for idx, page in enumerate(pdf.pages):
                text_u = (page.extract_text() or "").upper()
                if "ACB" in text_u and "SETTING" in text_u and "TABLE" in text_u:
                    target_index = idx
                    break
            if target_index is None:
                return result

            page = pdf.pages[target_index]
            cells = _cells_from_rects(page)
            if len(cells) < 12:
                cells = _cells_from_image(msbd_pdf_path, target_index, page)
            records = _build_panel_records(page, cells)
            if not records:
                records = _extract_panel_table_fallback(page)
            return records
    except Exception:
        return result


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


def extract_panel_info_from_msbd(msbd_pdf_path: str) -> List[Dict[str, Any]]:  # type: ignore[override]
    """Coordinate-based extraction of panel information from ACB SETTING TABLE (robust)."""
    result: List[Dict[str, Any]] = []
    try:
        import pdfplumber, re
        with pdfplumber.open(msbd_pdf_path) as pdf:
            target = None
            for pg in pdf.pages:
                t = (pg.extract_text() or "").upper()
                if "ACB" in t and "SETTING" in t and "TABLE" in t:
                    target = pg; break
            if target is None:
                return result
            words = target.extract_words() or []
            def midx(w): return (w["x0"]+w["x1"])/2.0
            def midy(w): return (w["top"]+w["bottom"])/2.0

            # panel columns
            panels = []
            for w in words:
                tx = w["text"].upper().strip()
                if re.match(r"NO\.\s*\d+\s+INCOMING", tx) or tx in ("BUS-TIE","BUS TIE","EMERGENCY PANEL","LINK TO EM'CY SWITCHBOARD","LINK TO EM’CY SWITCHBOARD"):
                    panels.append((tx, midx(w)))
            panels = sorted({(n,x) for n,x in panels}, key=lambda v: v[1])
            if not panels:
                return result
            cols = []
            for i,(name,cx) in enumerate(panels):
                xL = (panels[i-1][1] + cx)/2.0 if i>0 else cx-160
                xR = (cx + panels[i+1][1])/2.0 if i < len(panels)-1 else cx+160
                cols.append((name, xL, xR))

            # row anchors
            def row_y(pat):
                ys = [ midy(w) for w in words if re.search(pat, w["text"].upper()) ]
                if not ys: return None
                ys.sort(); return ys[len(ys)//2]

            y_acb = row_y(r"AIR\s+CIRCUIT\s+BREAKER\s+TYPE|ACB\s*(TYPE|MODEL)")
            y_ocr = row_y(r"OVERCURRENT\s+TRIP\s+TYPE|TRIP\s*UNIT|OCR\s*(TYPE)?")
            y_af  = row_y(r"AMPERE\s*FRAME|\bAF\b|\bMCR\b")
            y_in  = row_y(r"RATED\s+CURRENT|\bI[NO]\b|\bIo\b|\bIn\b")

            def band(x0,x1,y,dy=14.0):
                return [w for w in words if x0 <= midx(w) <= x1 and (y is None or abs(midy(w)-y) <= dy)]

            for name, x0, x1 in cols:
                info = {"panel":name, "acb_type":"","ocr_type":"","ampere_frame":"","rated_current_in":"",
                        "ip":"","paint":"","ir_percent":"","ir_amps":"","isd_percent":"","isd_amps":"",
                        "setting_time_s":"","setting_time_ms":"","remarks":""}

                # ACB TYPE
                cand = [w["text"].upper() for w in band(x0,x1,y_acb)+band(x0,x1,y_acb,24.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{1,}[A-Z0-9\-]*$", t) and t not in ("SETTING","SETTINGS")]
                if cand: info["acb_type"] = cand[0]

                # OCR
                cand = [w["text"].upper() for w in band(x0,x1,y_ocr)+band(x0,x1,y_ocr,24.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{0,2}$", t)]
                if cand: info["ocr_type"] = cand[0]

                # AF
                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_af)+band(x0,x1,y_af,24.0)]
                nums = [int(n) for n in nums if n]
                nums = [n for n in nums if n >= 400]
                if nums: info["ampere_frame"] = str(sorted(nums)[0])

                # In/Io
                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_in)+band(x0,x1,y_in,24.0)]
                nums = [n for n in nums if n]
                if nums: info["rated_current_in"] = nums[0]

                result.append(info)
        return result
    except Exception:
        return result


# ---- override with slightly wider bands / aliases (fix11) ----
def extract_panel_info_from_msbd(msbd_pdf_path: str) -> List[Dict[str, Any]]:  # type: ignore[override]
    result: List[Dict[str, Any]] = []
    try:
        import pdfplumber, re
        with pdfplumber.open(msbd_pdf_path) as pdf:
            target = None
            for pg in pdf.pages:
                t = (pg.extract_text() or "").upper()
                if ("ACB" in t and "SETTING" in t and "TABLE" in t) or ("ACB" in t and "SETTING TABLE" in t):
                    target = pg; break
            if target is None:
                return result
            words = target.extract_words() or []
            def midx(w): return (w["x0"]+w["x1"])/2.0
            def midy(w): return (w["top"]+w["bottom"])/2.0

            # panel columns (more aliases)
            panels = []
            for w in words:
                tx = w["text"].upper().strip()
                if re.match(r"NO\.\s*\d+\s*INCOMING", tx) or tx in ("BUS-TIE","BUS TIE","EMERGENCY PANEL","EMERGENCY","LINK TO EM'CY SWITCHBOARD","LINK TO EM’CY SWITCHBOARD"):
                    panels.append((tx, midx(w)))
            panels = sorted({(n,x) for n,x in panels}, key=lambda v: v[1])
            if not panels:
                return result
            cols = []
            for i,(name,cx) in enumerate(panels):
                xL = (panels[i-1][1] + cx)/2.0 if i>0 else cx-180
                xR = (cx + panels[i+1][1])/2.0 if i < len(panels)-1 else cx+180
                cols.append((name, xL, xR))

            # row anchors with more variants
            def row_y(pat):
                ys = [ ((w["top"]+w["bottom"])/2.0) for w in words if re.search(pat, w["text"].upper()) ]
                if not ys: return None
                ys.sort(); return ys[len(ys)//2]

            y_acb = row_y(r"ACB\s*(TYPE|MODEL)|AIR\s+CIRCUIT\s+BREAKER")
            y_ocr = row_y(r"TRIP\s*UNIT|OVERCURRENT\s*(TRIP)?\s*TYPE|OCR\s*(TYPE)?")
            y_af  = row_y(r"AMPERE\s*FRAME|\bAF\b|\bMCR\b|FRAME\s*\(A\)")
            y_in  = row_y(r"RATED\s*CURRENT|\bI[NO]\b|\bIO\b|\bIN\b|SETTING\s*CURRENT")

            def band(x0,x1,y,dy=18.0):
                return [w for w in words if x0 <= (w["x0"]+w["x1"])/2.0 <= x1 and (y is None or abs(((w["top"]+w["bottom"])/2.0)-y) <= dy)]

            for name, x0, x1 in cols:
                info = {"panel":name, "acb_type":"","ocr_type":"","ampere_frame":"","rated_current_in":"",
                        "ip":"","paint":"","ir_percent":"","ir_amps":"","isd_percent":"","isd_amps":"",
                        "setting_time_s":"","setting_time_ms":"","remarks":""}

                cand = [w["text"].upper() for w in band(x0,x1,y_acb)+band(x0,x1,y_acb,26.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{1,}[A-Z0-9\-]*$", t) and t not in ("SETTING","SETTINGS")]
                if cand: info["acb_type"] = cand[0]

                cand = [w["text"].upper() for w in band(x0,x1,y_ocr)+band(x0,x1,y_ocr,26.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{0,2}$", t)]
                if cand: info["ocr_type"] = cand[0]

                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_af)+band(x0,x1,y_af,26.0)]
                nums = [int(n) for n in nums if n]
                nums = [n for n in nums if n >= 400]
                if nums: info["ampere_frame"] = str(sorted(nums)[0])

                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_in)+band(x0,x1,y_in,26.0)]
                nums = [n for n in nums if n]
                if nums: info["rated_current_in"] = nums[0]

                result.append(info)
        return result
    except Exception:
        return result


# ---- override: IP from GENERAL SPEC page only (fix12) ----
def extract_ip_grade(pdf_path: str) -> str:  # type: ignore[override]
    """
    Detect IP grade strictly from the GENERAL SPEC page.
    Looks for IPxx tokens and checks for a checkmark (■/●/◼ or filled rect) right/left.
    """
    import re
    try:
        import pdfplumber
    except Exception:
        txt = extract_text_fast(pdf_path).upper()
        # fallback: nearest "GENERAL"..."IPxx" pattern
        block = ""
        m = re.search(r"GENERAL.*?(IP\s*\d{2})", txt, flags=re.S)
        if m: return "IP" + re.sub(r"\D", "", m.group(1))[-2:]
        m = re.search(r"\bIP\s*([0-9]{2})\b", txt)
        return f"IP{m.group(1)}" if m else ""

    with pdfplumber.open(pdf_path) as pdf:
        target = None
        for pg in pdf.pages:
            text_u = (pg.extract_text() or "").upper()
            if "GENERAL" in text_u and "SPEC" in text_u:
                target = pg; break
        if target is None:
            # fallback to first page
            target = pdf.pages[0]

        def ip_tokens(page):
            toks = []
            for w in page.extract_words() or []:
                t = w.get("text","").upper()
                m = re.match(r"IP[-\s]?([0-9]{2})\b", t)
                if m: toks.append((int(m.group(1)), w))
            return toks

        def has_mark_near(page, w):
            x0,x1,y0,y1 = w["x0"], w["x1"], w["top"], w["bottom"]
            windows = [(x0-40, x0-4, y0-8, y1+8), (x1+4, x1+40, y0-8, y1+8)]
            chars = page.chars or []
            rects = [r for r in (page.rects or []) if r.get("non_stroking_color") is not None and 1.5 <= r.get("width",0) <= 14.0 and 1.5 <= r.get("height",0) <= 14.0]
            for (mx0,mx1,my0,my1) in windows:
                for c in chars:
                    if c.get("text") in ("■","●","◼","▪","∙") and mx0 <= c.get("x0",0) <= mx1 and my0 <= c.get("top",0) <= my1:
                        return True
                for r in rects:
                    cx = (r["x0"]+r["x1"])/2.0; cy = (r["top"]+r["bottom"])/2.0
                    if mx0 <= cx <= mx1 and my0 <= cy <= my1:
                        return True
            return False

        toks = ip_tokens(target)
        if toks:
            for val, w in toks:
                if has_mark_near(target, w):
                    return f"IP{val:02d}"
            toks.sort(key=lambda t: (t[1]["x0"], t[1]["top"]))
            return f"IP{toks[0][0]:02d}"
    return ""


# ---- override ACB TABLE finder with misspelling tolerance (fix12) ----
def extract_panel_info_from_msbd(msbd_pdf_path: str) -> List[Dict[str, Any]]:  # type: ignore[override]
    """
    Coordinate-based extraction from ACB SETTING TABLE (tolerates TANLE/TABIE/TABEL typos).
    """
    result: List[Dict[str, Any]] = []
    try:
        import pdfplumber, re
        with pdfplumber.open(msbd_pdf_path) as pdf:
            target = None
            for pg in pdf.pages:
                t = (pg.extract_text() or "").upper()
                if "ACB" in t and "SETTING" in t and (re.search(r"TABL[EI]|TANLE|TABEL", t) or "TABLE" in t):
                    target = pg; break
            if target is None:
                return result
            words = target.extract_words() or []
            def midx(w): return (w["x0"]+w["x1"])/2.0
            def midy(w): return (w["top"]+w["bottom"])/2.0

            panels = []
            for w in words:
                tx = w["text"].upper().strip()
                if re.match(r"NO\.\s*\d+\s*INCOMING", tx) or tx in ("BUS-TIE","BUS TIE","EMERGENCY PANEL","EMERGENCY","LINK TO EM'CY SWITCHBOARD","LINK TO EM’CY SWITCHBOARD"):
                    panels.append((tx, midx(w)))
            panels = sorted({(n,x) for n,x in panels}, key=lambda v: v[1])
            if not panels:
                return result
            cols = []
            for i,(name,cx) in enumerate(panels):
                xL = (panels[i-1][1] + cx)/2.0 if i>0 else cx-180
                xR = (cx + panels[i+1][1])/2.0 if i < len(panels)-1 else cx+180
                cols.append((name, xL, xR))

            def row_y(pat):
                ys = [ midy(w) for w in words if re.search(pat, w["text"].upper()) ]
                if not ys: return None
                ys.sort(); return ys[len(ys)//2]

            y_acb = row_y(r"ACB\s*(TYPE|MODEL)|AIR\s+CIRCUIT\s+BREAKER")
            y_ocr = row_y(r"TRIP\s*UNIT|OVERCURRENT\s*(TRIP)?\s*TYPE|OCR\s*(TYPE)?")
            y_af  = row_y(r"AMPERE\s*FRAME|\bAF\b|\bMCR\b|FRAME\s*\(A\)")
            y_in  = row_y(r"RATED\s*CURRENT|\bI[NO]\b|\bIO\b|\bIN\b|SETTING\s*CURRENT")

            def band(x0,x1,y,dy=18.0):
                return [w for w in words if x0 <= midx(w) <= x1 and (y is None or abs(midy(w)-y) <= dy)]

            for name, x0, x1 in cols:
                info = {"panel":name, "acb_type":"","ocr_type":"","ampere_frame":"","rated_current_in":"",
                        "ir_percent":"","ir_amps":"","isd_percent":"","isd_amps":"","remarks":""}

                # ACB TYPE
                cand = [w["text"].upper() for w in band(x0,x1,y_acb)+band(x0,x1,y_acb,26.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{1,}[A-Z0-9\-]*$", t) and t not in ("SETTING","SETTINGS")]
                if cand: info["acb_type"] = cand[0]

                # OCR/TRIP UNIT
                cand = [w["text"].upper() for w in band(x0,x1,y_ocr)+band(x0,x1,y_ocr,26.0)]
                cand = [t for t in cand if re.match(r"[A-Z]{2,}[0-9]{0,2}$", t)]
                if cand: info["ocr_type"] = cand[0]

                # AMPERE FRAME
                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_af)+band(x0,x1,y_af,26.0)]
                nums = [int(n) for n in nums if n]
                nums = [n for n in nums if n >= 400]
                if nums: info["ampere_frame"] = str(sorted(nums)[0])

                # RATED CURRENT In/Io
                nums = [re.sub(r"[^0-9]","", w["text"]) for w in band(x0,x1,y_in)+band(x0,x1,y_in,26.0)]
                nums = [n for n in nums if n]
                if nums: info["rated_current_in"] = nums[0]

                result.append(info)
        return result
    except Exception:
        return result

# ---------------------------
# override: checkbox detection backed by pdf2image + OpenCV (GENERAL SPEC page only)
# This definition intentionally appears at the end of the module to override any earlier versions.
def extract_ip_grade(pdf_path: str, *args, **kwargs) -> str:  # type: ignore[override]
    """Determine IP grade from the GENERAL SPEC page using pdf2image + OpenCV."""
    try:
        import re
        try:
            import pdfplumber  # type: ignore
        except Exception:
            return "IP22"

        try:
            from pdf2image import convert_from_path  # type: ignore
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception:
            convert_from_path = None  # type: ignore
            cv2 = None  # type: ignore
            np = None  # type: ignore

        def is_general_spec_page(text: str) -> bool:
            t = (text or "").upper()
            return ("GENERAL" in t and "SPEC" in t)

        target_index = 0
        page_width = 0.0
        page_height = 0.0
        tokens: List[Tuple[int, Dict[str, float]]] = []
        chars: List[Dict[str, float]] = []
        rects: List[Dict[str, float]] = []

        with pdfplumber.open(pdf_path) as pdf:  # type: ignore
            target_page = None
            for idx, page in enumerate(pdf.pages):
                if is_general_spec_page(page.extract_text() or ""):
                    target_page = page
                    target_index = idx
                    break
            if target_page is None:
                if not pdf.pages:
                    return "IP22"
                target_page = pdf.pages[0]
                target_index = 0

            page_width = float(getattr(target_page, "width", 0.0) or 0.0)
            page_height = float(getattr(target_page, "height", 0.0) or 0.0)

            raw_words = target_page.extract_words() or []
            for idx, w in enumerate(raw_words):
                text = (w.get("text") or "").strip().upper()
                m = re.match(r"\bIP[-\s]?(\d{2})\b", text)
                if not m and text == "IP" and idx + 1 < len(raw_words):
                    nxt = raw_words[idx + 1]
                    nxt_txt = (nxt.get("text") or "").strip().upper()
                    if re.fullmatch(r"\d{2}", nxt_txt):
                        m = re.match(r"(\d{2})", nxt_txt)
                        if m:
                            try:
                                tokens.append(
                                    (
                                        int(m.group(1)),
                                        {
                                            "x0": float(min(w.get("x0", 0.0), nxt.get("x0", 0.0))),
                                            "x1": float(max(w.get("x1", 0.0), nxt.get("x1", 0.0))),
                                            "top": float(min(w.get("top", 0.0), nxt.get("top", 0.0))),
                                            "bottom": float(max(w.get("bottom", 0.0), nxt.get("bottom", 0.0))),
                                        },
                                    )
                                )
                            except Exception:
                                pass
                            continue
                if not m:
                    continue
                try:
                    tokens.append(
                        (
                            int(m.group(1)),
                            {
                                "x0": float(w.get("x0", 0.0)),
                                "x1": float(w.get("x1", 0.0)),
                                "top": float(w.get("top", 0.0)),
                                "bottom": float(w.get("bottom", 0.0)),
                            },
                        )
                    )
                except Exception:
                    continue

            if not tokens:
                return "IP22"

            chars = [dict(c) for c in (target_page.chars or [])]
            raw_rects = (getattr(target_page, "rects", []) or [])
            for r in raw_rects:
                if r.get("nonstroking", 0) or r.get("stroking", 0) or r.get("non_stroking_color") is not None:
                    rects.append(dict(r))

        def detect_with_image() -> Optional[int]:
            if convert_from_path is None or cv2 is None or np is None:
                return None
            if page_width <= 0 or page_height <= 0:
                return None
            try:
                images = convert_from_path(
                    pdf_path,
                    dpi=220,
                    first_page=target_index + 1,
                    last_page=target_index + 1,
                    fmt="png",
                )
            except Exception:
                return None
            if not images:
                return None
            try:
                pil_img = images[0]
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            except Exception:
                return None

            h_img, w_img = gray.shape[:2]
            scale_x = w_img / page_width
            scale_y = h_img / page_height

            def roi_has_mark(x0: float, x1: float, y0: float, y1: float) -> bool:
                rx0 = max(0, min(w_img, int(round(x0 * scale_x))))
                rx1 = max(0, min(w_img, int(round(x1 * scale_x))))
                ry0 = max(0, min(h_img, int(round(y0 * scale_y))))
                ry1 = max(0, min(h_img, int(round(y1 * scale_y))))
                if rx1 <= rx0 or ry1 <= ry0:
                    return False
                roi = gray[ry0:ry1, rx0:rx1]
                if roi.size == 0:
                    return False
                try:
                    blur = cv2.GaussianBlur(roi, (3, 3), 0)
                    _, thresh = cv2.threshold(
                        blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
                    )
                except Exception:
                    return False

                nz = float(cv2.countNonZero(thresh))
                ratio = nz / float(thresh.size or 1)

                # quick accept when there is heavy fill (checked box or dot)
                if ratio >= 0.06:
                    return True

                # Inspect individual contours for partially filled squares / crosses
                cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cnt in cnts:
                    x, y, w, h = cv2.boundingRect(cnt)
                    area = max(w * h, 1)
                    if w < 6 or h < 6 or w > 70 or h > 70:
                        continue
                    aspect = w / float(h)
                    if aspect < 0.4 or aspect > 2.5:
                        continue
                    sub = thresh[y : y + h, x : x + w]
                    fill = float(cv2.countNonZero(sub)) / float(area)
                    if fill >= 0.035:
                        # dilate thin marks to better judge "X" cases
                        if fill < 0.06:
                            kernel = np.ones((3, 3), np.uint8)
                            dil = cv2.dilate(sub, kernel, iterations=1)
                            fill = float(cv2.countNonZero(dil)) / float(area)
                        if fill >= 0.06:
                            return True

                # Fallback: detect strong edges (e.g., "X" marks) concentrated in the box region
                try:
                    edges = cv2.Canny(roi, 60, 180)
                    edge_ratio = float(cv2.countNonZero(edges)) / float(edges.size or 1)
                except Exception:
                    edge_ratio = 0.0
                return edge_ratio >= 0.09

            search_offsets = [(-110.0, -4.0), (4.0, 110.0)]
            vertical_pad = 18.0
            for val, box in tokens:
                x0 = box["x0"]
                x1 = box["x1"]
                y0 = max(0.0, box["top"] - vertical_pad)
                y1 = box["bottom"] + vertical_pad
                for off0, off1 in search_offsets:
                    wx0 = x0 + off0
                    wx1 = x0 + off1 if off1 < 0 else x1 + off1
                    if roi_has_mark(wx0, wx1, y0, y1):
                        return val
            return None

        detected_value = detect_with_image()
        if detected_value is not None:
            return f"IP{detected_value:02d}"

        def has_mark_near(box: Dict[str, float]) -> bool:
            x0 = box.get("x0", 0.0)
            x1 = box.get("x1", 0.0)
            y0 = box.get("top", 0.0) - 14.0
            y1 = box.get("bottom", 0.0) + 14.0
            windows = [
                (x0 - 100.0, x0 - 2.0, y0, y1),
                (x1 + 2.0, x1 + 100.0, y0, y1),
            ]
            for (wx0, wx1, wy0, wy1) in windows:
                for c in chars:
                    if c.get("text") in ("■", "●", "◼", "▪", "∙", "•", "☑", "√"):
                        cx = c.get("x0", 0.0)
                        cy = c.get("top", 0.0)
                        if wx0 <= cx <= wx1 and wy0 <= cy <= wy1:
                            return True
                for r in rects:
                    rx0 = r.get("x0", 0.0)
                    rx1 = r.get("x1", r.get("x0", 0.0))
                    ry0 = r.get("top", 0.0)
                    ry1 = r.get("bottom", r.get("top", 0.0))
                    width = abs(rx1 - rx0)
                    height = abs(ry1 - ry0)
                    if width < 3.0 or height < 3.0 or width > 20.0 or height > 20.0:
                        continue
                    cx = (rx0 + rx1) / 2.0
                    cy = (ry0 + ry1) / 2.0
                    if wx0 <= cx <= wx1 and wy0 <= cy <= wy1:
                        return True
            return False

        for val, box in tokens:
            if has_mark_near(box):
                return f"IP{val:02d}"

        return "IP22"
    except Exception:
        return "IP22"
# Ensure latest panel extractor is used by downstream code
extract_panel_info_from_msbd = _extract_panel_info_from_acb_table
# ---------------------------
