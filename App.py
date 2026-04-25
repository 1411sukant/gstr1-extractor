import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs. Extracts Month, Sales, Exports (6A, 6B, 6C), Credit Notes, Taxes, and 9A Amendments.")

# --- THE BULLETPROOF REGEX SYSTEM ---
def get_value_for_section(text, header_pattern, stop_pattern=None, target_word="total"):
    """Uses pattern matching to ignore weird PDF spaces, missing dashes, and line breaks."""
    start_match = re.search(header_pattern, text, re.IGNORECASE)
    if not start_match:
        return 0.0
        
    start = start_match.start()
    
    end = len(text)
    if stop_pattern:
        stop_match = re.search(stop_pattern, text[start:], re.IGNORECASE)
        if stop_match:
            end = start + stop_match.start()
        else:
            end = start + 1500
    else:
        end = start + 1500
        
    section = text[start:end]
    
    target_match = re.search(target_word, section, re.IGNORECASE)
    if not target_match:
        return 0.0
        
    target_idx = target_match.start()
    
    amounts = re.findall(r'-?[\d,]+\.\d{2}', section[target_idx:])
    if amounts:
        return float(amounts[0].replace(',', ''))
    return 0.0

# 1. ALLOW MULTIPLE FILES
uploaded_files = st.file_uploader("Drop all your GSTR-1 PDFs here", type="pdf", accept_multiple_files=True)

if uploaded_files:
    if st.button("Extract Data from All Files"):
        all_data = []
        months_list = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        
        with st.spinner('Processing your files...'):
            for file in uploaded_files:
                try:
                    with pdfplumber.open(file) as pdf:
                        full_text = ""
                        for page in pdf.pages:
                            full_text += page.extract_text() + " \n "
                    
                    # 1. Extract Month
                    month_name = "Unknown"
                    tax_period_match = re.search(r'tax period', full_text, re.IGNORECASE)
                    if tax_period_match:
                        chunk = full_text[tax_period_match.start():tax_period_match.start()+200]
                        for m in months_list:
                            if m.lower() in chunk.lower():
                                month_name = m
                                break
                    
                    # 2. Extract Business Data (The '?' makes the dashes optional so it never misses)
                    taxable_sale = get_value_for_section(full_text, r'4A\s*[-–]?\s*Taxable', r'4B\s*[-–]?\s*Taxable')
                    
                    export_6a = get_value_for_section(full_text, r'6A\s*[-–]?\s*Export', r'6B\s*[-–]?\s*Supplies')
                    sez_6b = get_value_for_section(full_text, r'6B\s*[-–]?\s*Supplies', r'6C\s*[-–]?\s*Deemed')
                    deemed_6c = get_value_for_section(full_text, r'6C\s*[-–]?\s*Deemed', r'7\s*[-–]?\s*Taxable')
                    
                    # 3. Credit Notes (Safely hunts for both Registered and Unregistered and adds them together)
                    cdnr_reg = get_value_for_section(full_text, r'9B\s*[-–]?\s*Credit.*Registered', r'9B\s*[-–]?\s*Credit.*Unregistered|9C\s*[-–]?\s*Amended', target_word="total")
                    cdnr_unreg = get_value_for_section(full_text, r'9B\s*[-–]?\s*Credit.*Unregistered', r'9C\s*[-–]?\s*Amended', target_word="total")
                    cdnr_total = cdnr_reg + cdnr_unreg
                    
                    # 4. 9A Amendments
                    amendment_9a = get_value_for_section(full_text, r'9A\s*[-–]?\s*Amendment', r'9B\s*[-–]?\s*Credit', target_word="net differential")
                    
                    # 5. Extract Total Liability
                    igst, cgst, sgst = 0.0, 0.0, 0.0
                    liab_match = re.search(r'Total Liability', full_text, re.IGNORECASE)
                    if liab_match:
                        chunk = full_text[liab_match.start():liab_match.start()+500]
                        amounts = re.findall(r'-?[\d,]+\.\d{2}', chunk)
                        if len(amounts) >= 4:
                            igst = float(amounts[1].replace(',', ''))
                            cgst = float(amounts[2].replace(',', ''))
                            sgst = float(amounts[3].replace(',', ''))

                    # 6. Save to Master List
                    all_data.append({
                        "Month": month_name,
                        "File Name": file.name,
                        "Taxable Sales (B2B)": taxable_sale,
                        "6A - Exports": export_6a,
                        "6B - SEZ Supplies": sez_6b,
                        "6C - Deemed Exports": deemed_6c,
                        "Credit/Debit Notes": cdnr_total,
                        "Total IGST": igst,
                        "Total CGST": cgst,
                        "Total SGST": sgst,
                        "Amendment (9A)": amendment_9a
                    })

                except Exception as e:
                    st.error(f"Could not process {file.name}. Error: {e}")
            
            # 7. Output Data
            if all_data:
                df = pd.DataFrame(all_data)
                
                # Sort chronologically (April to March)
                month_dict = {m: (i-3)%12 for i, m in enumerate(months_list)}
                df['Month_Sort'] = df['Month'].map(lambda x: month_dict.get(x, 99))
                df = df.sort_values('Month_Sort').drop('Month_Sort', axis=1)
                
                st.success(f"✅ Successfully processed {len(uploaded_files)} files!")
                st.dataframe(df, use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Consolidated Data",
                    data=csv,
                    file_name="Bulk_GSTR1_Extraction.csv",
                    mime="text/csv",
                )
