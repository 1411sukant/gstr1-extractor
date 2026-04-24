import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs. Extracts Month, Sales, Exports, SEZ, Credit Notes, Taxes, and 9A Amendments.")

# --- THE UPGRADED HUNTING SYSTEM ---
def find_amount(lines, start_idx, keyword, search_depth=15):
    """Hunts for a keyword, then grabs a 'chunk' of lines to ensure it catches wrapped numbers."""
    for j in range(start_idx, min(start_idx + search_depth, len(lines))):
        if keyword.lower() in lines[j].lower():
            # Combine the keyword line and the next 4 lines into one block of text
            chunk = " ".join(lines[j:j+5])
            # The '-?' ensures we catch negative numbers for credit notes and amendments
            amounts = re.findall(r'-?[\d,]+\.\d{2}', chunk)
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
                            full_text += page.extract_text() + "\n"
                    
                    # Initialize variables for this file
                    month_name = "Unknown"
                    taxable_sale, export_val, sez_val = 0.0, 0.0, 0.0
                    credit_debit_note_val, amendment_val = 0.0, 0.0
                    igst, cgst, sgst = 0.0, 0.0, 0.0
                    
                    lines = full_text.split('\n')
                    
                    for i, line in enumerate(lines):
                        
                        # Extract the Month
                        if "Tax period" in line or "Tax Period" in line:
                            chunk = " ".join(lines[i:i+3])
                            for m in months_list:
                                if m.lower() in chunk.lower():
                                    month_name = m
                                    break
                                    
                        # 1. B2B Sales
                        elif "4A-Taxable outward" in line or "4A - Taxable" in line:
                            taxable_sale += find_amount(lines, i, "Total")
                        
                        # 2. Exports
                        elif "6A-Exports" in line or "6A - Exports" in line:
                            export_val += find_amount(lines, i, "Total")
                            
                        # 3. SEZ
                        elif "6B-Supplies made to SEZ" in line or "6B - Supplies" in line:
                            sez_val += find_amount(lines, i, "Total")
                            
                        # 4. Credit/Debit Notes (Catches both Registered and Unregistered)
                        elif "9B-Credit/Debit" in line or "9B - Credit" in line:
                            # Usually labeled as 'Net Total' or 'Total - Net off'
                            val1 = find_amount(lines, i, "Net Total", search_depth=10)
                            val2 = find_amount(lines, i, "Total - Net off", search_depth=10)
                            credit_debit_note_val += max(abs(val1), abs(val2)) # Takes whichever is found
                            # If it's a credit note, you may want this to be negative. 
                            # If your PDF outputs negatives, remove 'abs()'
                            
                        # 5. Amendments (9A)
                        elif "9A-Amendment" in line or "9A - Amendment" in line:
                            # Looks for the net difference caused by the amendment
                            amendment_val += find_amount(lines, i, "Net differential", search_depth=12)

                        # 6. Total Liability (IGST, CGST, SGST from the summary)
                        elif "Total Liability" in line:
                            chunk = " ".join(lines[i:i+4])
                            amounts = re.findall(r'-?[\d,]+\.\d{2}', chunk)
                            if len(amounts) >= 4:
                                igst = float(amounts[1].replace(',', ''))
                                cgst = float(amounts[2].replace(',', ''))
                                sgst = float(amounts[3].replace(',', ''))

                    # SAVE THE FILE'S DATA
                    all_data.append({
                        "Month": month_name,
                        "File Name": file.name,
                        "Taxable Sales (B2B)": taxable_sale,
                        "Exports": export_val,
                        "SEZ Supplies": sez_val,
                        "Credit/Debit Notes": credit_debit_note_val,
                        "Total IGST": igst,
                        "Total CGST": cgst,
                        "Total SGST": sgst,
                        "Amendment (9A)": amendment_val
                    })

                except Exception as e:
                    st.error(f"Could not process {file.name}. Error: {e}")
            
            # OUTPUT MASTER EXCEL
            if all_data:
                df = pd.DataFrame(all_data)
                
                # Sort the dataframe chronologically if months were found
                month_dict = {m: i for i, m in enumerate(months_list)}
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
