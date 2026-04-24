import streamlit as st
import pandas as pd
import pdfplumber
import re

st.set_page_config(page_title="Bulk GSTR-1 Extractor", page_icon="📑", layout="wide")

st.title("📑 Bulk GSTR-1 PDF Extractor")
st.write("Upload multiple GSTR-1 PDFs at once. The app will extract your Sales, Exports, SEZ, Credit/Debit Notes, and Taxes into a single consolidated file.")

# 1. ALLOW MULTIPLE FILES
uploaded_files = st.file_uploader("Drop all your GSTR-1 PDFs here", type="pdf", accept_multiple_files=True)

if uploaded_files:
    if st.button("Extract Data from All Files"):
        
        # Create an empty list to hold the data for every file
        all_data = []
        
        with st.spinner('Processing your files...'):
            for file in uploaded_files:
                try:
                    with pdfplumber.open(file) as pdf:
                        full_text = ""
                        for page in pdf.pages:
                            full_text += page.extract_text() + "\n"
                    
                    # 2. INITIALIZE BUCKETS FOR THIS SPECIFIC FILE
                    taxable_sale = 0.0
                    export_val = 0.0
                    sez_val = 0.0
                    credit_debit_note_val = 0.0
                    igst = 0.0
                    cgst = 0.0
                    sgst = 0.0
                    
                    # 3. THE EXTRACTION LOGIC
                    lines = full_text.split('\n')
                    
                    for i, line in enumerate(lines):
                        # Find Regular B2B Sales (Table 4A)
                        if "4A-Taxable outward supplies" in line or "4A - Taxable" in line:
                            # Usually the total is a few lines down
                            for j in range(1, 6):
                                if i+j < len(lines) and "Total" in lines[i+j]:
                                    amounts = re.findall(r'[\d,]+\.\d{2}', lines[i+j])
                                    if amounts:
                                        taxable_sale += float(amounts[0].replace(',', ''))
                                    break
                        
                        # Find Exports (Table 6A)
                        elif "6A-Exports" in line or "6A - Exports" in line:
                            for j in range(1, 6):
                                if i+j < len(lines) and "Total" in lines[i+j]:
                                    amounts = re.findall(r'[\d,]+\.\d{2}', lines[i+j])
                                    if amounts:
                                        export_val += float(amounts[0].replace(',', ''))
                                    break
                                    
                        # Find SEZ (Table 6B)
                        elif "6B-Supplies made to SEZ" in line or "6B - Supplies" in line:
                            for j in range(1, 6):
                                if i+j < len(lines) and "Total" in lines[i+j]:
                                    amounts = re.findall(r'[\d,]+\.\d{2}', lines[i+j])
                                    if amounts:
                                        sez_val += float(amounts[0].replace(',', ''))
                                    break
                                    
                        # Find Credit/Debit Notes (Table 9B)
                        elif "9B-Credit/Debit Notes" in line or "9B - Credit" in line:
                            for j in range(1, 10):
                                if i+j < len(lines) and "Net Total" in lines[i+j]:
                                    amounts = re.findall(r'[\d,]+\.\d{2}', lines[i+j])
                                    if amounts:
                                        # Sometimes CDNR shows negative or positive impacts
                                        credit_debit_note_val += float(amounts[0].replace(',', ''))
                                    break

                        # Find the Grand Total Liability for the exact Tax amounts
                        elif "Total Liability" in line:
                            amounts = re.findall(r'[\d,]+\.\d{2}', line)
                            if len(amounts) >= 4:
                                igst = float(amounts[1].replace(',', ''))
                                cgst = float(amounts[2].replace(',', ''))
                                sgst = float(amounts[3].replace(',', ''))

                    # 4. SAVE THE FILE'S DATA TO OUR MASTER LIST
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
            
            # 5. CREATE THE MASTER CONSOLIDATED EXCEL/CSV
            if all_data:
                df = pd.DataFrame(all_data)
                
                st.success(f"✅ Successfully processed {len(uploaded_files)} files!")
                
                # Show the consolidated table on screen
                st.dataframe(df, use_container_width=True)
                
                # Provide the bulk download button
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Consolidated Data",
                    data=csv,
                    file_name="Bulk_GSTR1_Extraction.csv",
                    mime="text/csv",
                )
