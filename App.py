import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs. Extracts Sales (B2B+B2CS), Exports (6A+6B+6C), Credit/Debit Notes, Amendments, and Tax Liability.")


# ──────────────────────────────────────────────────────────────────────────────
# CORE HELPER: extract the first amount after the word "total" inside a section
# ──────────────────────────────────────────────────────────────────────────────
def get_section_total(text, header_pattern, stop_pattern=None, target_word="total", window=1500):
    """
    Finds header_pattern in text, slices a window up to stop_pattern,
    then returns the first ₹ amount after target_word.
    """
    start_match = re.search(header_pattern, text, re.IGNORECASE | re.DOTALL)
    if not start_match:
        return 0.0

    start = start_match.start()
    end = start + window

    if stop_pattern:
        stop_match = re.search(stop_pattern, text[start + 10:], re.IGNORECASE)
        if stop_match:
            end = start + 10 + stop_match.start()

    section = text[start:end]

    target_match = re.search(target_word, section, re.IGNORECASE)
    if not target_match:
        return 0.0

    amounts = re.findall(r'-?[\d,]+\.\d{2}', section[target_match.start():])
    if amounts:
        return float(amounts[0].replace(',', ''))
    return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# MONTH EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────
MONTHS = ["January","February","March","April","May","June",
          "July","August","September","October","November","December"]

def extract_month(text):
    match = re.search(r'Tax\s+[Pp]eriod\s+([A-Za-z]+)', text)
    if match:
        return match.group(1).capitalize()
    # fallback: scan for any month name near the top of the doc
    for m in MONTHS:
        if re.search(m, text[:500], re.IGNORECASE):
            return m
    return "Unknown"


# ──────────────────────────────────────────────────────────────────────────────
# TOTAL LIABILITY (IGST / CGST / SGST) — reads the summary line at doc end
# ──────────────────────────────────────────────────────────────────────────────
def extract_liability(text):
    """
    Looks for: Total Liability ... 39,51,023.20  1,97,551.16  0.00  0.00  0.00
    Columns:  Value | IGST | CGST | SGST | Cess
    """
    igst = cgst = sgst = 0.0
    match = re.search(
        r'Total\s+Liability\s*\(Outward[^)]+\)\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',
        text, re.IGNORECASE
    )
    if match:
        # groups: value, igst, cgst, sgst
        igst = float(match.group(2).replace(',', ''))
        cgst = float(match.group(3).replace(',', ''))
        sgst = float(match.group(4).replace(',', ''))
    else:
        # fallback: find "Total Liability" and grab next 4 amounts
        m2 = re.search(r'Total\s+Liability', text, re.IGNORECASE)
        if m2:
            chunk = text[m2.start(): m2.start() + 400]
            amounts = re.findall(r'-?[\d,]+\.\d{2}', chunk)
            if len(amounts) >= 4:
                igst = float(amounts[1].replace(',', ''))
                cgst = float(amounts[2].replace(',', ''))
                sgst = float(amounts[3].replace(',', ''))
    return igst, cgst, sgst


# ──────────────────────────────────────────────────────────────────────────────
# FILE UPLOADER
# ──────────────────────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Drop all your GSTR-1 PDFs here",
    type="pdf",
    accept_multiple_files=True
)

if uploaded_files:
    if st.button("⚡ Extract Data from All Files"):
        all_data = []

        with st.spinner("Processing your files…"):
            for file in uploaded_files:
                try:
                    with pdfplumber.open(file) as pdf:
                        full_text = "\n".join(
                            page.extract_text() or "" for page in pdf.pages
                        )

                    # ── 1. MONTH ──────────────────────────────────────────────
                    month_name = extract_month(full_text)

                    # ── 2. SALES = B2B (4A) + B2CS (7) ──────────────────────
                    b2b = get_section_total(
                        full_text,
                        r'4A\s*[-–]?\s*Taxable\s+outward\s+supplies\s+made\s+to\s+registered',
                        r'4B\s*[-–]?\s*Taxable'
                    )
                    b2cs = get_section_total(
                        full_text,
                        r'7\s*[-–]?\s*Taxable\s+supplies.*?unregistered',
                        r'8\s*[-–]?\s*Nil'
                    )
                    total_sales = b2b + b2cs

                    # ── 3. EXPORTS = 6A + 6B + 6C ────────────────────────────
                    exp_6a = get_section_total(
                        full_text,
                        r'6A\s*[–-]?\s*Exports?\s*\(',
                        r'6B\s*[-–]?\s*Supplies'
                    )
                    sez_6b = get_section_total(
                        full_text,
                        r'6B\s*[-–]?\s*Supplies\s+made\s+to\s+SEZ',
                        r'6C\s*[-–]?\s*Deemed'
                    )
                    deemed_6c = get_section_total(
                        full_text,
                        r'6C\s*[-–]?\s*Deemed\s+Exports',
                        r'7\s*[-–]?\s*Taxable'
                    )
                    total_exports = exp_6a + sez_6b + deemed_6c

                    # ── 4. CREDIT / DEBIT NOTES = 9B Reg + 9B Unreg ─────────
                    cdn_reg = get_section_total(
                        full_text,
                        r'9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Registered\)',
                        r'9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Unregistered\)',
                        target_word=r'Total\s*[-–]?\s*Net\s+off'
                    )
                    cdn_unreg = get_section_total(
                        full_text,
                        r'9B\s*[-–]?\s*Credit/Debit\s+Notes?\s*\(Unregistered\)',
                        r'9C\s*[-–]?\s*Amended',
                        target_word=r'Total\s*[-–]?\s*Net\s+off'
                    )
                    total_cdn = cdn_reg + cdn_unreg

                    # ── 5. AMENDMENT (9A) — net differential ─────────────────
                    # 9A has multiple sub-sections; we sum all "Net differential" lines
                    amendment_9a = 0.0
                    for nd_match in re.finditer(
                        r'Net\s+differential\s+amount.*?([\d,]+\.\d{2})',
                        full_text, re.IGNORECASE
                    ):
                        # only inside 9A section (before 9B)
                        pos = nd_match.start()
                        sec_9a = re.search(r'9A\s*[-–]?\s*Amendment', full_text, re.IGNORECASE)
                        sec_9b = re.search(r'9B\s*[-–]?\s*Credit', full_text, re.IGNORECASE)
                        if sec_9a and (not sec_9b or pos < sec_9b.start()) and pos > sec_9a.start():
                            val = float(nd_match.group(1).replace(',', ''))
                            amendment_9a += val

                    # ── 6. TAX LIABILITY ──────────────────────────────────────
                    igst, cgst, sgst = extract_liability(full_text)

                    all_data.append({
                        "Month":              month_name,
                        "File Name":          file.name,
                        "Sales (B2B)":        b2b,
                        "Sales (B2CS)":       b2cs,
                        "Total Sales":        total_sales,
                        "6A - Exports":       exp_6a,
                        "6B - SEZ":           sez_6b,
                        "6C - Deemed Export": deemed_6c,
                        "Total Exports":      total_exports,
                        "Credit/Debit Notes": total_cdn,
                        "Amendment (9A)":     amendment_9a,
                        "IGST":               igst,
                        "CGST":               cgst,
                        "SGST":               sgst,
                    })

                except Exception as e:
                    st.error(f"❌ Could not process **{file.name}**. Error: {e}")

        # ── OUTPUT ────────────────────────────────────────────────────────────
        if all_data:
            df = pd.DataFrame(all_data)

            # Sort April → March (financial year order)
            month_order = {m: (i - 3) % 12 for i, m in enumerate(MONTHS)}
            df["_sort"] = df["Month"].map(lambda x: month_order.get(x, 99))
            df = df.sort_values("_sort").drop(columns=["_sort"])

            st.success(f"✅ Processed {len(all_data)} file(s) successfully!")

            # Styled display
            currency_cols = [
                "Sales (B2B)", "Sales (B2CS)", "Total Sales",
                "6A - Exports", "6B - SEZ", "6C - Deemed Export", "Total Exports",
                "Credit/Debit Notes", "Amendment (9A)",
                "IGST", "CGST", "SGST"
            ]
            st.dataframe(
                df.style.format({c: "₹{:,.2f}" for c in currency_cols}),
                use_container_width=True
            )

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name="GSTR1_Bulk_Extraction.csv",
                mime="text/csv",
            )
