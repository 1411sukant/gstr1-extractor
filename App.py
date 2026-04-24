import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs at once. The app will extract your Sales, Exports, SEZ, Credit/Debit Notes, and Taxes into a single consolidated file.")

# --- THE NEW HUNTING SYSTEM ---
def find_amount(lines, start_idx, keyword, search_depth=15):
    """Hunts down the next few lines for a keyword, then grabs the first decimal number."""
    for j in range(start_idx, min(start_idx + search_depth, len(lines))):
        if keyword.lower() in lines[j].lower():
            # Found the keyword! Now scan this line and the next 3 lines for the amount
            for k in range(j, min(j + 4, len(lines))):
                # The '-?' ensures it captures negative numbers for Credit Notes!
                amounts = re.findall(r'-?[\d,]+\.\d{2}', lines[k])
                if amounts:
                    return float(amounts[0].replace(',', ''))
    return 0.0

# 1. ALLOW MULTIPLE FILES
uploaded_files = st.file_uploader("Drop all your GSTR-1 PDFs here", type="pdf", accept_multiple_files=True)

if uploaded_files:
    if st.button("Extract Data from All Files"):
        all_data = []
        with st.spinner('Processing your files...'):
            for file in uploaded_files:
                try:
                    with pdfplumber.open(file) as pdf:
                        full_text = ""
                        for page in pdf.pages:
                            full_text += page.extract_text() + "\n"
                    
                    taxable_sale, export_val, sez_val, credit_debit_note_val = 0.0, 0.0, 0.0, 0.0
                    igst, cgst, sgst = 0.0, 0.0, 0.0
                    
                    lines = full_text.split('\n')
                    
                    for i, line in enumerate(lines):
                        # 1. B2B Sales
                        if "4A-Taxable outward" in line or "4A - Taxable" in line:
                            taxable_sale += find_amount(lines, i, "Total")
                        
                        # 2. Exports
                        elif "6A-Exports" in line or "6A - Exports" in line:
                            export_val += find_amount(lines, i, "Total")
                            
                        # 3. SEZ
                        elif "6B-Supplies made to SEZ" in line or "6B - Supplies" in line:
                            sez_val += find_amount(lines, i, "Total")
                            
                        # 4. Credit/Debit Notes (Registered)
                        elif "9B-Credit/Debit Notes (Registered)" in line:
                            credit_debit_note_val += find_amount(lines, i, "Net Total")
                            
                        # 5. Credit/Debit Notes (Unregistered)
                        elif "9B-Credit/Debit Notes (Unregistered)" in line:
                            credit_debit_note_val += find_amount(lines, i, "Net Total")

                        # 6. Total Liability (IGST, CGST, SGST from the last page)
                        elif "Total Liability" in line:
                            # We combine the current line and the next 2 lines together just in case 
                            # the PDF split the numbers away from the words!
                            combined_chunk = " ".join(lines[i:i+3])
                            amounts = re.findall(r'-?[\d,]+\.\d{2}', combined_chunk)
                            if len(amounts) >= 4:
                                igst = float(amounts[1].replace(',', ''))
                                cgst = float(amounts[2].replace(',', ''))
                                sgst = float(amounts[3].replace(',', ''))

                    # SAVE THE FILE'S DATA
                    all_data.append({
                        "File Name": file.name,
                        "Taxable Sales (B2B)": taxable_sale,
                        "Exports": export_val,
                        "SEZ Supplies": sez_val,
                        "Credit/Debit Notes": credit_debit_note_val,
                        "Total IGST": igst,
                        "Total CGST": cgst,
                        "Total SGST": sgst
                    })

                except Exception as e:
                    st.error(f"Could not process {file.name}. Error: {e}")
            
            # OUTPUT MASTER EXCEL
            if all_data:
                df = pd.DataFrame(all_data)
                st.success(f"✅ Successfully processed {len(uploaded_files)} files!")
                st.dataframe(df, use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Consolidated Data",
                    data=csv,
                    file_name="Bulk_GSTR1_Extraction.csv",
                    mime="text/csv",
                )
