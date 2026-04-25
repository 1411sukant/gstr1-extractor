import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs. Extracts Month, Sales, Exports (6A, 6B, 6C), Credit Notes, Taxes, and 9A Amendments.")

# --- THE BULLETPROOF BLOCK EXTRACTION SYSTEM ---
def get_value_for_section(text, header, stop_header=None, target_word="total"):
    """Finds a section of the PDF, isolates it, and grabs the required number."""
    start = text.lower().find(header.lower())
    if start == -1:
        return 0.0
    
    end = len(text)
    if stop_header:
        stop_idx = text.lower().find(stop_header.lower(), start + len(header))
        if stop_idx != -1:
            end = stop_idx
    else:
        end = start + 1500 # Fallback safety buffer
        
    # Isolate the exact block of text for this specific table
    section = text[start:end]
    
    # Find the target word (usually 'Total' or 'Net differential')
    target_idx = section.lower().find(target_word.lower())
    if target_idx == -1:
        return 0.0
        
    # Find all decimal numbers AFTER the target word
    amounts = re.findall(r'-?[\d,]+\.\d{2}', section[target_idx:])
    if amounts:
        # Return the very first decimal number found
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
                    # Read the entire PDF into one giant string
                    with pdfplumber.open(file) as pdf:
                        full_text = ""
                        for page in pdf.pages:
                            full_text += page.extract_text() + "\n"
                    
                    # 1. Extract Month
                    month_name = "Unknown"
                    tax_period_idx = full_text.lower().find("tax period")
                    if tax_period_idx != -1:
                        chunk = full_text[tax_period_idx:tax_period_idx+200]
                        for m in months_list:
                            if m.lower() in chunk.lower():
                                month_name = m
                                break
                    
                    # 2. Extract Business Data using the Block Search
                    taxable_sale = get_value_for_section(full_text, "4A-Taxable outward", "4B-Taxable")
                    
                    export_6a = get_value_for_section(full_text, "6A-Exports", "6B-Supplies")
                    sez_6b = get_value_for_section(full_text, "6B-Supplies made to SEZ", "6C-Deemed")
                    deemed_6c = get_value_for_section(full_text, "6C-Deemed Exports", "7- Taxable")
                    
                    # Credit Notes (We check both registered and unregistered and combine them)
                    cdnr = get_value_for_section(full_text, "9B-Credit/Debit Notes", "9C-Amended", "total")
                    
                    # 9A Amendments (Targeting the 'Net differential' word instead of Total)
                    amendment_9a = get_value_for_section(full_text, "9A-Amendment", "9B-Credit", "net differential")
                    
                    # 3. Extract Total Liability (IGST, CGST, SGST)
                    igst, cgst, sgst = 0.0, 0.0, 0.0
                    liab_idx = full_text.lower().find("total liability")
                    if liab_idx != -1:
                        chunk = full_text[liab_idx:liab_idx+500]
                        amounts = re.findall(r'-?[\d,]+\.\d{2}', chunk)
                        if len(amounts) >= 4:
                            igst = float(amounts[1].replace(',', ''))
                            cgst = float(amounts[2].replace(',', ''))
                            sgst = float(amounts[3].replace(',', ''))

                    # 4. Save to Master List
                    all_data.append({
                        "Month": month_name,
                        "File Name": file.name,
                        "Taxable Sales (B2B)": taxable_sale,
                        "6A - Exports": export_6a,
                        "6B - SEZ Supplies": sez_6b,
                        "6C - Deemed Exports": deemed_6c,
                        "Credit/Debit Notes": cdnr,
                        "Total IGST": igst,
                        "Total CGST": cgst,
                        "Total SGST": sgst,
                        "Amendment (9A)": amendment_9a
                    })

                except Exception as e:
                    st.error(f"Could not process {file.name}. Error: {e}")
            
            # 5. Output Data
            if all_data:
                df = pd.DataFrame(all_data)
                
                # Sort chronologically (April to March for Financial Year)
                # Shifting index so April = 0, March = 11
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
