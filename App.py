"""
GST Bulk Extractor  ·  GSTR-1 + GSTR-3B
─────────────────────────────────────────
Multi-user ready: each Streamlit browser session is completely isolated.

Output: single Excel file with 4 sheets
  Sheet 1  GSTR-1       Sales, Exports, CDN, Amendments, Tax Liability
  Sheet 2  3.1(d) RCM   Taxable Value + IGST / CGST / SGST
  Sheet 3  4(C) ITC     Net ITC: IGST / CGST / SGST
  Sheet 4  6.1(A)       Tax paid via ITC: IGST / CGST / SGST
"""

import io
import re
import pandas as pd
import pdfplumber
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="GST Bulk Extractor", page_icon="🧾", layout="wide")
st.title("🧾 GST Bulk Extractor — GSTR-1 + GSTR-3B")
st.caption(
    "Upload multiple PDFs for each return type. "
    "Multiple team members can use this at the same time — every session is independent."
)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
]
MONTH_FY_ORDER = {m: (i - 3) % 12 for i, m in enumerate(MONTHS)}

# ── SHARED HELPERS ────────────────────────────────────────────────────────────
def pdf_to_text(file) -> str:
    with pdfplumber.open(file) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

def fix_broken_numbers(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'(\d[\d,]*\.\d+)\n(\d+)', r'\1\2', text)
    text = re.sub(r'(\d+)\n(\d{2})\b', r'\1\2', text)
    return text

def find_amounts(text: str, n: int = 1) -> list:
    vals = re.findall(r"-?[\d,]+\.\d{2}", text)
    result = []
    for v in vals:
        result.append(float(v.replace(",", "")))
        if len(result) == n:
            break
    return result

def section_total(text, header_re, stop_re=None, target_word="total", window=1500) -> float:
    m = re.search(header_re, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return 0.0
    start = m.start()
    end = start + window
    if stop_re:
        s = re.search(stop_re, text[start + 10:], re.IGNORECASE)
        if s:
            end = start + 10 + s.start()
    chunk = text[start:end]
    tm = re.search(target_word, chunk, re.IGNORECASE)
    if not tm:
        return 0.0
    vals = find_amounts(chunk[tm.start():], 1)
    return vals[0] if vals else 0.0

def extract_month(text: str) -> str:
    m = re.search(r"(?:Tax\s+[Pp]eriod|Period)\s+([A-Za-z]+)", text)
    if m:
        return m.group(1).capitalize()
    for mo in MONTHS:
        if re.search(mo, text[:600], re.IGNORECASE):
            return mo
    return "Unknown"

def sort_by_month(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_s"] = df["Month"].map(lambda x: MONTH_FY_ORDER.get(x, 99))
    return df.sort_values("_s").drop(columns=["_s"]).reset_index(drop=True)

def row_amounts(text: str, row_re: str, stop_re: str, count: int = 5) -> list:
    m = re.search(row_re, text, re.IGNORECASE)
    if not m:
        return [0.0] * count
    start = m.start()
    stop_m = re.search(stop_re, text[start + 5:], re.IGNORECASE)
    end = start + 5 + (stop_m.start() if stop_m else 500)
    vals = find_amounts(text[start:end], count)
    while len(vals) < count:
        vals.append(0.0)
    return vals

# ── CUSTOM 9A & 6.1(A) HELPERS ────────────────────────────────────────────────
def extract_9A_amendment(text: str) -> float:
    total = 0.0
    sections = re.split(r"\n\s*9A\s*[-–]", text, flags=re.IGNORECASE)
    
    for sec in sections[1:]:
        m = re.search(
            r"Net\s+differential\s+amount.*?(-?[\d,]+\.\d{2})",
            sec, re.IGNORECASE | re.DOTALL
        )
        if m:
            total += float(m.group(1).replace(",", ""))
            
    return total

def extract_6_1A(file):
    paid_igst = paid_cgst = paid_sgst = 0.0

    try:
        with pdfplumber.open(file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            
        # Fix split numbers before searching
        text = fix_broken_numbers(text)
        
        # Locate the 6.1 Payment Table
        m_61 = re.search(r"6\.1\s*Payment", text, re.IGNORECASE)
        if m_61:
            chunk = text[m_61.start(): m_61.start() + 2000]
            
            # This regex looks for the Tax Name, followed by all the numbers/dashes in that row
            row_pattern = r"(Integrated|Central|State/UT|State)\s*Tax\s+((?:(?:-|\bNA\b|\d[\d,]*\.\d{2})\s*){4,})"
            
            for match in re.finditer(row_pattern, chunk, re.IGNORECASE):
                nums_text = match.group(2)
                
                tokens = []
                for t in nums_text.split():
                    t_clean = t.replace(",", "").strip()
                    # Convert PDF dashes and blanks directly to 0.0
                    if t_clean in ("-", "NA", "0", "0.0"):
                        tokens.append(0.0)
                    elif re.match(r"^-?\d+\.\d{2}$", t_clean):
                        tokens.append(float(t_clean))
                
                # GSTR-3B Column Structure:
                # [0] Tax Payable | [1] IGST ITC | [2] CGST ITC | [3] SGST ITC
                if len(tokens) >= 4:
                    paid_igst += tokens[1]
                    paid_cgst += tokens[2]
                    paid_sgst += tokens[3]
                    
    except Exception:
        pass

    return paid_igst, paid_cgst, paid_sgst

# ── GSTR-1 PARSER ─────────────────────────────────────────────────────────────
def parse_gstr1(file) -> dict:
    text = fix_broken_numbers(pdf_to_text(file))
    month = extract_month(text)

    b2b = section_total(text, r"4A\s*[-–]?\s*Taxable\s+outward\s+supplies\s+made\s+to\s+registered", r"4B\s*[-–]?\s*Taxable")
    b2cs = section_total(text, r"7\s*[-–]?\s*Taxable\s+supplies.*?unregistered", r"8\s*[-–]?\s*Nil")

    exp_6a  = section_total(text, r"6A\s*[–-]?\s*Exports?\s*\(",   r"6B\s*[-–]?\s*Supplies")
    sez_6b  = section_total(text, r"6B\s*[-–]?\s*Supplies.*?SEZ",  r"6C\s*[-–]?\s*Deemed")
    dee_6c  = section_total(text, r"6C\s*[-–]?\s*Deemed\s+Exports", r"7\s*[-–]?\s*Taxable")

    cdn_reg   = section_total(text, r"9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Registered\)", r"9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Unregistered\)", target_word=r"Total\s*[-–]?\s*Net\s+off")
    cdn_unreg = section_total(text, r"9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Unregistered\)", r"9C\s*[-–]?\s*Amended", target_word=r"Total\s*[-–]?\s*Net\s+off")

    amendment_9a = extract_9A_amendment(text)

    igst = cgst = sgst = 0.0
    m = re.search(r"Total\s+Liability\s*\(Outward[^)]+\)\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text, re.IGNORECASE)
    if m:
        igst, cgst, sgst = float(m.group(2).replace(",","")), float(m.group(3).replace(",","")), float(m.group(4).replace(",",""))
    else:
        m2 = re.search(r"Total\s+Liability", text, re.IGNORECASE)
        if m2:
            v = find_amounts(text[m2.start(): m2.start()+400], 4)
            if len(v) >= 4:
                igst, cgst, sgst = v[1], v[2], v[3]

    return {
        "Month":              month,
        "File":               file.name,
        "Sales B2B (4A)":     b2b,
        "Sales B2CS (7)":     b2cs,
        "Total Sales":        b2b + b2cs,
        "6A Exports":         exp_6a,
        "6B SEZ":             sez_6b,
        "6C Deemed Export":   dee_6c,
        "Total Exports":      exp_6a + sez_6b + dee_6c,
        "Credit/Debit Notes": cdn_reg + cdn_unreg,
        "Amendment 9A":       amendment_9a,
        "IGST Liability":     igst,
        "CGST Liability":     cgst,
        "SGST Liability":     sgst,
    }

# ── GSTR-3B PARSER ────────────────────────────────────────────────────────────
def parse_gstr3b(file) -> dict:
    raw_text = pdf_to_text(file)
    text  = fix_broken_numbers(raw_text)
    month = extract_month(text)

    # 3.1(d)
    rcm = row_amounts(text, r"\(d\)\s+Inward supplies\s*\(liable to reverse charge\)", r"\(e\)\s+Non.GST", count=5)
    # 4(C)
    itc = row_amounts(text, r"C\.\s+Net ITC available\s*\(A[-–]?B\)", r"\(D\)\s+Other Details", count=4)

    paid_igst, paid_cgst, paid_sgst = extract_6_1A(file)

    return {
        "Month":          month,
        "File":           file.name,
        "RCM Taxable":    rcm[0],
        "RCM IGST":       rcm[1],
        "RCM CGST":       rcm[2],
        "RCM SGST":       rcm[3],
        "ITC IGST":       itc[0],
        "ITC CGST":       itc[1],
        "ITC SGST":       itc[2],
        "6.1A IGST via ITC": paid_igst,
        "6.1A CGST via ITC": paid_cgst,
        "6.1A SGST via ITC": paid_sgst,
    }

# ── EXCEL BUILDER ─────────────────────────────────────────────────────────────
HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
TTL_FONT = Font(bold=True, color="1F4E79", size=12)
RUPEE    = '#,##0.00'

def write_table(ws, title: str, df: pd.DataFrame, start_row: int) -> int:
    ws.cell(start_row, 1, title).font = TTL_FONT
    start_row += 1
    for ci, col in enumerate(df.columns, 1):
        c = ws.cell(start_row, ci, col)
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    start_row += 1
    for _, row in df.iterrows():
        for ci, val in enumerate(row, 1):
            c = ws.cell(start_row, ci, val)
            if isinstance(val, float):
                c.number_format = RUPEE
                c.alignment = Alignment(horizontal="right")
            else:
                c.alignment = Alignment(horizontal="left")
        start_row += 1
    return start_row + 1

def build_excel(gstr1_rows: list, gstr3b_rows: list) -> bytes:
    wb = Workbook()

    # Sheet 1 — GSTR-1
    ws1 = wb.active
    ws1.title = "GSTR-1"
    if gstr1_rows:
        df1 = sort_by_month(pd.DataFrame(gstr1_rows))
        write_table(ws1, "GSTR-1 Summary (Month-wise)", df1, 1)
        for i, col in enumerate(df1.columns, 1):
            ws1.column_dimensions[get_column_letter(i)].width = max(18, len(str(col)) + 2)

    # Sheets 2-4 — GSTR-3B
    ws2 = wb.create_sheet("3.1(d) RCM")
    ws3 = wb.create_sheet("4(C) Net ITC")
    ws4 = wb.create_sheet("6.1(A) Tax via ITC")

    if gstr3b_rows:
        df3 = sort_by_month(pd.DataFrame(gstr3b_rows))
        write_table(ws2, "3.1(d) – Inward Supplies Liable to RCM",
                    df3[["Month","File","RCM Taxable","RCM IGST","RCM CGST","RCM SGST"]], 1)
        write_table(ws3, "4(C) – Net ITC Available (A – B)",
                    df3[["Month","File","ITC IGST","ITC CGST","ITC SGST"]], 1)
        write_table(ws4, "6.1(A) – Tax Paid through ITC",
                    df3[["Month","File","6.1A IGST via ITC","6.1A CGST via ITC","6.1A SGST via ITC"]], 1)
        for ws in (ws2, ws3, ws4):
            for i in range(1, 8):
                ws.column_dimensions[get_column_letter(i)].width = 22

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# ── UI ────────────────────────────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.subheader("📄 GSTR-1 PDFs")
    gstr1_files = st.file_uploader(
        "Multiple months supported",
        type="pdf", accept_multiple_files=True, key="up1")

with col_r:
    st.subheader("📋 GSTR-3B PDFs")
    gstr3b_files = st.file_uploader(
        "Multiple months supported",
        type="pdf", accept_multiple_files=True, key="up2")

st.divider()

if st.button("⚡ Extract & Download Excel", type="primary",
             disabled=(not gstr1_files and not gstr3b_files)):

    gstr1_rows, gstr3b_rows, errors = [], [], []

    with st.spinner("Processing PDFs…"):
        for f in (gstr1_files or []):
            try:
                gstr1_rows.append(parse_gstr1(f))
            except Exception as e:
                errors.append(f"GSTR-1 | {f.name}: {e}")
        for f in (gstr3b_files or []):
            try:
                gstr3b_rows.append(parse_gstr3b(f))
            except Exception as e:
                errors.append(f"GSTR-3B | {f.name}: {e}")

    for err in errors:
        st.error(f"❌ {err}")

    if gstr1_rows:
        st.markdown("### GSTR-1 Summary")
        df1 = sort_by_month(pd.DataFrame(gstr1_rows))
        num_cols = [c for c in df1.columns if c not in ("Month","File")]
        st.dataframe(df1.style.format({c: "₹{:,.2f}" for c in num_cols}),
                     use_container_width=True)

    if gstr3b_rows:
        df3 = sort_by_month(pd.DataFrame(gstr3b_rows))
        
        st.markdown("### 3.1(d) — RCM")
        rcm_df = df3[["Month","File","RCM Taxable","RCM IGST","RCM CGST","RCM SGST"]]
        st.dataframe(rcm_df.style.format({c: "₹{:,.2f}" for c in rcm_df.columns if c not in ("Month","File")}),
                     use_container_width=True)

        st.markdown("### 4(C) — Net ITC Available")
        itc_df = df3[["Month","File","ITC IGST","ITC CGST","ITC SGST"]]
        st.dataframe(itc_df.style.format({c: "₹{:,.2f}" for c in itc_df.columns if c not in ("Month","File")}),
                     use_container_width=True)

        st.markdown("### 6.1(A) — Tax Paid via ITC")
        paid_df = df3[["Month","File","6.1A IGST via ITC","6.1A CGST via ITC","6.1A SGST via ITC"]]
        st.dataframe(paid_df.style.format({c: "₹{:,.2f}" for c in paid_df.columns if c not in ("Month","File")}),
                     use_container_width=True)

    if gstr1_rows or gstr3b_rows:
        excel_bytes = build_excel(gstr1_rows, gstr3b_rows)
        st.success(f"✅ {len(gstr1_rows)} GSTR-1 and {len(gstr3b_rows)} GSTR-3B file(s) processed.")
        st.download_button(
            label="📥 Download Combined Excel (4 sheets)",
            data=excel_bytes,
            file_name="GST_Bulk_Extract.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
